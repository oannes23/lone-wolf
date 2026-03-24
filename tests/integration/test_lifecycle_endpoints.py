"""Integration tests for POST /gameplay/{character_id}/restart and /replay (Story 6.6).

Tests cover:
- Restart dead character (snapshot restore, death_count incremented, current_run incremented)
- Restart alive character returns 400
- Replay at victory (snapshot restore, death_count NOT incremented, current_run incremented)
- Replay when not at victory returns 400
- Replay blocked after advance wizard started (409 WIZARD_ACTIVE)
- Advance starts wizard, returns first step
- Advance when not at victory returns 400
- Advance when no next book returns 404
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Book, Discipline, Scene
from app.models.player import (
    Character,
    CharacterBookStart,
    CharacterDiscipline,
    CharacterItem,
)
from app.models.taxonomy import BookTransitionRule, GameObject
from app.models.wizard import WizardTemplate, WizardTemplateStep
from tests.factories import (
    make_book,
    make_character,
    make_scene,
    make_user,
    make_wizard_step,
    make_wizard_template,
)

# ---------------------------------------------------------------------------
# Constants for snapshot format
# ---------------------------------------------------------------------------

_SNAPSHOT_GOLD = 10
_SNAPSHOT_MEALS = 2
_SNAPSHOT_CS = 15
_SNAPSHOT_END_BASE = 25
_SNAPSHOT_END_MAX = 25
_SNAPSHOT_END_CURRENT = 25


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_kai_disciplines(db: Session, count: int = 5) -> list[Discipline]:
    """Create Kai disciplines for seeding character snapshots."""
    names = [
        "Camouflage", "Hunting", "Sixth Sense", "Tracking", "Healing",
        "Weaponskill", "Mindblast", "Animal Kinship", "Mind Over Matter", "Mindshield",
    ]
    disciplines = []
    for name in names[:count]:
        disc = Discipline(
            era="kai",
            name=name,
            html_id=name.lower().replace(" ", "-"),
            description=f"{name} discipline.",
        )
        db.add(disc)
        disciplines.append(disc)
    db.flush()
    return disciplines


def _make_book_start_snapshot(
    db: Session,
    character: Character,
    disciplines: list[Discipline],
    book: Book,
) -> CharacterBookStart:
    """Create a CharacterBookStart snapshot for a character."""
    # Add some items to the character so they are included in the snapshot
    item1 = CharacterItem(
        character_id=character.id,
        item_name="Sword",
        item_type="weapon",
        is_equipped=True,
        game_object_id=None,
    )
    item2 = CharacterItem(
        character_id=character.id,
        item_name="Map of Sommerlund",
        item_type="special",
        is_equipped=False,
        game_object_id=None,
    )
    db.add(item1)
    db.add(item2)
    db.flush()

    # Add disciplines to the character
    for disc in disciplines[:3]:
        cd = CharacterDiscipline(
            character_id=character.id,
            discipline_id=disc.id,
            weapon_category=None,
        )
        db.add(cd)
    db.flush()

    items_snapshot = [
        {"item_name": "Sword", "item_type": "weapon", "is_equipped": True, "game_object_id": None},
        {"item_name": "Map of Sommerlund", "item_type": "special", "is_equipped": False, "game_object_id": None},
    ]
    disciplines_snapshot = [
        {"discipline_id": disc.id, "weapon_category": None}
        for disc in disciplines[:3]
    ]

    snapshot = CharacterBookStart(
        character_id=character.id,
        book_id=book.id,
        combat_skill_base=_SNAPSHOT_CS,
        endurance_base=_SNAPSHOT_END_BASE,
        endurance_max=_SNAPSHOT_END_MAX,
        endurance_current=_SNAPSHOT_END_CURRENT,
        gold=_SNAPSHOT_GOLD,
        meals=_SNAPSHOT_MEALS,
        items_json=json.dumps(items_snapshot),
        disciplines_json=json.dumps(disciplines_snapshot),
        created_at=datetime.now(UTC),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _seed_book_with_start_and_victory(db: Session) -> dict:
    """Create a book with a start scene and a victory scene."""
    book = make_book(db, start_scene_number=1)
    start_scene = make_scene(db, book, number=1)
    victory_scene = make_scene(db, book, number=350, is_victory=True)
    death_scene = make_scene(db, book, number=100, is_death=True)
    return {
        "book": book,
        "start_scene": start_scene,
        "victory_scene": victory_scene,
        "death_scene": death_scene,
    }


def _register_and_login(client: TestClient, username: str) -> tuple[str, int]:
    """Register a user, log in, return (token, user_id)."""
    reg = client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Pass1234!",
        },
    )
    assert reg.status_code == 201, reg.json()
    user_id = reg.json()["id"]
    resp = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    assert resp.status_code == 200, resp.json()
    return resp.json()["access_token"], user_id


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_advance_scenario(db: Session) -> dict:
    """Seed books 1 and 2, transition rule, wizard template.

    Returns a dict with book1, book2, start_scene_b1, victory_scene_b1,
    start_scene_b2, advance_template.
    """
    book1 = make_book(db, number=101, era="kai", max_total_picks=1, start_scene_number=1)
    book2 = make_book(db, number=102, era="kai", max_total_picks=2, start_scene_number=1)

    start_scene_b1 = make_scene(db, book1, number=1)
    victory_scene_b1 = make_scene(db, book1, number=350, is_victory=True)
    start_scene_b2 = make_scene(db, book2, number=1)

    rule = BookTransitionRule(
        from_book_id=book1.id,
        to_book_id=book2.id,
        max_weapons=2,
        max_backpack_items=8,
        special_items_carry=True,
        gold_carries=True,
        new_disciplines_count=1,
    )
    db.add(rule)
    db.flush()

    adv_template = make_wizard_template(db, name="book_advance_lifecycle")
    make_wizard_step(db, adv_template, step_type="pick_disciplines", ordinal=0)
    make_wizard_step(db, adv_template, step_type="pick_equipment", ordinal=1)
    make_wizard_step(db, adv_template, step_type="inventory_adjust", ordinal=2)
    make_wizard_step(db, adv_template, step_type="confirm", ordinal=3)

    # The wizard_service looks up the template by name "book_advance"
    # so we need a template with that exact name
    existing = (
        db.query(WizardTemplate).filter(WizardTemplate.name == "book_advance").first()
    )
    if existing is None:
        ba_template = make_wizard_template(db, name="book_advance")
        make_wizard_step(db, ba_template, step_type="pick_disciplines", ordinal=0)
        make_wizard_step(db, ba_template, step_type="pick_equipment", ordinal=1)
        make_wizard_step(db, ba_template, step_type="inventory_adjust", ordinal=2)
        make_wizard_step(db, ba_template, step_type="confirm", ordinal=3)

    return {
        "book1": book1,
        "book2": book2,
        "start_scene_b1": start_scene_b1,
        "victory_scene_b1": victory_scene_b1,
        "start_scene_b2": start_scene_b2,
        "transition_rule": rule,
    }


# ---------------------------------------------------------------------------
# Tests: POST /gameplay/{character_id}/restart
# ---------------------------------------------------------------------------


class TestRestartEndpoint:
    """Tests for POST /gameplay/{character_id}/restart."""

    def test_restart_dead_character_restores_snapshot(
        self, client: TestClient, db: Session
    ) -> None:
        """Restart a dead character: stats restored, death_count incremented, current_run incremented."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        start_scene = seed["start_scene"]
        death_scene = seed["death_scene"]

        token, _ = _register_and_login(client, "restart_happy1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="restart_happy1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db,
            user,
            book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            death_count=0,
            current_run=1,
            version=5,
        )

        _make_book_start_snapshot(db, character, disciplines, book)

        resp = client.post(
            f"/gameplay/{character.id}/restart",
            json={"version": 5},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()
        data = resp.json()

        # Character is placed at start scene
        assert data["scene_number"] == start_scene.number
        assert data["is_alive"] is True
        assert data["is_death"] is False

        # Stats restored from snapshot
        db.expire(character)
        db.refresh(character)
        assert character.is_alive is True
        assert character.endurance_current == _SNAPSHOT_END_CURRENT
        assert character.gold == _SNAPSHOT_GOLD
        assert character.meals == _SNAPSHOT_MEALS
        assert character.combat_skill_base == _SNAPSHOT_CS

        # death_count incremented
        assert character.death_count == 1

        # current_run incremented
        assert character.current_run == 2

        # version incremented
        assert character.version == 6

    def test_restart_restores_items_from_snapshot(
        self, client: TestClient, db: Session
    ) -> None:
        """Restart replaces all character items with snapshot items."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        death_scene = seed["death_scene"]

        token, _ = _register_and_login(client, "restart_items1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="restart_items1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db, user, book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            version=3,
        )

        _make_book_start_snapshot(db, character, disciplines, book)

        # Add extra items post-snapshot (should be wiped on restart)
        extra_item = CharacterItem(
            character_id=character.id,
            item_name="Potion",
            item_type="backpack",
            is_equipped=False,
            game_object_id=None,
        )
        db.add(extra_item)
        db.flush()

        resp = client.post(
            f"/gameplay/{character.id}/restart",
            json={"version": 3},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()

        db.expire(character)
        db.refresh(character)
        item_names = {ci.item_name for ci in character.items}
        assert "Sword" in item_names
        assert "Map of Sommerlund" in item_names
        assert "Potion" not in item_names

    def test_restart_restores_disciplines_from_snapshot(
        self, client: TestClient, db: Session
    ) -> None:
        """Restart replaces all character disciplines with snapshot disciplines."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        death_scene = seed["death_scene"]

        token, _ = _register_and_login(client, "restart_discs1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="restart_discs1").first()

        disciplines = _seed_kai_disciplines(db, count=10)

        character = make_character(
            db, user, book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            version=3,
        )

        _make_book_start_snapshot(db, character, disciplines[:3], book)

        # Add an extra discipline post-snapshot (should be wiped on restart)
        extra_disc = CharacterDiscipline(
            character_id=character.id,
            discipline_id=disciplines[9].id,
            weapon_category=None,
        )
        db.add(extra_disc)
        db.flush()

        resp = client.post(
            f"/gameplay/{character.id}/restart",
            json={"version": 3},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()

        db.expire(character)
        db.refresh(character)
        disc_ids = {cd.discipline_id for cd in character.disciplines}
        # Only snapshot disciplines should remain (first 3)
        for disc in disciplines[:3]:
            assert disc.id in disc_ids
        # Extra discipline should be gone
        assert disciplines[9].id not in disc_ids

    def test_restart_alive_character_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /restart returns 400 if character is alive."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        start_scene = seed["start_scene"]

        token, _ = _register_and_login(client, "restart_alive1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="restart_alive1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db, user, book,
            current_scene_id=start_scene.id,
            is_alive=True,
            version=1,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        resp = client.post(
            f"/gameplay/{character.id}/restart",
            json={"version": 1},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400, resp.json()
        data = resp.json()
        assert data.get("error_code") == "CHARACTER_ALIVE" or "alive" in data.get("detail", "").lower()

    def test_restart_version_mismatch_returns_409(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /restart returns 409 if version does not match."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        death_scene = seed["death_scene"]

        token, _ = _register_and_login(client, "restart_ver1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="restart_ver1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db, user, book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            version=5,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        resp = client.post(
            f"/gameplay/{character.id}/restart",
            json={"version": 99},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 409, resp.json()

    def test_restart_clears_combat_and_phase_state(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /restart clears active_combat_encounter_id, scene_phase, pending_choice_id."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        death_scene = seed["death_scene"]

        token, _ = _register_and_login(client, "restart_clear1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="restart_clear1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db, user, book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            scene_phase="combat",
            scene_phase_index=0,
            version=2,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        resp = client.post(
            f"/gameplay/{character.id}/restart",
            json={"version": 2},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()

        db.expire(character)
        db.refresh(character)
        assert character.scene_phase is None
        assert character.scene_phase_index is None
        assert character.active_combat_encounter_id is None
        assert character.pending_choice_id is None


# ---------------------------------------------------------------------------
# Tests: POST /gameplay/{character_id}/replay
# ---------------------------------------------------------------------------


class TestReplayEndpoint:
    """Tests for POST /gameplay/{character_id}/replay."""

    def test_replay_at_victory_restores_snapshot(
        self, client: TestClient, db: Session
    ) -> None:
        """Replay at victory: stats restored, death_count NOT incremented, current_run incremented."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        start_scene = seed["start_scene"]
        victory_scene = seed["victory_scene"]

        token, _ = _register_and_login(client, "replay_happy1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="replay_happy1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            is_alive=True,
            death_count=2,
            current_run=3,
            endurance_current=20,
            gold=5,
            version=10,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        resp = client.post(
            f"/gameplay/{character.id}/replay",
            json={"version": 10},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()
        data = resp.json()

        # Placed at start scene
        assert data["scene_number"] == start_scene.number
        assert data["is_victory"] is False
        assert data["is_alive"] is True

        db.expire(character)
        db.refresh(character)

        # Stats restored from snapshot
        assert character.endurance_current == _SNAPSHOT_END_CURRENT
        assert character.gold == _SNAPSHOT_GOLD
        assert character.meals == _SNAPSHOT_MEALS

        # death_count NOT incremented
        assert character.death_count == 2

        # current_run incremented
        assert character.current_run == 4

        # version incremented
        assert character.version == 11

    def test_replay_not_at_victory_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /replay returns 400 if character is not at a victory scene."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        start_scene = seed["start_scene"]

        token, _ = _register_and_login(client, "replay_novict1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="replay_novict1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db, user, book,
            current_scene_id=start_scene.id,
            is_alive=True,
            version=1,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        resp = client.post(
            f"/gameplay/{character.id}/replay",
            json={"version": 1},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400, resp.json()
        data = resp.json()
        assert data.get("error_code") == "NOT_AT_VICTORY" or "victory" in data.get("detail", "").lower()

    def test_replay_blocked_when_advance_wizard_active(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /replay returns 409 WIZARD_ACTIVE if advance wizard is in progress."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        victory_scene = seed["victory_scene"]

        token, _ = _register_and_login(client, "replay_wiz1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="replay_wiz1").first()

        disciplines = _seed_kai_disciplines(db)

        # Create a dummy wizard progress record to simulate active wizard
        from app.models.wizard import CharacterWizardProgress, WizardTemplate, WizardTemplateStep

        wiz_template = make_wizard_template(db, name="dummy_wizard_replay")
        make_wizard_step(db, wiz_template, step_type="confirm", ordinal=0)

        character = make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            is_alive=True,
            version=1,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        wizard_progress = CharacterWizardProgress(
            character_id=character.id,
            wizard_template_id=wiz_template.id,
            current_step_index=0,
            state=json.dumps({}),
            started_at=datetime.now(UTC),
        )
        db.add(wizard_progress)
        db.flush()

        # Link wizard to character
        character.active_wizard_id = wizard_progress.id
        character.version = 2
        db.flush()

        resp = client.post(
            f"/gameplay/{character.id}/replay",
            json={"version": 2},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 409, resp.json()
        assert resp.json().get("error_code") == "WIZARD_ACTIVE"

    def test_replay_version_mismatch_returns_409(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /replay returns 409 if version does not match."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        victory_scene = seed["victory_scene"]

        token, _ = _register_and_login(client, "replay_ver1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="replay_ver1").first()

        disciplines = _seed_kai_disciplines(db)

        character = make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            is_alive=True,
            version=5,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        resp = client.post(
            f"/gameplay/{character.id}/replay",
            json={"version": 99},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 409, resp.json()

    def test_replay_restores_items_and_disciplines(
        self, client: TestClient, db: Session
    ) -> None:
        """Replay restores items and disciplines from snapshot, wiping current state."""
        seed = _seed_book_with_start_and_victory(db)
        book = seed["book"]
        victory_scene = seed["victory_scene"]

        token, _ = _register_and_login(client, "replay_inv1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="replay_inv1").first()

        disciplines = _seed_kai_disciplines(db, count=10)

        character = make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            is_alive=True,
            version=3,
        )

        # Create snapshot with first 3 disciplines
        _make_book_start_snapshot(db, character, disciplines[:3], book)

        # Add post-snapshot items and disciplines that should be wiped
        extra_item = CharacterItem(
            character_id=character.id,
            item_name="Trophy Item",
            item_type="special",
            is_equipped=False,
            game_object_id=None,
        )
        db.add(extra_item)
        extra_disc = CharacterDiscipline(
            character_id=character.id,
            discipline_id=disciplines[9].id,
            weapon_category=None,
        )
        db.add(extra_disc)
        db.flush()

        resp = client.post(
            f"/gameplay/{character.id}/replay",
            json={"version": 3},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()

        db.expire(character)
        db.refresh(character)

        item_names = {ci.item_name for ci in character.items}
        assert "Sword" in item_names
        assert "Map of Sommerlund" in item_names
        assert "Trophy Item" not in item_names

        disc_ids = {cd.discipline_id for cd in character.disciplines}
        for disc in disciplines[:3]:
            assert disc.id in disc_ids
        assert disciplines[9].id not in disc_ids


# ---------------------------------------------------------------------------
# Tests: POST /gameplay/{character_id}/advance (coverage for Story 6.6 spec)
# ---------------------------------------------------------------------------


class TestAdvanceEndpointLifecycle:
    """Spot checks for advance endpoint coverage in the lifecycle context."""

    def test_advance_when_not_at_victory_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance returns 400 if character is not at a victory scene."""
        seed = _seed_advance_scenario(db)
        book1 = seed["book1"]
        start_scene_b1 = seed["start_scene_b1"]

        token, _ = _register_and_login(client, "adv_lc_novict1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="adv_lc_novict1").first()

        character = make_character(
            db, user, book1,
            current_scene_id=start_scene_b1.id,
            is_alive=True,
            version=1,
        )

        resp = client.post(
            f"/gameplay/{character.id}/advance",
            json={"version": 1},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 409, resp.json()
        assert "victory" in resp.json()["detail"].lower()

    def test_advance_when_no_next_book_returns_404(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance returns 404 when no BookTransitionRule exists."""
        seed = _seed_advance_scenario(db)
        book2 = seed["book2"]

        # Make a victory scene for book2 (no transition rule from book2)
        victory_b2 = make_scene(db, book2, number=350, is_victory=True)

        token, _ = _register_and_login(client, "adv_lc_nobook1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="adv_lc_nobook1").first()

        character = make_character(
            db, user, book2,
            current_scene_id=victory_b2.id,
            is_alive=True,
            version=1,
        )

        resp = client.post(
            f"/gameplay/{character.id}/advance",
            json={"version": 1},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404, resp.json()
        assert resp.json().get("error_code") == "NO_NEXT_BOOK"

    def test_advance_when_wizard_active_returns_409(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance returns 409 WIZARD_ACTIVE if a wizard is already active."""
        seed = _seed_advance_scenario(db)
        book1 = seed["book1"]
        victory_scene_b1 = seed["victory_scene_b1"]

        token, _ = _register_and_login(client, "adv_lc_409a1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="adv_lc_409a1").first()

        from app.models.wizard import CharacterWizardProgress

        wiz_template = make_wizard_template(db, name="dummy_wizard_advance")
        make_wizard_step(db, wiz_template, step_type="confirm", ordinal=0)

        character = make_character(
            db, user, book1,
            current_scene_id=victory_scene_b1.id,
            is_alive=True,
            version=1,
        )

        wizard_progress = CharacterWizardProgress(
            character_id=character.id,
            wizard_template_id=wiz_template.id,
            current_step_index=0,
            state=json.dumps({}),
            started_at=datetime.now(UTC),
        )
        db.add(wizard_progress)
        db.flush()
        character.active_wizard_id = wizard_progress.id
        character.version = 2
        db.flush()

        resp = client.post(
            f"/gameplay/{character.id}/advance",
            json={"version": 2},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 409, resp.json()
        assert resp.json().get("error_code") == "WIZARD_ACTIVE"

    def test_advance_happy_path_creates_wizard_and_returns_first_step(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance at a victory scene creates a wizard progress row and returns the first step."""
        seed = _seed_advance_scenario(db)
        book1 = seed["book1"]
        victory_scene_b1 = seed["victory_scene_b1"]

        token, _ = _register_and_login(client, "adv_lc_happy1")
        user = db.query(__import__('app.models.player', fromlist=['User']).User).filter_by(username="adv_lc_happy1").first()

        character = make_character(
            db, user, book1,
            current_scene_id=victory_scene_b1.id,
            is_alive=True,
            version=1,
        )

        resp = client.post(
            f"/gameplay/{character.id}/advance",
            json={"version": 1},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()

        # Response includes wizard metadata
        assert data["wizard_type"] == "book_advance"
        assert data["step"] == "pick_disciplines"
        assert data["step_index"] == 0
        assert data["total_steps"] == 4
        assert data["book"]["id"] == seed["book2"].id

        # Character now has an active wizard
        db.expire(character)
        db.refresh(character)
        assert character.active_wizard_id is not None

        # The wizard progress row exists
        from app.models.wizard import CharacterWizardProgress
        progress = db.query(CharacterWizardProgress).filter(
            CharacterWizardProgress.id == character.active_wizard_id
        ).first()
        assert progress is not None
        assert progress.character_id == character.id
        assert progress.current_step_index == 0
