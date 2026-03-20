"""Character lifecycle management for the Lone Wolf game engine.

Pure functions that handle character death, restart after death, and replay
after victory. No side effects — callers are responsible for persisting results.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.types import CharacterState


@dataclass
class DeathResult:
    """Result of a character death transition.

    Attributes:
        events: Ordered list of event dicts describing what happened.
        version: The new version number after the death transition.
    """

    events: list[dict]
    version: int


@dataclass
class RestoredState:
    """Character state restored from a snapshot for restart or replay.

    Attributes:
        character_id: The character being restored.
        combat_skill_base: Combat skill restored from snapshot.
        endurance_base: Base endurance restored from snapshot.
        endurance_max: Maximum endurance restored from snapshot.
        endurance_current: Current endurance restored from snapshot.
        gold: Gold restored from snapshot.
        meals: Meals restored from snapshot.
        items_json: Serialized items from snapshot.
        disciplines_json: Serialized disciplines from snapshot.
        is_alive: Always True after a successful restore.
        death_count: Updated death count (incremented on death restart, unchanged on replay).
        current_run: Updated run counter (always incremented).
        version: New version number after the restore transition.
        start_scene_number: Scene number where the character should be placed.
        events: Ordered list of event dicts describing what happened.
    """

    character_id: int
    combat_skill_base: int
    endurance_base: int
    endurance_max: int
    endurance_current: int
    gold: int
    meals: int
    items_json: str
    disciplines_json: str
    is_alive: bool
    death_count: int
    current_run: int
    version: int
    start_scene_number: int
    events: list[dict]


def handle_death(state: CharacterState) -> DeathResult:
    """Mark a character as dead and clear active scene tracking fields.

    Sets is_alive to False, clears scene_phase, scene_phase_index, and
    active_combat_encounter_id, then increments the version.

    Args:
        state: Current character state snapshot.

    Returns:
        A :class:`DeathResult` containing the death event and new version.
    """
    new_version = state.version + 1

    events: list[dict] = [
        {
            "type": "character_death",
            "character_id": state.character_id,
            "endurance_current": state.endurance_current,
            "scene_id": state.current_scene_id,
        }
    ]

    return DeathResult(events=events, version=new_version)


def enter_death_scene(state: CharacterState) -> DeathResult:
    """Process arrival at a death scene, bypassing all normal phase processing.

    Death scenes skip the full phase sequence immediately. Delegates directly
    to :func:`handle_death` to produce the death result.

    Args:
        state: Current character state snapshot.

    Returns:
        A :class:`DeathResult` containing the death event and new version.
    """
    return handle_death(state)


def restart_character(
    state: CharacterState, snapshot: dict, start_scene_number: int
) -> RestoredState:
    """Restore a dead character from a creation snapshot to start a new run.

    All stat and inventory fields are restored from ``snapshot``. The
    ``death_count`` is incremented (a death occurred). The ``current_run``
    is also incremented. The character is marked alive and placed at
    ``start_scene_number``.

    Args:
        state: Current character state snapshot (character must be dead).
        snapshot: Dict containing the fields to restore. Expected keys:
            ``combat_skill_base``, ``endurance_base``, ``endurance_max``,
            ``endurance_current``, ``gold``, ``meals``, ``items_json``,
            ``disciplines_json``.
        start_scene_number: Scene number where the restored character begins.

    Returns:
        A :class:`RestoredState` with all snapshot fields applied and
        ``start_scene_number`` set for placement.
    """
    new_death_count = state.death_count + 1
    new_current_run = state.current_run + 1
    new_version = state.version + 1

    events: list[dict] = [
        {
            "type": "character_restart",
            "character_id": state.character_id,
            "death_count": new_death_count,
            "current_run": new_current_run,
            "start_scene_number": start_scene_number,
        }
    ]

    return RestoredState(
        character_id=state.character_id,
        combat_skill_base=snapshot["combat_skill_base"],
        endurance_base=snapshot["endurance_base"],
        endurance_max=snapshot["endurance_max"],
        endurance_current=snapshot["endurance_current"],
        gold=snapshot["gold"],
        meals=snapshot["meals"],
        items_json=snapshot["items_json"],
        disciplines_json=snapshot["disciplines_json"],
        is_alive=True,
        death_count=new_death_count,
        current_run=new_current_run,
        version=new_version,
        start_scene_number=start_scene_number,
        events=events,
    )


def replay_book(
    state: CharacterState, snapshot: dict, start_scene_number: int
) -> RestoredState:
    """Restore a victorious character from a creation snapshot to replay the book.

    All stat and inventory fields are restored from ``snapshot``. Unlike
    :func:`restart_character`, the ``death_count`` is NOT incremented because
    this is a voluntary replay from a victory, not a death. Only
    ``current_run`` is incremented. The caller is responsible for validating
    that the character is at a victory scene before calling this function.

    Args:
        state: Current character state snapshot (character must be at a victory scene).
        snapshot: Dict containing the fields to restore. Expected keys:
            ``combat_skill_base``, ``endurance_base``, ``endurance_max``,
            ``endurance_current``, ``gold``, ``meals``, ``items_json``,
            ``disciplines_json``.
        start_scene_number: Scene number where the restored character begins.

    Returns:
        A :class:`RestoredState` with all snapshot fields applied and
        ``death_count`` unchanged, ``current_run`` incremented.
    """
    new_current_run = state.current_run + 1
    new_version = state.version + 1

    events: list[dict] = [
        {
            "type": "character_replay",
            "character_id": state.character_id,
            "death_count": state.death_count,
            "current_run": new_current_run,
            "start_scene_number": start_scene_number,
        }
    ]

    return RestoredState(
        character_id=state.character_id,
        combat_skill_base=snapshot["combat_skill_base"],
        endurance_base=snapshot["endurance_base"],
        endurance_max=snapshot["endurance_max"],
        endurance_current=snapshot["endurance_current"],
        gold=snapshot["gold"],
        meals=snapshot["meals"],
        items_json=snapshot["items_json"],
        disciplines_json=snapshot["disciplines_json"],
        is_alive=True,
        death_count=state.death_count,
        current_run=new_current_run,
        version=new_version,
        start_scene_number=start_scene_number,
        events=events,
    )
