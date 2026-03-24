"""Character event logging helpers.

Central helper for writing character_events rows with correct seq generation,
run tagging, and causality chain tracking.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.player import Character, CharacterEvent, DecisionLog


def log_character_event(
    db: Session,
    character: Character,
    event_type: str,
    scene_id: int,
    *,
    phase: str | None = None,
    details: dict | None = None,
    operations: list[dict] | None = None,
    parent_event_id: int | None = None,
) -> CharacterEvent:
    """Create and persist a character_event row with correct seq generation.

    The ``seq`` value is computed as ``MAX(seq) + 1`` for this character within
    the current transaction, starting at 1 for the first event.

    Args:
        db: Database session (caller owns the transaction boundary).
        character: The character whose event is being logged.
        event_type: Semantic event type (must match DB CHECK constraint).
        scene_id: The scene at which the event occurred.
        phase: The interactive phase name this event belongs to, or None.
        details: Arbitrary JSON-serializable details dict.
        operations: ops.md-style list of operation dicts to store as JSON.
        parent_event_id: ID of a parent event for causality chains.

    Returns:
        The newly created and flushed ``CharacterEvent`` ORM instance.
    """
    # Compute next seq — MAX(seq) + 1 for this character, or 1 if no prior events.
    current_max = (
        db.query(func.max(CharacterEvent.seq))
        .filter(CharacterEvent.character_id == character.id)
        .scalar()
    )
    next_seq = (current_max or 0) + 1

    event = CharacterEvent(
        character_id=character.id,
        scene_id=scene_id,
        run_number=character.current_run,
        event_type=event_type,
        phase=phase,
        details=json.dumps(details) if details is not None else None,
        seq=next_seq,
        operations=json.dumps(operations) if operations is not None else None,
        parent_event_id=parent_event_id,
        created_at=datetime.now(UTC),
    )
    db.add(event)
    db.flush()
    return event


def log_decision(
    db: Session,
    character: Character,
    from_scene_id: int,
    to_scene_id: int,
    choice_id: int | None,
    action_type: str,
    details: dict | None = None,
) -> DecisionLog:
    """Create and persist a decision_log row.

    Args:
        db: Database session (caller owns the transaction boundary).
        character: The character whose decision is being logged.
        from_scene_id: The scene the character navigated away from.
        to_scene_id: The scene the character is navigating to.
        choice_id: The Choice that triggered the navigation, or None.
        action_type: Semantic type (e.g. ``"choice"``, ``"random"``,
            ``"restart"``, ``"replay"``).
        details: Optional JSON-serialisable details dict.

    Returns:
        The newly created and flushed ``DecisionLog`` ORM instance.
    """
    entry = DecisionLog(
        character_id=character.id,
        run_number=character.current_run,
        from_scene_id=from_scene_id,
        to_scene_id=to_scene_id,
        choice_id=choice_id,
        action_type=action_type,
        details=json.dumps(details) if details is not None else None,
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    db.flush()
    return entry
