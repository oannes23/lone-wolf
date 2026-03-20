"""Phase sequence computation and automatic phase execution for the Lone Wolf game engine.

Pure functions that determine the ordered list of phases a character must progress through
when entering a scene, and execute the phases that resolve automatically (without player input).
No side effects on external state — callers are responsible for persisting returned state changes.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from app.engine.combat import should_fight
from app.engine.inventory import is_over_capacity
from app.engine.meters import apply_endurance_delta, apply_gold_delta, apply_meal_delta
from app.engine.types import CharacterState, SceneContext

# ---------------------------------------------------------------------------
# Phase dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Phase:
    """A single step in the scene processing sequence.

    Attributes:
        type: Phase identifier — one of: backpack_loss, item_loss, items, eat,
            combat, random, heal, choices.
        encounter_id: The encounter this phase refers to (combat phases only).
        metadata: Arbitrary extra context for the phase (e.g., flags passed
            to ``run_automatic_phase``).
    """

    type: str  # backpack_loss, item_loss, items, eat, combat, random, heal, choices
    encounter_id: int | None = None  # for combat phases
    metadata: dict | None = None  # extra context


@dataclass
class PhaseResult:
    """The outcome of executing a single automatic phase.

    Attributes:
        phase_type: The type of the phase that was executed.
        severity: Impact level — "info", "warn", or "danger".
        description: Human-readable summary of what happened.
        events: Ordered list of event dicts for audit logging.
        state_changes: Mapping of CharacterState field names to new values
            that must be applied by the caller (e.g. ``{"endurance_current": 20}``).
    """

    phase_type: str
    severity: str  # info, warn, danger
    description: str
    events: list[dict]
    state_changes: dict  # e.g. {"endurance_current": 20, "meals": 2}


# ---------------------------------------------------------------------------
# Phase sequence computation
# ---------------------------------------------------------------------------

_DEFAULT_PHASE_ORDER = [
    "backpack_loss",
    "item_loss",
    "items",
    "eat",
    "combat",
    "random",
    "heal",
    "choices",
]


def compute_phase_sequence(
    scene_context: SceneContext,
    character_state: CharacterState,
) -> list[Phase]:
    """Compute the ordered list of phases the character must process for this scene.

    Death scenes (``scene_context.is_death is True``) return an empty sequence;
    there is nothing to process when the character has already died.

    If ``scene_context.phase_sequence_override`` is not None, it is used verbatim
    instead of the computed sequence.  Each entry in the override list must be a
    dict with at minimum a ``"type"`` key.  An optional ``"encounter_id"`` key is
    forwarded to the resulting ``Phase``.

    Otherwise the default ordering is applied and each phase is included only
    when its inclusion rule is satisfied (see rules below).

    Inclusion rules per phase type:
    - ``backpack_loss``: only when ``scene_context.loses_backpack`` is True.
    - ``item_loss``: only when the scene has items with ``action="lose"`` and
      ``item_type`` not in ``{"gold", "meal"}``.
    - ``items``: only when the scene has items with ``action="gain"`` (excluding
      gold/meal which are auto-applied during phase progression).  Also injected
      when ``is_over_capacity`` is True and no items phase would otherwise appear.
    - ``eat``: only when ``scene_context.must_eat`` is True.
    - ``combat``: one entry per encounter where ``should_fight`` returns True,
      ordered by ``CombatEncounterData.ordinal``.
    - ``random``: only when the scene has ``random_outcomes`` entries OR all
      available choices are random-gated (scene-level random exit).
    - ``heal``: always included; ``should_heal`` determines at runtime whether
      healing actually fires.
    - ``choices``: always included as the final phase.

    Args:
        scene_context: Full scene context assembled by the service layer.
        character_state: Current character state snapshot.

    Returns:
        Ordered list of ``Phase`` objects to be processed in sequence.
    """
    # Death scenes bypass all phases.
    if scene_context.is_death:
        return []

    # Override support.
    if scene_context.phase_sequence_override is not None:
        return [
            Phase(
                type=entry["type"],
                encounter_id=entry.get("encounter_id"),
                metadata=entry.get("metadata"),
            )
            for entry in scene_context.phase_sequence_override
        ]

    phases: list[Phase] = []
    has_items_phase = False

    for phase_type in _DEFAULT_PHASE_ORDER:
        if phase_type == "backpack_loss":
            if scene_context.loses_backpack:
                phases.append(Phase(type="backpack_loss"))

        elif phase_type == "item_loss":
            has_loss_items = any(
                si.action == "lose" and si.item_type not in ("gold", "meal")
                for si in scene_context.scene_items
            )
            if has_loss_items:
                phases.append(Phase(type="item_loss"))

        elif phase_type == "items":
            has_gain_items = any(
                si.action == "gain" and si.item_type not in ("gold", "meal")
                for si in scene_context.scene_items
            )
            if has_gain_items:
                phases.append(Phase(type="items"))
                has_items_phase = True

        elif phase_type == "eat":
            if scene_context.must_eat:
                phases.append(Phase(type="eat"))

        elif phase_type == "combat":
            # Sort by ordinal, include only encounters where combat is required.
            sorted_encounters = sorted(
                scene_context.combat_encounters, key=lambda e: e.ordinal
            )
            for encounter in sorted_encounters:
                if should_fight(character_state, encounter):
                    phases.append(
                        Phase(type="combat", encounter_id=encounter.encounter_id)
                    )

        elif phase_type == "random":
            has_scene_random = len(scene_context.random_outcomes) > 0
            all_choices_random = len(scene_context.choices) > 0 and all(
                c.condition_type == "random" for c in scene_context.choices
            )
            if has_scene_random or all_choices_random:
                phases.append(Phase(type="random"))

        elif phase_type == "heal":
            phases.append(Phase(type="heal"))

        elif phase_type == "choices":
            phases.append(Phase(type="choices"))

    # Over-capacity injection: if the character is carrying too many items and
    # there is no items phase already, inject one so they can discard.
    if is_over_capacity(character_state) and not has_items_phase:
        # Insert before "heal" to preserve logical ordering.
        heal_index = next(
            (i for i, p in enumerate(phases) if p.type == "heal"), len(phases)
        )
        phases.insert(heal_index, Phase(type="items"))

    return phases


# ---------------------------------------------------------------------------
# should_heal helper
# ---------------------------------------------------------------------------


def should_heal(combat_occurred: bool) -> bool:
    """Return True if the Healing discipline bonus is eligible to fire this scene.

    The Healing discipline grants +1 END at the end of each scene, but only
    when no combat occurred during that scene.  Evasion counts as combat for
    this purpose.

    Args:
        combat_occurred: True if any combat engagement (including evasion)
            took place during this scene.

    Returns:
        True when healing may be applied; False when it must be suppressed.
    """
    return not combat_occurred


# ---------------------------------------------------------------------------
# Automatic phase execution
# ---------------------------------------------------------------------------


def run_automatic_phase(
    phase: Phase,
    character_state: CharacterState,
    scene_context: SceneContext,
) -> PhaseResult:
    """Execute a phase that resolves automatically without player input.

    Supported automatic phase types: eat, heal, item_loss, backpack_loss.
    Gold and meal scene items with ``action="gain"`` are also handled here
    as part of automatic application (not a player-choice pickup).

    Non-automatic phase types (items, combat, random, choices) are not handled
    by this function; callers should not invoke it for those types.

    If any automatic phase causes character death (e.g., meal starvation penalty
    at low endurance), the result will have ``severity="danger"`` and an event
    of type ``"character_death"``.

    Args:
        phase: The phase to execute.
        character_state: Current character state snapshot (not mutated).
        scene_context: Full scene context.

    Returns:
        A ``PhaseResult`` describing the outcome and any state changes to apply.
    """
    if phase.type == "eat":
        return _run_eat_phase(phase, character_state)
    if phase.type == "heal":
        return _run_heal_phase(phase, character_state)
    if phase.type == "item_loss":
        return _run_item_loss_phase(phase, character_state, scene_context)
    if phase.type == "backpack_loss":
        return _run_backpack_loss_phase(phase, character_state)
    if phase.type in ("gold_gain", "meal_gain"):
        return _run_resource_gain_phase(phase, character_state, scene_context)

    # Fallback for unrecognised automatic phases.
    return PhaseResult(
        phase_type=phase.type,
        severity="info",
        description=f"Phase '{phase.type}' has no automatic resolution.",
        events=[],
        state_changes={},
    )


# ---------------------------------------------------------------------------
# Individual phase handlers
# ---------------------------------------------------------------------------


def _run_eat_phase(phase: Phase, state: CharacterState) -> PhaseResult:
    """Consume one meal.  If no meals and no Hunting discipline, apply -3 END."""
    events: list[dict] = []
    state_changes: dict = {}

    if state.meals > 0:
        # Consume one meal.
        new_meals, _ = apply_meal_delta(state, -1)
        state_changes["meals"] = new_meals
        events.append({"type": "meal_consumed", "meals_remaining": new_meals})
        return PhaseResult(
            phase_type="eat",
            severity="info",
            description="You eat a meal from your pack.",
            events=events,
            state_changes=state_changes,
        )

    # No meals available.
    if "Hunting" in state.disciplines:
        # Hunting discipline: forage for food, no penalty.
        events.append({"type": "hunting_forage", "meals_remaining": 0})
        return PhaseResult(
            phase_type="eat",
            severity="info",
            description="You use your Hunting skill to forage for food.",
            events=events,
            state_changes=state_changes,
        )

    # No meals, no Hunting — starvation penalty.
    new_end, is_dead, end_events = apply_endurance_delta(state, -3)
    events.extend(end_events)
    state_changes["endurance_current"] = new_end

    if is_dead:
        state_changes["is_alive"] = False
        return PhaseResult(
            phase_type="eat",
            severity="danger",
            description="You have no food and your strength fails you. You perish from starvation.",
            events=events,
            state_changes=state_changes,
        )

    return PhaseResult(
        phase_type="eat",
        severity="warn",
        description="You have no food. You lose 3 ENDURANCE points from hunger.",
        events=events,
        state_changes=state_changes,
    )


def _run_heal_phase(phase: Phase, state: CharacterState) -> PhaseResult:
    """Apply +1 END if the Healing discipline is present and no combat occurred."""
    metadata = phase.metadata or {}
    combat_occurred: bool = metadata.get("combat_occurred", False)

    if "Healing" not in state.disciplines:
        return PhaseResult(
            phase_type="heal",
            severity="info",
            description="No healing available.",
            events=[],
            state_changes={},
        )

    if not should_heal(combat_occurred):
        return PhaseResult(
            phase_type="heal",
            severity="info",
            description="Healing suppressed: combat occurred this scene.",
            events=[{"type": "heal_suppressed", "reason": "combat_occurred"}],
            state_changes={},
        )

    new_end, _is_dead, end_events = apply_endurance_delta(state, 1)
    state_changes: dict = {"endurance_current": new_end}

    return PhaseResult(
        phase_type="heal",
        severity="info",
        description="Your Healing discipline restores 1 ENDURANCE point.",
        events=end_events,
        state_changes=state_changes,
    )


def _run_item_loss_phase(
    phase: Phase, state: CharacterState, scene_context: SceneContext
) -> PhaseResult:
    """Remove items the scene forces the character to lose."""
    events: list[dict] = []
    state_changes: dict = {}

    # Collect item names to remove (non-gold, non-meal, action="lose").
    loss_items = [
        si for si in scene_context.scene_items
        if si.action == "lose" and si.item_type not in ("gold", "meal")
    ]

    remaining_items = list(state.items)

    for scene_item in loss_items:
        # Find the first matching item in inventory by name.
        match = next(
            (i for i in remaining_items if i.item_name == scene_item.item_name),
            None,
        )
        if match is None:
            events.append(
                {
                    "type": "item_loss_skip",
                    "item_name": scene_item.item_name,
                    "reason": "not_in_inventory",
                }
            )
        else:
            remaining_items.remove(match)
            events.append(
                {
                    "type": "item_lost",
                    "item_name": match.item_name,
                    "item_type": match.item_type,
                }
            )

    state_changes["items"] = remaining_items

    return PhaseResult(
        phase_type="item_loss",
        severity="warn" if events else "info",
        description="Some items have been removed from your inventory.",
        events=events,
        state_changes=state_changes,
    )


def _run_backpack_loss_phase(phase: Phase, state: CharacterState) -> PhaseResult:
    """Remove all backpack items and reset meals to 0."""
    events: list[dict] = []

    lost_items = [i for i in state.items if i.item_type == "backpack"]
    kept_items = [i for i in state.items if i.item_type != "backpack"]

    for item in lost_items:
        events.append({"type": "item_lost", "item_name": item.item_name, "item_type": "backpack"})

    if state.meals > 0:
        events.append({"type": "meals_lost", "meals_lost": state.meals, "meals_remaining": 0})

    state_changes: dict = {
        "items": kept_items,
        "meals": 0,
    }

    return PhaseResult(
        phase_type="backpack_loss",
        severity="danger",
        description="You have lost your backpack and all its contents.",
        events=events,
        state_changes=state_changes,
    )


def _run_resource_gain_phase(
    phase: Phase, state: CharacterState, scene_context: SceneContext
) -> PhaseResult:
    """Auto-apply gold and meal scene items with action='gain'."""
    events: list[dict] = []
    state_changes: dict = {}

    # Apply gold gains.
    gold_items = [
        si for si in scene_context.scene_items
        if si.action == "gain" and si.item_type == "gold"
    ]
    current_gold = state.gold
    temp_state = dataclasses.replace(state, gold=current_gold)
    for si in gold_items:
        new_gold, actual_delta = apply_gold_delta(temp_state, si.quantity)
        events.append(
            {
                "type": "gold_gained",
                "amount_requested": si.quantity,
                "amount_applied": actual_delta,
                "new_total": new_gold,
            }
        )
        temp_state = dataclasses.replace(temp_state, gold=new_gold)
    if gold_items:
        state_changes["gold"] = temp_state.gold

    # Apply meal gains.
    meal_items = [
        si for si in scene_context.scene_items
        if si.action == "gain" and si.item_type == "meal"
    ]
    temp_meal_state = dataclasses.replace(state, meals=state.meals)
    for si in meal_items:
        new_meals, actual_delta = apply_meal_delta(temp_meal_state, si.quantity)
        events.append(
            {
                "type": "meal_gained",
                "amount_requested": si.quantity,
                "amount_applied": actual_delta,
                "new_total": new_meals,
            }
        )
        temp_meal_state = dataclasses.replace(temp_meal_state, meals=new_meals)
    if meal_items:
        state_changes["meals"] = temp_meal_state.meals

    return PhaseResult(
        phase_type=phase.type,
        severity="info",
        description="Resources have been automatically applied.",
        events=events,
        state_changes=state_changes,
    )
