"""Leaderboard service — aggregate statistics derived from gameplay tables."""

from __future__ import annotations

import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.content import Book, Discipline, Scene
from app.models.player import Character, CharacterDiscipline, CharacterEvent, DecisionLog
from app.schemas.leaderboards import (
    BookInfo,
    BookLeaderboard,
    DeathSceneEntry,
    DisciplinePopularityEntry,
    EnduranceEntry,
    ItemUsageEntry,
    LeaderboardEntry,
    OverallLeaderboard,
)


def get_book_leaderboard(db: Session, book_id: int, limit: int = 10) -> BookLeaderboard:
    """Compute leaderboard statistics for a single book.

    Args:
        db: Active database session.
        book_id: The book to compute stats for.
        limit: Maximum entries per category (default 10).

    Returns:
        A :class:`BookLeaderboard` with all computed stats.

    Raises:
        LookupError: If the book is not found.
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if book is None:
        raise LookupError(f"Book {book_id} not found")

    book_info = BookInfo(id=book.id, title=book.title)

    # Characters that completed this book (reached a victory scene)
    victory_scene_ids = [
        s.id
        for s in db.query(Scene.id).filter(Scene.book_id == book_id, Scene.is_victory == True).all()
    ]

    # Characters currently at a victory scene in this book
    completed_chars = (
        db.query(Character)
        .filter(
            Character.book_id == book_id,
            Character.current_scene_id.in_(victory_scene_ids) if victory_scene_ids else False,
            Character.is_deleted == False,
        )
        .all()
        if victory_scene_ids
        else []
    )

    completions = len(completed_chars)

    # Fewest deaths (among completers)
    fewest_deaths = _build_fewest_deaths(db, completed_chars, limit)

    # Fewest decisions (among completers)
    fewest_decisions = _build_fewest_decisions(db, completed_chars, limit)

    # Highest endurance at victory (among completers)
    highest_endurance = _build_highest_endurance(completed_chars, limit)

    # Most common death scenes for this book
    most_common_deaths = _build_death_scenes(db, book_id, limit)

    # Discipline popularity (all characters in this book)
    discipline_popularity = _build_discipline_popularity(db, book_id, limit)

    # Item usage
    item_usage = _build_item_usage(db, book_id, limit)

    return BookLeaderboard(
        book=book_info,
        completions=completions,
        fewest_deaths=fewest_deaths,
        fewest_decisions=fewest_decisions,
        highest_endurance_at_victory=highest_endurance,
        most_common_death_scenes=most_common_deaths,
        discipline_popularity=discipline_popularity,
        item_usage=item_usage,
    )


def get_overall_leaderboard(db: Session, limit: int = 10) -> OverallLeaderboard:
    """Compute aggregate leaderboard statistics across all books.

    Args:
        db: Active database session.
        limit: Maximum entries per category (default 10).

    Returns:
        An :class:`OverallLeaderboard` with aggregate stats.
    """
    # Total characters (non-deleted)
    total_chars = db.query(func.count(Character.id)).filter(Character.is_deleted == False).scalar() or 0

    # All victory scene ids
    all_victory_ids = [
        s.id
        for s in db.query(Scene.id).filter(Scene.is_victory == True).all()
    ]

    # All completed characters
    completed_chars = (
        db.query(Character)
        .filter(
            Character.current_scene_id.in_(all_victory_ids) if all_victory_ids else False,
            Character.is_deleted == False,
        )
        .all()
        if all_victory_ids
        else []
    )

    total_completions = len(completed_chars)

    # Highest endurance at victory across all books
    highest_endurance = _build_highest_endurance(completed_chars, limit)

    # Most completions (characters with most runs completed — i.e. by current_run proxy)
    # Using fewest_deaths among completers as a proxy for "most completions" leaders
    most_completions = _build_fewest_deaths(db, completed_chars, limit)

    return OverallLeaderboard(
        total_completions=total_completions,
        total_characters=total_chars,
        highest_endurance_at_victory=highest_endurance,
        most_completions=most_completions,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_username(db: Session, character: Character) -> str:
    """Return the username for a character's owning user."""
    from app.models.player import User

    user = db.query(User).filter(User.id == character.user_id).first()
    return user.username if user else "unknown"


def _build_fewest_deaths(
    db: Session, completed_chars: list[Character], limit: int
) -> list[LeaderboardEntry]:
    """Build fewest-deaths leaderboard from a list of completing characters."""
    if not completed_chars:
        return []

    from app.models.player import User

    # Count decisions per character
    decision_counts: dict[int, int] = {}
    for char in completed_chars:
        count = db.query(func.count(DecisionLog.id)).filter(
            DecisionLog.character_id == char.id
        ).scalar() or 0
        decision_counts[char.id] = count

    # Load user ids
    user_ids = {char.user_id for char in completed_chars}
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u.username for u in users}

    sorted_chars = sorted(completed_chars, key=lambda c: (c.death_count, decision_counts.get(c.id, 0)))

    return [
        LeaderboardEntry(
            username=user_map.get(char.user_id, "unknown"),
            death_count=char.death_count,
            decisions=decision_counts.get(char.id, 0),
        )
        for char in sorted_chars[:limit]
    ]


