"""UI auth router — login, register, change-password, logout pages.

These routes are at /ui/* and serve HTMX + Jinja2 HTML pages.
They call the same service layer as the JSON API — no internal HTTP calls.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.limiter import limiter
from app.models.player import User
from app.services.auth_service import (
    authenticate_user,
    change_user_password,
    create_access_token,
    register_user,
)
from app.ui_dependencies import get_current_ui_user, templates

router = APIRouter(prefix="/ui", tags=["ui-auth"])

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    """Render the login form."""
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"error": None},
    )


@router.post("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle login form submission.

    On success: sets httpOnly session cookie with JWT and redirects to /ui/characters.
    On failure: re-renders login form with error message.
    """
    try:
        user = authenticate_user(db, username, password)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Incorrect username or password"},
            status_code=401,
        )

    access_token = create_access_token(user_id=user.id, username=user.username)
    response = RedirectResponse(url="/ui/characters", status_code=303)
    response.set_cookie(
        key="session",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production behind HTTPS
    )
    return response


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request) -> HTMLResponse:
    """Render the registration form."""
    return templates.TemplateResponse(
        request,
        "auth/register.html",
        {"error": None},
    )


@router.post("/register", response_class=HTMLResponse)
@limiter.limit("3/minute")
def register_submit(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle registration form submission.

    On success: redirects to /ui/login.
    On failure: re-renders register form with error message.
    """
    # Basic input validation (JSON API validates via Pydantic schemas)
    if len(username) > 50:
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "Username must be 50 characters or fewer", "username": username, "email": email},
            status_code=422,
        )
    if "@" not in email or len(email) > 255:
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": "Please enter a valid email address", "username": username, "email": email},
            status_code=422,
        )

    try:
        register_user(db, username, email, password)
    except ValueError as exc:
        status = 400 if "already" in str(exc) else 422
        return templates.TemplateResponse(
            request, "auth/register.html",
            {"error": str(exc), "username": username, "email": email},
            status_code=status,
        )

    return RedirectResponse(url="/ui/login", status_code=303)


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


@router.get("/change-password", response_class=HTMLResponse)
def change_password_page(
    request: Request,
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the change password form. Requires authentication."""
    return templates.TemplateResponse(
        request,
        "auth/change_password.html",
        {"error": None, "success": None},
    )


@router.post("/change-password", response_class=HTMLResponse)
def change_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Handle change password form submission."""
    try:
        change_user_password(db, current_user, current_password, new_password)
    except ValueError as exc:
        msg = str(exc)
        status = 400 if "incorrect" in msg.lower() else 422
        return templates.TemplateResponse(
            request,
            "auth/change_password.html",
            {"error": msg, "success": None},
            status_code=status,
        )

    # Issue a new token with the new password epoch and update the cookie
    access_token = create_access_token(user_id=current_user.id, username=current_user.username)
    response = templates.TemplateResponse(
        request,
        "auth/change_password.html",
        {"error": None, "success": "Password changed successfully"},
    )
    response.set_cookie(
        key="session",
        value=access_token,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production behind HTTPS
    )
    return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.get("/logout")
def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to login."""
    response = RedirectResponse(url="/ui/login", status_code=303)
    response.delete_cookie(key="session")
    return response
