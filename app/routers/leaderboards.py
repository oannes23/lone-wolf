"""Leaderboards router — aggregate statistics from gameplay data."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.player import User
from app.schemas.leaderboards import BookLeaderboard, OverallLeaderboard
from app.services.leaderboard_service import get_book_leaderboard, get_overall_leaderboard

router = APIRouter(prefix="/leaderboards", tags=["leaderboards"])


@router.get("/books/{book_id}", response_model=BookLeaderboard)
def book_leaderboard(
    book_id: int,
    limit: int = Query(10, ge=1, le=100, description="Top N per category"),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> BookLeaderboard:
    """Get per-book leaderboard statistics.

    Args:
        book_id: The book to compute stats for.
        limit: Maximum entries per leaderboard category.
        db: Database session.
        _current_user: Authenticated user (not used directly, required for auth).

    Returns:
        Full book leaderboard with all stat categories.

    Raises:
        HTTPException 404: If the book is not found.
    """
    try:
        return get_book_leaderboard(db=db, book_id=book_id, limit=limit)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/overall", response_model=OverallLeaderboard)
def overall_leaderboard(
    limit: int = Query(10, ge=1, le=100, description="Top N per category"),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> OverallLeaderboard:
    """Get aggregate leaderboard statistics across all books.

    Args:
        limit: Maximum entries per leaderboard category.
        db: Database session.
        _current_user: Authenticated user.

    Returns:
        Overall leaderboard with aggregate stats.
    """
    return get_overall_leaderboard(db=db, limit=limit)