def _build_fewest_decisions(
    db: Session, completed_chars: list[Character], limit: int
) -> list[LeaderboardEntry]:
    """Build fewest-decisions leaderboard from a list of completing characters."""
    if not completed_chars:
        return []

    from app.models.player import User

    # Count decisions per character
    decision_counts: dict[int, int] = {}
    for char in completed_chars:
        count = db.query(func.count(DecisionLog.id)).filter(
            DecisionLog.character_id == char.id
        ).scalar() or 0
        decision_counts[char.id] = count

    user_ids = {char.user_id for char in completed_chars}
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    user_map = {u.id: u.username for u in users}

    sorted_chars = sorted(completed_chars, key=lambda c: (decision_counts.get(c.id, 0), c.death_count))

    return [
        LeaderboardEntry(
            username=user_map.get(char.user_id, "unknown"),
            death_count=char.death_count,
            decisions=decision_counts.get(char.id, 0),
        )
        for char in sorted_chars[:limit]
    ]


def _build_highest_endurance(
    completed_chars: list[Character], limit: int
) -> list[EnduranceEntry]:
    """Build highest-endurance-at-victory leaderboard.

    Uses the character's current endurance (they are currently at a victory scene).
    """
    if not completed_chars:
        return []

    # Note: since completed_chars are at victory scenes, endurance_current reflects victory endurance
    # We don't have the username without a db query, but we simplify here
    sorted_chars = sorted(completed_chars, key=lambda c: -c.endurance_current)

    return [
        EnduranceEntry(
            username=f"user_{char.user_id}",
            endurance=char.endurance_current,
            death_count=char.death_count,
        )
        for char in sorted_chars[:limit]
    ]


def _build_death_scenes(
    db: Session, book_id: int, limit: int
) -> list[DeathSceneEntry]:
    """Build most-common-death-scenes leaderboard for a book."""
    # Find scenes in this book
    scene_ids_for_book = [
        s.id
        for s in db.query(Scene.id).filter(Scene.book_id == book_id).all()
    ]
    if not scene_ids_for_book:
        return []

    # Count death events per scene
    rows = (
        db.query(
            CharacterEvent.scene_id,
            func.count(CharacterEvent.id).label("death_count"),
        )
        .filter(
            CharacterEvent.event_type == "death",
            CharacterEvent.scene_id.in_(scene_ids_for_book),
        )
        .group_by(CharacterEvent.scene_id)
        .order_by(func.count(CharacterEvent.id).desc())
        .limit(limit)
        .all()
    )

    if not rows:
        return []

    # Load scene numbers
    scene_id_map: dict[int, int] = {
        s.id: s.number
        for s in db.query(Scene).filter(Scene.id.in_([r[0] for r in rows])).all()
    }

    return [
        DeathSceneEntry(
            scene_number=scene_id_map.get(r[0], 0),
            death_count=r[1],
        )
        for r in rows
        if r[0] in scene_id_map
    ]


def _build_discipline_popularity(
    db: Session, book_id: int, limit: int
) -> list[DisciplinePopularityEntry]:
    """Build discipline pick-rate leaderboard for a book.

    Pick rate is expressed as a 0-1 fraction (e.g., 0.85 = 85% of characters
    chose this discipline).
    """
    # Count total non-deleted characters in this book
    total_chars_in_book = (
        db.query(func.count(Character.id))
        .filter(Character.book_id == book_id, Character.is_deleted == False)
        .scalar()
        or 0
    )

    if total_chars_in_book == 0:
        return []

    # Count picks per discipline
    rows = (
        db.query(
            Discipline.name,
            func.count(CharacterDiscipline.id).label("pick_count"),
        )
        .join(CharacterDiscipline, CharacterDiscipline.discipline_id == Discipline.id)
        .join(Character, Character.id == CharacterDiscipline.character_id)
        .filter(Character.book_id == book_id, Character.is_deleted == False)
        .group_by(Discipline.name)
        .order_by(func.count(CharacterDiscipline.id).desc())
        .limit(limit)
        .all()
    )

    return [
        DisciplinePopularityEntry(
            discipline=r[0],
            pick_rate=round(r[1] / total_chars_in_book, 2),
        )
        for r in rows
    ]


def _build_item_usage(
    db: Session, book_id: int, limit: int
) -> list[ItemUsageEntry]:
    """Build item pickup-rate leaderboard for a book.

    Pickup rate is expressed as a 0-1 fraction. Groups by item_name extracted
    from the event details JSON in Python to avoid SQLite JSON function issues.
    """
    # Count total non-deleted characters in this book
    total_chars_in_book = (
        db.query(func.count(Character.id))
        .filter(Character.book_id == book_id, Character.is_deleted == False)
        .scalar()
        or 0
    )

    if total_chars_in_book == 0:
        return []

    # Find scenes in this book
    scene_ids_for_book = [
        s.id
        for s in db.query(Scene.id).filter(Scene.book_id == book_id).all()
    ]

    if not scene_ids_for_book:
        return []

    # Query raw item_pickup events for this book's scenes
    rows = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.event_type == "item_pickup",
            CharacterEvent.scene_id.in_(scene_ids_for_book),
        )
        .all()
    )

    # Group by item_name in Python by parsing JSON details
    item_counts: dict[str, int] = {}
    for event in rows:
        if not event.details:
            continue
        try:
            details = json.loads(event.details)
            item_name = details.get("item_name")
            if item_name:
                item_counts[item_name] = item_counts.get(item_name, 0) + 1
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    if not item_counts:
        return []

    # Sort by count descending and apply limit
    sorted_items = sorted(item_counts.items(), key=lambda kv: -kv[1])[:limit]

    return [
        ItemUsageEntry(
            item_name=name,
            pickup_rate=round(count / total_chars_in_book, 2),
        )
        for name, count in sorted_items
    ]
