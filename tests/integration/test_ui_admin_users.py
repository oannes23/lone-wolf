"""Integration tests for Story 9.4: Admin User & Character Management UI.

Covers:
- GET /admin/ui/users returns 200 with user list
- GET /admin/ui/users without auth redirects to admin login
- POST /admin/ui/users/{id}/max-characters updates max_characters
- POST /admin/ui/users/{id}/max-characters with invalid value returns 422
- GET /admin/ui/characters returns character list
- GET /admin/ui/characters?deleted=deleted shows only deleted characters
- GET /admin/ui/characters?user_id=N filters by user
- POST /admin/ui/characters/{id}/restore restores a soft-deleted character
- POST /admin/ui/characters/{id}/restore on non-deleted character returns 400
- GET /admin/ui/events returns event list
- GET /admin/ui/events?character_id=N filters by character
- GET /admin/ui/events?event_type=X filters by event type
- Pagination works for characters and events
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.admin import AdminUser
from app.models.content import Book, Scene
from app.models.player import Character, CharacterEvent, User
from app.services.auth_service import create_admin_token, hash_password
from tests.factories import make_book, make_character, make_scene, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(db: Session, username: str = "useradmin") -> AdminUser:
    """Create and flush an AdminUser, return the instance."""
    admin = AdminUser(
        username=username,
        password_hash=hash_password("AdminPass1!"),
    )
    db.add(admin)
    db.flush()
    return admin


def _admin_cookie(admin: AdminUser) -> str:
    """Generate an admin_session JWT for the given admin."""
    return create_admin_token(admin_id=admin.id)


def _make_character_event(
    db: Session,
    character: Character,
    scene: Scene,
    *,
    event_type: str = "gold_change",
    seq: int = 1,
    phase: str | None = "items",
    details: str | None = None,
) -> CharacterEvent:
    """Create and flush a CharacterEvent, return the instance."""
    event = CharacterEvent(
        character_id=character.id,
        scene_id=scene.id,
        run_number=character.current_run,
        event_type=event_type,
        seq=seq,
        phase=phase,
        details=details,
        created_at=datetime.now(tz=UTC),
    )
    db.add(event)
    db.flush()
    return event


# ---------------------------------------------------------------------------
# GET /admin/ui/users
# ---------------------------------------------------------------------------


class TestAdminUserList:
    def test_returns_200_with_user_table(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db)
        make_user(db)

        resp = client.get(
            "/admin/ui/users",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"<table" in resp.content
        assert b"Users" in resp.content

    def test_unauthenticated_redirects_to_admin_login(self, client: TestClient) -> None:
        resp = client.get("/admin/ui/users", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_shows_user_data_in_table(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "useradmin2")
        user = make_user(db, username="shownuser", email="shown@test.com")
        book = make_book(db)
        make_character(db, user, book)

        resp = client.get(
            "/admin/ui/users",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "shownuser" in content
        assert "shown@test.com" in content

    def test_shows_max_characters_input_field(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "maxcharadmin")
        make_user(db, username="maxcharuser", max_characters=5)

        resp = client.get(
            "/admin/ui/users",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b'type="number"' in resp.content
        assert b'name="max_characters"' in resp.content

    def test_shows_character_count_for_user(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "countadmin")
        user = make_user(db, username="countuser")
        book = make_book(db)
        make_character(db, user, book)
        make_character(db, user, book)
        # deleted character should not count
        make_character(db, user, book, is_deleted=True)

        resp = client.get(
            "/admin/ui/users",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        # Two active characters
        assert "2" in content

    def test_shows_htmx_post_attribute_for_inline_edit(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "htmxadmin")
        make_user(db, username="htmxuser")

        resp = client.get(
            "/admin/ui/users",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"hx-post" in resp.content


# ---------------------------------------------------------------------------
# POST /admin/ui/users/{id}/max-characters
# ---------------------------------------------------------------------------


class TestAdminUpdateMaxCharacters:
    def test_updates_max_characters_and_returns_partial(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "updateadmin1")
        user = make_user(db, username="updateuser1", max_characters=3)

        resp = client.post(
            f"/admin/ui/users/{user.id}/max-characters",
            data={"max_characters": "7"},
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"7" in resp.content

        db.refresh(user)
        assert user.max_characters == 7

    def test_invalid_value_below_one_returns_422(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "updateadmin2")
        user = make_user(db, username="updateuser2", max_characters=3)

        resp = client.post(
            f"/admin/ui/users/{user.id}/max-characters",
            data={"max_characters": "0"},
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 422

    def test_nonexistent_user_returns_404(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "updateadmin3")

        resp = client.post(
            "/admin/ui/users/99999/max-characters",
            data={"max_characters": "5"},
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 404

    def test_unauthenticated_redirects(self, client: TestClient, db: Session) -> None:
        user = make_user(db, username="unauthupdateuser")
        resp = client.post(
            f"/admin/ui/users/{user.id}/max-characters",
            data={"max_characters": "5"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_returned_partial_contains_input_with_new_value(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "updateadmin4")
        user = make_user(db, username="updateuser4", max_characters=2)

        resp = client.post(
            f"/admin/ui/users/{user.id}/max-characters",
            data={"max_characters": "9"},
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b'type="number"' in resp.content
        assert b"9" in resp.content


# ---------------------------------------------------------------------------
# GET /admin/ui/characters
# ---------------------------------------------------------------------------


class TestAdminCharacterList:
    def test_returns_200_with_character_table(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "charadmin1")
        user = make_user(db, username="charlistuser1")
        book = make_book(db)
        make_character(db, user, book, name="Lone Wolf Alpha")

        resp = client.get(
            "/admin/ui/characters",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"<table" in resp.content
        assert b"Lone Wolf Alpha" in resp.content

    def test_unauthenticated_redirects_to_admin_login(self, client: TestClient) -> None:
        resp = client.get("/admin/ui/characters", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_default_shows_only_active_characters(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "charadmin2")
        user = make_user(db, username="charlistuser2")
        book = make_book(db)
        make_character(db, user, book, name="Active One")
        make_character(db, user, book, name="Deleted One", is_deleted=True)

        resp = client.get(
            "/admin/ui/characters",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Active One" in content
        assert "Deleted One" not in content

    def test_deleted_filter_shows_only_deleted(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "charadmin3")
        user = make_user(db, username="charlistuser3")
        book = make_book(db)
        make_character(db, user, book, name="Active Two")
        make_character(db, user, book, name="Deleted Two", is_deleted=True)

        resp = client.get(
            "/admin/ui/characters?deleted=deleted",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Deleted Two" in content
        assert "Active Two" not in content

    def test_all_filter_shows_all_characters(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "charadmin4")
        user = make_user(db, username="charlistuser4")
        book = make_book(db)
        make_character(db, user, book, name="Active Three")
        make_character(db, user, book, name="Deleted Three", is_deleted=True)

        resp = client.get(
            "/admin/ui/characters?deleted=all",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Active Three" in content
        assert "Deleted Three" in content

    def test_user_id_filter(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "charadmin5")
        user_a = make_user(db, username="charlistusera")
        user_b = make_user(db, username="charlistuserb")
        book = make_book(db)
        make_character(db, user_a, book, name="Char For UserA")
        make_character(db, user_b, book, name="Char For UserB")

        resp = client.get(
            f"/admin/ui/characters?deleted=all&user_id={user_a.id}",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Char For UserA" in content
        assert "Char For UserB" not in content

    def test_book_id_filter(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "charadmin6")
        user = make_user(db, username="charlistuser6")
        book_a = make_book(db)
        book_b = make_book(db)
        make_character(db, user, book_a, name="Char In BookA")
        make_character(db, user, book_b, name="Char In BookB")

        resp = client.get(
            f"/admin/ui/characters?deleted=all&book_id={book_a.id}",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Char In BookA" in content
        assert "Char In BookB" not in content

    def test_pagination_defaults_to_page_one(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "charpageadmin")
        user = make_user(db, username="charlistpageuser")
        book = make_book(db)
        # Create 30 characters to trigger pagination (25 per page)
        for i in range(30):
            make_character(db, user, book, name=f"Paginated Char {i}")

        resp = client.get(
            "/admin/ui/characters",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        # Should show pagination nav since total > 25
        content = resp.content.decode()
        assert "Next" in content

    def test_restore_button_visible_on_deleted_characters(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "charadmin7")
        user = make_user(db, username="charlistuser7")
        book = make_book(db)
        make_character(db, user, book, name="SoftDeleted", is_deleted=True)

        resp = client.get(
            "/admin/ui/characters?deleted=deleted",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"Restore" in resp.content


# ---------------------------------------------------------------------------
# POST /admin/ui/characters/{id}/restore
# ---------------------------------------------------------------------------


class TestAdminRestoreCharacter:
    def test_restores_deleted_character_and_returns_partial(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "restoreadmin1")
        user = make_user(db, username="restoreuser1")
        book = make_book(db)
        char = make_character(
            db, user, book, name="Deleted Hero", is_deleted=True
        )

        resp = client.post(
            f"/admin/ui/characters/{char.id}/restore",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        # Row partial should no longer have a Restore button
        content = resp.content.decode()
        assert "Active" in content

        db.refresh(char)
        assert char.is_deleted is False
        assert char.deleted_at is None

    def test_restore_on_non_deleted_character_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "restoreadmin2")
        user = make_user(db, username="restoreuser2")
        book = make_book(db)
        char = make_character(db, user, book, name="Active Hero", is_deleted=False)

        resp = client.post(
            f"/admin/ui/characters/{char.id}/restore",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 400

    def test_restore_nonexistent_character_returns_404(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "restoreadmin3")

        resp = client.post(
            "/admin/ui/characters/99999/restore",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 404

    def test_restore_unauthenticated_redirects(
        self, client: TestClient, db: Session
    ) -> None:
        user = make_user(db, username="unauthrestoreuser")
        book = make_book(db)
        char = make_character(db, user, book, is_deleted=True)

        resp = client.post(
            f"/admin/ui/characters/{char.id}/restore",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_restored_row_shows_is_deleted_false(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "restoreadmin4")
        user = make_user(db, username="restoreuser4")
        book = make_book(db)
        char = make_character(db, user, book, name="WasDeleted", is_deleted=True)

        resp = client.post(
            f"/admin/ui/characters/{char.id}/restore",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        # The row partial should show "No" for is_deleted
        assert "No" in content
        assert "Restore" not in content


# ---------------------------------------------------------------------------
# GET /admin/ui/events
# ---------------------------------------------------------------------------


class TestAdminEventList:
    def test_returns_200_with_event_table(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "eventadmin1")
        user = make_user(db, username="eventlistuser1")
        book = make_book(db)
        char = make_character(db, user, book)
        scene = make_scene(db, book)
        _make_character_event(db, char, scene, event_type="gold_change")

        resp = client.get(
            "/admin/ui/events",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"<table" in resp.content
        assert b"Character Events" in resp.content

    def test_unauthenticated_redirects_to_admin_login(self, client: TestClient) -> None:
        resp = client.get("/admin/ui/events", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_character_id_filter(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "eventadmin2")
        user = make_user(db, username="eventlistuser2")
        book = make_book(db)
        char_a = make_character(db, user, book)
        char_b = make_character(db, user, book)
        scene = make_scene(db, book)
        # Use distinct event types so we can distinguish which character's events appear
        _make_character_event(db, char_a, scene, event_type="gold_change", seq=1)
        _make_character_event(db, char_b, scene, event_type="meal_consumed", seq=2)

        resp = client.get(
            f"/admin/ui/events?character_id={char_a.id}",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "gold_change" in content
        assert "meal_consumed" not in content

    def test_event_type_filter(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "eventadmin3")
        user = make_user(db, username="eventlistuser3")
        book = make_book(db)
        char = make_character(db, user, book)
        scene = make_scene(db, book)
        _make_character_event(db, char, scene, event_type="gold_change", seq=1)
        _make_character_event(db, char, scene, event_type="meal_consumed", seq=2)

        resp = client.get(
            "/admin/ui/events?event_type=gold_change",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "gold_change" in content
        assert "meal_consumed" not in content

    def test_scene_id_filter(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "eventadmin4")
        user = make_user(db, username="eventlistuser4")
        book = make_book(db)
        char = make_character(db, user, book)
        scene_a = make_scene(db, book)
        scene_b = make_scene(db, book)
        # Use distinct event types to differentiate events in the table
        _make_character_event(db, char, scene_a, event_type="gold_change", seq=1)
        _make_character_event(db, char, scene_b, event_type="meal_consumed", seq=2)

        resp = client.get(
            f"/admin/ui/events?scene_id={scene_a.id}",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "gold_change" in content
        # scene_b's event should not appear
        assert "meal_consumed" not in content

    def test_pagination_works_for_events(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "eventpageadmin")
        user = make_user(db, username="eventpageuser")
        book = make_book(db)
        char = make_character(db, user, book)
        scene = make_scene(db, book)
        # Create 55 events to trigger pagination (50 per page)
        for seq in range(1, 56):
            _make_character_event(
                db, char, scene, event_type="gold_change", seq=seq
            )

        resp = client.get(
            "/admin/ui/events",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Next" in content

    def test_event_table_shows_expected_columns(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "eventcoladmin")
        user = make_user(db, username="eventcoluser")
        book = make_book(db)
        char = make_character(db, user, book)
        scene = make_scene(db, book)
        _make_character_event(
            db, char, scene, event_type="gold_change", seq=42, phase="items"
        )

        resp = client.get(
            "/admin/ui/events",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"gold_change" in resp.content
        assert b"items" in resp.content
        # Seq should appear
        assert b"42" in resp.content

    def test_empty_event_list_shows_no_results_message(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "eventemptyadmin")

        resp = client.get(
            "/admin/ui/events?character_id=99999",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"No events match" in resp.content
