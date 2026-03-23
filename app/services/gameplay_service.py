"""Gameplay service — assembles scene state from the database for the scene endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.engine.combat import effective_combat_skill
from app.engine.conditions import filter_choices
from app.engine.inventory import can_pickup, drop_item, equip_weapon, unequip_weapon, use_consumable
from app.engine.meters import apply_endurance_delta, apply_gold_delta, apply_meal_delta
from app.engine.phases import compute_phase_sequence, run_automatic_phase, should_heal
from app.engine.types import (
    CharacterState,
    ChoiceData,
    CombatContext,
    CombatEncounterData,
    CombatModifierData,
    ItemState,
    RandomOutcomeData,
    SceneContext,
    SceneItemData,
)
from app.events import log_character_event
from app.models.content import Book, CombatEncounter, Scene, SceneItem
from app.models.player import Character, CharacterEvent, CharacterItem, DecisionLog
from app.models.taxonomy import GameObject
from app.schemas.gameplay import (
    ChoiceInfo,
    CombatState,
    PendingItem,
    PhaseResult,
    SceneResponse,
)


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

    book = db.query(Book).filter(Book.id == character.book_id).first()

    # Build the engine CharacterState DTO (needed for choice filtering and combat)
    char_state = _build_character_state(db, character)

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


def _build_character_state(db: Session, character: Character) -> CharacterState:
    """Construct an engine-layer CharacterState DTO from a Character ORM model.

    Fixes N+1: collects all game_object_ids from character items in one pass,
    then does a single batch query for the corresponding GameObjects.

    Args:
        db: Active database session.
        character: The character ORM model.

    Returns:
        A fully populated :class:`CharacterState` dataclass.
    """
    # Collect discipline names
    disciplines: list[str] = []
    weapon_skill_category: str | None = None
    for cd in character.disciplines:
        disciplines.append(cd.discipline.name)
        if cd.weapon_category is not None:
            weapon_skill_category = cd.weapon_category

    # Collect all game_object_ids to batch-load
    game_object_ids = [
        ci.game_object_id
        for ci in character.items
        if ci.game_object_id is not None
    ]

    # Single batch query for all game objects
    go_lookup: dict[int, GameObject] = {}
    if game_object_ids:
        game_objects = (
            db.query(GameObject)
            .filter(GameObject.id.in_(game_object_ids))
            .all()
        )
        go_lookup = {go.id: go for go in game_objects}

    # Build item states
    items: list[ItemState] = []
    for ci in character.items:
        if ci.game_object_id is not None and ci.game_object_id in go_lookup:
            go = go_lookup[ci.game_object_id]
            try:
                properties = json.loads(go.properties) if isinstance(go.properties, str) else go.properties
            except (json.JSONDecodeError, TypeError, AttributeError):
                properties = {}
        else:
            properties = {}

        items.append(
            ItemState(
                character_item_id=ci.id,
                item_name=ci.item_name,
                item_type=ci.item_type,
                is_equipped=ci.is_equipped,
                game_object_id=ci.game_object_id,
                properties=properties,
            )
        )

    # Parse rule_overrides
    try:
        rule_overrides = (
            json.loads(character.rule_overrides)
            if character.rule_overrides
            else None
        )
    except (json.JSONDecodeError, TypeError, AttributeError):
        rule_overrides = None

    return CharacterState(
        character_id=character.id,
        combat_skill_base=character.combat_skill_base,
        endurance_base=character.endurance_base,
        endurance_max=character.endurance_max,
        endurance_current=character.endurance_current,
        gold=character.gold,
        meals=character.meals,
        is_alive=character.is_alive,
        disciplines=disciplines,
        weapon_skill_category=weapon_skill_category,
        items=items,
        version=character.version,
        current_run=character.current_run,
        death_count=character.death_count,
        rule_overrides=rule_overrides,
        current_scene_id=character.current_scene_id,
        scene_phase=character.scene_phase,
        scene_phase_index=character.scene_phase_index,
        active_combat_encounter_id=character.active_combat_encounter_id,
    )


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
    from app.models.content import ChoiceRandomOutcome

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

    Computes hero_effective_cs and combat_ratio using the engine function.

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

    # Build CombatContext for effective_combat_skill calculation
    modifiers = [
        CombatModifierData(
            modifier_type=m.modifier_type,
            modifier_value=m.modifier_value,
            condition=m.condition,
        )
        for m in encounter.modifiers
    ]

    # Determine rounds fought from combat_rounds table
    from app.models.player import CombatRound

    rounds_fought = (
        db.query(CombatRound)
        .filter(
            CombatRound.character_id == character.id,
            CombatRound.combat_encounter_id == encounter.id,
            CombatRound.run_number == character.current_run,
        )
        .count()
    )

    # Get enemy endurance remaining (latest combat_round if any, else full END)
    enemy_end_remaining = encounter.enemy_end
    if rounds_fought > 0:
        last_round = (
            db.query(CombatRound)
            .filter(
                CombatRound.character_id == character.id,
                CombatRound.combat_encounter_id == encounter.id,
                CombatRound.run_number == character.current_run,
            )
            .order_by(CombatRound.round_number.desc())
            .first()
        )
        if last_round:
            enemy_end_remaining = last_round.enemy_end_remaining

    combat_ctx = CombatContext(
        encounter_id=encounter.id,
        enemy_name=encounter.enemy_name,
        enemy_cs=encounter.enemy_cs,
        enemy_end=encounter.enemy_end,
        enemy_end_remaining=enemy_end_remaining,
        mindblast_immune=encounter.mindblast_immune,
        evasion_after_rounds=encounter.evasion_after_rounds,
        evasion_target=encounter.evasion_target,
        evasion_damage=encounter.evasion_damage,
        modifiers=modifiers,
        rounds_fought=rounds_fought,
    )

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
        enemy_end_remaining=enemy_end_remaining,
        hero_end_remaining=character.endurance_current,
        rounds_fought=rounds_fought,
        evasion_available=evasion_available,
        can_evade=can_evade,
        evasion_after_rounds=encounter.evasion_after_rounds,
        hero_effective_cs=hero_effective_cs,
        combat_ratio=combat_ratio,
    )


# ---------------------------------------------------------------------------
# Scene transition logic
# ---------------------------------------------------------------------------


def _build_scene_context(scene: Scene) -> SceneContext:
    """Build a SceneContext DTO from a Scene ORM model.

    Args:
        scene: The scene ORM model with all relationships loaded.

    Returns:
        A fully populated :class:`SceneContext` dataclass for engine functions.
    """
    # Parse phase_sequence_override if present.
    phase_sequence_override: list[dict] | None = None
    if scene.phase_sequence_override:
        try:
            parsed = json.loads(scene.phase_sequence_override)
            if isinstance(parsed, list):
                phase_sequence_override = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    choices = [
        ChoiceData(
            choice_id=c.id,
            target_scene_id=c.target_scene_id,
            target_scene_number=c.target_scene_number,
            display_text=c.display_text,
            condition_type=c.condition_type,
            condition_value=c.condition_value,
            has_random_outcomes=bool(c.random_outcomes),
        )
        for c in scene.choices
    ]

    combat_encounters = [
        CombatEncounterData(
            encounter_id=enc.id,
            enemy_name=enc.enemy_name,
            enemy_cs=enc.enemy_cs,
            enemy_end=enc.enemy_end,
            ordinal=enc.ordinal,
            mindblast_immune=enc.mindblast_immune,
            evasion_after_rounds=enc.evasion_after_rounds,
            evasion_target=enc.evasion_target,
            evasion_damage=enc.evasion_damage,
            condition_type=enc.condition_type,
            condition_value=enc.condition_value,
            modifiers=[
                CombatModifierData(
                    modifier_type=m.modifier_type,
                    modifier_value=m.modifier_value,
                    condition=m.condition,
                )
                for m in enc.modifiers
            ],
        )
        for enc in scene.combat_encounters
    ]

    scene_items = [
        SceneItemData(
            scene_item_id=si.id,
            item_name=si.item_name,
            item_type=si.item_type,
            quantity=si.quantity,
            action=si.action,
            is_mandatory=si.is_mandatory,
            game_object_id=si.game_object_id,
            properties={},  # properties not needed for phase logic
        )
        for si in scene.scene_items
    ]

    random_outcomes = [
        RandomOutcomeData(
            outcome_id=ro.id,
            roll_group=ro.roll_group,
            range_min=ro.range_min,
            range_max=ro.range_max,
            effect_type=ro.effect_type,
            effect_value=ro.effect_value,
            narrative_text=ro.narrative_text,
        )
        for ro in scene.random_outcomes
    ]

    return SceneContext(
        scene_id=scene.id,
        book_id=scene.book_id,
        scene_number=scene.number,
        is_death=scene.is_death,
        is_victory=scene.is_victory,
        must_eat=scene.must_eat,
        loses_backpack=scene.loses_backpack,
        phase_sequence_override=phase_sequence_override,
        choices=choices,
        combat_encounters=combat_encounters,
        scene_items=scene_items,
        random_outcomes=random_outcomes,
    )


def _apply_state_changes_to_character(
    db: Session,
    character: Character,
    state_changes: dict,
) -> None:
    """Persist engine-returned state_changes dict onto the Character ORM model.

    Handles the special cases:
    - ``items``: removes CharacterItem rows that are no longer in the list.
    - Other keys map directly to character attributes.

    Args:
        db: Active database session.
        character: The character ORM model to update.
        state_changes: Dict returned from :func:`run_automatic_phase`.
    """
    for key, value in state_changes.items():
        if key == "items":
            # ``value`` is a list[ItemState] of items to KEEP; remove all others.
            kept_ids = {item.character_item_id for item in value}
            for ci in list(character.items):
                if ci.id not in kept_ids:
                    db.delete(ci)
        else:
            setattr(character, key, value)


def _log_phase_result(
    db: Session,
    character: Character,
    scene: Scene,
    phase_type: str,
    result: object,
) -> None:
    """Log a character event based on the engine PhaseResult for an automatic phase.

    Translates the high-level PhaseResult into the appropriate DB event_type
    (must satisfy the CHECK constraint on ``character_events.event_type``).

    Args:
        db: Active database session.
        character: The character the events belong to.
        scene: The scene where the events occurred.
        phase_type: The phase that generated the result.
        result: The :class:`app.engine.phases.PhaseResult` instance.
    """
    if phase_type == "eat":
        # Determine the correct event type from the result description.
        if result.severity == "info":
            # Could be meal_consumed or hunting_forage (no penalty).
            has_meal_event = any(
                e.get("type") == "meal_consumed" for e in result.events
            )
            if has_meal_event:
                log_character_event(
                    db,
                    character,
                    "meal_consumed",
                    scene_id=scene.id,
                    phase=phase_type,
                    details={"meals_remaining": result.state_changes.get("meals", character.meals)},
                )
        else:
            # warn or danger = meal penalty (starvation)
            log_character_event(
                db,
                character,
                "meal_penalty",
                scene_id=scene.id,
                phase=phase_type,
                details={
                    "endurance_lost": 3,
                    "new_endurance": result.state_changes.get("endurance_current"),
                    "is_dead": result.state_changes.get("is_alive") is False,
                },
            )

    elif phase_type == "heal":
        has_end_change = any(
            e.get("type") == "endurance_change" for e in result.events
        )
        if has_end_change:
            log_character_event(
                db,
                character,
                "healing",
                scene_id=scene.id,
                phase=phase_type,
                details={
                    "new_endurance": result.state_changes.get("endurance_current"),
                    "delta": 1,
                },
            )

    elif phase_type == "item_loss":
        for event in result.events:
            if event.get("type") == "item_lost":
                log_character_event(
                    db,
                    character,
                    "item_loss",
                    scene_id=scene.id,
                    phase=phase_type,
                    details=event,
                )
            elif event.get("type") == "item_loss_skip":
                log_character_event(
                    db,
                    character,
                    "item_loss_skip",
                    scene_id=scene.id,
                    phase=phase_type,
                    details=event,
                )

    elif phase_type == "backpack_loss":
        for event in result.events:
            if event.get("type") == "item_lost":
                log_character_event(
                    db,
                    character,
                    "backpack_loss",
                    scene_id=scene.id,
                    phase=phase_type,
                    details=event,
                )


def transition_to_scene(
    db: Session,
    character: Character,
    target_scene_id: int,
) -> SceneResponse:
    """Transition a character to a new scene and run all automatic phases.

    Performs the full scene entry flow:
    1. Sets ``character.current_scene_id`` to ``target_scene_id``.
    2. If the scene is a death scene, marks the character dead and returns.
    3. Computes the phase sequence for the new scene.
    4. Runs all automatic phases (backpack_loss, item_loss, gold/meal gains, eat, heal).
    5. Sets ``character.scene_phase`` and ``scene_phase_index`` to the first
       interactive (non-automatic) phase.
    6. Increments ``character.version``.
    7. Flushes and returns the assembled SceneResponse.

    The caller must commit the transaction after calling this function.

    Args:
        db: Active database session (caller owns the transaction).
        character: The character ORM model (mutated in place).
        target_scene_id: The scene the character is transitioning to.

    Returns:
        A :class:`SceneResponse` describing the new scene state.

    Raises:
        ValueError: If the target scene does not exist.
    """
    new_scene = db.query(Scene).filter(Scene.id == target_scene_id).first()
    if new_scene is None:
        raise ValueError(f"Target scene {target_scene_id} not found")

    # Step 1: Move to the new scene.
    character.current_scene_id = target_scene_id

    # Step 2: Death scene check — mark dead and bail out early.
    if new_scene.is_death:
        character.is_alive = False
        character.scene_phase = None
        character.scene_phase_index = None
        character.active_combat_encounter_id = None
        character.version += 1
        db.flush()
        return get_scene_state(db=db, character=character)

    # Build current character state for engine calls.
    char_state = _build_character_state(db, character)

    # Step 3: Build scene context.
    scene_ctx = _build_scene_context(new_scene)

    # Step 4: Compute phase sequence.
    phases = compute_phase_sequence(scene_ctx, char_state)

    # Automatic phases: backpack_loss, item_loss, gold/meal gains, eat, heal.
    _AUTOMATIC_PHASE_TYPES = frozenset({"backpack_loss", "item_loss", "eat", "heal"})

    first_interactive_phase_index: int | None = None
    first_interactive_phase_type: str | None = None

    for idx, phase in enumerate(phases):
        if phase.type in _AUTOMATIC_PHASE_TYPES:
            # Run the phase and apply state changes.
            result = run_automatic_phase(phase, char_state, scene_ctx)

            # Apply state changes to character ORM model.
            _apply_state_changes_to_character(db, character, result.state_changes)

            # Re-sync char_state from character for next phase.
            # Update simple scalar fields directly on char_state.
            for key, value in result.state_changes.items():
                if key != "items":
                    setattr(char_state, key, value)
                # Items list changes are tracked via DB; char_state.items is not
                # re-read here (phases after item_loss don't need it).

            # Log events.
            _log_phase_result(db, character, new_scene, phase.type, result)

            # If death occurred during an automatic phase, stop immediately.
            if result.state_changes.get("is_alive") is False:
                character.is_alive = False
                character.scene_phase = None
                character.scene_phase_index = None
                character.active_combat_encounter_id = None
                character.version += 1
                db.flush()
                return get_scene_state(db=db, character=character)

        else:
            # First interactive phase — stop automatic processing here.
            if first_interactive_phase_index is None:
                first_interactive_phase_index = idx
                first_interactive_phase_type = phase.type
            # Keep running heal phases that come after interactive phases
            # (heal is always automatic even when it follows combat/random).
            # Actually: once we hit the first interactive phase we break.
            break

    # Handle case where gold/meal gain scene_items need auto-applying.
    # These are NOT part of run_automatic_phase — we apply them here for scene
    # items with action='gain' and item_type in ('gold', 'meal').
    _auto_apply_gold_meal_items(db, character, char_state, new_scene)

    # Set the character's phase to the first interactive phase.
    if first_interactive_phase_type is None:
        # All phases were automatic — the character ends up at 'choices'.
        # Find 'choices' in the sequence.
        choices_idx = next(
            (i for i, p in enumerate(phases) if p.type == "choices"),
            len(phases) - 1 if phases else 0,
        )
        character.scene_phase = "choices"
        character.scene_phase_index = choices_idx
    else:
        character.scene_phase = first_interactive_phase_type
        character.scene_phase_index = first_interactive_phase_index

    # Step 6: Increment version.
    character.version += 1
    db.flush()

    return get_scene_state(db=db, character=character)


def _auto_apply_gold_meal_items(
    db: Session,
    character: Character,
    char_state: CharacterState,
    scene: Scene,
) -> None:
    """Auto-apply gold and meal scene items with action='gain'.

    Applies gold and meal gains directly to the character without requiring
    player interaction. Logs gold_change events. Updates char_state in place.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
        char_state: The character's engine state snapshot (mutated in place).
        scene: The new scene ORM model.
    """
    for si in scene.scene_items:
        if si.action != "gain":
            continue

        if si.item_type == "gold":
            new_gold, actual_delta = apply_gold_delta(char_state, si.quantity)
            if actual_delta != 0:
                character.gold = new_gold
                char_state.gold = new_gold
                log_character_event(
                    db,
                    character,
                    "gold_change",
                    scene_id=scene.id,
                    phase=None,
                    details={
                        "amount_requested": si.quantity,
                        "amount_applied": actual_delta,
                        "new_total": new_gold,
                        "scene_item_id": si.id,
                    },
                )

        elif si.item_type == "meal":
            new_meals, actual_delta = apply_meal_delta(char_state, si.quantity)
            if actual_delta != 0:
                character.meals = new_meals
                char_state.meals = new_meals
                # Meal gains don't get a DB event (no "meal_change" in CHECK constraint).
                # They are reflected in the character state and reconstructed from
                # the scene_items data if needed.


# ---------------------------------------------------------------------------
# Item & inventory helper functions (Story 6.4)
# ---------------------------------------------------------------------------


def _load_game_object_properties(db: Session, game_object_id: int | None) -> dict:
    """Return the parsed properties dict for a game object, or empty dict."""
    if game_object_id is None:
        return {}
    obj = db.query(GameObject).filter(GameObject.id == game_object_id).first()
    if obj is None:
        return {}
    try:
        return json.loads(obj.properties)
    except (json.JSONDecodeError, TypeError):
        return {}


def _inventory_out(character_id: int, db: Session) -> list[dict]:
    """Return the current inventory as a list of dicts for API responses.

    Queries the DB directly to avoid stale relationship cache on the character
    ORM object.

    Args:
        character_id: Primary key of the character.
        db: Database session.

    Returns:
        List of inventory item dicts matching ``InventoryItemOut``.
    """
    items = (
        db.query(CharacterItem)
        .filter(CharacterItem.character_id == character_id)
        .all()
    )
    return [
        {
            "character_item_id": ci.id,
            "item_name": ci.item_name,
            "item_type": ci.item_type,
            "is_equipped": ci.is_equipped,
            "game_object_id": ci.game_object_id,
        }
        for ci in items
    ]


def _count_pending_items(character: Character, db: Session) -> int:
    """Count scene items that have not yet been accepted or declined.

    An item is 'pending' when it belongs to the character's current scene,
    has action='gain', is not a gold/meal type (those are auto-applied),
    and has not been accepted (present in inventory by name) or declined
    (recorded as item_decline event for this scene).

    Args:
        character: The ORM character instance.
        db: Database session.

    Returns:
        Number of pending items remaining for this scene.
    """
    if character.current_scene_id is None:
        return 0

    # Get all gain items for this scene (excluding gold and meal)
    scene_items = (
        db.query(SceneItem)
        .filter(
            SceneItem.scene_id == character.current_scene_id,
            SceneItem.action == "gain",
            SceneItem.item_type.notin_(["gold", "meal"]),
        )
        .all()
    )

    if not scene_items:
        return 0

    # Names already in inventory (accepted) — use direct query to avoid stale cache
    current_items = (
        db.query(CharacterItem).filter(CharacterItem.character_id == character.id).all()
    )
    picked_up_names: set[str] = {ci.item_name for ci in current_items}

    # Names that have been declined (via item_decline events at current scene)
    declined_events = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.character_id == character.id,
            CharacterEvent.scene_id == character.current_scene_id,
            CharacterEvent.event_type == "item_decline",
        )
        .all()
    )
    declined_names: set[str] = set()
    for ev in declined_events:
        if ev.details:
            try:
                d = json.loads(ev.details)
                if "item_name" in d:
                    declined_names.add(d["item_name"])
            except (json.JSONDecodeError, TypeError):
                pass

    pending = 0
    for si in scene_items:
        if si.item_name not in picked_up_names and si.item_name not in declined_names:
            pending += 1
    return pending


def _increment_version(character: Character, db: Session) -> None:
    """Increment character version and update the updated_at timestamp."""
    character.version += 1
    character.updated_at = datetime.now(tz=UTC)


def _advance_phase_if_complete(character: Character, pending_remaining: int) -> None:
    """Advance from 'items' phase when all pending items are resolved.

    If there are no more pending items and the character is in the 'items'
    phase, advance the phase to 'choices'.  The caller must handle further
    phase progression if needed.

    Args:
        character: The ORM character instance (mutated in place).
        pending_remaining: Number of pending items still to resolve.
    """
    if pending_remaining == 0 and character.scene_phase == "items":
        # Advance to choices phase — the simplest next phase
        character.scene_phase = "choices"
        character.scene_phase_index = 0


# ---------------------------------------------------------------------------
# Accept / Decline item
# ---------------------------------------------------------------------------


def process_item_action(
    db: Session,
    character: Character,
    scene_item_id: int,
    action: str,
) -> dict:
    """Accept or decline a pending scene item.

    Accept flow:
    - Validates slot capacity (400 INVENTORY_FULL unless mandatory).
    - Creates a new ``CharacterItem`` row.
    - Recalculates ``endurance_max``.
    - Logs an ``item_pickup`` event.

    Decline flow:
    - Rejects mandatory items (400 ITEM_MANDATORY).
    - Logs an ``item_decline`` event.

    After processing, if all items are resolved and the character is in the
    'items' phase, the phase is advanced.

    Args:
        db: Database session (caller owns the transaction).
        character: The ORM character instance (mutated in place).
        scene_item_id: Primary key of the ``scene_items`` row to process.
        action: One of ``"accept"`` or ``"decline"``.

    Returns:
        A dict matching the ``ItemActionResponse`` schema.

    Raises:
        LookupError: If the scene_item_id is not found.
        ValueError: For business-rule violations (inventory full, mandatory decline).
    """
    # Load the scene item
    scene_item = db.query(SceneItem).filter(SceneItem.id == scene_item_id).first()
    if scene_item is None:
        raise LookupError(f"scene_item {scene_item_id} not found")

    # Validate the scene item belongs to the character's current scene
    if scene_item.scene_id != character.current_scene_id:
        raise ValueError("scene_item does not belong to the character's current scene")

    # Expire the items relationship to ensure fresh data (avoids stale ORM cache
    # when a previous request in the same session deleted items)
    db.expire(character, ["items"])

    # Build character state DTO
    state = _build_character_state(db, character)

    new_character_item_id: int | None = None

    if action == "accept":
        # Construct scene item DTO
        props = _load_game_object_properties(db, scene_item.game_object_id)
        scene_item_data = SceneItemData(
            scene_item_id=scene_item.id,
            item_name=scene_item.item_name,
            item_type=scene_item.item_type,
            quantity=scene_item.quantity,
            action=scene_item.action,
            is_mandatory=scene_item.is_mandatory,
            game_object_id=scene_item.game_object_id,
            properties=props,
        )

        # Check capacity
        if not can_pickup(state, scene_item.item_type, scene_item.is_mandatory):
            raise ValueError(
                f"INVENTORY_FULL: cannot carry more "
                f"{'weapons' if scene_item.item_type == 'weapon' else 'backpack items'}"
            )

        # Create the CharacterItem row
        new_item = CharacterItem(
            character_id=character.id,
            game_object_id=scene_item.game_object_id,
            item_name=scene_item.item_name,
            item_type=scene_item.item_type,
            is_equipped=False,
        )
        db.add(new_item)
        db.flush()
        new_character_item_id = new_item.id

        # Recalculate endurance_max — build a fresh item list after adding the new row
        all_items = (
            db.query(CharacterItem).filter(CharacterItem.character_id == character.id).all()
        )
        item_states2 = [
            ItemState(
                character_item_id=ci2.id,
                item_name=ci2.item_name,
                item_type=ci2.item_type,
                is_equipped=ci2.is_equipped,
                game_object_id=ci2.game_object_id,
                properties=_load_game_object_properties(db, ci2.game_object_id),
            )
            for ci2 in all_items
        ]
        from app.engine.meters import compute_endurance_max as _compute_max
        new_max = _compute_max(character.endurance_base, [], item_states2)
        character.endurance_max = new_max

        # Log event
        log_character_event(
            db,
            character,
            "item_pickup",
            character.current_scene_id,
            phase=character.scene_phase,
            details={
                "item_name": scene_item.item_name,
                "item_type": scene_item.item_type,
                "is_mandatory": scene_item.is_mandatory,
            },
        )

    elif action == "decline":
        if scene_item.is_mandatory:
            raise ValueError("ITEM_MANDATORY: cannot decline a mandatory item")

        # Log event
        log_character_event(
            db,
            character,
            "item_decline",
            character.current_scene_id,
            phase=character.scene_phase,
            details={
                "item_name": scene_item.item_name,
                "item_type": scene_item.item_type,
            },
        )
    else:
        raise ValueError(f"Unknown action: {action}")

    # Count pending items after this action
    pending_remaining = _count_pending_items(character, db)

    # Advance phase if complete
    phase_complete = pending_remaining == 0
    _advance_phase_if_complete(character, pending_remaining)

    # Increment version and flush all pending changes
    _increment_version(character, db)
    db.flush()

    inventory = _inventory_out(character.id, db)

    result: dict = {
        "action": action,
        "pending_items_remaining": pending_remaining,
        "phase_complete": phase_complete,
        "inventory": inventory,
        "version": character.version,
    }

    if action == "accept":
        result["item_name"] = scene_item.item_name
        result["item_type"] = scene_item.item_type
        result["character_item_id"] = new_character_item_id

    return result


# ---------------------------------------------------------------------------
# Inventory management (drop / equip / unequip)
# ---------------------------------------------------------------------------


def process_inventory_action(
    db: Session,
    character: Character,
    character_item_id: int,
    action: str,
) -> dict:
    """Manage the character's inventory: drop, equip, or unequip an item.

    Drop:
    - Removes the item from ``character_items``.
    - Recalculates ``endurance_max`` and clamps ``endurance_current``.
    - Logs an ``item_loss`` event.

    Equip:
    - Sets ``is_equipped = True`` on the weapon.
    - Validates the item is a weapon.

    Unequip:
    - Sets ``is_equipped = False`` on the weapon.

    All operations are available in any scene phase including 'items'.

    Args:
        db: Database session (caller owns the transaction).
        character: The ORM character instance (mutated in place).
        character_item_id: Primary key of the ``character_items`` row.
        action: One of ``"drop"``, ``"equip"``, or ``"unequip"``.

    Returns:
        A dict matching the ``InventoryResponse`` schema.

    Raises:
        LookupError: If character_item_id is not found.
        ValueError: For business-rule violations (not a weapon, special item drop, etc.).
    """
    # Verify the item belongs to this character
    ci = (
        db.query(CharacterItem)
        .filter(
            CharacterItem.id == character_item_id,
            CharacterItem.character_id == character.id,
        )
        .first()
    )
    if ci is None:
        raise LookupError(f"character_item {character_item_id} not found")

    # Expire the items relationship to ensure fresh data (avoids stale ORM cache)
    db.expire(character, ["items"])

    state = _build_character_state(db, character)

    if action == "drop":
        result = drop_item(state, character_item_id)
        if not result.success:
            raise ValueError(result.events[0]["reason"] if result.events else "drop failed")

        # Persist: delete the item row
        db.delete(ci)
        db.flush()

        # Recalculate endurance using a fresh direct query (avoids stale relationship cache)
        from app.engine.meters import compute_endurance_max as _compute_max

        remaining_items = (
            db.query(CharacterItem).filter(CharacterItem.character_id == character.id).all()
        )
        item_states2 = [
            ItemState(
                character_item_id=ri.id,
                item_name=ri.item_name,
                item_type=ri.item_type,
                is_equipped=ri.is_equipped,
                game_object_id=ri.game_object_id,
                properties=_load_game_object_properties(db, ri.game_object_id),
            )
            for ri in remaining_items
        ]
        new_max = _compute_max(character.endurance_base, [], item_states2)
        character.endurance_max = new_max
        if character.endurance_current > new_max:
            character.endurance_current = new_max

        # Log event
        log_character_event(
            db,
            character,
            "item_loss",
            character.current_scene_id,
            phase=character.scene_phase,
            details={
                "item_name": ci.item_name,
                "item_type": ci.item_type,
                "reason": "player_dropped",
            },
        )

    elif action == "equip":
        result = equip_weapon(state, character_item_id)
        if not result.success:
            raise ValueError(result.reason or "equip failed")

        # Persist: set is_equipped = True on the target
        ci.is_equipped = True
        db.flush()

    elif action == "unequip":
        result = unequip_weapon(state, character_item_id)
        if not result.success:
            raise ValueError(result.reason or "unequip failed")

        # Persist: set is_equipped = False
        ci.is_equipped = False
        db.flush()

    else:
        raise ValueError(f"Unknown action: {action}")

    # Increment version and flush all pending changes
    _increment_version(character, db)
    db.flush()

    inventory = _inventory_out(character.id, db)

    return {
        "action": action,
        "inventory": inventory,
        "version": character.version,
    }


# ---------------------------------------------------------------------------
# Use consumable item
# ---------------------------------------------------------------------------


def process_use_item(
    db: Session,
    character: Character,
    character_item_id: int,
) -> dict:
    """Use a consumable item from the character's inventory.

    Blocked during combat phase. Applies the item's effect (e.g.
    ``endurance_restore``), removes the item, recalculates ``endurance_max``,
    and logs an ``item_consumed`` event.

    Args:
        db: Database session (caller owns the transaction).
        character: The ORM character instance (mutated in place).
        character_item_id: Primary key of the ``character_items`` row.

    Returns:
        A dict matching the ``UseItemResponse`` schema.

    Raises:
        ValueError: If in combat phase, item not found, or item not consumable.
    """
    # Block during combat
    if character.scene_phase == "combat":
        raise ValueError("WRONG_PHASE: cannot use items during combat")

    # Verify the item belongs to this character
    ci = (
        db.query(CharacterItem)
        .filter(
            CharacterItem.id == character_item_id,
            CharacterItem.character_id == character.id,
        )
        .first()
    )
    if ci is None:
        raise LookupError(f"character_item {character_item_id} not found")

    # Expire the items relationship to ensure fresh data (avoids stale ORM cache)
    db.expire(character, ["items"])

    # Check consumable in properties
    props = _load_game_object_properties(db, ci.game_object_id)
    if not props.get("consumable", False):
        raise ValueError("ITEM_NOT_CONSUMABLE: this item cannot be used")

    # Build state and apply via engine
    state = _build_character_state(db, character)

    consume_result = use_consumable(state, character_item_id)
    if not consume_result.success:
        raise ValueError(consume_result.reason or "use_consumable failed")

    # Persist state mutations from engine (endurance_current was updated by engine)
    character.endurance_current = state.endurance_current

    # Remove the item from character_items
    db.delete(ci)
    db.flush()

    # Recalculate endurance_max with item removed (use direct query, not relationship)
    from app.engine.meters import compute_endurance_max as _compute_max

    remaining_items = (
        db.query(CharacterItem).filter(CharacterItem.character_id == character.id).all()
    )
    item_states2 = [
        ItemState(
            character_item_id=ri.id,
            item_name=ri.item_name,
            item_type=ri.item_type,
            is_equipped=ri.is_equipped,
            game_object_id=ri.game_object_id,
            properties=_load_game_object_properties(db, ri.game_object_id),
        )
        for ri in remaining_items
    ]
    new_max = _compute_max(character.endurance_base, [], item_states2)
    character.endurance_max = new_max
    # Clamp endurance_current to new max
    if character.endurance_current > new_max:
        character.endurance_current = new_max

    # Log event
    log_character_event(
        db,
        character,
        "item_consumed",
        character.current_scene_id,
        phase=character.scene_phase,
        details={
            "item_name": ci.item_name,
            "effect_applied": consume_result.effect_applied,
        },
    )

    # Increment version and flush all pending changes
    _increment_version(character, db)
    db.flush()

    inventory = _inventory_out(character.id, db)

    return {
        "effect_applied": consume_result.effect_applied,
        "endurance_current": character.endurance_current,
        "endurance_max": character.endurance_max,
        "inventory": inventory,
        "version": character.version,
    }


# ---------------------------------------------------------------------------
# Roll endpoint (Story 6.5)
# ---------------------------------------------------------------------------


MAX_REDIRECT_DEPTH = 5


def process_roll(
    db: Session,
    character: Character,
    random_number: int,
) -> dict:
    """Resolve a random roll for the character's current state.

    Dispatches to one of three handlers based on character state:

    1. **Choice-triggered random** (``pending_choice_id`` is set): Resolves the
       pending choice's outcome bands, clears ``pending_choice_id``, and
       transitions to the target scene running automatic phases.

    2. **Phase-based random** (``scene_phase='random'`` and the scene has
       ``random_outcomes``): Matches the roll against the current roll group,
       applies the matched effect to the character, and returns phase-effect
       details.  If the effect is ``scene_redirect``, completes the heal phase
       first then transitions.  Tracks completed groups via ``random_roll``
       events — when all groups are resolved, the phase advances.

    3. **Scene-level random exit** (``scene_phase='random'`` and all choices have
       ``condition_type='random'``): Matches the roll against choice ranges and
       transitions to the determined target scene, running automatic phases.

    Args:
        db: Database session (caller owns the transaction).
        character: The ORM character instance (mutated in place).
        random_number: Server-generated random number (0–9).

    Returns:
        A dict matching either ``RollPhaseEffectResponse`` or
        ``RollSceneTransitionResponse`` schema.

    Raises:
        ValueError: If the character is not in a rollable state
            (not in random phase, no pending choice).
        ValueError: If redirect depth limit is exceeded.
    """
    from app.engine.random import (
        has_remaining_rolls,
        resolve_choice_triggered_random,
        resolve_phase_random,
        resolve_scene_exit_random,
    )
    from app.models.content import Choice as _Choice

    # --- Dispatch 1: Choice-triggered random ---
    if character.pending_choice_id is not None:
        return _resolve_choice_triggered_random(
            db=db,
            character=character,
            choice_id=character.pending_choice_id,
            random_number=random_number,
        )

    # --- Require random phase for other dispatches ---
    if character.scene_phase != "random":
        raise ValueError(
            "NOT_IN_RANDOM_PHASE: character is not in random phase and has no pending choice"
        )

    # Load current scene
    scene = db.query(Scene).filter(Scene.id == character.current_scene_id).first()
    if scene is None:
        raise ValueError("Current scene not found")

    # --- Dispatch 2: Phase-based random (scene has random_outcomes) ---
    if scene.random_outcomes:
        return _resolve_phase_random(
            db=db,
            character=character,
            scene=scene,
            random_number=random_number,
        )

    # --- Dispatch 3: Scene-level random exit (all choices are random-gated) ---
    all_random = len(scene.choices) > 0 and all(
        c.condition_type == "random" for c in scene.choices
    )
    if all_random:
        return _resolve_scene_exit_random(
            db=db,
            character=character,
            scene=scene,
            random_number=random_number,
        )

    raise ValueError(
        "NOT_IN_RANDOM_PHASE: character is in random phase but scene has no random outcomes "
        "and no random-gated choices"
    )


def _resolve_choice_triggered_random(
    db: Session,
    character: Character,
    choice_id: int,
    random_number: int,
) -> dict:
    """Resolve a choice-triggered random roll against the choice's outcome bands.

    Looks up the choice's ChoiceRandomOutcome rows, matches the roll,
    clears ``pending_choice_id``, logs a ``random_roll`` event, then
    transitions to the target scene running automatic phases.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
        choice_id: ID of the pending choice to resolve.
        random_number: Server-generated random number (0–9).

    Returns:
        Dict matching ``RollSceneTransitionResponse`` with
        ``random_type="choice_outcome"``.

    Raises:
        ValueError: If no outcome band covers the roll value.
    """
    from app.engine.random import resolve_choice_triggered_random as _engine_choice_random
    from app.models.content import Choice as _Choice

    choice = db.query(_Choice).filter(_Choice.id == choice_id).first()
    if choice is None:
        raise ValueError(f"Pending choice {choice_id} not found")

    outcome_bands = [
        {
            "range_min": ro.range_min,
            "range_max": ro.range_max,
            "target_scene_id": ro.target_scene_id,
            "target_scene_number": ro.target_scene_number,
            "narrative_text": ro.narrative_text,
        }
        for ro in sorted(choice.random_outcomes, key=lambda r: r.range_min)
    ]

    result = _engine_choice_random(outcome_bands, random_number)

    # Clear pending choice
    character.pending_choice_id = None

    # Log the random_roll event before transitioning
    from_scene_id = character.current_scene_id
    log_character_event(
        db,
        character,
        "random_roll",
        scene_id=from_scene_id,
        phase="choices",
        details={
            "random_type": "choice_outcome",
            "random_number": random_number,
            "choice_id": choice_id,
            "target_scene_id": result.target_scene_id,
            "outcome_text": result.narrative_text,
        },
    )

    # Log decision log entry
    from app.models.player import DecisionLog as _DecisionLog

    decision = _DecisionLog(
        character_id=character.id,
        run_number=character.current_run,
        from_scene_id=from_scene_id,
        to_scene_id=result.target_scene_id,
        choice_id=choice_id,
        action_type="random",
        details=None,
        created_at=datetime.now(UTC),
    )
    db.add(decision)

    # Transition to target scene (runs automatic phases, increments version)
    scene_response = transition_to_scene(
        db=db, character=character, target_scene_id=result.target_scene_id
    )

    return {
        "random_type": "choice_outcome",
        "random_number": random_number,
        "outcome_text": result.narrative_text,
        "scene_number": scene_response.scene_number,
        "narrative": scene_response.narrative,
        "phase_results": [pr.model_dump() for pr in scene_response.phase_results],
        "requires_confirm": True,
        "version": character.version,
    }


def _resolve_phase_random(
    db: Session,
    character: Character,
    scene: Scene,
    random_number: int,
) -> dict:
    """Resolve a phase-based random roll against the scene's random_outcomes table.

    Determines which roll group to resolve next by counting ``random_roll``
    events already logged at this scene.  Applies the matched effect, logs the
    event, and either returns a phase-effect result or handles ``scene_redirect``
    by completing the heal phase then transitioning.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
        scene: The current scene ORM model.
        random_number: Server-generated random number (0–9).

    Returns:
        Dict matching ``RollPhaseEffectResponse``.
    """
    from app.engine.random import (
        get_roll_groups,
        has_remaining_rolls,
        resolve_phase_random as _engine_phase_random,
    )

    # Build RandomOutcomeData list for the engine
    ro_data_list = [
        RandomOutcomeData(
            outcome_id=ro.id,
            roll_group=ro.roll_group,
            range_min=ro.range_min,
            range_max=ro.range_max,
            effect_type=ro.effect_type,
            effect_value=ro.effect_value,
            narrative_text=ro.narrative_text,
        )
        for ro in scene.random_outcomes
    ]

    # Determine which groups have already been resolved at this scene and
    # check redirect depth before proceeding.
    prior_roll_events = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.character_id == character.id,
            CharacterEvent.scene_id == scene.id,
            CharacterEvent.run_number == character.current_run,
            CharacterEvent.event_type == "random_roll",
        )
        .all()
    )

    # Count redirect events first — if depth limit reached, 409 before doing anything.
    redirect_count = sum(
        1
        for ev in prior_roll_events
        if ev.details and "scene_redirect" in (ev.details or "")
    )
    if redirect_count >= MAX_REDIRECT_DEPTH:
        raise ValueError(
            f"REDIRECT_DEPTH_EXCEEDED: maximum redirect depth of {MAX_REDIRECT_DEPTH} reached"
        )

    completed_groups: list[int] = []
    for ev in prior_roll_events:
        try:
            d = json.loads(ev.details) if ev.details else {}
            if "roll_group" in d:
                completed_groups.append(int(d["roll_group"]))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # Determine the current group to resolve.
    # Use a set so that duplicate event entries (e.g. from repeated redirect loops) do
    # not incorrectly mark the same group as completed multiple times.
    completed_groups_set = set(completed_groups)
    all_groups = get_roll_groups(ro_data_list)
    remaining_groups = [g for g in all_groups if g not in completed_groups_set]
    if not remaining_groups:
        raise ValueError(
            "NOT_IN_RANDOM_PHASE: all roll groups have been resolved for this scene"
        )
    current_group = remaining_groups[0]

    # Build character state for the engine
    char_state = _build_character_state(db, character)

    # Resolve via engine
    result = _engine_phase_random(ro_data_list, random_number, current_group, char_state)

    # Apply meter effects from result to character
    for effect in result.effects_applied:
        effect_type = effect.get("type")
        if effect_type == "gold_change":
            character.gold = effect["new_gold"]
        elif effect_type == "endurance_change":
            character.endurance_current = effect["new_endurance"]
            if effect.get("is_dead"):
                character.is_alive = False
        elif effect_type == "meal_change":
            character.meals = effect["new_meals"]
        # item_gain and item_loss are logged as events but not immediately
        # applied to DB (service layer handles item operations)

    # Log the random_roll event
    log_character_event(
        db,
        character,
        "random_roll",
        scene_id=scene.id,
        phase="random",
        details={
            "random_type": "phase_effect",
            "random_number": random_number,
            "roll_group": current_group,
            "effect_type": result.matched_outcome.effect_type if result.matched_outcome else None,
            "effects_applied": result.effects_applied,
            "narrative_text": result.narrative_text,
        },
    )

    # If death occurred, flush and return early (no redirect logic needed)
    if not character.is_alive:
        _increment_version(character, db)
        db.flush()
        return {
            "random_type": "phase_effect",
            "random_number": random_number,
            "outcome_text": result.narrative_text,
            "effect_type": result.matched_outcome.effect_type if result.matched_outcome else "none",
            "effect_applied": result.effects_applied[0] if result.effects_applied else None,
            "current_roll_group": current_group,
            "rolls_remaining": 0,
            "phase_complete": True,
            "requires_confirm": True,
            "version": character.version + 1,  # will be incremented
            "scene_number": None,
            "narrative": None,
            "phase_results": [],
        }

    # --- Handle scene_redirect ---
    if result.scene_redirect is not None:
        return _handle_scene_redirect(
            db=db,
            character=character,
            scene=scene,
            result=result,
            random_number=random_number,
            current_group=current_group,
        )

    # --- Normal phase effect (not a redirect) ---
    # Mark current group as completed and calculate rolls_remaining
    completed_groups_set.add(current_group)
    has_more, next_group = has_remaining_rolls(ro_data_list, list(completed_groups_set))
    rolls_remaining = len([g for g in all_groups if g not in completed_groups_set])

    phase_complete = not has_more
    if phase_complete:
        # Advance phase from 'random' to next interactive phase
        # Compute the full phase sequence to find the next phase
        _advance_random_phase(db, character, scene)

    _increment_version(character, db)
    db.flush()

    return {
        "random_type": "phase_effect",
        "random_number": random_number,
        "outcome_text": result.narrative_text,
        "effect_type": result.matched_outcome.effect_type if result.matched_outcome else "none",
        "effect_applied": result.effects_applied[0] if result.effects_applied else None,
        "current_roll_group": current_group,
        "rolls_remaining": rolls_remaining,
        "phase_complete": phase_complete,
        "requires_confirm": True,
        "scene_number": None,
        "narrative": None,
        "phase_results": [],
        "version": character.version,
    }


def _handle_scene_redirect(
    db: Session,
    character: Character,
    scene: Scene,
    result: object,
    random_number: int,
    current_group: int,
) -> dict:
    """Handle a scene_redirect outcome from a phase-based random roll.

    Runs the heal phase at the current scene before transitioning to the
    redirect target.  Respects ``MAX_REDIRECT_DEPTH`` to prevent infinite loops.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
        scene: The current scene ORM model.
        result: The ``PhaseRandomResult`` from the engine (has ``scene_redirect``).
        random_number: The roll value for event logging.
        current_group: The roll group that produced the redirect.

    Returns:
        Dict matching ``RollPhaseEffectResponse`` with scene redirect fields populated.

    Raises:
        ValueError: If ``MAX_REDIRECT_DEPTH`` is exceeded.
    """
    from app.engine.phases import Phase, run_automatic_phase, should_heal

    # Note: redirect depth check is done in _resolve_phase_random before this is called.

    # Run heal phase at current scene before redirecting
    char_state = _build_character_state(db, character)
    scene_ctx = _build_scene_context(scene)

    heal_phase = Phase(type="heal")
    heal_result = run_automatic_phase(heal_phase, char_state, scene_ctx)

    heal_phase_results: list[dict] = []
    if heal_result.state_changes:
        _apply_state_changes_to_character(db, character, heal_result.state_changes)
        for key, value in heal_result.state_changes.items():
            if key != "items":
                setattr(char_state, key, value)
        _log_phase_result(db, character, scene, "heal", heal_result)
        # Build phase result entry for response
        if any(e.get("type") == "endurance_change" for e in heal_result.events):
            heal_phase_results.append(
                {
                    "type": "heal",
                    "result": "healed",
                    "severity": "info",
                    "details": heal_result.state_changes,
                }
            )

    # Transition to redirect target scene
    target_scene_id = result.scene_redirect
    scene_response = transition_to_scene(
        db=db, character=character, target_scene_id=target_scene_id
    )

    # Merge phase_results: heal results come first
    all_phase_results = heal_phase_results + [
        pr.model_dump() for pr in scene_response.phase_results
    ]

    return {
        "random_type": "phase_effect",
        "random_number": random_number,
        "outcome_text": result.narrative_text,
        "effect_type": "scene_redirect",
        "effect_applied": {"target_scene_id": target_scene_id},
        "current_roll_group": current_group,
        "rolls_remaining": 0,
        "phase_complete": True,
        "requires_confirm": True,
        "scene_number": scene_response.scene_number,
        "narrative": scene_response.narrative,
        "phase_results": all_phase_results,
        "version": character.version,
    }


def _advance_random_phase(db: Session, character: Character, scene: Scene) -> None:
    """Advance the character's phase past 'random' to the next interactive phase.

    After all roll groups are resolved, the character should move to the heal
    phase (automatic, run immediately) then on to choices.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
        scene: The current scene ORM model.
    """
    from app.engine.phases import Phase, run_automatic_phase

    char_state = _build_character_state(db, character)
    scene_ctx = _build_scene_context(scene)

    # Run the heal phase (it always follows random in the default sequence)
    heal_phase = Phase(type="heal")
    heal_result = run_automatic_phase(heal_phase, char_state, scene_ctx)
    if heal_result.state_changes:
        _apply_state_changes_to_character(db, character, heal_result.state_changes)
        _log_phase_result(db, character, scene, "heal", heal_result)

    # Advance to choices
    character.scene_phase = "choices"
    character.scene_phase_index = 0


def _resolve_scene_exit_random(
    db: Session,
    character: Character,
    scene: Scene,
    random_number: int,
) -> dict:
    """Resolve a scene-level random exit: all choices are random-gated.

    Matches the roll against the choice conditions, logs a ``random_roll``
    event, then transitions to the target scene.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
        scene: The current scene ORM model.
        random_number: Server-generated random number (0–9).

    Returns:
        Dict matching ``RollSceneTransitionResponse`` with
        ``random_type="scene_exit"``.

    Raises:
        ValueError: If no choice range covers the roll value.
    """
    from app.engine.random import resolve_scene_exit_random as _engine_scene_exit

    choice_data_list = [
        ChoiceData(
            choice_id=c.id,
            target_scene_id=c.target_scene_id,
            target_scene_number=c.target_scene_number,
            display_text=c.display_text,
            condition_type=c.condition_type,
            condition_value=c.condition_value,
            has_random_outcomes=bool(c.random_outcomes),
        )
        for c in scene.choices
    ]

    target_scene_id = _engine_scene_exit(choice_data_list, random_number)
    if target_scene_id is None:
        raise ValueError(
            f"No random choice covers roll {random_number} at scene {scene.number}"
        )

    # Determine outcome text from the matched choice
    matched_choice = next(
        (c for c in scene.choices if c.target_scene_id == target_scene_id), None
    )
    outcome_text = matched_choice.display_text if matched_choice else None

    # Log the random_roll event before transitioning
    from_scene_id = character.current_scene_id
    log_character_event(
        db,
        character,
        "random_roll",
        scene_id=from_scene_id,
        phase="random",
        details={
            "random_type": "scene_exit",
            "random_number": random_number,
            "target_scene_id": target_scene_id,
            "outcome_text": outcome_text,
        },
    )

    # Log decision log entry
    from app.models.player import DecisionLog as _DecisionLog

    decision = _DecisionLog(
        character_id=character.id,
        run_number=character.current_run,
        from_scene_id=from_scene_id,
        to_scene_id=target_scene_id,
        choice_id=matched_choice.id if matched_choice else None,
        action_type="random",
        details=None,
        created_at=datetime.now(UTC),
    )
    db.add(decision)

    # Transition to target scene
    scene_response = transition_to_scene(
        db=db, character=character, target_scene_id=target_scene_id
    )

    return {
        "random_type": "scene_exit",
        "random_number": random_number,
        "outcome_text": outcome_text,
        "scene_number": scene_response.scene_number,
        "narrative": scene_response.narrative,
        "phase_results": [pr.model_dump() for pr in scene_response.phase_results],
        "requires_confirm": True,
        "version": character.version,
    }
