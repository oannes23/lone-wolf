"""Pydantic schemas for the reports endpoints."""

from datetime import datetime

from pydantic import BaseModel

VALID_TAGS: frozenset[str] = frozenset(
    {
        "wrong_items",
        "meal_issue",
        "missing_choice",
        "combat_issue",
        "narrative_error",
        "discipline_issue",
        "other",
    }
)


class CreateReportRequest(BaseModel):
    """Request body for POST /reports."""

    character_id: int | None = None
    scene_id: int | None = None
    tags: list[str] = []
    free_text: str | None = None


class ReportResponse(BaseModel):
    """Response body for a single report."""

    id: int
    tags: list[str]
    status: str
    free_text: str | None
    character_id: int | None
    scene_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportListResponse(BaseModel):
    """Response body for GET /reports."""

    reports: list[ReportResponse]
