"""Unit tests for app/dependencies.py.

Strategy: mount a small set of test-only routes on the app that exercise each
dependency. The ``client`` fixture from conftest provides a TestClient with the
database session overridden to the in-transaction test session.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_owned_character, verify_version
from app.main import app
from app.models.player import Character, User
from app.services.auth_service import create_access_token, create_token
from tests.factories import make_book, make_character, make_user

# ---------------------------------------------------------------------------
# Test router — mount once at module level
# ---------------------------------------------------------------------------

_router = APIRouter(prefix="/_test_deps")


@_router.get("/me")
async def _me(user: User = Depends(get_current_user)) -> dict:
    return {"user_id": user.id}


@_router.get("/characters/{character_id}")
async def _get_char(character: Character = Depends(get_owned_character)) -> dict:
    return {"character_id": character.id}


@_router.post("/characters/{character_id}/action")
async def _action(
    version: int | None = None,
    character: Character = Depends(get_owned_character),
) -> dict:
    verify_version(character, version)
    return {"ok": True}


app.include_router(_router)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _valid_token(user: User) -> str:
    return create_access_token(user_id=user.id, username=user.username)


def _expired_token(user: User) -> str:
    return create_token(
        data={"sub": str(user.id), "username": user.username},
        token_type="access",
        expires_delta=timedelta(seconds=-1),
    )


def _stale_token(user: User, issued_before: datetime) -> str:
    """Create a token whose iat is set in the past, before a password change."""
    from datetime import timedelta as td

    return create_token(
        data={"sub": str(user.id), "username": user.username},
        token_type="access",
        # Expire far in the future so the token is still valid signature-wise
        expires_delta=td(hours=24),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def book(db: Session):
    return make_book(db)


@pytest.fixture
def user(db: Session) -> User:
    return make_user(db)


@pytest.fixture
def other_user(db: Session) -> User:
    return make_user(db)


@pytest.fixture
def character(db: Session, user: User, book) -> Character:
    return make_character(db, user, book)


@pytest.fixture
def other_character(db: Session, other_user: User, book) -> Character:
    return make_character(db, other_user, book)


@pytest.fixture
def deleted_character(db: Session, user: User, book) -> Character:
    return make_character(db, user, book, is_deleted=True)


# ---------------------------------------------------------------------------
# get_current_user — expired token
# ---------------------------------------------------------------------------


class TestGetCurrentUserExpiredToken:
    def test_rejects_expired_token(self, client: TestClient, user: User) -> None:
        token = _expired_token(user)
        response = client.get("/_test_deps/me", headers=_bearer(token))
        assert response.status_code == 401

    def test_rejects_malformed_token(self, client: TestClient) -> None:
        response = client.get("/_test_deps/me", headers=_bearer("not.a.token"))
        assert response.status_code == 401

    def test_rejects_missing_token(self, client: TestClient) -> None:
        response = client.get("/_test_deps/me")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# get_current_user — stale token (issued before password change)
# ---------------------------------------------------------------------------


class TestGetCurrentUserStaleToken:
    def test_rejects_token_issued_before_password_change(
        self, client: TestClient, db: Session, user: User
    ) -> None:
        # Token is created now; then we back-date password_changed_at to 1 minute later
        token = _valid_token(user)
        # Set password_changed_at to 1 minute in the future relative to token iat
        user.password_changed_at = datetime.now(UTC) + timedelta(minutes=1)
        db.flush()

        response = client.get("/_test_deps/me", headers=_bearer(token))
        assert response.status_code == 401

    def test_accepts_token_issued_after_password_change(
        self, client: TestClient, db: Session, user: User
    ) -> None:
        # Password changed 1 hour ago; token issued now — should pass
        user.password_changed_at = datetime.now(UTC) - timedelta(hours=1)
        db.flush()

        token = _valid_token(user)
        response = client.get("/_test_deps/me", headers=_bearer(token))
        assert response.status_code == 200
        assert response.json()["user_id"] == user.id


# ---------------------------------------------------------------------------
# get_current_user — valid token
# ---------------------------------------------------------------------------


class TestGetCurrentUserValidToken:
    def test_returns_user_for_valid_token(self, client: TestClient, user: User) -> None:
        token = _valid_token(user)
        response = client.get("/_test_deps/me", headers=_bearer(token))
        assert response.status_code == 200
        assert response.json()["user_id"] == user.id

    def test_rejects_when_user_not_in_db(
        self, client: TestClient, db: Session
    ) -> None:
        # Create a token for a user ID that doesn't exist
        token = create_access_token(user_id=99999, username="ghost")
        response = client.get("/_test_deps/me", headers=_bearer(token))
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# get_owned_character — cross-user access
# ---------------------------------------------------------------------------


class TestGetOwnedCharacterOwnership:
    def test_blocks_cross_user_access(
        self,
        client: TestClient,
        user: User,
        other_character: Character,
    ) -> None:
        # user tries to access other_user's character
        token = _valid_token(user)
        response = client.get(
            f"/_test_deps/characters/{other_character.id}",
            headers=_bearer(token),
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "Not your character"

    def test_allows_own_character(
        self,
        client: TestClient,
        user: User,
        character: Character,
    ) -> None:
        token = _valid_token(user)
        response = client.get(
            f"/_test_deps/characters/{character.id}",
            headers=_bearer(token),
        )
        assert response.status_code == 200
        assert response.json()["character_id"] == character.id


# ---------------------------------------------------------------------------
# get_owned_character — deleted and non-existent characters
# ---------------------------------------------------------------------------


class TestGetOwnedCharacterNotFound:
    def test_returns_404_for_deleted_character(
        self,
        client: TestClient,
        user: User,
        deleted_character: Character,
    ) -> None:
        token = _valid_token(user)
        response = client.get(
            f"/_test_deps/characters/{deleted_character.id}",
            headers=_bearer(token),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Character not found"

    def test_returns_404_for_nonexistent_character(
        self,
        client: TestClient,
        user: User,
    ) -> None:
        token = _valid_token(user)
        response = client.get(
            "/_test_deps/characters/99999",
            headers=_bearer(token),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Character not found"


# ---------------------------------------------------------------------------
# verify_version
# ---------------------------------------------------------------------------


class TestVerifyVersion:
    def test_missing_version_returns_422(
        self,
        client: TestClient,
        user: User,
        character: Character,
    ) -> None:
        token = _valid_token(user)
        # No version query param supplied
        response = client.post(
            f"/_test_deps/characters/{character.id}/action",
            headers=_bearer(token),
        )
        assert response.status_code == 422
        assert "version" in response.json()["detail"].lower()
        assert response.headers["X-Current-Version"] == str(character.version)

    def test_version_mismatch_returns_409(
        self,
        client: TestClient,
        user: User,
        character: Character,
    ) -> None:
        token = _valid_token(user)
        wrong_version = character.version + 1
        response = client.post(
            f"/_test_deps/characters/{character.id}/action?version={wrong_version}",
            headers=_bearer(token),
        )
        assert response.status_code == 409
        body = response.json()
        assert body["error_code"] == "VERSION_MISMATCH"
        assert body["current_version"] == character.version
        assert response.headers["X-Current-Version"] == str(character.version)

    def test_correct_version_succeeds(
        self,
        client: TestClient,
        user: User,
        character: Character,
    ) -> None:
        token = _valid_token(user)
        response = client.post(
            f"/_test_deps/characters/{character.id}/action?version={character.version}",
            headers=_bearer(token),
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
