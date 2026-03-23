"""Lifecycle service — restart (after death) and replay (after victory) operations.

These functions restore a character from their CharacterBookStart snapshot,
update the character's scene position, and log the lifecycle event.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.engine.lifecycle import restart_character, replay_book
from app.engine.types import CharacterState
from app.events import log_character_event
from app.models.content import Book, Scene
from app.models.player import (
    Character,
    CharacterBookStart,
    CharacterDiscipline,
    CharacterItem,
    DecisionLog,
)
from app.schemas.gameplay import SceneResponse
from app.services.gameplay_service import get_scene_state


def _build_minimal_char_state(character: Character) -> CharacterState:
    """Build a minimal CharacterState DTO from a Character ORM model.

    Used only to pass to pure engine lifecycle functions — does not need
    full item/discipline detail because the engine only reads basic counters.

    Args:
        character: The character ORM model.

    Returns:
        A :class:`CharacterState` dataclass populated from the character fields.
    """
    return CharacterState(
        character_id=character.id,
        combat_skill_base=character.combat_skill_base,
        endurance_base=character.endurance_base,
        endurance_max=character.endurance_max,
        endurance_current=character.endurance_current,
        gold=character.gold,
        meals=character.meals,
        is_alive=character.is_alive,
        disciplines=[],
        weapon_skill_category=None,
        items=[],
        version=character.version,
        current_run=character.current_run,
        death_count=character.death_count,
        rule_overrides=None,
        current_scene_id=character.current_scene_id,
        scene_phase=character.scene_phase,
        scene_phase_index=character.scene_phase_index,
        active_combat_encounter_id=character.active_combat_encounter_id,
    )


def _get_book_start_snapshot(db: Session, character: Character) -> CharacterBookStart:
    """Fetch the character's snapshot for their current book.

    Args:
        db: Database session.
        character: The character whose snapshot to fetch.

    Returns:
        The :class:`CharacterBookStart` snapshot row.

    Raises:
        ValueError: If no snapshot exists for this character+book.
    """
    snapshot = (
        db.query(CharacterBookStart)
        .filter(
            CharacterBookStart.character_id == character.id,
            CharacterBookStart.book_id == character.book_id,
        )
        .first()
    )
    if snapshot is None:
        raise ValueError(
            f"No book start snapshot found for character {character.id} "
            f"in book {character.book_id}"
        )
    return snapshot


def _get_start_scene(db: Session, character: Character) -> Scene:
    """Find the book's start scene for a character.

    Args:
        db: Database session.
        character: The character whose book start scene to find.

    Returns:
        The start :class:`Scene` ORM instance.

    Raises:
        ValueError: If the book or start scene is not found.
    """
    book = db.query(Book).filter(Book.id == character.book_id).first()
    if book is None:
        raise ValueError(f"Book {character.book_id} not found")

    start_scene = (
        db.query(Scene)
        .filter(
            Scene.book_id == character.book_id,
            Scene.number == book.start_scene_number,
        )
        .first()
    )
    if start_scene is None:
        raise ValueError(
            f"Start scene (number={book.start_scene_number}) not found "
            f"for book {character.book_id}"
        )
    return start_scene


def _restore_items_from_snapshot(
    db: Session, character: Character, items_json: str
) -> None:
    """Delete all current character items and restore from snapshot JSON.

    Args:
        db: Database session.
        character: The character whose items to restore.
        items_json: JSON string of item dicts from the CharacterBookStart snapshot.
    """
    # Delete existing items
    db.query(CharacterItem).filter(CharacterItem.character_id == character.id).delete()

    # Parse snapshot items
    try:
        items = json.loads(items_json) if items_json else []
    except (json.JSONDecodeError, TypeError):
        items = []

    for item_dict in items:
        new_item = CharacterItem(
            character_id=character.id,
            game_object_id=item_dict.get("game_object_id"),
            item_name=item_dict["item_name"],
            item_type=item_dict["item_type"],
            is_equipped=item_dict.get("is_equipped", False),
        )
        db.add(new_item)

    db.flush()


def _restore_disciplines_from_snapshot(
    db: Session, character: Character, disciplines_json: str
) -> None:
    """Delete all current character disciplines and restore from snapshot JSON.

    Args:
        db: Database session.
        character: The character whose disciplines to restore.
        disciplines_json: JSON string of discipline dicts from the CharacterBookStart snapshot.
    """
    # Delete existing disciplines
    db.query(CharacterDiscipline).filter(
        CharacterDiscipline.character_id == character.id
    ).delete()

    # Parse snapshot disciplines
    try:
        disciplines = json.loads(disciplines_json) if disciplines_json else []
    except (json.JSONDecodeError, TypeError):
        disciplines = []

    for disc_dict in disciplines:
        new_disc = CharacterDiscipline(
            character_id=character.id,
            discipline_id=disc_dict["discipline_id"],
            weapon_category=disc_dict.get("weapon_category"),
        )
        db.add(new_disc)

    db.flush()


def _apply_restored_state_to_character(
    character: Character,
    start_scene: Scene,
    restored_state: object,
    now: datetime,
) -> None:
    """Write all restored fields onto the character ORM model.

    Clears active_combat_encounter_id, pending_choice_id, scene_phase, and
    scene_phase_index, places the character at the start scene, and applies
    all stat values from the engine's RestoredState result.

    Args:
        character: The character ORM model to update in place.
        start_scene: The scene to place the character at.
        restored_state: A :class:`app.engine.lifecycle.RestoredState` instance.
        now: The current UTC datetime for updated_at.
    """
    character.combat_skill_base = restored_state.combat_skill_base
    character.endurance_base = restored_state.endurance_base
    character.endurance_max = restored_state.endurance_max
    character.endurance_current = restored_state.endurance_current
    character.gold = restored_state.gold
    character.meals = restored_state.meals
    character.is_alive = True
    character.death_count = restored_state.death_count
    character.current_run = restored_state.current_run
    character.version = restored_state.version
    character.current_scene_id = start_scene.id
    # Clear transient combat/choice state
    character.active_combat_encounter_id = None
    character.pending_choice_id = None
    character.scene_phase = None
    character.scene_phase_index = None
    character.updated_at = now


def _log_decision_log_entry(
    db: Session,
    character: Character,
    from_scene_id: int,
    to_scene_id: int,
    action_type: str,
) -> None:
    """Write a decision_log row for the lifecycle event.

    Args:
        db: Database session.
        character: The character the log entry belongs to.
        from_scene_id: The scene the character was at before.
        to_scene_id: The start scene they are placed at.
        action_type: Either 'restart' or 'replay'.
    """
    entry = DecisionLog(
        character_id=character.id,
        run_number=character.current_run,
        from_scene_id=from_scene_id,
        to_scene_id=to_scene_id,
        choice_id=None,
        action_type=action_type,
        details=json.dumps({"lifecycle": action_type}),
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    db.flush()


def restart(db: Session, character: Character) -> SceneResponse:
    """Restart a dead character from their book start snapshot.

    Validates the character is dead, restores stats/items/disciplines from
    the CharacterBookStart snapshot, increments death_count and current_run,
    places the character at the book's start scene, and returns the scene state.

    Args:
        db: Database session (caller owns transaction boundary).
        character: The character to restart (must be dead).

    Returns:
        A :class:`SceneResponse` at the book's start scene.

    Raises:
        ValueError: If the character is alive (must be dead to restart).
        ValueError: If no snapshot or start scene is found.
    """
    if character.is_alive:
        raise ValueError("CHARACTER_ALIVE: character must be dead to restart")

    snapshot = _get_book_start_snapshot(db, character)
    start_scene = _get_start_scene(db, character)

    char_state = _build_minimal_char_state(character)
    snapshot_dict = {
        "combat_skill_base": snapshot.combat_skill_base,
        "endurance_base": snapshot.endurance_base,
        "endurance_max": snapshot.endurance_max,
        "endurance_current": snapshot.endurance_current,
        "gold": snapshot.gold,
        "meals": snapshot.meals,
        "items_json": snapshot.items_json,
        "disciplines_json": snapshot.disciplines_json,
    }

    restored = restart_character(char_state, snapshot_dict, start_scene.number)

    # Remember current scene before overwriting for decision log
    original_scene_id = character.current_scene_id or start_scene.id

    now = datetime.now(UTC)
    _apply_restored_state_to_character(character, start_scene, restored, now)
    db.flush()

    # Restore items and disciplines from snapshot
    _restore_items_from_snapshot(db, character, snapshot.items_json)
    _restore_disciplines_from_snapshot(db, character, snapshot.disciplines_json)

    # Log character event at start scene
    log_character_event(
        db,
        character,
        event_type="restart",
        scene_id=start_scene.id,
        phase=None,
        details={
            "death_count": character.death_count,
            "current_run": character.current_run,
            "start_scene_number": start_scene.number,
        },
    )

    # Log decision log entry
    _log_decision_log_entry(
        db,
        character,
        from_scene_id=original_scene_id,
        to_scene_id=start_scene.id,
        action_type="restart",
    )

    db.flush()

    # Expire the character so relationship loads reflect the restored state
    db.expire(character)
    db.refresh(character)

    return get_scene_state(db=db, character=character)


def replay(db: Session, character: Character) -> SceneResponse:
    """Replay a victorious character from their book start snapshot.

    Validates the character is at a victory scene, restores stats/items/disciplines
    from the CharacterBookStart snapshot, increments current_run only (NOT
    death_count), and returns the scene state at the start scene.

    Args:
        db: Database session (caller owns transaction boundary).
        character: The character to replay (must be at a victory scene).

    Returns:
        A :class:`SceneResponse` at the book's start scene.

    Raises:
        ValueError: If the character is not at a victory scene.
        ValueError: If an advance wizard is already active (WIZARD_ACTIVE).
        ValueError: If no snapshot or start scene is found.
    """
    # Must be at a victory scene
    if character.current_scene_id is None:
        raise ValueError("Character has no current scene")

    current_scene = (
        db.query(Scene).filter(Scene.id == character.current_scene_id).first()
    )
    if current_scene is None or not current_scene.is_victory:
        raise ValueError("NOT_AT_VICTORY: character must be at a victory scene to replay")

    # Must not have an active wizard
    if character.active_wizard_id is not None:
        raise ValueError("WIZARD_ACTIVE: advance wizard is already in progress")

    snapshot = _get_book_start_snapshot(db, character)
    start_scene = _get_start_scene(db, character)

    char_state = _build_minimal_char_state(character)
    snapshot_dict = {
        "combat_skill_base": snapshot.combat_skill_base,
        "endurance_base": snapshot.endurance_base,
        "endurance_max": snapshot.endurance_max,
        "endurance_current": snapshot.endurance_current,
        "gold": snapshot.gold,
        "meals": snapshot.meals,
        "items_json": snapshot.items_json,
        "disciplines_json": snapshot.disciplines_json,
    }

    restored = replay_book(char_state, snapshot_dict, start_scene.number)

    # Remember current scene before overwriting for decision log
    original_scene_id = character.current_scene_id

    now = datetime.now(UTC)
    _apply_restored_state_to_character(character, start_scene, restored, now)
    db.flush()

    # Restore items and disciplines from snapshot
    _restore_items_from_snapshot(db, character, snapshot.items_json)
    _restore_disciplines_from_snapshot(db, character, snapshot.disciplines_json)

    # Log character event at start scene
    log_character_event(
        db,
        character,
        event_type="replay",
        scene_id=start_scene.id,
        phase=None,
        details={
            "death_count": character.death_count,
            "current_run": character.current_run,
            "start_scene_number": start_scene.number,
        },
    )

    # Log decision log entry
    _log_decision_log_entry(
        db,
        character,
        from_scene_id=original_scene_id,
        to_scene_id=start_scene.id,
        action_type="replay",
    )

    db.flush()

    # Expire the character so relationship loads reflect the restored state
    db.expire(character)
    db.refresh(character)

    return get_scene_state(db=db, character=character)
