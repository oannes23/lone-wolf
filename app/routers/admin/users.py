"""Admin user management router — update user limits and restore soft-deleted characters."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.admin import AdminUser
from app.models.player import Character, User
from app.schemas.admin import CharacterAdminResponse, UpdateMaxCharactersRequest, UserAdminResponse

router = APIRouter(prefix="/admin", tags=["admin-users"])


@router.put("/users/{id}", response_model=UserAdminResponse)
def update_user_max_characters(
    id: int,
    body: UpdateMaxCharactersRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> UserAdminResponse:
    """Update a player's maximum allowed characters.

    Args:
        id: The user's primary key, taken from the URL path.
        body: The update payload containing ``max_characters``.
        db: Database session injected by FastAPI.
        _admin: The authenticated admin, resolved by ``get_current_admin``.

    Returns:
        The updated user with id, username, email, and max_characters.

    Raises:
        HTTPException 404: If the user does not exist.
        HTTPException 422: If ``max_characters`` is less than 1 (handled by Pydantic).
    """
    user = db.query(User).filter(User.id == id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.max_characters = body.max_characters
    db.flush()

    return UserAdminResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        max_characters=user.max_characters,
    )


@router.put("/characters/{id}/restore", response_model=CharacterAdminResponse)
def restore_character(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> CharacterAdminResponse:
    """Restore a soft-deleted character, clearing its deletion flags.

    Args:
        id: The character's primary key, taken from the URL path.
        db: Database session injected by FastAPI.
        _admin: The authenticated admin, resolved by ``get_current_admin``.

    Returns:
        The restored character with id, name, and is_deleted set to False.

    Raises:
        HTTPException 404: If the character does not exist.
        HTTPException 400: If the character is not currently deleted.
    """
    character = db.query(Character).filter(Character.id == id).first()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    if not character.is_deleted:
        raise HTTPException(status_code=400, detail="Character is not deleted")

    character.is_deleted = False
    character.deleted_at = None
    db.flush()

    return CharacterAdminResponse(
        id=character.id,
        name=character.name,
        is_deleted=character.is_deleted,
    )
