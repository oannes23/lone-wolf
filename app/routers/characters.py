"""Characters router — stat rolling and character creation flow."""

import random
from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_owned_character, verify_version
from app.limiter import limiter
from app.models.content import Book
from app.models.player import Character, User
from app.models.wizard import CharacterWizardProgress, WizardTemplate, WizardTemplateStep
from app.schemas.characters import (
    ActiveWizardInfo,
    CharacterResponse,
    CreateCharacterRequest,
    RollFormula,
    RollRequest,
    RollResponse,
    WizardCompleteResponse,
    WizardConfirmRequest,
    WizardConfirmStepResponse,
    WizardDisciplineRequest,
    WizardDisciplineStepResponse,
    WizardEquipmentRequest,
    WizardEquipmentStepResponse,
    WizardInventoryRequest,
    WizardInventoryStepResponse,
    WizardInventoryItemInfo,
    WizardDisciplineItem,
)
from app.services.auth_service import create_roll_token
from app.services.character_service import create_character
from app.services.wizard_service import (
    get_wizard_state,
    handle_book_advance_confirm_step,
    handle_confirm_step,
    handle_discipline_step,
    handle_equipment_step,
    handle_inventory_adjust_step,
)

router = APIRouter(prefix="/characters", tags=["characters"])


def get_active_wizard_info(db: Session, character: Character) -> ActiveWizardInfo | None:
    """Build ActiveWizardInfo from a character's active wizard, or return None."""
    if character.active_wizard_id is None:
        return None

    progress = (
        db.query(CharacterWizardProgress)
        .filter(CharacterWizardProgress.id == character.active_wizard_id)
        .first()
    )
    if progress is None:
        return None

    template = (
        db.query(WizardTemplate)
        .filter(WizardTemplate.id == progress.wizard_template_id)
        .first()
    )
    steps = (
        db.query(WizardTemplateStep)
        .filter(WizardTemplateStep.template_id == template.id)
        .order_by(WizardTemplateStep.ordinal)
        .all()
        if template
        else []
    )
    current_step = (
        steps[progress.current_step_index]
        if steps and progress.current_step_index < len(steps)
        else None
    )
    return ActiveWizardInfo(
        type=template.name if template else "unknown",
        step=current_step.step_type if current_step else "unknown",
        step_index=progress.current_step_index,
        total_steps=len(steps),
    )


@router.post("/roll", response_model=RollResponse)
@limiter.limit("10/minute")
def roll_stats(
    request: Request,
    body: RollRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RollResponse:
    """Roll starting stats for a new character.

    Looks up the requested book, validates it is Book 1 (Kai era MVP restriction),
    generates Combat Skill and Endurance using the Kai formula, and returns a
    signed roll token containing the rolled values.

    This endpoint is stateless — no database writes occur. It can be called
    repeatedly; each call produces fresh rolls and a fresh token.

    Rate-limited to 10 requests per minute per IP.

    Args:
        request: The incoming HTTP request (required by slowapi).
        body: Request body containing the book_id to roll for.
        db: Database session.
        current_user: The authenticated player resolved from the Bearer token.

    Returns:
        Roll token, rolled stat values, era name, and formula breakdown.

    Raises:
        HTTPException 404: If the book_id does not exist.
        HTTPException 400: If the book is not Book 1 (MVP restriction).
        HTTPException 401: If the request is not authenticated.
        HTTPException 429: If the rate limit is exceeded.
    """
    book = db.query(Book).filter(Book.id == body.book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if book.number != 1:
        raise HTTPException(
            status_code=400,
            detail="Only Book 1 is supported in this version",
        )

    cs_bonus = random.randint(0, 9)
    end_bonus = random.randint(0, 9)
    cs = 10 + cs_bonus
    end = 20 + end_bonus

    roll_token = create_roll_token(
        user_id=current_user.id,
        cs=cs,
        end=end,
        book_id=book.id,
    )

    return RollResponse(
        roll_token=roll_token,
        combat_skill_base=cs,
        endurance_base=end,
        era=book.era,
        formula=RollFormula(
            cs=f"10 + {cs_bonus}",
            end=f"20 + {end_bonus}",
        ),
    )


@router.post("", status_code=201, response_model=CharacterResponse)
@limiter.limit("5/minute")
def create_character_endpoint(
    request: Request,
    body: CreateCharacterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CharacterResponse:
    """Create a new character by consuming a roll token.

    Validates the roll token, selects disciplines, and initialises the
    character with the equipment-selection wizard ready to proceed.

    Rate-limited to 5 requests per minute per IP.

    Args:
        request: The incoming HTTP request (required by slowapi).
        body: Character creation payload including the roll_token.
        db: Database session.
        current_user: The authenticated player resolved from the Bearer token.

    Returns:
        The created character with id, stats, disciplines, and active wizard.

    Raises:
        HTTPException 400: INVALID_ROLL_TOKEN — token invalid/expired/mismatched.
        HTTPException 400: MAX_CHARACTERS — user has reached their character limit.
        HTTPException 400: Discipline validation failed.
        HTTPException 400: weapon_skill_type validation failed.
        HTTPException 404: Book not found.
        HTTPException 401: Request not authenticated.
        HTTPException 429: Rate limit exceeded.
    """
    try:
        character = create_character(
            db=db,
            user=current_user,
            name=body.name,
            book_id=body.book_id,
            roll_token=body.roll_token,
            discipline_ids=body.discipline_ids,
            weapon_skill_type=body.weapon_skill_type,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        # Flat error_code format matching the project convention (see main.py
        # version_conflict_handler).  Frontend branches on error_code, displays detail.
        if "INVALID_ROLL_TOKEN" in msg:
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "INVALID_ROLL_TOKEN"},
            )
        if "MAX_CHARACTERS" in msg:
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "MAX_CHARACTERS"},
            )
        raise HTTPException(status_code=400, detail=msg) from exc

    return _build_character_response(db, character)


