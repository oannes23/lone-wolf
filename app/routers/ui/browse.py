"""UI browse router — books, game objects, and leaderboard pages.

These routes are at /ui/* and serve HTMX + Jinja2 HTML pages.
They call the service layer and ORM directly — no internal HTTP calls.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.content import Book, Discipline, Scene
from app.models.player import User
from app.models.taxonomy import GameObject, GameObjectRef
from app.services.leaderboard_service import get_book_leaderboard, get_overall_leaderboard
from app.ui_dependencies import get_current_ui_user, templates
from app.utils.json_fields import parse_json_dict, parse_json_dict_or_none, parse_json_list

router = APIRouter(prefix="/ui", tags=["ui-browse"])

# Valid game object kinds (mirrors DB CHECK constraint in taxonomy.py)
_GO_KINDS = ["character", "location", "creature", "organization", "item", "foe", "scene"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_first_appearance(go: GameObject, db: Session) -> dict | None:
    """Return first_appearance dict for a game object, or None."""
    if go.first_book_id is None:
        return None
    book = db.query(Book).filter(Book.id == go.first_book_id).first()
    if book is None:
        return None
    return {"book_id": book.id, "book_title": book.title}


def _list_books(db: Session) -> list[Book]:
    """Return all books sorted by number."""
    return db.query(Book).order_by(Book.number).all()


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------


@router.get("/books", response_class=HTMLResponse)
def books_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the books list page."""
    books = _list_books(db)
    return templates.TemplateResponse(
        request,
        "books/list.html",
        {"books": books},
    )


@router.get("/books/{book_id}", response_class=HTMLResponse)
def book_detail(
    request: Request,
    book_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the book detail page."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    scene_count = (
        db.query(sqlfunc.count(Scene.id))
        .filter(Scene.book_id == book_id)
        .scalar()
    ) or 0

    disciplines = (
        db.query(Discipline)
        .filter(Discipline.era == book.era)
        .order_by(Discipline.id)
        .all()
    )

    # Build a book-like object with the extra fields the template needs
    book_ctx = {
        "id": book.id,
        "number": book.number,
        "slug": book.slug,
        "title": book.title,
        "era": book.era,
        "start_scene_number": book.start_scene_number,
        "scene_count": scene_count,
        "max_total_picks": book.max_total_picks,
        "disciplines": [
            {"id": d.id, "name": d.name, "description": d.description}
            for d in disciplines
        ],
    }

    return templates.TemplateResponse(
        request,
        "books/detail.html",
        {"book": book_ctx},
    )


# ---------------------------------------------------------------------------
# Game objects
# ---------------------------------------------------------------------------


def _query_game_objects(
    db: Session,
    kind: str | None,
    search: str | None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Run the game objects query and return serialisable dicts."""
    query = db.query(GameObject)

    if kind:
        query = query.filter(GameObject.kind == kind)

    if search:
        search_lower = f"%{search.lower()}%"
        query = query.filter(
            sqlfunc.lower(GameObject.name).like(search_lower)
            | sqlfunc.lower(GameObject.description).like(search_lower)
            | sqlfunc.lower(GameObject.aliases).like(search_lower)
        )

    objects = query.order_by(GameObject.name).offset(offset).limit(limit).all()

    return [
        {
            "id": go.id,
            "name": go.name,
            "kind": go.kind,
            "description": go.description,
            "aliases": parse_json_list(go.aliases),
        }
        for go in objects
    ]


@router.get("/game-objects", response_class=HTMLResponse)
def game_objects_list(
    request: Request,
    kind: str | None = Query(None),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the game objects browse page.

    Supports HTMX-driven kind filter and debounced search. When the request
    carries the HX-Request header, only the results partial is returned.
    """
    objects = _query_game_objects(db, kind, search)

    context = {
        "objects": objects,
        "kinds": _GO_KINDS,
        "selected_kind": kind or "",
        "search": search or "",
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "game_objects/_results.html",
            context,
        )

    return templates.TemplateResponse(
        request,
        "game_objects/list.html",
        context,
    )


@router.get("/game-objects/{object_id}", response_class=HTMLResponse)
def game_object_detail(
    request: Request,
    object_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the game object detail page."""
    go = db.query(GameObject).filter(GameObject.id == object_id).first()
    if go is None:
        raise HTTPException(status_code=404, detail="Game object not found")

    refs_data = (
        db.query(GameObjectRef)
        .filter(GameObjectRef.source_id == object_id)
        .limit(50)
        .all()
    )

    refs = []
    for ref in refs_data:
        target_obj = db.query(GameObject).filter(GameObject.id == ref.target_id).first()
        if target_obj is None:
            continue
        refs.append(
            {
                "target": {
                    "id": target_obj.id,
                    "name": target_obj.name,
                    "kind": target_obj.kind,
                },
                "tags": parse_json_list(ref.tags),
                "metadata": parse_json_dict_or_none(ref.metadata_),
            }
        )

    obj_ctx = {
        "id": go.id,
        "name": go.name,
        "kind": go.kind,
        "description": go.description,
        "aliases": parse_json_list(go.aliases),
        "properties": parse_json_dict(go.properties),
        "first_appearance": _build_first_appearance(go, db),
        "refs": refs,
    }

    return templates.TemplateResponse(
        request,
        "game_objects/detail.html",
        {"obj": obj_ctx},
    )


# ---------------------------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------------------------


@router.get("/leaderboards", response_class=HTMLResponse)
def leaderboards(
    request: Request,
    book_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the leaderboards page.

    Supports HTMX book filter: when HX-Request is present, only the leaderboard
    content partial is returned to replace #leaderboard-content.
    """
    books = _list_books(db)

    if book_id is not None:
        try:
            lb = get_book_leaderboard(db=db, book_id=book_id, limit=10)
        except LookupError:
            lb = None
        fewest_deaths = lb.fewest_deaths if lb else []
        fewest_decisions = lb.fewest_decisions if lb else []
        highest_endurance = lb.highest_endurance_at_victory if lb else []
    else:
        lb = get_overall_leaderboard(db=db, limit=10)
        fewest_deaths = []  # Not available in overall view
        fewest_decisions = []
        highest_endurance = lb.highest_endurance_at_victory if lb else []

    context = {
        "books": books,
        "selected_book_id": book_id,
        "leaderboard": lb,
        "fewest_deaths": fewest_deaths,
        "fewest_decisions": fewest_decisions,
        "highest_endurance": highest_endurance,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request,
            "leaderboards/_content.html",
            context,
        )

    return templates.TemplateResponse(
        request,
        "leaderboards/index.html",
        context,
    )
