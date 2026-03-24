"""Roll service — random roll resolution for choice-triggered, phase-based, and scene-exit randoms."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.engine.phases import Phase, run_automatic_phase
from app.engine.random import (
    get_roll_groups,
    has_remaining_rolls,
    resolve_choice_triggered_random as _engine_choice_random,
    resolve_phase_random as _engine_phase_random,
    resolve_scene_exit_random as _engine_scene_exit,
)
from app.engine.types import CharacterState, ChoiceData, RandomOutcomeData
from app.events import log_character_event, log_decision
from app.models.content import Choice, Scene
from app.models.player import Character, CharacterEvent
from app.services.state_builder import build_character_state, build_scene_context, mark_character_dead
from app.services.transition_service import (
    apply_state_changes,
    increment_version,
    log_phase_result,
    transition_to_scene,
)

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
    choice = db.query(Choice).filter(Choice.id == choice_id).first()
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
    log_decision(
        db,
        character,
        from_scene_id=from_scene_id,
        to_scene_id=result.target_scene_id,
        choice_id=choice_id,
        action_type="random",
    )

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
    char_state = build_character_state(db, character)

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
                mark_character_dead(character)
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
        increment_version(character, db)
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
            "version": character.version,
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

    increment_version(character, db)
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
    # Note: redirect depth check is done in _resolve_phase_random before this is called.

    # Run heal phase at current scene before redirecting
    char_state = build_character_state(db, character)
    scene_ctx = build_scene_context(scene)

    heal_phase = Phase(type="heal")
    heal_result = run_automatic_phase(heal_phase, char_state, scene_ctx)

    heal_phase_results: list[dict] = []
    if heal_result.state_changes:
        apply_state_changes(db, character, heal_result.state_changes)
        for key, value in heal_result.state_changes.items():
            if key != "items":
                setattr(char_state, key, value)
        log_phase_result(db, character, scene, "heal", heal_result)
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
    char_state = build_character_state(db, character)
    scene_ctx = build_scene_context(scene)

    # Run the heal phase (it always follows random in the default sequence)
    heal_phase = Phase(type="heal")
    heal_result = run_automatic_phase(heal_phase, char_state, scene_ctx)
    if heal_result.state_changes:
        apply_state_changes(db, character, heal_result.state_changes)
        log_phase_result(db, character, scene, "heal", heal_result)

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
    log_decision(
        db,
        character,
        from_scene_id=from_scene_id,
        to_scene_id=target_scene_id,
        choice_id=matched_choice.id if matched_choice else None,
        action_type="random",
    )

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
