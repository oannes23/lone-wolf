"""Transition service — scene transitions, choose processing, and automatic phase execution."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.engine.conditions import filter_choices
from app.engine.meters import apply_gold_delta, apply_meal_delta
from app.engine.phases import compute_phase_sequence, run_automatic_phase
from app.engine.types import CharacterState, ChoiceData
from app.events import log_character_event, log_decision
from app.models.content import Choice, Scene, SceneItem
from app.models.player import Character, CharacterEvent, CharacterItem
from app.schemas.gameplay import OutcomeBand, SceneResponse
from app.services.scene_service import get_scene_state
from app.services.state_builder import (
    build_character_state,
    build_scene_context,
    mark_character_dead,
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
    if new_scene.is_death and not get_settings().DEBUG_PLAYTEST:
        mark_character_dead(character)
        increment_version(character, db)
        db.flush()
        return get_scene_state(db=db, character=character)

    # Build current character state for engine calls.
    char_state = build_character_state(db, character)

    # Step 3: Build scene context.
    scene_ctx = build_scene_context(new_scene)

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
            apply_state_changes(db, character, result.state_changes)

            # Re-sync char_state from character for next phase.
            # Update simple scalar fields directly on char_state.
            for key, value in result.state_changes.items():
                if key != "items":
                    setattr(char_state, key, value)
                # Items list changes are tracked via DB; char_state.items is not
                # re-read here (phases after item_loss don't need it).

            # Log events.
            log_phase_result(db, character, new_scene, phase.type, result)

            # If death occurred during an automatic phase, stop immediately.
            if result.state_changes.get("is_alive") is False:
                if get_settings().DEBUG_PLAYTEST:
                    result.state_changes.pop("is_alive", None)
                    character.endurance_current = max(1, character.endurance_current)
                else:
                    mark_character_dead(character)
                    increment_version(character, db)
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
    increment_version(character, db)
    db.flush()

    return get_scene_state(db=db, character=character)


def process_choose(
    db: Session,
    character: Character,
    choice_id: int,
) -> dict:
    """Process a player choice and transition the character to the next scene.

    Performs all validation and business logic for the ``choose`` action:
    phase check, pending items check, unresolved combat check, choice loading,
    availability filtering, gold deduction, random outcome assembly, and scene
    transition (or pending roll setup).

    Both the JSON API router and the UI router delegate to this function.

    Args:
        db: Active database session (caller owns the transaction).
        character: The character ORM model (mutated in place).
        choice_id: Primary key of the choice the player selected.

    Returns:
        A dict with one of two shapes:

        - Normal transition: ``{"type": "transition", "scene_response": SceneResponse}``
        - Requires roll: ``{"type": "requires_roll", "choice_id": int,
          "choice_text": str, "outcome_bands": list[OutcomeBand], "version": int}``

    Raises:
        ValueError: For client errors; the message begins with an error code
            (``WRONG_PHASE``, ``PENDING_ITEMS``, ``COMBAT_UNRESOLVED``,
            ``CHOICE_UNAVAILABLE``, ``PATH_UNAVAILABLE``).
        LookupError: If the character has no current scene or the scene is missing.
        HTTPException-like: Callers should pass-through unexpected errors.
    """
    # --- Phase check: must be in 'choices' phase ---
    if character.scene_phase != "choices":
        raise ValueError(
            f"WRONG_PHASE: Character is in '{character.scene_phase}' phase, not 'choices'."
        )

    # --- Load current scene ---
    if character.current_scene_id is None:
        raise LookupError("Character has no current scene")

    scene = db.query(Scene).filter(Scene.id == character.current_scene_id).first()
    if scene is None:
        raise LookupError(f"Scene {character.current_scene_id} not found")

    # --- Pending items check ---
    pending_count = count_pending_items(character, db)
    if pending_count > 0:
        raise ValueError(
            f"PENDING_ITEMS: There are {pending_count} unresolved scene items."
        )

    # --- Unresolved combat check ---
    if character.active_combat_encounter_id is not None:
        raise ValueError("COMBAT_UNRESOLVED: There is an unresolved combat encounter.")

    # --- Load choice and verify it belongs to the current scene ---
    choice = db.query(Choice).filter(Choice.id == choice_id).first()
    if choice is None or choice.scene_id != character.current_scene_id:
        raise ValueError("INVALID_CHOICE: Choice not found in current scene.")

    # --- Availability check ---
    char_state = build_character_state(db, character)
    choice_data = ChoiceData(
        choice_id=choice.id,
        target_scene_id=choice.target_scene_id,
        target_scene_number=choice.target_scene_number,
        display_text=choice.display_text,
        condition_type=choice.condition_type,
        condition_value=choice.condition_value,
        has_random_outcomes=bool(choice.random_outcomes),
    )
    filtered = filter_choices([choice_data], char_state)
    if filtered and not filtered[0].available:
        reason = filtered[0].reason or "condition_not_met"
        if reason == "path_unavailable":
            raise ValueError(f"PATH_UNAVAILABLE: Choice is not available: {reason}")
        raise ValueError(f"CHOICE_UNAVAILABLE: Choice is not available: {reason}")

    # --- Gold-gated choice: deduct gold before transitioning ---
    from_scene_id = character.current_scene_id
    if choice.condition_type == "gold" and choice.condition_value is not None:
        gold_cost = int(choice.condition_value)
        new_gold, actual_delta = apply_gold_delta(char_state, -gold_cost)
        character.gold = new_gold
        char_state.gold = new_gold
        log_character_event(
            db,
            character,
            "gold_change",
            scene_id=character.current_scene_id,
            phase="choices",
            details={
                "reason": "gold_gated_choice",
                "choice_id": choice.id,
                "amount_deducted": abs(actual_delta),
                "new_total": new_gold,
            },
        )

    # --- Choice-triggered random: set pending_choice_id and return outcome bands ---
    if choice.random_outcomes:
        character.pending_choice_id = choice.id
        increment_version(character, db)
        db.flush()

        outcome_bands = [
            OutcomeBand(
                range_min=ro.range_min,
                range_max=ro.range_max,
                target_scene_number=ro.target_scene_number,
                narrative_text=ro.narrative_text,
            )
            for ro in sorted(choice.random_outcomes, key=lambda r: r.range_min)
        ]
        return {
            "type": "requires_roll",
            "choice_id": choice.id,
            "choice_text": choice.display_text,
            "outcome_bands": outcome_bands,
            "version": character.version,
        }

    # --- Normal choice: validate target, log decision, and transition ---
    if choice.target_scene_id is None:
        raise ValueError(
            "PATH_UNAVAILABLE: Choice has no target scene and no random outcomes."
        )

    log_decision(
        db,
        character,
        from_scene_id=from_scene_id,
        to_scene_id=choice.target_scene_id,
        choice_id=choice.id,
        action_type="choice",
    )

    scene_response = transition_to_scene(
        db=db, character=character, target_scene_id=choice.target_scene_id
    )
    return {"type": "transition", "scene_response": scene_response}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def apply_state_changes(
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


def log_phase_result(
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


def increment_version(character: Character, db: Session) -> None:
    """Increment character version and update the updated_at timestamp.

    Args:
        character: The character ORM model (mutated in place).
        db: Active database session (unused; kept for API consistency).
    """
    character.version += 1
    character.updated_at = datetime.now(tz=UTC)


def count_pending_items(character: Character, db: Session) -> int:
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
            CharacterEvent.run_number == character.current_run,
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
