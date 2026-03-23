"""Shared dependencies for the HTMX + Jinja2 UI layer.

Provides cookie-based authentication and the shared Jinja2 template engine.
"""

from pathlib import Path

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.player import User
from app.services.auth_service import resolve_user_from_token

# ---------------------------------------------------------------------------
# Jinja2 template engine — shared across all UI routers
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Login-required sentinel exception
# ---------------------------------------------------------------------------


class LoginRequired(Exception):
    """Raised by UI dependencies when the user is not authenticated.

    The app's exception handler converts this to a 303 redirect to /ui/login.
    """


# ---------------------------------------------------------------------------
# Cookie-based authentication dependency
# ---------------------------------------------------------------------------


def get_current_ui_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the current user from the httpOnly session cookie.

    Reads the JWT access token stored in the "session" cookie, verifies it,
    and returns the authenticated User.  If no valid token is present, raises
    ``LoginRequired`` which the app-level exception handler converts to a
    303 redirect to ``/ui/login``.

    Args:
        request: The incoming HTTP request (provides cookie access).
        db: Database session injected by FastAPI.

    Returns:
        The authenticated ``User`` ORM instance.

    Raises:
        LoginRequired: If the cookie is missing, the token is
            invalid/expired, the user no longer exists, or the token is
            stale (issued before the last password change).
    """
    token = request.cookies.get("session")
    if not token:
        raise LoginRequired()

    try:
        return resolve_user_from_token(db, token)
    except ValueError:
        raise LoginRequired()


def login_required_handler(request: Request, exc: LoginRequired) -> RedirectResponse:  # noqa: ARG001
    """Convert a LoginRequired exception to a 303 redirect to /ui/login.

    Registered as an exception handler in ``app/main.py``.
    """
    return RedirectResponse(url="/ui/login", status_code=303)
