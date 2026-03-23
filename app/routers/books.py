"""Books router — content browsing for books, disciplines, and game rules."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.content import Book, Discipline, Scene, WeaponCategory
from app.models.player import User
from app.schemas.books import (
    BookDetail,
    BookListItem,
    BookRulesResponse,
    CombatRulesSummary,
    DisciplineInfo,
    EquipmentRulesSummary,
)

router = APIRouter(prefix="/books", tags=["books"])


def _discipline_info_list(db: Session, era: str) -> list[DisciplineInfo]:
    """Return all disciplines for the given era as DisciplineInfo instances.

    Args:
        db: Database session.
        era: The era string (e.g. ``"kai"``).

    Returns:
        A list of :class:`DisciplineInfo` sorted by database ID.
    """
    rows = (
        db.query(Discipline)
        .filter(Discipline.era == era)
        .order_by(Discipline.id)
        .all()
    )
    return [DisciplineInfo(id=d.id, name=d.name, description=d.description) for d in rows]


@router.get("", response_model=list[BookListItem])
def list_books(
    era: str | None = None,
    series: str | None = None,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[BookListItem]:
    """List all books, optionally filtered by era and/or series.

    Query params:
        era: Filter by era (e.g. ``kai``, ``magnakai``).
        series: Filter by series (e.g. ``lone_wolf``).

    Args:
        era: Optional era filter.
        series: Optional series filter.
        db: Database session.
        _current_user: The authenticated user (auth enforcement only).

    Returns:
        A list of :class:`BookListItem` sorted by book number.

    Raises:
        HTTPException 401: If the request is not authenticated.
    """
    query = db.query(Book)
    if era is not None:
        query = query.filter(Book.era == era)
    if series is not None:
        query = query.filter(Book.series == series)
    books = query.order_by(Book.number).all()
    return [
        BookListItem(
            id=b.id,
            number=b.number,
            slug=b.slug,
            title=b.title,
            era=b.era,
            start_scene_number=b.start_scene_number,
        )
        for b in books
    ]


@router.get("/{book_id}", response_model=BookDetail)
def get_book(
    book_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> BookDetail:
    """Return full book detail including scene count and discipline list.

    Args:
        book_id: The book's primary key.
        db: Database session.
        _current_user: The authenticated user (auth enforcement only).

    Returns:
        A :class:`BookDetail` with scene count and era-scoped discipline list.

    Raises:
        HTTPException 404: If the book does not exist.
        HTTPException 401: If the request is not authenticated.
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    scene_count = (
        db.query(func.count(Scene.id))
        .filter(Scene.book_id == book_id)
        .scalar()
    ) or 0

    disciplines = _discipline_info_list(db, book.era)

    return BookDetail(
        id=book.id,
        number=book.number,
        slug=book.slug,
        title=book.title,
        era=book.era,
        start_scene_number=book.start_scene_number,
        scene_count=scene_count,
        max_total_picks=book.max_total_picks,
        disciplines=disciplines,
    )


@router.get("/{book_id}/rules", response_model=BookRulesResponse)
def get_book_rules(
    book_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> BookRulesResponse:
    """Return game rules for a book — disciplines, equipment, and combat summary.

    The disciplines list contains full descriptions for the book's era.
    Equipment rules summarise the weapon categories available and a note about
    starting equipment.  Combat rules give a plain-English summary of how the
    combat ratio and random number table work for the book's era.

    Args:
        book_id: The book's primary key.
        db: Database session.
        _current_user: The authenticated user (auth enforcement only).

    Returns:
        A :class:`BookRulesResponse`.

    Raises:
        HTTPException 404: If the book does not exist.
        HTTPException 401: If the request is not authenticated.
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found")

    disciplines = _discipline_info_list(db, book.era)

    # Weapon categories — distinct category names, sorted alphabetically
    category_rows = (
        db.query(WeaponCategory.category)
        .distinct()
        .order_by(WeaponCategory.category)
        .all()
    )
    weapon_categories = [row[0] for row in category_rows]

    equipment_rules = EquipmentRulesSummary(
        weapon_categories=weapon_categories,
        starting_equipment_note=(
            "You may carry a maximum of 2 weapons and up to 8 items in your "
            "Backpack. Starting equipment is chosen during character creation."
        ),
    )

    combat_rules = CombatRulesSummary(
        era=book.era,
        combat_ratio_explained=(
            "Combat Ratio is your Combat Skill minus the enemy's Combat Skill. "
            "Look up the ratio on the Combat Results Table to find damage dealt "
            "and received for each round."
        ),
        random_number_range="0-9 (Lone Wolf random number table)",
    )

    return BookRulesResponse(
        disciplines=disciplines,
        equipment_rules=equipment_rules,
        combat_rules=combat_rules,
    )
