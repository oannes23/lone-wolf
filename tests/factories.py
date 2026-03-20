"""Test factories — helper functions for creating model instances in tests.

Each factory accepts a db session as its first argument, uses sensible defaults,
adds the object to the session, flushes to assign a database ID, and returns it.
Override any required field by passing keyword arguments.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.content import Book, Choice, CombatEncounter, Scene
from app.models.player import Character, User
from app.models.taxonomy import GameObject
from app.models.wizard import WizardTemplate, WizardTemplateStep

# ---------------------------------------------------------------------------
# Auto-incrementing counters for unique defaults
# ---------------------------------------------------------------------------
_counters: dict[str, itertools.count[int]] = {}


def _next(key: str) -> int:
    if key not in _counters:
        _counters[key] = itertools.count(1)
    return next(_counters[key])


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_book(db: Session, **overrides: object) -> Book:
    """Create a Book with defaults. Adds to session and flushes."""
    n = _next("book")
    defaults: dict[str, object] = {
        "slug": f"book-{n:03d}",
        "number": n,
        "title": f"Test Book {n}",
        "era": "kai",
        "series": "lone_wolf",
        "start_scene_number": 1,
        "max_total_picks": 1,
    }
    defaults.update(overrides)
    book = Book(**defaults)
    db.add(book)
    db.flush()
    return book


def make_scene(db: Session, book: Book, **overrides: object) -> Scene:
    """Create a Scene in the given book. Adds to session and flushes."""
    n = _next("scene")
    defaults: dict[str, object] = {
        "book_id": book.id,
        "number": n,
        "html_id": f"sect{n}",
        "narrative": f"Scene {n} narrative text.",
        "is_death": False,
        "is_victory": False,
        "must_eat": False,
        "loses_backpack": False,
        "source": "manual",
    }
    defaults.update(overrides)
    scene = Scene(**defaults)
    db.add(scene)
    db.flush()
    return scene


def make_choice(db: Session, scene: Scene, **overrides: object) -> Choice:
    """Create a Choice for the given scene. Adds to session and flushes."""
    n = _next("choice")
    defaults: dict[str, object] = {
        "scene_id": scene.id,
        "target_scene_number": n + 100,
        "raw_text": f"If you wish to go to {n + 100}, turn to {n + 100}.",
        "display_text": f"Turn to {n + 100}.",
        "ordinal": n,
        "source": "manual",
    }
    defaults.update(overrides)
    choice = Choice(**defaults)
    db.add(choice)
    db.flush()
    return choice


def make_encounter(db: Session, scene: Scene, **overrides: object) -> CombatEncounter:
    """Create a CombatEncounter for the given scene. Adds to session and flushes."""
    n = _next("encounter")
    defaults: dict[str, object] = {
        "scene_id": scene.id,
        "enemy_name": f"Test Foe {n}",
        "enemy_cs": 15,
        "enemy_end": 20,
        "ordinal": n,
        "mindblast_immune": False,
        "evasion_damage": 0,
        "source": "manual",
    }
    defaults.update(overrides)
    encounter = CombatEncounter(**defaults)
    db.add(encounter)
    db.flush()
    return encounter


def make_user(db: Session, **overrides: object) -> User:
    """Create a User with defaults. Adds to session and flushes."""
    n = _next("user")
    defaults: dict[str, object] = {
        "username": f"testuser{n}",
        "email": f"testuser{n}@example.com",
        "password_hash": "$2b$12$fakehashfortest000000000000000000000000000000000000000000",
        "max_characters": 3,
        "created_at": _now(),
    }
    defaults.update(overrides)
    user = User(**defaults)
    db.add(user)
    db.flush()
    return user


def make_character(db: Session, user: User, book: Book, **overrides: object) -> Character:
    """Create a Character for the given user and book. Adds to session and flushes."""
    n = _next("character")
    now = _now()
    defaults: dict[str, object] = {
        "user_id": user.id,
        "book_id": book.id,
        "name": f"Test Character {n}",
        "combat_skill_base": 15,
        "endurance_base": 25,
        "endurance_max": 25,
        "endurance_current": 25,
        "gold": 10,
        "meals": 2,
        "is_alive": True,
        "is_deleted": False,
        "death_count": 0,
        "current_run": 1,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    character = Character(**defaults)
    db.add(character)
    db.flush()
    return character


def make_game_object(db: Session, **overrides: object) -> GameObject:
    """Create a GameObject with defaults. Adds to session and flushes."""
    n = _next("game_object")
    defaults: dict[str, object] = {
        "kind": "item",
        "name": f"Test Item {n}",
        "aliases": "[]",
        "properties": "{}",
        "source": "manual",
    }
    defaults.update(overrides)
    obj = GameObject(**defaults)
    db.add(obj)
    db.flush()
    return obj


def make_wizard_template(db: Session, **overrides: object) -> WizardTemplate:
    """Create a WizardTemplate with defaults. Adds to session and flushes."""
    n = _next("wizard_template")
    defaults: dict[str, object] = {
        "name": f"test_wizard_{n}",
        "description": f"Test wizard template {n}",
    }
    defaults.update(overrides)
    template = WizardTemplate(**defaults)
    db.add(template)
    db.flush()
    return template


def make_wizard_step(
    db: Session, template: WizardTemplate, **overrides: object
) -> WizardTemplateStep:
    """Create a WizardTemplateStep for the given template. Adds to session and flushes."""
    n = _next("wizard_step")
    defaults: dict[str, object] = {
        "template_id": template.id,
        "step_type": "confirm",
        "ordinal": n,
    }
    defaults.update(overrides)
    step = WizardTemplateStep(**defaults)
    db.add(step)
    db.flush()
    return step
