"""Combat service — orchestrates combat round and evasion endpoints.

Handles DB interactions: loading context, persisting CombatRound rows, updating
character state, and logging events.  Pure combat logic lives in app.engine.combat.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import get_settings
from app.engine.combat import evade_combat, resolve_combat_round, should_fight
from app.engine.types import CombatContext, CombatEncounterData, CombatModifierData
from app.events import log_character_event
from app.models.content import Book, CombatEncounter, CombatResults, Scene
from app.models.player import Character, CombatRound
from app.schemas.gameplay import CombatRoundResponse
from app.services.state_builder import build_character_state, build_scene_context, mark_character_dead
from app.services.transition_service import transition_to_scene


# ---------------------------------------------------------------------------
# CRT loading
# ---------------------------------------------------------------------------


def _load_crt_rows(db: Session, era: str) -> list[dict]:
    """Load all CRT rows for the given era as plain dicts for engine consumption.

    Args:
        db: Active database session.
        era: Book era string (e.g. ``"kai"``).

    Returns:
        List of dicts with keys: random_number, combat_ratio_min, combat_ratio_max,
        enemy_loss, hero_loss.
    """
    rows = db.query(CombatResults).filter(CombatResults.era == era).all()
    return [
        {
            "random_number": r.random_number,
            "combat_ratio_min": r.combat_ratio_min,
            "combat_ratio_max": r.combat_ratio_max,
            "enemy_loss": r.enemy_loss,
            "hero_loss": r.hero_loss,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Build CombatContext from ORM
# ---------------------------------------------------------------------------


def build_combat_context(
    db: Session, encounter: CombatEncounter, character: Character
) -> tuple[CombatContext, int]:
    """Build a CombatContext DTO and determine the current round count.

    Args:
        db: Active database session.
        encounter: The CombatEncounter ORM model.
        character: The character ORM model.

    Returns:
        A two-tuple of (CombatContext, rounds_fought_count).
    """
    modifiers = [
        CombatModifierData(
            modifier_type=m.modifier_type,
            modifier_value=m.modifier_value,
            condition=m.condition,
        )
        for m in encounter.modifiers
    ]

    # Count rounds fought in this run for this encounter
    rounds_fought = (
        db.query(CombatRound)
        .filter(
            CombatRound.character_id == character.id,
            CombatRound.combat_encounter_id == encounter.id,
            CombatRound.run_number == character.current_run,
        )
        .count()
    )

    # Get enemy endurance remaining from last combat round (or full START endurance)
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

    ctx = CombatContext(
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

    return ctx, rounds_fought


# ---------------------------------------------------------------------------
# Phase advancement helpers
# ---------------------------------------------------------------------------


def _skip_conditional_encounters(
    db: Session, character: Character, encounters: list[CombatEncounter]
) -> CombatEncounter | None:
    """Iterate encounters, logging skipped ones, returning the first to fight.

    Args:
        db: Active database session.
        character: The character ORM model.
        encounters: Ordered list of CombatEncounter ORM models to check.

    Returns:
        The first encounter that must be fought, or None if all are skipped.
    """
    char_state = build_character_state(db, character)

    for enc in encounters:
        enc_data = CombatEncounterData(
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
        )
        if should_fight(char_state, enc_data):
            return enc
        # Skipped — log and continue
        log_character_event(
            db=db,
            character=character,
            event_type="combat_skipped",
            scene_id=character.current_scene_id,
            phase="combat",
            details={
                "encounter_id": enc.id,
                "enemy_name": enc.enemy_name,
                "reason": "condition_met",
                "condition_type": enc.condition_type,
                "condition_value": enc.condition_value,
            },
        )

    return None


def _find_next_combat_encounter(
    db: Session, character: Character, current_encounter: CombatEncounter
) -> CombatEncounter | None:
    """Find the next combat encounter by ordinal in the same scene.

    Skips conditional encounters the character is allowed to bypass.

    Args:
        db: Active database session.
        character: The character ORM model.
        current_encounter: The encounter that just ended.

    Returns:
        The next CombatEncounter ORM model to fight, or None.
    """
    next_encounters = (
        db.query(CombatEncounter)
        .filter(
            CombatEncounter.scene_id == current_encounter.scene_id,
            CombatEncounter.ordinal > current_encounter.ordinal,
        )
        .order_by(CombatEncounter.ordinal)
        .all()
    )

    return _skip_conditional_encounters(db, character, next_encounters)


def _advance_past_combat(db: Session, character: Character) -> None:
    """Advance character past all remaining combat phases to the next non-combat phase.

    Computes the full phase sequence and finds the first phase after the last
    combat phase, then updates scene_phase and scene_phase_index accordingly.
    Clears active_combat_encounter_id.  Does NOT increment version or commit.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
    """
    from app.engine.phases import compute_phase_sequence

    scene = db.query(Scene).filter(Scene.id == character.current_scene_id).first()
    if scene is None:
        return

    char_state = build_character_state(db, character)
    scene_ctx = build_scene_context(scene)

    phases = compute_phase_sequence(scene_ctx, char_state)

    # Interactive phases that can be stored as scene_phase
    _INTERACTIVE_PHASES = frozenset({"items", "combat", "random", "choices"})

    # Find the index after the last combat phase, looking for the next interactive one
    last_combat_idx = None
    for i, ph in enumerate(phases):
        if ph.type == "combat":
            last_combat_idx = i

    # Clear active combat encounter before selecting next phase
    character.active_combat_encounter_id = None

    if last_combat_idx is not None:
        # Look for the next interactive phase after the last combat phase
        next_interactive_idx = None
        next_interactive_type = None
        for i in range(last_combat_idx + 1, len(phases)):
            if phases[i].type in _INTERACTIVE_PHASES:
                next_interactive_idx = i
                next_interactive_type = phases[i].type
                break

        if next_interactive_idx is not None:
            character.scene_phase = next_interactive_type
            character.scene_phase_index = next_interactive_idx
        else:
            # Only heal/automatic phases left after combat — go to choices
            choices_idx = next(
                (i for i, p in enumerate(phases) if p.type == "choices"),
                len(phases) - 1 if phases else 0,
            )
            character.scene_phase = "choices"
            character.scene_phase_index = choices_idx
    else:
        # No combat phase found in sequence — go to choices
        choices_idx = next(
            (i for i, p in enumerate(phases) if p.type == "choices"),
            len(phases) - 1 if phases else 0,
        )
        character.scene_phase = "choices"
        character.scene_phase_index = choices_idx


# ---------------------------------------------------------------------------
# Round resolution
# ---------------------------------------------------------------------------


def resolve_round(
    db: Session,
    character: Character,
    use_psi_surge: bool,
) -> CombatRoundResponse:
    """Resolve one round of combat and persist the results.

    Loads the active encounter, runs engine combat resolution, persists the
    CombatRound row, updates character endurance, and handles death / enemy
    defeat outcomes.

    Args:
        db: Active database session (caller owns transaction).
        character: The character ORM model (mutated in place, not committed).
        use_psi_surge: Whether the player activates Psi-surge this round.

    Returns:
        A :class:`CombatRoundResponse` describing the round outcome.

    Raises:
        ValueError: If the character has no active combat encounter or scene.
    """
    if character.active_combat_encounter_id is None:
        raise ValueError("No active combat encounter")

    encounter = (
        db.query(CombatEncounter)
        .filter(CombatEncounter.id == character.active_combat_encounter_id)
        .first()
    )
    if encounter is None:
        raise ValueError(f"Combat encounter {character.active_combat_encounter_id} not found")

    # Build engine DTOs
    char_state = build_character_state(db, character)
    combat_ctx, rounds_fought = build_combat_context(db, encounter, character)

    # Load CRT for this era
    book = db.query(Book).filter(Book.id == character.book_id).first()
    era = book.era if book else "kai"
    crt_rows = _load_crt_rows(db, era)

    # Server-generated random number (0-9)
    random_number = random.randint(0, 9)  # noqa: S311

    # Call engine
    round_result = resolve_combat_round(
        state=char_state,
        encounter=combat_ctx,
        crt_rows=crt_rows,
        random_number=random_number,
        use_psi_surge=use_psi_surge,
    )

    # Determine new round number
    round_number = rounds_fought + 1

    # Log combat_start event on first round
    if round_number == 1:
        log_character_event(
            db=db,
            character=character,
            event_type="combat_start",
            scene_id=character.current_scene_id,
            phase="combat",
            details={
                "encounter_id": encounter.id,
                "enemy_name": encounter.enemy_name,
                "enemy_cs": encounter.enemy_cs,
                "enemy_end": encounter.enemy_end,
            },
        )

    # Persist CombatRound row
    combat_round_row = CombatRound(
        character_id=character.id,
        combat_encounter_id=encounter.id,
        run_number=character.current_run,
        round_number=round_number,
        random_number=random_number,
        combat_ratio=round_result.combat_ratio,
        enemy_loss=round_result.enemy_damage,
        hero_loss=round_result.hero_damage,
        enemy_end_remaining=round_result.enemy_end_remaining,
        hero_end_remaining=round_result.hero_end_remaining,
        psi_surge_used=round_result.psi_surge_used,
        created_at=datetime.now(UTC),
    )
    db.add(combat_round_row)
    db.flush()

    # Apply hero damage to character
    character.endurance_current = round_result.hero_end_remaining

    # Determine outcome
    combat_over = round_result.hero_dead or round_result.enemy_dead
    result_str = "continue"

    if round_result.hero_dead:
        if get_settings().DEBUG_PLAYTEST:
            character.endurance_current = 1
        else:
            result_str = "loss"

            # Mark character dead and clear phase state
            mark_character_dead(character)

            # Log combat_end event
            combat_end_event = log_character_event(
                db=db,
                character=character,
                event_type="combat_end",
                scene_id=character.current_scene_id,
                phase="combat",
                details={
                    "encounter_id": encounter.id,
                    "enemy_name": encounter.enemy_name,
                    "result": "hero_dead",
                    "rounds_fought": round_number,
                },
            )

            # Log death event with parent_event_id pointing to combat_end
            log_character_event(
                db=db,
                character=character,
                event_type="death",
                scene_id=character.current_scene_id,
                phase="combat",
                details={
                    "cause": "combat",
                    "encounter_id": encounter.id,
                    "enemy_name": encounter.enemy_name,
                    "round_number": round_number,
                },
                parent_event_id=combat_end_event.id,
            )

    elif round_result.enemy_dead:
        result_str = "win"

        # Log combat_end event
        log_character_event(
            db=db,
            character=character,
            event_type="combat_end",
            scene_id=character.current_scene_id,
            phase="combat",
            details={
                "encounter_id": encounter.id,
                "enemy_name": encounter.enemy_name,
                "result": "enemy_dead",
                "rounds_fought": round_number,
            },
        )

        # Check for next enemy in multi-enemy sequence
        next_encounter = _find_next_combat_encounter(db, character, encounter)

        if next_encounter is not None:
            # Advance to next encounter (scene_phase stays "combat")
            character.active_combat_encounter_id = next_encounter.id
        else:
            # All enemies defeated — advance past combat phase
            _advance_past_combat(db, character)

    # Increment version (optimistic locking)
    character.version += 1
    character.updated_at = datetime.now(UTC)
    db.flush()

    # Compute evasion state for response (after damage applied)
    new_rounds_fought = round_number
    evasion_available = encounter.evasion_after_rounds is not None
    can_evade = (
        evasion_available
        and encounter.evasion_after_rounds is not None
        and new_rounds_fought >= encounter.evasion_after_rounds
        and not combat_over
    )

    return CombatRoundResponse(
        round_number=round_number,
        random_number=random_number,
        combat_ratio=round_result.combat_ratio,
        hero_damage=round_result.hero_damage,
        enemy_damage=round_result.enemy_damage,
        hero_end_remaining=round_result.hero_end_remaining,
        enemy_end_remaining=round_result.enemy_end_remaining,
        psi_surge_used=round_result.psi_surge_used,
        combat_over=combat_over,
        result=result_str,
        evasion_available=evasion_available,
        can_evade=can_evade,
        version=character.version,
    )


# ---------------------------------------------------------------------------
# Evasion
# ---------------------------------------------------------------------------


def resolve_evasion(
    db: Session,
    character: Character,
) -> tuple[int, bool]:
    """Attempt to evade the active combat encounter and return outcome.

    Validates evasion eligibility, applies evasion damage, handles death if it
    occurs, and (on survival) transitions the character to the evasion target scene.

    The caller must NOT call ``transition_to_scene`` after this function — evasion
    handles the scene transition internally (or stops at the current scene on death).

    Args:
        db: Active database session (caller owns transaction).
        character: The character ORM model (mutated in place, not committed).

    Returns:
        A two-tuple of (evasion_damage, hero_died).

    Raises:
        ValueError: If evasion is not allowed yet or no active encounter.
    """
    if character.active_combat_encounter_id is None:
        raise ValueError("No active combat encounter")

    encounter = (
        db.query(CombatEncounter)
        .filter(CombatEncounter.id == character.active_combat_encounter_id)
        .first()
    )
    if encounter is None:
        raise ValueError(f"Combat encounter {character.active_combat_encounter_id} not found")

    char_state = build_character_state(db, character)
    combat_ctx, rounds_fought = build_combat_context(db, encounter, character)

    # Validate evasion eligibility
    if (
        encounter.evasion_after_rounds is None
        or rounds_fought < encounter.evasion_after_rounds
    ):
        raise ValueError(
            f"Evasion not yet allowed — need {encounter.evasion_after_rounds} rounds, "
            f"have {rounds_fought}"
        )

    # Call engine evasion
    evade_result = evade_combat(char_state, combat_ctx)

    # Apply hero damage
    character.endurance_current = evade_result.hero_end_remaining

    # Log evasion event
    evasion_event = log_character_event(
        db=db,
        character=character,
        event_type="evasion",
        scene_id=character.current_scene_id,
        phase="combat",
        details={
            "encounter_id": encounter.id,
            "enemy_name": encounter.enemy_name,
            "evasion_damage": evade_result.evasion_damage,
            "hero_died": evade_result.hero_dead,
            "target_scene_id": evade_result.target_scene_id,
        },
    )

    if evade_result.hero_dead:
        if get_settings().DEBUG_PLAYTEST:
            character.endurance_current = 1
        else:
            # Death during evasion — no transition
            mark_character_dead(character)

            log_character_event(
                db=db,
                character=character,
                event_type="death",
                scene_id=character.current_scene_id,
                phase="combat",
                details={
                    "cause": "evasion_damage",
                    "encounter_id": encounter.id,
                    "enemy_name": encounter.enemy_name,
                },
                parent_event_id=evasion_event.id,
            )

            character.version += 1
            character.updated_at = datetime.now(UTC)
            db.flush()
            return evade_result.evasion_damage, True

    # Survival — transition to evasion target scene using the full transition function.
    # transition_to_scene increments version and runs automatic phases.
    if evade_result.target_scene_id is None:
        raise ValueError("Evasion succeeded but no target scene configured")

    # Clear combat state before transition
    character.active_combat_encounter_id = None

    transition_to_scene(
        db=db,
        character=character,
        target_scene_id=evade_result.target_scene_id,
    )

    return evade_result.evasion_damage, False
