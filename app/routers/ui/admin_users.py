"""Admin user & character management UI router.

Serves HTMX + Jinja2 HTML pages for managing users, characters, and browsing
character events. All routes require admin authentication via the admin_session
cookie. Routes live under /admin/ui/users, /admin/ui/characters, and
/admin/ui/events.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import AdminUser
from app.models.content import Book
from app.models.player import Character, CharacterEvent, User
from app.ui_dependencies import get_current_admin_ui, templates

router = APIRouter(prefix="/admin/ui", tags=["admin-ui-users"])

_CHARS_PER_PAGE = 25
_EVENTS_PER_PAGE = 50


# ---------------------------------------------------------------------------
# GET /admin/ui/users — user list with inline max_characters edit
# ---------------------------------------------------------------------------


@router.get("/users", response_class=HTMLResponse)
def user_list(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the user management list page.

    Queries all users ordered by ID and counts their active (non-deleted)
    characters. Each row has an inline editable max_characters field using HTMX.

    Args:
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        HTML response with the user list.
    """
    users = db.query(User).order_by(User.id).all()

    user_data = []
    for user in users:
        char_count = (
            db.query(Character)
            .filter(
                Character.user_id == user.id,
                Character.is_deleted.is_(False),
            )
            .count()
        )
        user_data.append({"user": user, "char_count": char_count})

    return templates.TemplateResponse(
        request,
        "admin/users/list.html",
        {"admin": admin, "user_data": user_data},
    )


# ---------------------------------------------------------------------------
# POST /admin/ui/users/{user_id}/max-characters — HTMX inline update
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/max-characters", response_class=HTMLResponse)
def update_max_characters(
    user_id: int,
    request: Request,
    max_characters: int = Form(...),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Handle inline max_characters update submitted via HTMX.

    Validates the new value, persists it, and returns a partial template
    containing just the updated <td> for HTMX to swap in.

    Args:
        user_id: Primary key of the user to update.
        request: Incoming HTTP request.
        max_characters: New limit submitted from the inline form.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        Partial HTML response with the updated max_characters cell.

    Raises:
        HTTPException 404: If the user does not exist.
        HTTPException 422: If max_characters is less than 1.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if max_characters < 1:
        raise HTTPException(
            status_code=422, detail="max_characters must be >= 1"
        )

    user.max_characters = max_characters
    db.flush()

    return templates.TemplateResponse(
        request,
        "admin/users/_max_chars_cell.html",
        {"user": user},
    )


# ---------------------------------------------------------------------------
# GET /admin/ui/characters — character list with filters and pagination
# ---------------------------------------------------------------------------


@router.get("/characters", response_class=HTMLResponse)
def character_list(
    request: Request,
    user_id: int | None = None,
    book_id: int | None = None,
    deleted: str = "active",
    page: int = 1,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the character management list page with optional filters.

    Supports filtering by user_id, book_id, and deletion status. Paginates
    results at 25 per page.

    Args:
        request: Incoming HTTP request.
        user_id: Filter to characters belonging to this user.
        book_id: Filter to characters playing this book.
        deleted: Deletion status filter — "all", "active" (default), or "deleted".
        page: Page number (1-indexed).
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        HTML response with the filtered, paginated character list.
    """
    q = db.query(Character)

    if user_id is not None:
        q = q.filter(Character.user_id == user_id)
    if book_id is not None:
        q = q.filter(Character.book_id == book_id)
    if deleted == "active":
        q = q.filter(Character.is_deleted.is_(False))
    elif deleted == "deleted":
        q = q.filter(Character.is_deleted.is_(True))
    # "all" applies no filter

    total = q.count()
    page = max(1, page)
    characters = (
        q.order_by(Character.id)
        .offset((page - 1) * _CHARS_PER_PAGE)
        .limit(_CHARS_PER_PAGE)
        .all()
    )
    total_pages = max(1, (total + _CHARS_PER_PAGE - 1) // _CHARS_PER_PAGE)

    # Build lookup of book titles for display
    book_ids = {c.book_id for c in characters}
    books = {
        b.id: b
        for b in db.query(Book).filter(Book.id.in_(book_ids)).all()
    } if book_ids else {}

    # Build user lookup
    user_ids = {c.user_id for c in characters}
    users = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    char_rows = [
        {
            "char": c,
            "username": users.get(c.user_id, {}).username if c.user_id in users else str(c.user_id),
            "book_title": books.get(c.book_id, {}).title if c.book_id in books else str(c.book_id),
        }
        for c in characters
    ]

    return templates.TemplateResponse(
        request,
        "admin/characters/list.html",
        {
            "admin": admin,
            "char_rows": char_rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "filter_user_id": user_id or "",
            "filter_book_id": book_id or "",
            "filter_deleted": deleted,
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/ui/characters/{character_id}/restore — HTMX restore
# ---------------------------------------------------------------------------


@router.post("/characters/{character_id}/restore", response_class=HTMLResponse)
def restore_character(
    character_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Restore a soft-deleted character via HTMX.

    Clears is_deleted and deleted_at on the character and returns a partial
    template for HTMX to swap the updated row in place.

    Args:
        character_id: Primary key of the character to restore.
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        Partial HTML response with the restored character row.

    Raises:
        HTTPException 404: If the character does not exist.
        HTTPException 400: If the character is not currently deleted.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    if not character.is_deleted:
        raise HTTPException(status_code=400, detail="Character is not deleted")

    character.is_deleted = False
    character.deleted_at = None
    db.flush()

    # Resolve username and book title for the row partial
    user = db.query(User).filter(User.id == character.user_id).first()
    book = db.query(Book).filter(Book.id == character.book_id).first()

    return templates.TemplateResponse(
        request,
        "admin/characters/_row.html",
        {
            "char": character,
            "username": user.username if user else str(character.user_id),
            "book_title": book.title if book else str(character.book_id),
        },
    )


# ---------------------------------------------------------------------------
# GET /admin/ui/events — character event viewer with filters and pagination
# ---------------------------------------------------------------------------


@router.get("/events", response_class=HTMLResponse)
def event_list(
    request: Request,
    character_id: int | None = None,
    event_type: str | None = None,
    scene_id: int | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the character event viewer with optional filters.

    Supports filtering by character_id, event_type, and scene_id. Paginates
    results at 50 per page, ordered newest first.

    Args:
        request: Incoming HTTP request.
        character_id: Filter to events for a specific character.
        event_type: Filter to events of a specific type.
        scene_id: Filter to events that occurred in a specific scene.
        page: Page number (1-indexed).
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        HTML response with the filtered, paginated event list.
    """
    q = db.query(CharacterEvent)

    if character_id is not None:
        q = q.filter(CharacterEvent.character_id == character_id)
    if event_type is not None:
        q = q.filter(CharacterEvent.event_type == event_type)
    if scene_id is not None:
        q = q.filter(CharacterEvent.scene_id == scene_id)

    total = q.count()
    page = max(1, page)
    events = (
        q.order_by(CharacterEvent.created_at.desc())
        .offset((page - 1) * _EVENTS_PER_PAGE)
        .limit(_EVENTS_PER_PAGE)
        .all()
    )
    total_pages = max(1, (total + _EVENTS_PER_PAGE - 1) // _EVENTS_PER_PAGE)

    return templates.TemplateResponse(
        request,
        "admin/events/list.html",
        {
            "admin": admin,
            "events": events,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "filter_character_id": character_id or "",
            "filter_event_type": event_type or "",
            "filter_scene_id": scene_id or "",
        },
    )
