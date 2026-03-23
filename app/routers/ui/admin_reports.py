"""Admin report triage UI router.

Serves HTMX + Jinja2 HTML pages for viewing, filtering, and triaging player
bug reports. All routes require admin authentication via the admin_session cookie.
Routes live under /admin/ui/reports.
"""

from collections import defaultdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import AdminUser, Report
from app.models.content import Scene
from app.ui_dependencies import get_current_admin_ui, templates
from app.utils.json_fields import parse_json_list

router = APIRouter(prefix="/admin/ui", tags=["admin-ui-reports"])

_VALID_STATUSES = frozenset({"open", "triaging", "resolved", "wont_fix"})
_PER_PAGE = 25


# ---------------------------------------------------------------------------
# GET /admin/ui/reports/stats — aggregate stats (must be registered before /{id})
# ---------------------------------------------------------------------------


@router.get("/reports/stats", response_class=HTMLResponse)
def report_stats(
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the report statistics page.

    Calculates total reports, breakdown by status, breakdown by tag, and the
    overall resolution rate.

    Args:
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        HTML response with aggregate report stats.
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

    resolution_rate = (resolved / total * 100) if total > 0 else 0.0

    by_status = sorted(status_counts.items())
    by_tag = sorted(tag_counts.items())

    return templates.TemplateResponse(
        request,
        "admin/reports/stats.html",
        {
            "admin": admin,
            "total": total,
            "by_status": by_status,
            "by_tag": by_tag,
            "resolution_rate": resolution_rate,
        },
    )


# ---------------------------------------------------------------------------
# GET /admin/ui/reports — report list with filters
# ---------------------------------------------------------------------------


@router.get("/reports", response_class=HTMLResponse)
def report_list(
    request: Request,
    status: str | None = None,
    tags: str | None = None,
    page: int = 1,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the report queue list with optional status and tag filters.

    Applies status filter via SQL and tag filter in Python (SQLite JSON limitation).
    Paginates results at 25 per page.

    Args:
        request: Incoming HTTP request.
        status: Filter by report status (open, triaging, resolved, wont_fix).
        tags: Filter to reports that contain this tag value.
        page: Page number (1-indexed).
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        HTML response with paginated, filtered report list.
    """
    q = db.query(Report)
    if status:
        q = q.filter(Report.status == status)

    reports = q.order_by(Report.created_at.desc()).all()

    if tags:
        reports = [r for r in reports if tags in parse_json_list(r.tags)]

    total = len(reports)
    page = max(1, page)
    reports = reports[(page - 1) * _PER_PAGE : page * _PER_PAGE]

    # Pre-parse tags for template display
    report_rows = [
        {
            "id": r.id,
            "user_id": r.user_id,
            "character_id": r.character_id,
            "scene_id": r.scene_id,
            "tags": parse_json_list(r.tags),
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in reports
    ]

    total_pages = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)

    return templates.TemplateResponse(
        request,
        "admin/reports/list.html",
        {
            "admin": admin,
            "reports": report_rows,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "filter_status": status or "",
            "filter_tags": tags or "",
        },
    )


# ---------------------------------------------------------------------------
# GET /admin/ui/reports/{id} — report detail with triage form
# ---------------------------------------------------------------------------


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def report_detail(
    report_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the report detail page with linked scene snippet and triage form.

    If the report has an associated scene_id, the scene narrative is included.

    Args:
        report_id: Primary key of the report to display.
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        HTML response with report detail and triage form, or 404 if not found.
    """
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        return templates.TemplateResponse(
            request,
            "admin/reports/detail.html",
            {"admin": admin, "report": None, "error": "Report not found"},
            status_code=404,
        )

    scene = None
    if report.scene_id is not None:
        scene = db.query(Scene).filter(Scene.id == report.scene_id).first()

    tags = parse_json_list(report.tags)

    return templates.TemplateResponse(
        request,
        "admin/reports/detail.html",
        {
            "admin": admin,
            "report": report,
            "tags": tags,
            "scene": scene,
            "valid_statuses": sorted(_VALID_STATUSES),
            "error": None,
            "success": None,
        },
    )


# ---------------------------------------------------------------------------
# POST /admin/ui/reports/{id} — triage form submission
# ---------------------------------------------------------------------------


@router.post("/reports/{report_id}", response_class=HTMLResponse)
def report_triage(
    report_id: int,
    request: Request,
    status: str = Form(...),
    admin_notes: str = Form(""),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Handle triage form submission — update status, admin_notes, and resolved_by.

    If status is resolved or wont_fix, auto-sets resolved_by to the current admin.
    Returns 422 for invalid status values. On success redirects back to the detail page.

    Args:
        report_id: Primary key of the report to triage.
        request: Incoming HTTP request.
        status: New status value from the form.
        admin_notes: Admin notes text from the form.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        Redirect to detail page on success, or re-rendered detail with error.
    """
    report = db.query(Report).filter(Report.id == report_id).first()
    if not report:
        return templates.TemplateResponse(
            request,
            "admin/reports/detail.html",
            {"admin": admin, "report": None, "error": "Report not found"},
            status_code=404,
        )

    if status not in _VALID_STATUSES:
        tags = parse_json_list(report.tags)
        scene = None
        if report.scene_id is not None:
            scene = db.query(Scene).filter(Scene.id == report.scene_id).first()
        return templates.TemplateResponse(
            request,
            "admin/reports/detail.html",
            {
                "admin": admin,
                "report": report,
                "tags": tags,
                "scene": scene,
                "valid_statuses": sorted(_VALID_STATUSES),
                "error": f"Invalid status '{status}'. Must be one of: {sorted(_VALID_STATUSES)}",
                "success": None,
            },
            status_code=422,
        )

    report.status = status
    report.admin_notes = admin_notes if admin_notes else None
    if status in ("resolved", "wont_fix"):
        report.resolved_by = admin.id
    else:
        report.resolved_by = None
    report.updated_at = datetime.now(tz=UTC)
    db.flush()

    return RedirectResponse(
        url=f"/admin/ui/reports/{report_id}",
        status_code=303,
    )
