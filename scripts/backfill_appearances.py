"""Backfill game_object_scene_appearances from existing DB data.

Scans combat encounters, scene items, scene game_object links, and
narrative text to populate the junction table.

Usage:
    uv run python scripts/backfill_appearances.py --book 01fftd
    uv run python scripts/backfill_appearances.py --all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.content import (  # noqa: E402
    Book,
    CombatEncounter,
    Scene,
    SceneItem,
)
from app.models.taxonomy import (  # noqa: E402
    GameObject,
    GameObjectSceneAppearance,
)


def _upsert_appearance(
    db: Session,
    game_object_id: int,
    scene_id: int,
    appearance_type: str,
) -> bool:
    """Insert an appearance if it doesn't already exist. Returns True if new."""
    existing = (
        db.query(GameObjectSceneAppearance)
        .filter_by(
            game_object_id=game_object_id,
            scene_id=scene_id,
            appearance_type=appearance_type,
        )
        .one_or_none()
    )
    if existing is not None:
        return False
    db.add(GameObjectSceneAppearance(
        game_object_id=game_object_id,
        scene_id=scene_id,
        appearance_type=appearance_type,
        source="auto",
    ))
    return True


def _parse_aliases(aliases_raw: str) -> list[str]:
    """Parse aliases from DB (JSON or Python repr format)."""
    if not aliases_raw or aliases_raw == "[]":
        return []
    try:
        result = json.loads(aliases_raw)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    import ast
    try:
        result = ast.literal_eval(aliases_raw)
        if isinstance(result, list):
            return result
    except (ValueError, SyntaxError):
        pass
    return []


def backfill_book(db: Session, book: Book) -> dict[str, int]:
    """Backfill scene appearances for all game objects relevant to a book."""
    counts: dict[str, int] = {
        "combat_foe": 0,
        "item": 0,
        "scene_object": 0,
        "narrative": 0,
    }

    scenes = db.query(Scene).filter_by(book_id=book.id).all()
    scene_map = {s.id: s for s in scenes}

    # 1. Combat foe appearances
    encounters = (
        db.query(CombatEncounter)
        .filter(
            CombatEncounter.scene_id.in_([s.id for s in scenes]),
            CombatEncounter.foe_game_object_id.isnot(None),
        )
        .all()
    )
    for enc in encounters:
        if _upsert_appearance(db, enc.foe_game_object_id, enc.scene_id, "combat_foe"):
            counts["combat_foe"] += 1

    # 2. Item appearances
    items = (
        db.query(SceneItem)
        .filter(
            SceneItem.scene_id.in_([s.id for s in scenes]),
            SceneItem.game_object_id.isnot(None),
        )
        .all()
    )
    for si in items:
        if _upsert_appearance(db, si.game_object_id, si.scene_id, "item"):
            counts["item"] += 1

    # 3. Scene-linked game objects
    for scene in scenes:
        if scene.game_object_id is not None:
            if _upsert_appearance(db, scene.game_object_id, scene.id, "scene_object"):
                counts["scene_object"] += 1

    # 4. Narrative text matching
    all_gos = db.query(GameObject).all()

    # Build search patterns: name + aliases, sorted longest-first to avoid
    # partial matches ("Giak Officer" before "Giak")
    search_entries: list[tuple[int, str]] = []  # (go_id, pattern_text)
    for go in all_gos:
        names = [go.name] + _parse_aliases(go.aliases)
        for name in names:
            if len(name) >= 3:  # skip very short names to avoid false positives
                search_entries.append((go.id, name))

    # Sort longest first
    search_entries.sort(key=lambda x: len(x[1]), reverse=True)

    # Precompile patterns with word boundaries
    compiled: list[tuple[int, re.Pattern[str]]] = []
    for go_id, text in search_entries:
        try:
            pattern = re.compile(r"\b" + re.escape(text) + r"\b", re.IGNORECASE)
            compiled.append((go_id, pattern))
        except re.error:
            continue

    for scene in scenes:
        narrative = scene.narrative or ""
        matched_ids: set[int] = set()
        for go_id, pattern in compiled:
            if go_id in matched_ids:
                continue
            if pattern.search(narrative):
                matched_ids.add(go_id)
                if _upsert_appearance(db, go_id, scene.id, "narrative"):
                    counts["narrative"] += 1

    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="backfill_appearances",
        description="Backfill game_object_scene_appearances from existing data.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--book", metavar="SLUG", help="Book slug to backfill")
    group.add_argument("--all", action="store_true", help="Backfill all books with scenes")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.all:
            books = db.query(Book).order_by(Book.number).all()
        else:
            books = db.query(Book).filter_by(slug=args.book).all()
            if not books:
                print(f"ERROR: Book '{args.book}' not found", file=sys.stderr)
                return 1

        books = [b for b in books if db.query(Scene).filter_by(book_id=b.id).count() > 0]

        for book in books:
            print(f"Backfilling Book {book.number}: {book.title} ...")
            counts = backfill_book(db, book)
            db.commit()
            total = sum(counts.values())
            print(f"  Added {total} appearances: {counts}")

        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