def _build_character_response(db: Session, character: Character) -> CharacterResponse:
    """Build a CharacterResponse from an ORM Character instance.

    Args:
        db: Database session (used to load wizard info).
        character: The character to serialise.

    Returns:
        A ``CharacterResponse`` Pydantic model.
    """
    return CharacterResponse(
        id=character.id,
        name=character.name,
        combat_skill_base=character.combat_skill_base,
        endurance_base=character.endurance_base,
        endurance_max=character.endurance_max,
        endurance_current=character.endurance_current,
        gold=character.gold,
        meals=character.meals,
        death_count=character.death_count,
        current_run=character.current_run,
        version=character.version,
        disciplines=[cd.discipline.name for cd in character.disciplines],  # type: ignore[attr-defined]
        active_wizard=get_active_wizard_info(db, character),
    )


@router.get(
    "/{character_id}/wizard",
    response_model=Union[
        WizardEquipmentStepResponse,
        WizardConfirmStepResponse,
        WizardDisciplineStepResponse,
        WizardInventoryStepResponse,
    ],
)
def get_wizard(
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> (
    WizardEquipmentStepResponse
    | WizardConfirmStepResponse
    | WizardDisciplineStepResponse
    | WizardInventoryStepResponse
):
    """Get the current wizard step and available options.

    Returns different response shapes depending on the wizard step:
    - pick_disciplines: lists available disciplines to pick.
    - pick_equipment: lists fixed items, auto-applied resources, and choices.
    - inventory_adjust: shows current inventory with carry-over limits.
    - confirm: returns a preview of the character with all selections applied.

    Works for both character creation and book advance wizards.

    Args:
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Step-specific response model depending on the current wizard step.

    Raises:
        HTTPException 404: If the character has no active wizard.
    """
    try:
        state = get_wizard_state(db, character)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    step = state.get("step", "")

    if step == "pick_disciplines":
        return WizardDisciplineStepResponse(
            wizard_type=state["wizard_type"],
            step=state["step"],
            step_index=state["step_index"],
            total_steps=state["total_steps"],
            available_disciplines=[
                WizardDisciplineItem(**d) for d in state["available_disciplines"]
            ],
            disciplines_to_pick=state["disciplines_to_pick"],
        )

    elif step == "pick_equipment":
        return WizardEquipmentStepResponse(
            wizard_type=state["wizard_type"],
            step=state["step"],
            step_index=state["step_index"],
            total_steps=state["total_steps"],
            included_items=state["included_items"],
            auto_applied=state["auto_applied"],
            available_equipment=state["available_equipment"],
            pick_limit=state["pick_limit"],
        )

    elif step == "inventory_adjust":
        return WizardInventoryStepResponse(
            wizard_type=state["wizard_type"],
            step=state["step"],
            step_index=state["step_index"],
            total_steps=state["total_steps"],
            current_weapons=[WizardInventoryItemInfo(**w) for w in state["current_weapons"]],
            current_backpack=[WizardInventoryItemInfo(**b) for b in state["current_backpack"]],
            current_special=[WizardInventoryItemInfo(**s) for s in state["current_special"]],
            max_weapons=state["max_weapons"],
            max_backpack_items=state["max_backpack_items"],
        )

    else:
        # confirm step (both wizard types)
        preview = state["character_preview"]
        return WizardConfirmStepResponse(
            wizard_type=state["wizard_type"],
            step=state["step"],
            step_index=state["step_index"],
            total_steps=state["total_steps"],
            character_preview=CharacterResponse(**preview),
        )


@router.post(
    "/{character_id}/wizard",
    response_model=Union[CharacterResponse, WizardCompleteResponse],
)
async def post_wizard(
    request: Request,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> CharacterResponse | WizardCompleteResponse:
    """Submit the current wizard step.

    The request body is dispatched based on the character's current wizard step:

    Equipment step — body must be ``WizardEquipmentRequest`` shape:
      ``{"selected_items": ["Sword"], "version": N}``
      Validates and stores the selected items, advances to the confirm step.
      Returns the character in its updated state.

    Confirm step — body must be ``WizardConfirmRequest`` shape:
      ``{"confirm": true, "version": N}``
      Finalises the wizard — applies all items, saves the book-start snapshot,
      places the character at the start scene, and clears the wizard.
      Returns WizardCompleteResponse with wizard_complete=True.

    Args:
        body: Raw request body dict — dispatched by current wizard step.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        CharacterResponse (equipment step) or WizardCompleteResponse (confirm step).

    Raises:
        HTTPException 400: Validation failed (too many items, invalid names, confirm=False).
        HTTPException 404: Active wizard not found.
        HTTPException 409: Version mismatch.
        HTTPException 422: Version field missing.
    """
    body = await request.json()

    # Validate version is present (mirrors verify_version behaviour)
    raw_version = body.get("version")
    if raw_version is None:
        raise HTTPException(
            status_code=422,
            detail="version is required for state-mutating operations",
            headers={"X-Current-Version": str(character.version)},
        )
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="version must be an integer",
            headers={"X-Current-Version": str(character.version)},
        )
    verify_version(character, version)

    # Determine current step from wizard progress
    if character.active_wizard_id is None:
        raise HTTPException(status_code=404, detail="No active wizard on this character")

    progress = (
        db.query(CharacterWizardProgress)
        .filter(CharacterWizardProgress.id == character.active_wizard_id)
        .first()
    )
    if progress is None:
        raise HTTPException(status_code=404, detail="Wizard progress record not found")

    steps = (
        db.query(WizardTemplateStep)
        .filter(WizardTemplateStep.template_id == progress.wizard_template_id)
        .order_by(WizardTemplateStep.ordinal)
        .all()
    )
    step_index = progress.current_step_index
    current_step = steps[step_index] if step_index < len(steps) else None
    step_type = current_step.step_type if current_step else None

    # Determine wizard type for confirm dispatch (reuse already-loaded progress)
    wizard_type: str = "character_creation"
    tmpl = (
        db.query(WizardTemplate)
        .filter(WizardTemplate.id == progress.wizard_template_id)
        .first()
    )
    if tmpl:
        wizard_type = tmpl.name

    if step_type == "pick_disciplines":
        try:
            req_disc = WizardDisciplineRequest(**body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            character = handle_discipline_step(
                db=db,
                character=character,
                discipline_ids=req_disc.discipline_ids,
                weapon_skill_type=req_disc.weapon_skill_type,
                version=version,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return _build_character_response(db, character)

    elif step_type == "pick_equipment":
        # Parse as equipment request
        try:
            req = WizardEquipmentRequest(**body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            character = handle_equipment_step(
                db=db,
                character=character,
                selected_items=req.selected_items,
                version=version,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return _build_character_response(db, character)

    elif step_type == "inventory_adjust":
        try:
            req_inv = WizardInventoryRequest(**body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            character = handle_inventory_adjust_step(
                db=db,
                character=character,
                keep_weapons=req_inv.keep_weapons,
                keep_backpack=req_inv.keep_backpack,
                version=version,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return _build_character_response(db, character)

    elif step_type == "confirm":
        # Parse as confirm request
        try:
            req_confirm = WizardConfirmRequest(**body)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if not req_confirm.confirm:
            raise HTTPException(status_code=400, detail="confirm must be true to finalise the wizard")

        if wizard_type == "book_advance":
            try:
                character = handle_book_advance_confirm_step(db=db, character=character, version=version)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            book = db.query(Book).filter(Book.id == character.book_id).first()
            book_title = book.title if book else f"book {character.book_id}"
            return WizardCompleteResponse(
                message=f"Advanced to {book_title}",
                wizard_complete=True,
                character=_build_character_response(db, character),
            )
        else:
            try:
                character = handle_confirm_step(db=db, character=character, version=version)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

            return WizardCompleteResponse(
                message="Character creation complete",
                wizard_complete=True,
                character=_build_character_response(db, character),
            )

    else:
        raise HTTPException(status_code=400, detail=f"Unknown wizard step type: {step_type}")
