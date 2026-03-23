"""Reports router — player bug report submission and listing."""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.admin import Report
from app.models.player import User
from app.schemas.reports import (
    VALID_TAGS,
    CreateReportRequest,
    ReportListResponse,
    ReportResponse,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _report_to_response(report: Report) -> ReportResponse:
    """Convert a Report ORM instance to a ReportResponse.

    Args:
        report: The Report ORM instance to serialise.

    Returns:
        A ``ReportResponse`` Pydantic model.
    """
    tags: list[str] = json.loads(report.tags) if report.tags else []
    return ReportResponse(
        id=report.id,
        tags=tags,
        status=report.status,
        free_text=report.free_text,
        character_id=report.character_id,
        scene_id=report.scene_id,
        created_at=report.created_at,
    )


@router.post("", status_code=201, response_model=ReportResponse)
def create_report(
    body: CreateReportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportResponse:
    """Submit a player bug report.

    Validates submitted tags against the allowed set, then persists the report
    linked to the authenticated user. ``user_id`` is taken from the auth context
    and cannot be supplied by the caller.

    Args:
        body: The report payload (character_id, scene_id, tags, free_text).
        db: Database session.
        current_user: The authenticated player resolved from the Bearer token.

    Returns:
        The created report with id, status, and created_at (201).

    Raises:
        HTTPException 400: If any tag in ``body.tags`` is not in the allowed set.
        HTTPException 401: If the request is not authenticated.
    """
    invalid = [t for t in body.tags if t not in VALID_TAGS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid tag(s): {', '.join(invalid)}. "
            f"Allowed tags: {', '.join(sorted(VALID_TAGS))}",
        )

    now = datetime.now(timezone.utc)
    report = Report(
        user_id=current_user.id,
        character_id=body.character_id,
        scene_id=body.scene_id,
        tags=json.dumps(body.tags),
        free_text=body.free_text,
        status="open",
        created_at=now,
        updated_at=now,
    )
    db.add(report)
    db.flush()
    db.refresh(report)

    return _report_to_response(report)


@router.get("", response_model=ReportListResponse)
def list_reports(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReportListResponse:
    """List bug reports belonging to the authenticated user.

    Returns only reports where ``user_id`` matches the current user — reports
    from other users are never included.

    Args:
        db: Database session.
        current_user: The authenticated player resolved from the Bearer token.

    Returns:
        A list of the user's own reports ordered by creation date descending.

    Raises:
        HTTPException 401: If the request is not authenticated.
    """
    reports = (
        db.query(Report)
        .filter(Report.user_id == current_user.id)
        .order_by(Report.created_at.desc())
        .all()
    )
    return ReportListResponse(reports=[_report_to_response(r) for r in reports])
