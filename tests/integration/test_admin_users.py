"""Integration tests for admin user management API endpoints.

Covers: update max_characters (happy path, 404, 422, non-admin rejection) and
restore soft-deleted character (happy path, 404, already-active 400, non-admin rejection).
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.models.admin import AdminUser
from app.services.auth_service import hash_password
from tests.factories import make_book, make_character, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(db, username: str = "adminuser", password: str = "AdminPass1!") -> AdminUser:
    """Insert an admin user directly into the test database."""
    admin = AdminUser(username=username, password_hash=hash_password(password))
    db.add(admin)
    db.flush()
    return admin


def _admin_token(client: TestClient, db, username: str = "adminuser") -> str:
    """Create an admin, log in, and return the access token."""
    _make_admin(db, username=username)
    resp = client.post(
        "/admin/auth/login",
        json={"username": username, "password": "AdminPass1!"},
    )
    return resp.json()["access_token"]


def _player_token(client: TestClient) -> str:
    """Register a player and return a player access token."""
    client.post(
        "/auth/register",
        json={"username": "playertest", "email": "playertest@test.com", "password": "Pass1234!"},
    )
    resp = client.post("/auth/login", data={"username": "playertest", "password": "Pass1234!"})
    return resp.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# PUT /admin/users/{id} — update max_characters
# ---------------------------------------------------------------------------


class TestUpdateMaxCharacters:
    def test_admin_can_update_max_characters(self, client: TestClient, db) -> None:
        """Admin can set a user's max_characters and gets the updated value back."""
        token = _admin_token(client, db, username="adminupdate1")
        user = make_user(db, max_characters=3)

        resp = client.put(
            f"/admin/users/{user.id}",
            json={"max_characters": 5},
            headers=_bearer(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == user.id
        assert data["username"] == user.username
        assert data["email"] == user.email
        assert data["max_characters"] == 5

    def test_update_persists_to_database(self, client: TestClient, db) -> None:
        """After a successful update, the new value is reflected in the database."""
        from app.models.player import User

        token = _admin_token(client, db, username="adminupdate2")
        user = make_user(db, max_characters=2)

        client.put(
            f"/admin/users/{user.id}",
            json={"max_characters": 10},
            headers=_bearer(token),
        )

        db.refresh(user)
        assert user.max_characters == 10

    def test_non_admin_update_returns_401(self, client: TestClient, db) -> None:
        """A player token is rejected on PUT /admin/users/{id}."""
        player_tok = _player_token(client)
        user = make_user(db)

        resp = client.put(
            f"/admin/users/{user.id}",
            json={"max_characters": 5},
            headers=_bearer(player_tok),
        )

        assert resp.status_code == 401

    def test_unauthenticated_update_returns_401(self, client: TestClient, db) -> None:
        """No token at all returns 401."""
        user = make_user(db)

        resp = client.put(f"/admin/users/{user.id}", json={"max_characters": 5})

        assert resp.status_code == 401

    def test_nonexistent_user_returns_404(self, client: TestClient, db) -> None:
        """PUT /admin/users/99999 returns 404 when the user does not exist."""
        token = _admin_token(client, db, username="adminupdate3")

        resp = client.put(
            "/admin/users/99999",
            json={"max_characters": 5},
            headers=_bearer(token),
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_max_characters_zero_returns_422(self, client: TestClient, db) -> None:
        """max_characters < 1 is rejected with 422 by Pydantic validation."""
        token = _admin_token(client, db, username="adminupdate4")
        user = make_user(db)

        resp = client.put(
            f"/admin/users/{user.id}",
            json={"max_characters": 0},
            headers=_bearer(token),
        )

        assert resp.status_code == 422

    def test_max_characters_negative_returns_422(self, client: TestClient, db) -> None:
        """Negative max_characters is rejected with 422 by Pydantic validation."""
        token = _admin_token(client, db, username="adminupdate5")
        user = make_user(db)

        resp = client.put(
            f"/admin/users/{user.id}",
            json={"max_characters": -3},
            headers=_bearer(token),
        )

        assert resp.status_code == 422

    def test_max_characters_one_is_valid(self, client: TestClient, db) -> None:
        """max_characters=1 is the minimum valid value."""
        token = _admin_token(client, db, username="adminupdate6")
        user = make_user(db)

        resp = client.put(
            f"/admin/users/{user.id}",
            json={"max_characters": 1},
            headers=_bearer(token),
        )

        assert resp.status_code == 200
        assert resp.json()["max_characters"] == 1


# ---------------------------------------------------------------------------
# PUT /admin/characters/{id}/restore — restore soft-deleted character
# ---------------------------------------------------------------------------


class TestRestoreCharacter:
    def test_admin_can_restore_deleted_character(self, client: TestClient, db) -> None:
        """Admin can restore a soft-deleted character; response shows is_deleted=false."""
        token = _admin_token(client, db, username="adminrestore1")
        user = make_user(db)
        book = make_book(db)
        character = make_character(
            db,
            user,
            book,
            is_deleted=True,
            deleted_at=datetime.now(tz=UTC),
        )

        resp = client.put(
            f"/admin/characters/{character.id}/restore",
            headers=_bearer(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == character.id
        assert data["name"] == character.name
        assert data["is_deleted"] is False

    def test_restore_clears_deleted_at_in_database(self, client: TestClient, db) -> None:
        """After restore, is_deleted=False and deleted_at=None in the database."""
        token = _admin_token(client, db, username="adminrestore2")
        user = make_user(db)
        book = make_book(db)
        character = make_character(
            db,
            user,
            book,
            is_deleted=True,
            deleted_at=datetime.now(tz=UTC),
        )

        client.put(
            f"/admin/characters/{character.id}/restore",
            headers=_bearer(token),
        )

        db.refresh(character)
        assert character.is_deleted is False
        assert character.deleted_at is None

    def test_non_admin_restore_returns_401(self, client: TestClient, db) -> None:
        """A player token is rejected on PUT /admin/characters/{id}/restore."""
        player_tok = _player_token(client)
        user = make_user(db)
        book = make_book(db)
        character = make_character(
            db,
            user,
            book,
            is_deleted=True,
            deleted_at=datetime.now(tz=UTC),
        )

        resp = client.put(
            f"/admin/characters/{character.id}/restore",
            headers=_bearer(player_tok),
        )

        assert resp.status_code == 401

    def test_unauthenticated_restore_returns_401(self, client: TestClient, db) -> None:
        """No token at all returns 401."""
        user = make_user(db)
        book = make_book(db)
        character = make_character(
            db,
            user,
            book,
            is_deleted=True,
            deleted_at=datetime.now(tz=UTC),
        )

        resp = client.put(f"/admin/characters/{character.id}/restore")

        assert resp.status_code == 401

    def test_nonexistent_character_returns_404(self, client: TestClient, db) -> None:
        """PUT /admin/characters/99999/restore returns 404 when character does not exist."""
        token = _admin_token(client, db, username="adminrestore3")

        resp = client.put(
            "/admin/characters/99999/restore",
            headers=_bearer(token),
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_restoring_non_deleted_character_returns_400(self, client: TestClient, db) -> None:
        """Attempting to restore a character that is not deleted returns 400."""
        token = _admin_token(client, db, username="adminrestore4")
        user = make_user(db)
        book = make_book(db)
        character = make_character(db, user, book, is_deleted=False)

        resp = client.put(
            f"/admin/characters/{character.id}/restore",
            headers=_bearer(token),
        )

        assert resp.status_code == 400
        assert "not deleted" in resp.json()["detail"].lower()
