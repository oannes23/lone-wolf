"""Admin UI router — login, dashboard, and admin navigation pages.

These routes are at /admin/ui/* and serve HTMX + Jinja2 HTML pages.
They authenticate against the AdminUser model using a separate "admin_session"
cookie that carries an admin_access JWT — distinct from the player "session"
cookie.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.limiter import limiter
from app.models.admin import AdminUser, Report
from app.models.content import Book, Scene
from app.models.player import Character, User
from app.services.auth_service import create_admin_token, verify_password
from app.ui_dependencies import AdminLoginRequired, get_current_admin_ui, templates
from app.utils.json_fields import parse_json_list

router = APIRouter(prefix="/admin/ui", tags=["admin-ui"])


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
def admin_login_page(request: Request) -> HTMLResponse:
    """Render the admin login form."""
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        {"error": None},
    )


@router.post("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle admin login form submission.

    On success: sets httpOnly admin_session cookie with admin JWT and redirects
    to /admin/ui/dashboard.
    On failure: re-renders login form with error message.
    """
    admin = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not admin or not verify_password(password, admin.password_hash):
        return templates.TemplateResponse(
            request,
            "admin/login.html",
            {"error": "Incorrect username or password"},
            status_code=401,
        )

    access_token = create_admin_token(admin_id=admin.id)
    response = RedirectResponse(url="/admin/ui/dashboard", status_code=303)
    response.set_cookie(
        key="admin_session",
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
def admin_logout() -> RedirectResponse:
    """Clear the admin_session cookie and redirect to admin login."""
    response = RedirectResponse(url="/admin/ui/login", status_code=303)
    response.delete_cookie(key="admin_session")
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the admin dashboard with summary counts.

    Queries aggregate counts for reports, users, characters, and books
    with parsed scenes. Shows recent open/triaging reports.

    Args:
        request: The incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user (raises AdminLoginRequired if missing).

    Returns:
        HTML response with dashboard data.
    """
    open_reports = db.query(Report).filter(Report.status == "open").count()
    total_users = db.query(User).count()
    total_characters = db.query(Character).filter(Character.is_deleted.is_(False)).count()
    books_with_content = (
        db.query(Book.id)
        .join(Scene, Scene.book_id == Book.id)
        .distinct()
        .count()
    )

    # Recent reports — last 5 across all statuses, newest first
    recent_report_rows = (
        db.query(Report)
        .order_by(Report.created_at.desc())
        .limit(5)
        .all()
    )

    # Build simple dicts for template rendering (tags parsed from JSON)
    recent_reports = [
        {
            "id": r.id,
            "status": r.status,
            "tags": ", ".join(parse_json_list(r.tags)) or "(none)",
            "created_at": r.created_at,
        }
        for r in recent_report_rows
    ]

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "admin": admin,
            "open_reports": open_reports,
            "total_users": total_users,
            "total_characters": total_characters,
            "books_with_content": books_with_content,
            "recent_reports": recent_reports,
        },
    )
