"""Scene service — assembles scene state from the database for the scene endpoint."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.engine.combat import effective_combat_skill
from app.engine.conditions import filter_choices
from app.engine.types import CharacterState, ChoiceData
from app.models.content import Book, CombatEncounter, Scene
from app.models.player import Character, CharacterEvent, CharacterItem
from app.schemas.gameplay import (
    ChoiceInfo,
    CombatState,
    PendingItem,
    PhaseResult,
    SceneResponse,
)
from app.services.state_builder import build_character_state


def get_scene_state(db: Session, character: Character) -> SceneResponse:
    """Assemble the full scene state for a character's current scene.

    Queries the database for scene content, reconstructs phase results from
    character events, evaluates choice availability, and returns a complete
    scene response.

    Args:
        db: Active database session.
        character: The character ORM model (must be loaded with current state).

    Returns:
        A :class:`SceneResponse` describing the full current scene state.

    Raises:
        ValueError: If the character has no current scene.
    """
    if character.current_scene_id is None:
        raise ValueError("Character has no current scene")

    scene = db.query(Scene).filter(Scene.id == character.current_scene_id).first()
    if scene is None:
        raise ValueError(f"Scene {character.current_scene_id} not found")

    db.query(Book).filter(Book.id == character.book_id).first()  # eager-load book

    # Build the engine CharacterState DTO (needed for choice filtering and combat)
    char_state = build_character_state(db, character)

    # Compute phase sequence from scene data
    phase_sequence = _compute_phase_sequence(scene, character)

    # Reconstruct phase results from character_events
    phase_results = _reconstruct_phase_results(db, character, scene)

    # Build choice list with availability
    choices = _build_choices(db, scene, char_state)

    # Build pending items (scene items not yet resolved in items phase)
    pending_items = _get_pending_items(db, character, scene)

    # Build combat state if in combat phase
    combat: CombatState | None = None
    if character.scene_phase == "combat" and character.active_combat_encounter_id is not None:
        combat = _get_combat_state(db, character, char_state)

    # Build illustration URL
    illustration_url: str | None = None
    if scene.illustration_path:
        illustration_url = f"/static/{scene.illustration_path}"

    return SceneResponse(
        scene_number=scene.number,
        narrative=scene.narrative,
        illustration_url=illustration_url,
        phase=character.scene_phase,
        phase_index=character.scene_phase_index,
        phase_sequence=phase_sequence,
        phase_results=phase_results,
        choices=choices,
        combat=combat,
        pending_items=pending_items,
        is_death=scene.is_death,
        is_victory=scene.is_victory,
        is_alive=character.is_alive,
        version=character.version,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_phase_sequence(scene: Scene, character: Character) -> list[str]:
    """Compute the ordered phase sequence for a scene.

    Uses the scene's ``phase_sequence_override`` if set, otherwise builds a
    default sequence based on the scene's content flags.

    Args:
        scene: The scene ORM model.
        character: The character ORM model (for current phase position).

    Returns:
        Ordered list of phase name strings.
    """
    if scene.phase_sequence_override:
        try:
            override = json.loads(scene.phase_sequence_override)
            if isinstance(override, list):
                # Extract phase type names from override entries
                return [
                    entry["type"] if isinstance(entry, dict) else str(entry)
                    for entry in override
                ]
        except (json.JSONDecodeError, TypeError, AttributeError, KeyError):
            pass

    # Default phase sequence based on scene flags
    phases: list[str] = []

    if scene.loses_backpack:
        phases.append("backpack_loss")

    if scene.scene_items:
        # Check if there are item losses (auto-applied) vs item gains (pending)
        has_losses = any(si.action == "lose" for si in scene.scene_items)
        has_gains = any(si.action == "gain" for si in scene.scene_items)
        if has_losses:
            phases.append("item_loss")
        if has_gains:
            phases.append("items")

    if scene.must_eat:
        phases.append("eat")

    if scene.combat_encounters:
        for enc in sorted(scene.combat_encounters, key=lambda e: e.ordinal):
            phases.append("combat")

    if scene.random_outcomes:
        phases.append("random")

    phases.append("choices")

    return phases


def _reconstruct_phase_results(
    db: Session, character: Character, scene: Scene
) -> list[PhaseResult]:
    """Reconstruct phase results from character_events for the current scene.

    Reads character events at the current scene to rebuild what happened during
    automatic phase processing (meal consumed, healing applied, item losses, etc.).

    Args:
        db: Active database session.
        character: The character ORM model.
        scene: The current scene ORM model.

    Returns:
        Ordered list of :class:`PhaseResult` instances.
    """
    events = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.character_id == character.id,
            CharacterEvent.scene_id == scene.id,
            CharacterEvent.run_number == character.current_run,
        )
        .order_by(CharacterEvent.seq)
        .all()
    )

    results: list[PhaseResult] = []
    for event in events:
        # Only include auto-phase events (eat, heal, item_loss, backpack_loss)
        if event.event_type not in (
            "meal_consumed",
            "meal_penalty",
            "healing",
            "item_loss",
            "backpack_loss",
            "item_loss_skip",
        ):
            continue

        try:
            details = json.loads(event.details) if event.details else {}
        except (json.JSONDecodeError, TypeError, AttributeError):
            details = {}

        # Map event_type to phase type and result strings
        event_type_map = {
            "meal_consumed": ("eat", "meal_consumed"),
            "meal_penalty": ("eat", "meal_penalty"),
            "healing": ("heal", "healed"),
            "item_loss": ("item_loss", "item_lost"),
            "backpack_loss": ("backpack_loss", "backpack_lost"),
            "item_loss_skip": ("item_loss", "item_loss_skip"),
        }

        if event.event_type in event_type_map:
            phase_type, result_str = event_type_map[event.event_type]
            severity = "warn" if event.event_type == "meal_penalty" else "info"
            results.append(
                PhaseResult(
                    type=phase_type,
                    result=result_str,
                    severity=severity,
                    details=details if details else None,
                )
            )

    return results


def _build_choices(
    db: Session, scene: Scene, char_state: CharacterState
) -> list[ChoiceInfo]:
    """Build the filtered choice list for a scene.

    Evaluates each choice's condition against the character state and returns
    all choices with availability flags.

    Args:
        db: Active database session.
        scene: The scene ORM model (with choices loaded).
        char_state: The character's engine state snapshot.

    Returns:
        List of :class:`ChoiceInfo` instances in ordinal order.
    """
    # Build engine ChoiceData objects sorted by ordinal
    sorted_choices = sorted(scene.choices, key=lambda c: c.ordinal)

    choice_data_list: list[ChoiceData] = []
    for choice in sorted_choices:
        has_random_outcomes = bool(choice.random_outcomes)
        choice_data_list.append(
            ChoiceData(
                choice_id=choice.id,
                target_scene_id=choice.target_scene_id,
                target_scene_number=choice.target_scene_number,
                display_text=choice.display_text,
                condition_type=choice.condition_type,
                condition_value=choice.condition_value,
                has_random_outcomes=has_random_outcomes,
            )
        )

    # Filter choices with availability evaluation
    filtered = filter_choices(choice_data_list, char_state)

    result: list[ChoiceInfo] = []
    for cwa in filtered:
        # Build condition dict from choice condition_type and condition_value
        condition: dict | None = None
        choice_model = next(
            (c for c in sorted_choices if c.id == cwa.choice.choice_id), None
        )
        if choice_model and choice_model.condition_type and choice_model.condition_type not in (None, "none"):
            condition = {
                "type": choice_model.condition_type,
                "value": choice_model.condition_value,
            }
        elif not cwa.available and cwa.reason == "path_unavailable":
            condition = {"type": "path_unavailable"}

        result.append(
            ChoiceInfo(
                id=cwa.choice.choice_id,
                text=cwa.choice.display_text,
                available=cwa.available,
                condition=condition,
                unavailability_reason=cwa.reason,
                has_random_outcomes=cwa.choice.has_random_outcomes,
            )
        )

    return result


def _get_pending_items(
    db: Session, character: Character, scene: Scene
) -> list[PendingItem]:
    """Return scene items pending the player's accept/decline decision.

    Only returns gain items that have not yet been resolved (no matching
    character event at this scene for the item).

    Args:
        db: Active database session.
        character: The character ORM model.
        scene: The current scene ORM model.

    Returns:
        List of :class:`PendingItem` instances for unresolved gain items.
    """
    if character.scene_phase != "items":
        return []

    # Find which scene items have already been resolved at this scene
    resolved_events = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.character_id == character.id,
            CharacterEvent.scene_id == scene.id,
            CharacterEvent.run_number == character.current_run,
            CharacterEvent.event_type.in_(["item_pickup", "item_decline"]),
        )
        .all()
    )

    resolved_ids: set[int] = set()
    for event in resolved_events:
        try:
            details = json.loads(event.details) if event.details else {}
            if "scene_item_id" in details:
                resolved_ids.add(int(details["scene_item_id"]))
        except (json.JSONDecodeError, TypeError, AttributeError, ValueError):
            pass

    pending: list[PendingItem] = []
    for si in scene.scene_items:
        if si.action != "gain":
            continue
        if si.id in resolved_ids:
            continue
        # Skip gold and meal items (auto-applied)
        if si.item_type in ("gold", "meal"):
            continue

        pending.append(
            PendingItem(
                id=si.id,
                item_name=si.item_name,
                item_type=si.item_type,
                quantity=si.quantity,
                is_mandatory=si.is_mandatory,
            )
        )

    return pending


def _get_combat_state(
    db: Session, character: Character, char_state: CharacterState
) -> CombatState | None:
    """Build the combat state for the current active encounter.

    Delegates CombatContext construction to
    :func:`app.services.combat_service._build_combat_context` to avoid
    duplicating the rounds-fought and enemy-endurance logic.

    Args:
        db: Active database session.
        character: The character ORM model.
        char_state: The character's engine state snapshot (used for CS computation).

    Returns:
        A :class:`CombatState` or None if no active encounter.
    """
    if character.active_combat_encounter_id is None:
        return None

    encounter = (
        db.query(CombatEncounter)
        .filter(CombatEncounter.id == character.active_combat_encounter_id)
        .first()
    )
    if encounter is None:
        return None

    from app.services.combat_service import build_combat_context

    combat_ctx, rounds_fought = build_combat_context(db, encounter, character)

    hero_effective_cs = effective_combat_skill(char_state, combat_ctx)
    combat_ratio = hero_effective_cs - encounter.enemy_cs

    evasion_available = encounter.evasion_after_rounds is not None
    can_evade = (
        evasion_available
        and encounter.evasion_after_rounds is not None
        and rounds_fought >= encounter.evasion_after_rounds
    )

    return CombatState(
        encounter_id=encounter.id,
        enemy_name=encounter.enemy_name,
        enemy_cs=encounter.enemy_cs,
        enemy_end_remaining=combat_ctx.enemy_end_remaining,
        hero_end_remaining=character.endurance_current,
        rounds_fought=rounds_fought,
        evasion_available=evasion_available,
        can_evade=can_evade,
        evasion_after_rounds=encounter.evasion_after_rounds,
        hero_effective_cs=hero_effective_cs,
        combat_ratio=combat_ratio,
    )
