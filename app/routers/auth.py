"""Authentication router — register, login, refresh, change-password, me."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.player import User
from app.schemas.auth import (
    ChangePasswordRequest,
    MessageResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
)
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    verify_token_not_stale,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201, response_model=RegisterResponse)
@limiter.limit("3/minute")
def register(
    request: Request,
    body: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    """Register a new player account.

    Rate-limited to 3 requests per minute per IP.

    Args:
        request: The incoming HTTP request (required by slowapi).
        body: Registration fields — username, email, password.
        db: Database session.

    Returns:
        The newly created user's id, username, and email.

    Raises:
        HTTPException 400: If the username or email is already taken.
        HTTPException 429: If the rate limit is exceeded.
    """
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Username or email already registered") from None

    return RegisterResponse(id=user.id, username=user.username, email=user.email)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate a player and return access + refresh tokens.

    Accepts form-encoded body for OAuth2 compatibility.
    Rate-limited to 5 requests per minute per IP.

    Args:
        request: The incoming HTTP request (required by slowapi).
        form_data: OAuth2 form with username and password fields.
        db: Database session.

    Returns:
        Access token, refresh token, and token type.

    Raises:
        HTTPException 400: If credentials are incorrect.
        HTTPException 429: If the rate limit is exceeded.
    """
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token = create_access_token(user_id=user.id, username=user.username)
    refresh_token = create_refresh_token(user_id=user.id, username=user.username)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    body: RefreshRequest,
    db: Session = Depends(get_db),
) -> RefreshResponse:
    """Exchange a valid refresh token for a new access token.

    Args:
        body: The refresh token.
        db: Database session.

    Returns:
        A new access token.

    Raises:
        HTTPException 401: If the refresh token is invalid, expired, or stale.
    """
    try:
        payload = decode_token(body.refresh_token, expected_type="refresh")
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

    access_token = create_access_token(user_id=user.id, username=user.username)
    return RefreshResponse(access_token=access_token)


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageResponse:
    """Change the authenticated user's password.

    Updates ``password_hash`` and stamps ``password_changed_at`` so that all
    previously issued tokens are invalidated.

    Args:
        body: Current and new passwords.
        db: Database session.
        current_user: The authenticated user resolved from the Bearer token.

    Returns:
        A success message.

    Raises:
        HTTPException 400: If the current password is wrong.
    """
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.password_hash = hash_password(body.new_password)
    # Set password_changed_at to the next whole second so that:
    # - Tokens issued at or before the current second (old tokens) are rejected,
    #   because their integer iat < password_changed_at.
    # - Tokens issued in the next second or later (new tokens) are accepted,
    #   because their iat >= password_changed_at.
    now_trunc = datetime.now(UTC).replace(microsecond=0)
    current_user.password_changed_at = now_trunc + timedelta(seconds=1)
    db.flush()
    return MessageResponse(message="Password changed successfully")


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the authenticated user's profile.

    Args:
        current_user: The authenticated user resolved from the Bearer token.

    Returns:
        The user's id, username, and email.
    """
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
    )
