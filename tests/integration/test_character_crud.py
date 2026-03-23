"""Integration tests for character CRUD and history endpoints (Story 6.7).

Covers:
- GET /characters — list active characters
- GET /characters/{id} — full character sheet
- DELETE /characters/{id} — soft delete
- GET /characters/{id}/history — decision log, filterable by run, paginated
- GET /characters/{id}/events — events, filterable by type/run/scene
- GET /characters/{id}/runs — per-run summaries
- Error cases: 401, 403, 404
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Book, Scene
from app.models.player import (
    Character,
    CharacterDiscipline,
    CharacterEvent,
    CharacterItem,
    DecisionLog,
    User,
)
from tests.factories import make_book, make_character, make_scene, make_user


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _register_and_login(client: TestClient, username: str) -> tuple[str, int]:
    """Register a user, log in, and return (access_token, user_id)."""
    reg = client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Pass1234!",
        },
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]
    resp = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    assert resp.status_code == 200
    return resp.json()["access_token"], user_id


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _make_character_with_scene(
    db: Session, user: User, book: Book, scene: Scene, **overrides: object
) -> Character:
    """Create a character placed at the given scene."""
    char = make_character(db, user, book, current_scene_id=scene.id, **overrides)
    return char


def _add_item(
    db: Session, character: Character, name: str = "Sword", item_type: str = "weapon"
) -> CharacterItem:
    """Add an item to a character's inventory."""
    item = CharacterItem(
        character_id=character.id,
        item_name=name,
        item_type=item_type,
        is_equipped=False,
    )
    db.add(item)
    db.flush()
    return item


def _add_discipline_row(
    db: Session, character: Character, discipline_id: int, name: str = "Camouflage"
) -> CharacterDiscipline:
    """Add a discipline to a character (assumes discipline already exists)."""
    cd = CharacterDiscipline(
        character_id=character.id,
        discipline_id=discipline_id,
        weapon_category=None,
    )
    db.add(cd)
    db.flush()
    return cd


