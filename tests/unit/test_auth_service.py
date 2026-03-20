"""Unit tests for app/services/auth_service.py.

These tests are purely functional — no database or HTTP client is needed.
"""

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt

from app.config import get_settings
from app.services.auth_service import (
    create_access_token,
    create_admin_token,
    create_refresh_token,
    create_roll_token,
    create_token,
    decode_token,
    hash_password,
    verify_password,
    verify_token_not_stale,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SETTINGS = get_settings()


def _decode_raw(token: str) -> dict:
    """Decode a token without verification so we can inspect raw claims."""
    return jwt.decode(
        token,
        _SETTINGS.JWT_SECRET,
        algorithms=[_SETTINGS.JWT_ALGORITHM],
        options={"verify_exp": False},
    )


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


class TestPasswordHashing:
    def test_hash_returns_string(self) -> None:
        result = hash_password("secret")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_is_not_plaintext(self) -> None:
        result = hash_password("mypassword")
        assert result != "mypassword"

    def test_verify_correct_password_returns_true(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("correct-horse-battery-staple", hashed) is True

    def test_verify_wrong_password_returns_false(self) -> None:
        hashed = hash_password("correct-horse-battery-staple")
        assert verify_password("wrong-password", hashed) is False

    def test_same_password_produces_different_hashes(self) -> None:
        """bcrypt salts should make each hash unique."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2

    def test_hash_verify_round_trip(self) -> None:
        password = "P@ssw0rd!42"
        assert verify_password(password, hash_password(password)) is True


# ---------------------------------------------------------------------------
# Generic token creation / decoding
# ---------------------------------------------------------------------------


class TestCreateToken:
    def test_creates_valid_jwt_string(self) -> None:
        token = create_token(
            data={"sub": "1", "username": "kai"},
            token_type="access",
            expires_delta=timedelta(hours=1),
        )
        assert isinstance(token, str)
        assert token.count(".") == 2  # header.payload.signature

    def test_payload_contains_type_claim(self) -> None:
        token = create_token(
            data={"sub": "1"},
            token_type="refresh",
            expires_delta=timedelta(days=7),
        )
        payload = _decode_raw(token)
        assert payload["type"] == "refresh"

    def test_payload_contains_iat_and_exp(self) -> None:
        token = create_token(
            data={"sub": "99"},
            token_type="access",
            expires_delta=timedelta(hours=24),
        )
        payload = _decode_raw(token)
        assert "iat" in payload
        assert "exp" in payload

    def test_exp_is_after_iat(self) -> None:
        token = create_token(
            data={"sub": "1"},
            token_type="access",
            expires_delta=timedelta(hours=1),
        )
        payload = _decode_raw(token)
        assert payload["exp"] > payload["iat"]

    def test_data_claims_are_included(self) -> None:
        token = create_token(
            data={"sub": "42", "username": "lone_wolf"},
            token_type="access",
            expires_delta=timedelta(hours=1),
        )
        payload = _decode_raw(token)
        assert payload["sub"] == "42"
        assert payload["username"] == "lone_wolf"


class TestDecodeToken:
    def test_decodes_valid_token(self) -> None:
        token = create_token(
            data={"sub": "7", "username": "banedon"},
            token_type="access",
            expires_delta=timedelta(hours=1),
        )
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "7"
        assert payload["username"] == "banedon"

    def test_raises_on_wrong_type(self) -> None:
        token = create_token(
            data={"sub": "1"},
            token_type="access",
            expires_delta=timedelta(hours=1),
        )
        with pytest.raises(ValueError, match="Invalid token"):
            decode_token(token, expected_type="refresh")

    def test_raises_on_expired_token(self) -> None:
        token = create_token(
            data={"sub": "1"},
            token_type="access",
            expires_delta=timedelta(seconds=-1),  # already expired
        )
        with pytest.raises(ValueError, match="Invalid or expired token"):
            decode_token(token, expected_type="access")

    def test_raises_on_malformed_token(self) -> None:
        with pytest.raises(ValueError, match="Invalid or expired token"):
            decode_token("not.a.valid.token", expected_type="access")

    def test_raises_on_tampered_signature(self) -> None:
        token = create_token(
            data={"sub": "1"},
            token_type="access",
            expires_delta=timedelta(hours=1),
        )
        tampered = token[:-4] + "XXXX"
        with pytest.raises(ValueError, match="Invalid or expired token"):
            decode_token(tampered, expected_type="access")


# ---------------------------------------------------------------------------
# Player access token
# ---------------------------------------------------------------------------


class TestAccessToken:
    def test_creates_token_with_correct_claims(self) -> None:
        token = create_access_token(user_id=1, username="lone_wolf")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "1"
        assert payload["username"] == "lone_wolf"
        assert payload["type"] == "access"

    def test_access_token_expires_in_24_hours(self) -> None:
        before = datetime.now(UTC)
        token = create_access_token(user_id=1, username="lone_wolf")
        after = datetime.now(UTC)
        payload = _decode_raw(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        # Allow a 5-second window for test execution time
        assert exp >= before + timedelta(hours=24) - timedelta(seconds=5)
        assert exp <= after + timedelta(hours=24) + timedelta(seconds=5)

    def test_decode_fails_with_wrong_type(self) -> None:
        token = create_access_token(user_id=1, username="lone_wolf")
        with pytest.raises(ValueError):
            decode_token(token, expected_type="refresh")


# ---------------------------------------------------------------------------
# Player refresh token
# ---------------------------------------------------------------------------


class TestRefreshToken:
    def test_creates_token_with_correct_claims(self) -> None:
        token = create_refresh_token(user_id=2, username="banedon")
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "2"
        assert payload["username"] == "banedon"
        assert payload["type"] == "refresh"

    def test_refresh_token_expires_in_7_days(self) -> None:
        before = datetime.now(UTC)
        token = create_refresh_token(user_id=2, username="banedon")
        after = datetime.now(UTC)
        payload = _decode_raw(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        assert exp >= before + timedelta(days=7) - timedelta(seconds=5)
        assert exp <= after + timedelta(days=7) + timedelta(seconds=5)

    def test_decode_fails_with_wrong_type(self) -> None:
        token = create_refresh_token(user_id=2, username="banedon")
        with pytest.raises(ValueError):
            decode_token(token, expected_type="access")


# ---------------------------------------------------------------------------
# Admin access token
# ---------------------------------------------------------------------------


class TestAdminToken:
    def test_creates_token_with_correct_claims(self) -> None:
        token = create_admin_token(admin_id=99)
        payload = decode_token(token, expected_type="admin_access")
        assert payload["sub"] == "99"
        assert payload["role"] == "admin"
        assert payload["type"] == "admin_access"

    def test_admin_token_expires_in_8_hours(self) -> None:
        before = datetime.now(UTC)
        token = create_admin_token(admin_id=99)
        after = datetime.now(UTC)
        payload = _decode_raw(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        assert exp >= before + timedelta(hours=8) - timedelta(seconds=5)
        assert exp <= after + timedelta(hours=8) + timedelta(seconds=5)

    def test_decode_fails_with_wrong_type(self) -> None:
        token = create_admin_token(admin_id=99)
        with pytest.raises(ValueError):
            decode_token(token, expected_type="access")


# ---------------------------------------------------------------------------
# Roll token
# ---------------------------------------------------------------------------


class TestRollToken:
    def test_creates_token_with_correct_claims(self) -> None:
        token = create_roll_token(user_id=5, cs=15, end=22, book_id=1)
        payload = decode_token(token, expected_type="roll")
        assert payload["sub"] == "5"
        assert payload["cs"] == 15
        assert payload["end"] == 22
        assert payload["book_id"] == 1
        assert payload["type"] == "roll"

    def test_roll_token_expires_in_1_hour(self) -> None:
        before = datetime.now(UTC)
        token = create_roll_token(user_id=5, cs=15, end=22, book_id=1)
        after = datetime.now(UTC)
        payload = _decode_raw(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        assert exp >= before + timedelta(hours=1) - timedelta(seconds=5)
        assert exp <= after + timedelta(hours=1) + timedelta(seconds=5)

    def test_decode_fails_with_wrong_type(self) -> None:
        token = create_roll_token(user_id=5, cs=15, end=22, book_id=1)
        with pytest.raises(ValueError):
            decode_token(token, expected_type="access")


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------


class TestVerifyTokenNotStale:
    def test_passes_when_password_changed_at_is_none(self) -> None:
        """No password change recorded — token should always pass."""
        token = create_access_token(user_id=1, username="lone_wolf")
        payload = decode_token(token, expected_type="access")
        # Must not raise
        verify_token_not_stale(payload, password_changed_at=None)

    def test_passes_when_token_issued_after_password_change(self) -> None:
        token = create_access_token(user_id=1, username="lone_wolf")
        payload = decode_token(token, expected_type="access")
        # Password was changed 1 hour ago — token is newer
        changed_at = datetime.now(UTC) - timedelta(hours=1)
        verify_token_not_stale(payload, password_changed_at=changed_at)

    def test_raises_when_token_issued_before_password_change(self) -> None:
        # Create a token with an iat in the past
        token = create_token(
            data={"sub": "1", "username": "lone_wolf"},
            token_type="access",
            expires_delta=timedelta(hours=24),
        )
        payload = _decode_raw(token)

        # Simulate password changed 1 minute after the token was issued
        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
        changed_at = iat + timedelta(minutes=1)

        with pytest.raises(ValueError, match="issued before"):
            verify_token_not_stale(payload, password_changed_at=changed_at)

    def test_passes_when_token_issued_at_same_second_as_password_change(self) -> None:
        """Boundary: token issued exactly at changed_at is accepted (not strictly before)."""
        token = create_access_token(user_id=1, username="lone_wolf")
        payload = decode_token(token, expected_type="access")
        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)
        # changed_at == iat — should not raise because iat < changed_at is False
        verify_token_not_stale(payload, password_changed_at=iat)

    def test_raises_when_payload_missing_iat(self) -> None:
        payload = {"sub": "1", "type": "access"}
        with pytest.raises(ValueError, match="missing 'iat'"):
            verify_token_not_stale(payload, password_changed_at=datetime.now(UTC))

    def test_accepts_naive_password_changed_at(self) -> None:
        """A timezone-naive password_changed_at should be treated as UTC."""
        token = create_access_token(user_id=1, username="lone_wolf")
        payload = decode_token(token, expected_type="access")
        # Naive datetime 1 hour ago — token should still pass
        changed_at_naive = datetime.now() - timedelta(hours=1)  # no tzinfo
        verify_token_not_stale(payload, password_changed_at=changed_at_naive)
