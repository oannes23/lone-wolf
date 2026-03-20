"""Admin authentication router — login only (8-hour access token, no refresh)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.limiter import limiter
from app.models.admin import AdminUser
from app.schemas.admin_auth import AdminLoginRequest, AdminTokenResponse
from app.services.auth_service import create_admin_token, verify_password

router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


@router.post("/login", response_model=AdminTokenResponse)
@limiter.limit("5/minute")
def admin_login(
    request: Request,
    body: AdminLoginRequest,
    db: Session = Depends(get_db),
) -> AdminTokenResponse:
    """Authenticate an admin user and return an 8-hour access token.

    Rate-limited to 5 requests per minute per IP.
    No refresh token is issued — admins must re-authenticate after 8 hours.

    Args:
        request: The incoming HTTP request (required by slowapi).
        body: Admin credentials — username and password.
        db: Database session.

    Returns:
        An admin-scoped access token with ``type="admin_access"`` and ``role="admin"`` claims.

    Raises:
        HTTPException 400: If the username does not exist or the password is wrong.
        HTTPException 429: If the rate limit is exceeded.
    """
    admin = db.query(AdminUser).filter(AdminUser.username == body.username).first()
    if not admin or not verify_password(body.password, admin.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token = create_admin_token(admin_id=admin.id)
    return AdminTokenResponse(access_token=access_token)
