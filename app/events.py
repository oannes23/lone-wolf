"""Character event logging helpers.

Central helper for writing character_events rows with correct seq generation,
run tagging, and causality chain tracking.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.player import Character, CharacterEvent


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
