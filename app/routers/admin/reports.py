"""Admin reports router — report triage, event viewer, and aggregate stats.

All endpoints require admin auth (``get_current_admin``).
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.admin import AdminUser, Report
from app.models.content import Scene
from app.models.player import CharacterEvent
from app.utils.json_fields import parse_json_list
from app.schemas.admin import (
    AdminReportDetailResponse,
    AdminReportResponse,
    AdminReportStatsResponse,
    CharacterEventAdminResponse,
    ReportStatusStats,
    ReportTagStats,
    UpdateReportRequest,
)

router = APIRouter(prefix="/admin", tags=["admin-reports"])

_VALID_STATUSES = frozenset({"open", "triaging", "resolved", "wont_fix"})


def _report_to_response(report: Report) -> AdminReportResponse:
    """Convert a Report ORM instance to an AdminReportResponse.

    Handles the JSON-encoded ``tags`` column.

    Args:
        report: The Report ORM instance.

    Returns:
        An AdminReportResponse with tags as a list.
    """
    return AdminReportResponse(
        id=report.id,
        user_id=report.user_id,
        character_id=report.character_id,
        scene_id=report.scene_id,
        tags=parse_json_list(report.tags),
        free_text=report.free_text,
        status=report.status,
        admin_notes=report.admin_notes,
        resolved_by=report.resolved_by,
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


# ---------------------------------------------------------------------------
# GET /admin/reports/stats — aggregate stats (must be before /{id})
# ---------------------------------------------------------------------------


@router.get("/reports/stats", response_model=AdminReportStatsResponse)
def get_report_stats(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> AdminReportStatsResponse:
    """Return aggregate report statistics.

    Includes total report count, breakdown by status, breakdown by tag (parsed
    from the JSON ``tags`` column), and the overall resolution rate.

    Args:
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        An AdminReportStatsResponse with totals and breakdowns.
    """
    reports = db.query(Report).all()
    total = len(reports)

    status_counts: dict[str, int] = defaultdict(int)
    tag_counts: dict[str, int] = defaultdict(int)

    resolved = 0
    for report in reports:
        status_counts[report.status] += 1
        if report.status == "resolved":
            resolved += 1
        for tag in parse_json_list(report.tags):
            tag_counts[tag] += 1

    resolution_rate = (resolved / total) if total > 0 else 0.0

    by_status = [
        ReportStatusStats(status=status, count=count)
        for status, count in sorted(status_counts.items())
    ]
    by_tag = [
        ReportTagStats(tag=tag, count=count)
        for tag, count in sorted(tag_counts.items())
    ]

    return AdminReportStatsResponse(
        total=total,
        by_tag=by_tag,
        by_status=by_status,
        resolution_rate=resolution_rate,
    )


# ---------------------------------------------------------------------------
# GET /admin/reports — list all reports with optional filters
# ---------------------------------------------------------------------------


@router.get("/reports", response_model=list[AdminReportResponse])
def list_reports(
    status: str | None = None,
    tags: str | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[AdminReportResponse]:
    """List all reports with optional filtering.

    Args:
        status: Filter by report status (e.g. ``'open'``, ``'triaging'``).
        tags: Filter — only include reports that contain this tag value in their
            JSON tags array. A simple substring match is used for SQLite
            compatibility.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        A list of all matching reports.
    """
    q = db.query(Report)
    if status is not None:
        q = q.filter(Report.status == status)
    reports = q.order_by(Report.created_at.desc()).all()

    if tags is not None:
        # Filter in Python since SQLite JSON functions are limited
        reports = [r for r in reports if tags in parse_json_list(r.tags)]

    return [_report_to_response(r) for r in reports]


# ---------------------------------------------------------------------------
# GET /admin/reports/{id} — detail with linked scene content
# ---------------------------------------------------------------------------


@router.get("/reports/{id}", response_model=AdminReportDetailResponse)
def get_report(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> AdminReportDetailResponse:
    """Retrieve a single report with linked scene information.

    If the report has an associated ``scene_id``, the scene's number and
    narrative are included in the response.

    Args:
        id: Report primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        An AdminReportDetailResponse with optional scene fields populated.

    Raises:
        HTTPException 404: If no report with the given ID exists.
    """
    report = db.query(Report).filter(Report.id == id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    scene_number = None
    scene_narrative = None
    if report.scene_id is not None:
        scene = db.query(Scene).filter(Scene.id == report.scene_id).first()
        if scene:
            scene_number = scene.number
            scene_narrative = scene.narrative

    return AdminReportDetailResponse(
        id=report.id,
        user_id=report.user_id,
        character_id=report.character_id,
        scene_id=report.scene_id,
        tags=parse_json_list(report.tags),
        free_text=report.free_text,
        status=report.status,
        admin_notes=report.admin_notes,
        resolved_by=report.resolved_by,
        created_at=report.created_at,
        updated_at=report.updated_at,
        scene_number=scene_number,
        scene_narrative=scene_narrative,
    )


# ---------------------------------------------------------------------------
# PUT /admin/reports/{id} — update status, admin_notes, resolved_by
# ---------------------------------------------------------------------------


@router.put("/reports/{id}", response_model=AdminReportResponse)
def update_report(
    id: int,
    body: UpdateReportRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> AdminReportResponse:
    """Update a report's status, admin notes, and/or resolved_by.

    Only supplied fields are changed. If ``status`` is provided it must be one
    of the valid status values.

    Args:
        id: Report primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated report.

    Raises:
        HTTPException 404: If no report with the given ID exists.
        HTTPException 400: If the status value is not valid.
    """
    report = db.query(Report).filter(Report.id == id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    if body.status is not None:
        if body.status not in _VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{body.status}'. Must be one of: {sorted(_VALID_STATUSES)}",
            )
        report.status = body.status

    if body.admin_notes is not None:
        report.admin_notes = body.admin_notes

    if body.resolved_by is not None:
        report.resolved_by = body.resolved_by

    from datetime import UTC, datetime
    report.updated_at = datetime.now(tz=UTC)

    db.flush()
    return _report_to_response(report)


# ---------------------------------------------------------------------------
# GET /admin/character-events — filterable event viewer
# ---------------------------------------------------------------------------


@router.get("/character-events", response_model=list[CharacterEventAdminResponse])
def list_character_events(
    character_id: int | None = None,
    event_type: str | None = None,
    scene_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[CharacterEventAdminResponse]:
    """List character events with optional filters for admin review.

    Args:
        character_id: Filter to events for a specific character.
        event_type: Filter to events of a specific type.
        scene_id: Filter to events that occurred in a specific scene.
        limit: Maximum number of results (default 100).
        offset: Number of results to skip (default 0).
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        A list of matching character events ordered by creation time descending.
    """
    q = db.query(CharacterEvent)
    if character_id is not None:
        q = q.filter(CharacterEvent.character_id == character_id)
    if event_type is not None:
        q = q.filter(CharacterEvent.event_type == event_type)
    if scene_id is not None:
        q = q.filter(CharacterEvent.scene_id == scene_id)

    events = (
        q.order_by(CharacterEvent.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [CharacterEventAdminResponse.model_validate(e) for e in events]