def _add_decision(
    db: Session,
    character: Character,
    from_scene: Scene,
    to_scene: Scene,
    run_number: int = 1,
    action_type: str = "choice",
    choice_id: int | None = None,
) -> DecisionLog:
    """Add a decision log entry."""
    entry = DecisionLog(
        character_id=character.id,
        run_number=run_number,
        from_scene_id=from_scene.id,
        to_scene_id=to_scene.id,
        choice_id=choice_id,
        action_type=action_type,
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    db.flush()
    return entry


def _add_event(
    db: Session,
    character: Character,
    scene: Scene,
    event_type: str,
    run_number: int = 1,
    seq: int = 1,
    details: str | None = None,
) -> CharacterEvent:
    """Add a character event."""
    event = CharacterEvent(
        character_id=character.id,
        scene_id=scene.id,
        run_number=run_number,
        event_type=event_type,
        seq=seq,
        details=details,
        created_at=datetime.now(UTC),
    )
    db.add(event)
    db.flush()
    return event


# ---------------------------------------------------------------------------
# GET /characters
# ---------------------------------------------------------------------------


class TestListCharacters:
    def test_returns_active_characters_only(self, client: TestClient, db: Session) -> None:
        """List endpoint returns non-deleted characters for the authenticated user."""
        token, user_id = _register_and_login(client, "listuser1")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        scene = make_scene(db, book, number=1)

        char_active = _make_character_with_scene(db, user, book, scene, name="Active Hero")
        char_deleted = _make_character_with_scene(
            db, user, book, scene, name="Deleted Hero", is_deleted=True, deleted_at=datetime.now(UTC)
        )

        resp = client.get("/characters", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        ids = [c["id"] for c in data]
        assert char_active.id in ids
        assert char_deleted.id not in ids

    def test_returns_correct_fields(self, client: TestClient, db: Session) -> None:
        """List response includes id, name, book_title, current_scene_number, is_alive, death_count, current_run, version."""
        token, user_id = _register_and_login(client, "listuser2")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai", title="Flight from the Dark")
        scene = make_scene(db, book, number=5)

        make_character(
            db,
            user,
            book,
            name="Lone Wolf",
            current_scene_id=scene.id,
            is_alive=True,
            death_count=2,
            current_run=3,
            version=7,
        )

        resp = client.get("/characters", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        char = data[0]
        assert char["name"] == "Lone Wolf"
        assert char["book_title"] == "Flight from the Dark"
        assert char["current_scene_number"] == 5
        assert char["is_alive"] is True
        assert char["death_count"] == 2
        assert char["current_run"] == 3
        assert char["version"] == 7

    def test_does_not_show_other_users_characters(self, client: TestClient, db: Session) -> None:
        """Characters belonging to other users are not returned."""
        token_a, user_a_id = _register_and_login(client, "listuser3a")
        token_b, user_b_id = _register_and_login(client, "listuser3b")
        user_b = db.query(User).filter(User.id == user_b_id).first()
        book = make_book(db, number=1, era="kai")
        make_character(db, user_b, book, name="User B Hero")

        resp = client.get("/characters", headers=_auth(token_a))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_unauthenticated_returns_401(self, client: TestClient, db: Session) -> None:
        """Unauthenticated requests to list endpoint return 401."""
        resp = client.get("/characters")
        assert resp.status_code == 401

    def test_null_scene_when_no_current_scene(self, client: TestClient, db: Session) -> None:
        """current_scene_number is None when character has no scene set."""
        token, user_id = _register_and_login(client, "listuser4")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        make_character(db, user, book, name="No Scene", current_scene_id=None)

        resp = client.get("/characters", headers=_auth(token))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["current_scene_number"] is None


# ---------------------------------------------------------------------------
# GET /characters/{id}
# ---------------------------------------------------------------------------


class TestGetCharacterDetail:
    def test_returns_full_character_sheet(self, client: TestClient, db: Session) -> None:
        """Detail endpoint returns all expected fields including stats."""
        token, user_id = _register_and_login(client, "detailuser1")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai", title="Test Book")
        scene = make_scene(db, book, number=10)

        char = make_character(
            db,
            user,
            book,
            name="Detail Hero",
            combat_skill_base=15,
            endurance_base=25,
            endurance_max=27,
            endurance_current=20,
            gold=10,
            meals=3,
            is_alive=True,
            death_count=1,
            current_run=2,
            version=5,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        resp = client.get(f"/characters/{char.id}", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == char.id
        assert data["name"] == "Detail Hero"
        assert data["book_title"] == "Test Book"
        assert data["combat_skill_base"] == 15
        assert data["endurance_base"] == 25
        assert data["endurance_max"] == 27
        assert data["endurance_current"] == 20
        assert data["gold"] == 10
        assert data["meals"] == 3
        assert data["is_alive"] is True
        assert data["death_count"] == 1
        assert data["current_run"] == 2
        assert data["version"] == 5
        assert data["scene_phase"] == "choices"
        assert data["current_scene_number"] == 10

    def test_returns_full_inventory(self, client: TestClient, db: Session) -> None:
        """Detail endpoint includes all inventory items with character_item_id and is_equipped."""
        token, user_id = _register_and_login(client, "detailuser2")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        sword = _add_item(db, char, name="Sword", item_type="weapon")
        lembas = _add_item(db, char, name="Laumspur Potion", item_type="backpack")

        resp = client.get(f"/characters/{char.id}", headers=_auth(token))

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        item_names = {i["item_name"] for i in items}
        assert "Sword" in item_names
        assert "Laumspur Potion" in item_names
        for item in items:
            assert "character_item_id" in item
            assert "is_equipped" in item
            assert "item_type" in item

    def test_returns_disciplines(self, client: TestClient, db: Session) -> None:
        """Detail endpoint includes disciplines with name and weapon_category."""
        from app.models.content import Discipline

        token, user_id = _register_and_login(client, "detailuser3")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        disc = Discipline(
            era="kai",
            name="Camouflage",
            html_id="camouflage",
            description="Camouflage discipline.",
        )
        db.add(disc)
        db.flush()

        cd = CharacterDiscipline(
            character_id=char.id,
            discipline_id=disc.id,
            weapon_category=None,
        )
        db.add(cd)
        db.flush()

        resp = client.get(f"/characters/{char.id}", headers=_auth(token))

        assert resp.status_code == 200
        disciplines = resp.json()["disciplines"]
        assert len(disciplines) == 1
        assert disciplines[0]["name"] == "Camouflage"
        assert disciplines[0]["weapon_category"] is None

    def test_returns_404_for_nonexistent_character(self, client: TestClient, db: Session) -> None:
        """Requesting a non-existent character returns 404."""
        token, _ = _register_and_login(client, "detailuser4")
        resp = client.get("/characters/99999", headers=_auth(token))
        assert resp.status_code == 404

    def test_returns_403_for_other_users_character(self, client: TestClient, db: Session) -> None:
        """Requesting a character owned by a different user returns 403."""
        token_a, _ = _register_and_login(client, "detailuser5a")
        token_b, user_b_id = _register_and_login(client, "detailuser5b")
        user_b = db.query(User).filter(User.id == user_b_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user_b, book)

        resp = client.get(f"/characters/{char.id}", headers=_auth(token_a))
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, client: TestClient, db: Session) -> None:
        """Unauthenticated requests to character detail return 401."""
        resp = client.get("/characters/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /characters/{id}
# ---------------------------------------------------------------------------


class TestDeleteCharacter:
    def test_soft_delete_returns_204(self, client: TestClient, db: Session) -> None:
        """Soft delete returns 204 No Content."""
        token, user_id = _register_and_login(client, "deleteuser1")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        resp = client.delete(f"/characters/{char.id}", headers=_auth(token))
        assert resp.status_code == 204

    def test_deleted_character_disappears_from_list(self, client: TestClient, db: Session) -> None:
        """After soft delete, character does not appear in the list endpoint."""
        token, user_id = _register_and_login(client, "deleteuser2")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        resp = client.get("/characters", headers=_auth(token))
        assert len(resp.json()) == 1

        client.delete(f"/characters/{char.id}", headers=_auth(token))

        resp = client.get("/characters", headers=_auth(token))
        assert resp.json() == []

    def test_deleted_character_does_not_count_toward_limit(
        self, client: TestClient, db: Session
    ) -> None:
        """Soft-deleted characters do not count toward the max_characters limit.

        After soft-deleting one character from a full account (max=1), the
        max_characters check in create_character must allow a new character.
        """
        token, user_id = _register_and_login(client, "deleteuser3")
        user = db.query(User).filter(User.id == user_id).first()
        user.max_characters = 1
        db.flush()

        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        # With max_characters=1, character count should now be at limit
        active_count = (
            db.query(Character)
            .filter(Character.user_id == user.id, Character.is_deleted == False)  # noqa: E712
            .count()
        )
        assert active_count == 1

        # Soft delete
        client.delete(f"/characters/{char.id}", headers=_auth(token))

        # After deletion, count should be 0
        db.expire(char)
        active_count_after = (
            db.query(Character)
            .filter(Character.user_id == user.id, Character.is_deleted == False)  # noqa: E712
            .count()
        )
        assert active_count_after == 0

    def test_deleted_character_returns_404_on_detail(self, client: TestClient, db: Session) -> None:
        """Accessing a soft-deleted character via detail endpoint returns 404."""
        token, user_id = _register_and_login(client, "deleteuser4")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        client.delete(f"/characters/{char.id}", headers=_auth(token))

        resp = client.get(f"/characters/{char.id}", headers=_auth(token))
        assert resp.status_code == 404

    def test_cannot_delete_other_users_character(self, client: TestClient, db: Session) -> None:
        """Attempting to delete another user's character returns 403."""
        token_a, _ = _register_and_login(client, "deleteuser5a")
        token_b, user_b_id = _register_and_login(client, "deleteuser5b")
        user_b = db.query(User).filter(User.id == user_b_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user_b, book)

        resp = client.delete(f"/characters/{char.id}", headers=_auth(token_a))
        assert resp.status_code == 403

    def test_unauthenticated_delete_returns_401(self, client: TestClient, db: Session) -> None:
        """Unauthenticated delete returns 401."""
        resp = client.delete("/characters/1")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /characters/{id}/history
# ---------------------------------------------------------------------------


class TestCharacterHistory:
    def test_returns_history_in_chronological_order(self, client: TestClient, db: Session) -> None:
        """History entries are returned in chronological order."""
        token, user_id = _register_and_login(client, "histuser1")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)
        scene_c = make_scene(db, book, number=3)

        _add_decision(db, char, from_scene=scene_a, to_scene=scene_b, run_number=1)
        _add_decision(db, char, from_scene=scene_b, to_scene=scene_c, run_number=1)

        resp = client.get(f"/characters/{char.id}/history", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["scene_number"] == 1
        assert data["items"][1]["scene_number"] == 2

    def test_filterable_by_run(self, client: TestClient, db: Session) -> None:
        """History can be filtered by run number."""
        token, user_id = _register_and_login(client, "histuser2")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)
        scene_c = make_scene(db, book, number=10)

        _add_decision(db, char, from_scene=scene_a, to_scene=scene_b, run_number=1)
        _add_decision(db, char, from_scene=scene_a, to_scene=scene_c, run_number=2)

        resp = client.get(f"/characters/{char.id}/history?run=1", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["scene_number"] == scene_a.number
        assert data["items"][0]["target_scene_number"] == scene_b.number
        assert data["items"][0]["run_number"] == 1

    def test_pagination_limit_and_offset(self, client: TestClient, db: Session) -> None:
        """History supports limit and offset pagination."""
        token, user_id = _register_and_login(client, "histuser3")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        scenes = [make_scene(db, book, number=i) for i in range(1, 6)]
        for i in range(4):
            _add_decision(db, char, from_scene=scenes[i], to_scene=scenes[i + 1], run_number=1)

        resp = client.get(
            f"/characters/{char.id}/history?limit=2&offset=1", headers=_auth(token)
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 4
        assert data["limit"] == 2
        assert data["offset"] == 1
        assert len(data["items"]) == 2

    def test_empty_history_returns_empty_list(self, client: TestClient, db: Session) -> None:
        """Empty decision log returns an empty paginated list."""
        token, user_id = _register_and_login(client, "histuser4")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)

        resp = client.get(f"/characters/{char.id}/history", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_returns_403_for_other_users_character(self, client: TestClient, db: Session) -> None:
        """History for another user's character returns 403."""
        token_a, _ = _register_and_login(client, "histuser5a")
        token_b, user_b_id = _register_and_login(client, "histuser5b")
        user_b = db.query(User).filter(User.id == user_b_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user_b, book)

        resp = client.get(f"/characters/{char.id}/history", headers=_auth(token_a))
        assert resp.status_code == 403

    def test_returns_404_for_nonexistent_character(self, client: TestClient, db: Session) -> None:
        """History for a non-existent character returns 404."""
        token, _ = _register_and_login(client, "histuser6")
        resp = client.get("/characters/99999/history", headers=_auth(token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /characters/{id}/events
# ---------------------------------------------------------------------------


class TestCharacterEvents:
    def test_returns_events_in_seq_order(self, client: TestClient, db: Session) -> None:
        """Events are returned in seq order."""
        token, user_id = _register_and_login(client, "evtuser1")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)
        scene = make_scene(db, book, number=1)

        _add_event(db, char, scene, "item_pickup", run_number=1, seq=1)
        _add_event(db, char, scene, "gold_change", run_number=1, seq=2)

        resp = client.get(f"/characters/{char.id}/events", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        items = data["items"]
        assert items[0]["event_type"] == "item_pickup"
        assert items[0]["seq"] == 1
        assert items[1]["event_type"] == "gold_change"
        assert items[1]["seq"] == 2

    def test_filterable_by_event_type(self, client: TestClient, db: Session) -> None:
        """Events can be filtered by event_type."""
        token, user_id = _register_and_login(client, "evtuser2")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)
        scene = make_scene(db, book, number=1)

        _add_event(db, char, scene, "item_pickup", run_number=1, seq=1)
        _add_event(db, char, scene, "death", run_number=1, seq=2)
        _add_event(db, char, scene, "item_pickup", run_number=1, seq=3)

        resp = client.get(
            f"/characters/{char.id}/events?event_type=death", headers=_auth(token)
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["event_type"] == "death"

    def test_filterable_by_run(self, client: TestClient, db: Session) -> None:
        """Events can be filtered by run number."""
        token, user_id = _register_and_login(client, "evtuser3")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)
        scene = make_scene(db, book, number=1)

        _add_event(db, char, scene, "item_pickup", run_number=1, seq=1)
        _add_event(db, char, scene, "gold_change", run_number=2, seq=2)

        resp = client.get(f"/characters/{char.id}/events?run=2", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["event_type"] == "gold_change"
        assert data["items"][0]["run_number"] == 2

    def test_filterable_by_scene_id(self, client: TestClient, db: Session) -> None:
        """Events can be filtered by scene_id."""
        token, user_id = _register_and_login(client, "evtuser4")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)
        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)

        _add_event(db, char, scene_a, "item_pickup", run_number=1, seq=1)
        _add_event(db, char, scene_b, "gold_change", run_number=1, seq=2)

        resp = client.get(
            f"/characters/{char.id}/events?scene_id={scene_b.id}", headers=_auth(token)
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["scene_id"] == scene_b.id

    def test_pagination(self, client: TestClient, db: Session) -> None:
        """Events support limit and offset pagination."""
        token, user_id = _register_and_login(client, "evtuser5")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book)
        scene = make_scene(db, book, number=1)

        for i in range(5):
            _add_event(db, char, scene, "item_pickup", run_number=1, seq=i + 1)

        resp = client.get(
            f"/characters/{char.id}/events?limit=2&offset=2", headers=_auth(token)
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 2
        assert len(data["items"]) == 2

    def test_returns_403_for_other_users_character(self, client: TestClient, db: Session) -> None:
        """Events for another user's character returns 403."""
        token_a, _ = _register_and_login(client, "evtuser6a")
        token_b, user_b_id = _register_and_login(client, "evtuser6b")
        user_b = db.query(User).filter(User.id == user_b_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user_b, book)

        resp = client.get(f"/characters/{char.id}/events", headers=_auth(token_a))
        assert resp.status_code == 403

    def test_returns_404_for_nonexistent_character(self, client: TestClient, db: Session) -> None:
        """Events for a non-existent character returns 404."""
        token, _ = _register_and_login(client, "evtuser7")
        resp = client.get("/characters/99999/events", headers=_auth(token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /characters/{id}/runs
# ---------------------------------------------------------------------------


class TestCharacterRuns:
    def test_returns_run_summaries(self, client: TestClient, db: Session) -> None:
        """Runs endpoint returns per-run summaries with correct fields."""
        token, user_id = _register_and_login(client, "runuser1")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book, current_run=1)

        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)

        _add_decision(db, char, from_scene=scene_a, to_scene=scene_b, run_number=1)

        resp = client.get(f"/characters/{char.id}/runs", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        run1 = next(r for r in data if r["run_number"] == 1)
        assert run1["decision_count"] == 1
        assert run1["scenes_visited"] >= 1
        assert "outcome" in run1
        assert "started_at" in run1

    def test_in_progress_run_outcome(self, client: TestClient, db: Session) -> None:
        """A run without a death or victory event has outcome 'in_progress'."""
        token, user_id = _register_and_login(client, "runuser2")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book, current_run=1, is_alive=True)

        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)
        _add_decision(db, char, from_scene=scene_a, to_scene=scene_b, run_number=1)

        resp = client.get(f"/characters/{char.id}/runs", headers=_auth(token))

        assert resp.status_code == 200
        run1 = next(r for r in resp.json() if r["run_number"] == 1)
        assert run1["outcome"] == "in_progress"
        assert run1["death_scene_number"] is None

    def test_death_run_outcome(self, client: TestClient, db: Session) -> None:
        """A run with a death event has outcome 'death' and death_scene_number set."""
        token, user_id = _register_and_login(client, "runuser3")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book, current_run=2, is_alive=False, death_count=1)

        scene_a = make_scene(db, book, number=1)
        scene_death = make_scene(db, book, number=350, is_death=True)

        _add_decision(db, char, from_scene=scene_a, to_scene=scene_death, run_number=1)
        _add_event(db, char, scene_death, "death", run_number=1, seq=1)

        resp = client.get(f"/characters/{char.id}/runs", headers=_auth(token))

        assert resp.status_code == 200
        runs = resp.json()
        run1 = next(r for r in runs if r["run_number"] == 1)
        assert run1["outcome"] == "death"
        assert run1["death_scene_number"] == 350

    def test_multiple_runs(self, client: TestClient, db: Session) -> None:
        """Multiple runs are returned ordered by run_number."""
        token, user_id = _register_and_login(client, "runuser4")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book, current_run=2)

        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)
        scene_c = make_scene(db, book, number=3)

        _add_decision(db, char, from_scene=scene_a, to_scene=scene_b, run_number=1)
        _add_decision(db, char, from_scene=scene_a, to_scene=scene_c, run_number=2)
        _add_decision(db, char, from_scene=scene_b, to_scene=scene_c, run_number=2)

        resp = client.get(f"/characters/{char.id}/runs", headers=_auth(token))

        assert resp.status_code == 200
        runs = resp.json()
        run_numbers = [r["run_number"] for r in runs]
        # Should include both run 1 and run 2
        assert 1 in run_numbers
        assert 2 in run_numbers
        # Should be sorted
        assert run_numbers == sorted(run_numbers)
        run2 = next(r for r in runs if r["run_number"] == 2)
        assert run2["decision_count"] == 2

    def test_no_decisions_returns_current_run(self, client: TestClient, db: Session) -> None:
        """Even with no decisions, the current run is included as in_progress."""
        token, user_id = _register_and_login(client, "runuser5")
        user = db.query(User).filter(User.id == user_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user, book, current_run=1)

        resp = client.get(f"/characters/{char.id}/runs", headers=_auth(token))

        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 1
        assert runs[0]["run_number"] == 1
        assert runs[0]["outcome"] == "in_progress"
        assert runs[0]["decision_count"] == 0

    def test_returns_403_for_other_users_character(self, client: TestClient, db: Session) -> None:
        """Runs for another user's character returns 403."""
        token_a, _ = _register_and_login(client, "runuser6a")
        token_b, user_b_id = _register_and_login(client, "runuser6b")
        user_b = db.query(User).filter(User.id == user_b_id).first()
        book = make_book(db, number=1, era="kai")
        char = make_character(db, user_b, book)

        resp = client.get(f"/characters/{char.id}/runs", headers=_auth(token_a))
        assert resp.status_code == 403

    def test_returns_404_for_nonexistent_character(self, client: TestClient, db: Session) -> None:
        """Runs for a non-existent character returns 404."""
        token, _ = _register_and_login(client, "runuser7")
        resp = client.get("/characters/99999/runs", headers=_auth(token))
        assert resp.status_code == 404
