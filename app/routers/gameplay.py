"""Gameplay router — scene navigation and book advance wizard initiation."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_character, verify_version
from app.models.player import Character
from app.schemas.characters import AdvanceInitResponse, AdvanceWizardBookInfo
from app.services.wizard_service import init_book_advance_wizard

router = APIRouter(prefix="/gameplay", tags=["gameplay"])


class AdvanceRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/advance."""

    version: int = Field(..., description="Optimistic lock version")


@router.post("/{character_id}/advance", status_code=201, response_model=AdvanceInitResponse)
def advance_to_next_book(
    body: AdvanceRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> AdvanceInitResponse:
    """Start the book advance wizard for a character at a victory scene.

    Creates the wizard progress record, links it to the character, and returns
    the first step info (pick_disciplines step).

    Args:
        body: Request body with the required version field.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        AdvanceInitResponse with wizard_type, step, step_index, total_steps,
        and the target book info.

    Raises:
        HTTPException 400: If the character is not at a victory scene.
        HTTPException 404: If there is no next book (no BookTransitionRule).
        HTTPException 409: If the character already has an active wizard.
        HTTPException 422: If version is missing.
    """
    verify_version(character, body.version)

    try:
        result = init_book_advance_wizard(db=db, character=character)
    except ValueError as exc:
        msg = str(exc)
        if "already has an active wizard" in msg:
            return JSONResponse(
                status_code=409,
                content={"detail": msg, "error_code": "WIZARD_ALREADY_ACTIVE"},
            )
        return JSONResponse(
            status_code=400,
            content={"detail": msg, "error_code": "ADVANCE_NOT_ALLOWED"},
        )
    except LookupError as exc:
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc), "error_code": "NO_NEXT_BOOK"},
        )

    return AdvanceInitResponse(
        wizard_type=result["wizard_type"],
        step=result["step"],
        step_index=result["step_index"],
        total_steps=result["total_steps"],
        book=AdvanceWizardBookInfo(
            id=result["book"]["id"],
            title=result["book"]["title"],
        ),
    )
