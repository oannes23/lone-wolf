"""Authentication service — JWT creation/verification and password hashing.

All functions are stateless. Inject settings via ``get_settings()`` rather than
reading module-level globals so tests can monkeypatch cleanly.
"""

import hashlib
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# bcrypt silently truncates or errors on passwords longer than 72 bytes.
# We pre-hash with SHA-256 (producing a 64-char hex digest, well under 72 bytes)
# so that passwords up to 128 characters are handled correctly.


def _prehash(password: str) -> bytes:
    """Return a SHA-256 hex digest of *password* as bytes.

    This keeps bcrypt input well under its 72-byte limit while preserving the
    full entropy of long passwords.
    """
    return hashlib.sha256(password.encode()).hexdigest().encode()


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*.

    Passwords are pre-hashed with SHA-256 before bcrypt so that passwords
    longer than 72 characters are supported without truncation.
    """
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the bcrypt *hashed* password."""
    return bcrypt.checkpw(_prehash(plain), hashed.encode())


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

# Recognised token type values
_VALID_TYPES = {"access", "refresh", "admin_access", "roll"}


def create_token(data: dict, token_type: str, expires_delta: timedelta) -> str:
    """Encode *data* as a signed JWT with the given *token_type* and expiry.

    The ``type`` and standard ``iat``/``exp`` claims are set automatically.
    *data* should contain all domain-specific claims (e.g. ``sub``, ``username``).

    Args:
        data: Domain claims to embed in the token payload.
        token_type: One of ``"access"``, ``"refresh"``, ``"admin_access"``, ``"roll"``.
        expires_delta: How long until the token expires.

    Returns:
        A signed JWT string.

    Raises:
        ValueError: If *token_type* is not a recognised type.
    """
    if token_type not in _VALID_TYPES:
        raise ValueError(f"Unknown token type: {token_type!r}")
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        **data,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    """Decode and validate a JWT string.

    Verifies the signature, expiry, and ``type`` claim. Does **not** check
    ``password_changed_at``; use :func:`verify_token_not_stale` for that.

    Args:
        token: The JWT string to decode.
        expected_type: The ``type`` claim value that must be present.

    Returns:
        The decoded payload dict.

    Raises:
        ValueError: If the token is invalid, expired, or has the wrong type.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise ValueError("Invalid or expired token")

    if payload.get("type") != expected_type:
        raise ValueError("Invalid token")
    return payload


# ---------------------------------------------------------------------------
# Token factory helpers
# ---------------------------------------------------------------------------


def create_access_token(user_id: int, username: str) -> str:
    """Create a player access token valid for ACCESS_TOKEN_EXPIRE_HOURS.

    Claims: ``sub``, ``username``, ``type="access"``, ``iat``, ``exp``.
    """
    settings = get_settings()
    return create_token(
        data={"sub": str(user_id), "username": username},
        token_type="access",
        expires_delta=timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS),
    )


def create_refresh_token(user_id: int, username: str) -> str:
    """Create a player refresh token valid for REFRESH_TOKEN_EXPIRE_DAYS.

    Claims: ``sub``, ``username``, ``type="refresh"``, ``iat``, ``exp``.
    """
    settings = get_settings()
    return create_token(
        data={"sub": str(user_id), "username": username},
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_admin_token(admin_id: int) -> str:
    """Create an admin access token valid for ADMIN_TOKEN_EXPIRE_HOURS.

    Claims: ``sub``, ``role="admin"``, ``type="admin_access"``, ``iat``, ``exp``.
    """
    settings = get_settings()
    return create_token(
        data={"sub": str(admin_id), "role": "admin"},
        token_type="admin_access",
        expires_delta=timedelta(hours=settings.ADMIN_TOKEN_EXPIRE_HOURS),
    )


def create_roll_token(user_id: int, cs: int, end: int, book_id: int) -> str:
    """Create a roll token valid for ROLL_TOKEN_EXPIRE_HOURS.

    Claims: ``sub``, ``cs``, ``end``, ``book_id``, ``type="roll"``, ``iat``, ``exp``.
    """
    settings = get_settings()
    return create_token(
        data={"sub": str(user_id), "cs": cs, "end": end, "book_id": book_id},
        token_type="roll",
        expires_delta=timedelta(hours=settings.ROLL_TOKEN_EXPIRE_HOURS),
    )


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------


def verify_token_not_stale(payload: dict, password_changed_at: datetime | None) -> None:
    """Raise ValueError if the token was issued before *password_changed_at*.

    This invalidates all tokens that existed prior to a password change.

    Args:
        payload: A decoded JWT payload dict (must contain ``iat``).
        password_changed_at: The UTC datetime of the last password change, or
            ``None`` if the password has never been changed (skip check).

    Raises:
        ValueError: If ``iat`` predates ``password_changed_at``.
    """
    if password_changed_at is None:
        return

    iat_raw = payload.get("iat")
    if iat_raw is None:
        raise ValueError("Token payload missing 'iat' claim")

    # python-jose decodes iat as a numeric timestamp (int/float)
    if isinstance(iat_raw, (int, float)):
        issued_at = datetime.fromtimestamp(iat_raw, tz=UTC)
    else:
        # Already a datetime (e.g. in unit tests that inject dicts directly)
        issued_at = iat_raw if iat_raw.tzinfo else iat_raw.replace(tzinfo=UTC)

    # Normalise password_changed_at to UTC-aware
    if password_changed_at.tzinfo is None:
        password_changed_at = password_changed_at.replace(tzinfo=UTC)

    if issued_at < password_changed_at:
        raise ValueError("Token was issued before the most recent password change")
