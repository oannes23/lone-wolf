"""Shared FastAPI dependencies."""

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import AdminUser
from app.models.player import Character, User
from app.services.auth_service import decode_token, verify_token_not_stale

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Separate OAuth2 scheme for admin endpoints so Swagger UI shows distinct auth slots.
admin_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the current authenticated user from a Bearer token.

    Decodes the access token, looks up the user, and checks the token is not
    stale (i.e. was issued after the last password change).

    Args:
        token: The JWT access token from the Authorization header.
        db: Database session injected by FastAPI.

    Returns:
        The authenticated ``User`` ORM instance.

    Raises:
        HTTPException 401: If the token is invalid, expired, stale, or the
            user no longer exists.
    """
    try:
        payload = decode_token(token, expected_type="access")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    try:
        verify_token_not_stale(payload, user.password_changed_at)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return user


async def get_owned_character(
    character_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Character:
    """Resolve a character that belongs to the authenticated user.

    Looks up the character by ID, checks it is not soft-deleted, and verifies
    that it belongs to the requesting user.

    Args:
        character_id: The character's primary key, taken from the URL path.
        user: The authenticated user, resolved by ``get_current_user``.
        db: Database session injected by FastAPI.

    Returns:
        The ``Character`` ORM instance.

    Raises:
        HTTPException 404: If the character does not exist or is soft-deleted.
        HTTPException 403: If the character belongs to a different user.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted:
        raise HTTPException(status_code=404, detail="Character not found")
    if character.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your character")
    return character


async def get_current_admin(
    token: str = Depends(admin_oauth2_scheme),
    db: Session = Depends(get_db),
) -> AdminUser:
    """Resolve the current authenticated admin from a Bearer token.

    Decodes the admin access token and looks up the AdminUser by ``sub`` claim.
    Player tokens are rejected because their ``type`` claim is ``"access"``, not
    ``"admin_access"``.

    Args:
        token: The JWT admin access token from the Authorization header.
        db: Database session injected by FastAPI.

    Returns:
        The authenticated ``AdminUser`` ORM instance.

    Raises:
        HTTPException 401: If the token is invalid, expired, or the admin no longer exists.
    """
    try:
        payload = decode_token(token, expected_type="admin_access")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    admin_id = int(payload["sub"])
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=401, detail="Admin user not found")

    return admin


def verify_version(character: Character, version: int | None) -> None:
    """Assert that the client's version matches the character's current version.

    Used to implement optimistic locking on state-mutating operations. The
    client must read the current version and echo it back; if the server's
    version has advanced (due to a concurrent write) the request is rejected.

    Args:
        character: The character whose version is being checked.
        version: The version value supplied by the client, or ``None`` if
            omitted.

    Raises:
        HTTPException 422: If *version* is ``None`` (not supplied by client).
        HTTPException 409: If *version* does not match ``character.version``.
            Both responses include an ``X-Current-Version`` header.
    """
    if version is None:
        raise HTTPException(
            status_code=422,
            detail="version is required for state-mutating operations",
            headers={"X-Current-Version": str(character.version)},
        )
    if version != character.version:
        raise VersionConflictError(character.version)


class VersionConflictError(Exception):
    """Raised when optimistic lock version does not match."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"Version mismatch (current: {current_version})")
