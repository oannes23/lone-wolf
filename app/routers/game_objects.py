"""Game objects router — browse the game object knowledge graph."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.content import Book
from app.models.player import User
from app.models.taxonomy import GameObject, GameObjectRef
from app.utils.json_fields import parse_json_dict, parse_json_dict_or_none, parse_json_list
from app.schemas.game_objects import (
    FirstAppearance,
    GameObjectDetail,
    GameObjectRef as GameObjectRefSchema,
    GameObjectSummary,
    RefTarget,
)

router = APIRouter(prefix="/game-objects", tags=["game-objects"])


def _build_first_appearance(game_object: GameObject, db: Session) -> FirstAppearance | None:
    """Build the structured FirstAppearance from a game object's first_book_id.

    Joins with Book to get the title.

    Args:
        game_object: The game object ORM model.
        db: Active database session.

    Returns:
        A :class:`FirstAppearance` if the game object has a first_book_id, else None.
    """
    if game_object.first_book_id is None:
        return None
    book = db.query(Book).filter(Book.id == game_object.first_book_id).first()
    if book is None:
        return None
    return FirstAppearance(book_id=book.id, book_title=book.title)


@router.get("", response_model=list[GameObjectSummary])
def list_game_objects(
    kind: str | None = Query(None, description="Filter by kind (character, item, foe, etc.)"),
    book_id: int | None = Query(None, description="Filter by first_book_id"),
    search: str | None = Query(None, description="Case-insensitive search on name/description/aliases"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[GameObjectSummary]:
    """List game objects with optional filtering.

    Args:
        kind: Filter by game object kind.
        book_id: Filter by first_book_id.
        search: Case-insensitive search on name, description, or aliases.
        limit: Max results to return.
        offset: Offset for pagination.
        db: Database session.
        _current_user: Authenticated user (not used in body, but required for auth).

    Returns:
        List of game object summaries.
    """
    query = db.query(GameObject)

    if kind is not None:
        query = query.filter(GameObject.kind == kind)

    if book_id is not None:
        query = query.filter(GameObject.first_book_id == book_id)

    if search is not None:
        search_lower = f"%{search.lower()}%"
        from sqlalchemy import func as sqlfunc
        query = query.filter(
            sqlfunc.lower(GameObject.name).like(search_lower)
            | sqlfunc.lower(GameObject.description).like(search_lower)
            | sqlfunc.lower(GameObject.aliases).like(search_lower)
        )

    game_objects = query.offset(offset).limit(limit).all()

    return [
        GameObjectSummary(
            id=go.id,
            name=go.name,
            kind=go.kind,
            description=go.description,
            aliases=parse_json_list(go.aliases),
            first_appearance=_build_first_appearance(go, db),
        )
        for go in game_objects
    ]


@router.get("/{object_id}", response_model=GameObjectDetail)
def get_game_object(
    object_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> GameObjectDetail:
    """Get game object detail with properties and outgoing refs.

    Args:
        object_id: The game object ID.
        db: Database session.
        _current_user: Authenticated user.

    Returns:
        Full game object detail.

    Raises:
        HTTPException 404: If the game object is not found.
    """
    go = db.query(GameObject).filter(GameObject.id == object_id).first()
    if go is None:
        raise HTTPException(status_code=404, detail=f"Game object {object_id} not found")

    # Load outgoing refs (first page, no limit for MVP)
    refs_data = (
        db.query(GameObjectRef)
        .filter(GameObjectRef.source_id == object_id)
        .limit(50)
        .all()
    )

    refs: list[GameObjectRefSchema] = []
    for ref in refs_data:
        target_obj = db.query(GameObject).filter(GameObject.id == ref.target_id).first()
        if target_obj is None:
            continue
        refs.append(
            GameObjectRefSchema(
                target=RefTarget(id=target_obj.id, name=target_obj.name, kind=target_obj.kind),
                tags=parse_json_list(ref.tags),
                metadata=parse_json_dict_or_none(ref.metadata_),
            )
        )

    return GameObjectDetail(
        id=go.id,
        name=go.name,
        kind=go.kind,
        description=go.description,
        aliases=parse_json_list(go.aliases),
        properties=parse_json_dict(go.properties),
        first_appearance=_build_first_appearance(go, db),
        refs=refs,
    )


@router.get("/{object_id}/refs", response_model=list[GameObjectRefSchema])
def get_game_object_refs(
    object_id: int,
    tag: str | None = Query(None, description="Filter refs by tag"),
    direction: str | None = Query(None, description="'outgoing' or 'incoming'"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> list[GameObjectRefSchema]:
    """Get paginated refs for a game object.

    Args:
        object_id: The game object ID.
        tag: Filter by tag string (substring match).
        direction: 'outgoing' (source) or 'incoming' (target).
        limit: Max results.
        offset: Pagination offset.
        db: Database session.
        _current_user: Authenticated user.

    Returns:
        List of tagged refs.

    Raises:
        HTTPException 404: If the game object is not found.
    """
    go = db.query(GameObject).filter(GameObject.id == object_id).first()
    if go is None:
        raise HTTPException(status_code=404, detail=f"Game object {object_id} not found")

    # Build query based on direction
    if direction == "incoming":
        query = db.query(GameObjectRef).filter(GameObjectRef.target_id == object_id)
    else:
        # Default to outgoing
        query = db.query(GameObjectRef).filter(GameObjectRef.source_id == object_id)

    if tag is not None:
        from sqlalchemy import func as sqlfunc
        query = query.filter(sqlfunc.lower(GameObjectRef.tags).like(f"%{tag.lower()}%"))

    refs_data = query.offset(offset).limit(limit).all()

    result: list[GameObjectRefSchema] = []
    for ref in refs_data:
        if direction == "incoming":
            peer_id = ref.source_id
        else:
            peer_id = ref.target_id

        peer_obj = db.query(GameObject).filter(GameObject.id == peer_id).first()
        if peer_obj is None:
            continue

        result.append(
            GameObjectRefSchema(
                target=RefTarget(id=peer_obj.id, name=peer_obj.name, kind=peer_obj.kind),
                tags=parse_json_list(ref.tags),
                metadata=parse_json_dict_or_none(ref.metadata_),
            )
        )

    return result
