"""Characters router — stat rolling and character creation flow."""

import random
from datetime import UTC, datetime
from typing import Annotated, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user, get_owned_character, verify_version
from app.limiter import limiter
from app.models.content import Book, Choice, Scene
from app.models.player import Character, CharacterEvent, DecisionLog, User
from app.models.wizard import CharacterWizardProgress, WizardTemplate, WizardTemplateStep
from app.schemas.characters import (
    ActiveWizardInfo,
    CharacterDetailResponse,
    CharacterDisciplineInfo,
    CharacterItemInfo,
    CharacterListItem,
    CharacterResponse,
    CreateCharacterRequest,
    EventEntry,
    HistoryEntry,
    PaginatedResponse,
    RollFormula,
    RollRequest,
    RollResponse,
    RunSummary,
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


# ---------------------------------------------------------------------------
# Character CRUD & History endpoints (Story 6.7)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[CharacterListItem])
def list_characters(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CharacterListItem]:
    """List all active (non-deleted) characters for the authenticated user.

    Args:
        current_user: The authenticated player resolved from the Bearer token.
        db: Database session.

    Returns:
        List of character summaries for the user's non-deleted characters.

    Raises:
        HTTPException 401: If the request is not authenticated.
    """
    characters = (
        db.query(Character)
        .filter(
            Character.user_id == current_user.id,
            Character.is_deleted == False,  # noqa: E712
        )
        .all()
    )

    result = []
    for char in characters:
        book = db.query(Book).filter(Book.id == char.book_id).first()
        book_title = book.title if book else f"Book {char.book_id}"

        current_scene_number: int | None = None
        if char.current_scene_id is not None:
            scene = db.query(Scene).filter(Scene.id == char.current_scene_id).first()
            if scene:
                current_scene_number = scene.number

        result.append(
            CharacterListItem(
                id=char.id,
                name=char.name,
                book_title=book_title,
                current_scene_number=current_scene_number,
                is_alive=char.is_alive,
                death_count=char.death_count,
                current_run=char.current_run,
                version=char.version,
            )
        )

    return result


@router.get("/{character_id}", response_model=CharacterDetailResponse)
def get_character_detail(
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> CharacterDetailResponse:
    """Return the full character sheet including inventory and disciplines.

    Args:
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Full character detail including stats, items, disciplines, scene, and wizard.

    Raises:
        HTTPException 401: If the request is not authenticated.
        HTTPException 403: If the character belongs to a different user.
        HTTPException 404: If the character does not exist or is deleted.
    """
    book = db.query(Book).filter(Book.id == character.book_id).first()
    book_title = book.title if book else f"Book {character.book_id}"

    current_scene_number: int | None = None
    if character.current_scene_id is not None:
        scene = db.query(Scene).filter(Scene.id == character.current_scene_id).first()
        if scene:
            current_scene_number = scene.number

    items = [
        CharacterItemInfo(
            character_item_id=item.id,
            item_name=item.item_name,
            item_type=item.item_type,
            is_equipped=item.is_equipped,
        )
        for item in character.items
    ]

    disciplines = [
        CharacterDisciplineInfo(
            name=cd.discipline.name,
            weapon_category=cd.weapon_category,
        )
        for cd in character.disciplines
    ]

    active_wizard = get_active_wizard_info(db, character)

    return CharacterDetailResponse(
        id=character.id,
        name=character.name,
        book_title=book_title,
        combat_skill_base=character.combat_skill_base,
        endurance_base=character.endurance_base,
        endurance_max=character.endurance_max,
        endurance_current=character.endurance_current,
        gold=character.gold,
        meals=character.meals,
        is_alive=character.is_alive,
        death_count=character.death_count,
        current_run=character.current_run,
        version=character.version,
        scene_phase=character.scene_phase,
        current_scene_number=current_scene_number,
        items=items,
        disciplines=disciplines,
        active_wizard=active_wizard,
    )


@router.delete("/{character_id}", status_code=204)
def delete_character(
    response: Response,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete a character.

    Sets ``is_deleted=True`` and ``deleted_at`` to the current UTC timestamp.
    The character is excluded from list results and from the active character
    count enforced by the ``MAX_CHARACTERS`` limit.

    Args:
        response: The HTTP response (used to return 204 No Content).
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Raises:
        HTTPException 401: If the request is not authenticated.
        HTTPException 403: If the character belongs to a different user.
        HTTPException 404: If the character does not exist or is already deleted.
    """
    character.is_deleted = True
    character.deleted_at = datetime.now(UTC)
    db.flush()


@router.get("/{character_id}/history")
def get_character_history(
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
    run: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse:
    """Return the decision log for a character in chronological order.

    Filterable by run number. Results are paginated.

    Args:
        character: The authenticated user's character, resolved by dependency.
        db: Database session.
        run: Optional run number to filter by.
        limit: Maximum entries to return (default 50, max 200).
        offset: Number of entries to skip (default 0).

    Returns:
        Paginated list of history entries with scene numbers and choice text.

    Raises:
        HTTPException 401: If the request is not authenticated.
        HTTPException 403: If the character belongs to a different user.
        HTTPException 404: If the character does not exist or is deleted.
    """
    query = db.query(DecisionLog).filter(DecisionLog.character_id == character.id)

    if run is not None:
        query = query.filter(DecisionLog.run_number == run)

    query = query.order_by(DecisionLog.created_at)

    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    # Build scene_id -> scene_number cache
    scene_ids = set()
    choice_ids = set()
    for row in rows:
        scene_ids.add(row.from_scene_id)
        scene_ids.add(row.to_scene_id)
        if row.choice_id is not None:
            choice_ids.add(row.choice_id)

    scenes_by_id: dict[int, Scene] = {}
    if scene_ids:
        for scene in db.query(Scene).filter(Scene.id.in_(scene_ids)).all():
            scenes_by_id[scene.id] = scene

    choices_by_id: dict[int, Choice] = {}
    if choice_ids:
        for choice in db.query(Choice).filter(Choice.id.in_(choice_ids)).all():
            choices_by_id[choice.id] = choice

    items = []
    for row in rows:
        from_scene = scenes_by_id.get(row.from_scene_id)
        to_scene = scenes_by_id.get(row.to_scene_id)
        choice = choices_by_id.get(row.choice_id) if row.choice_id else None

        items.append(
            HistoryEntry(
                scene_number=from_scene.number if from_scene else None,
                choice_text=choice.display_text if choice else None,
                target_scene_number=to_scene.number if to_scene else None,
                action_type=row.action_type,
                run_number=row.run_number,
                created_at=row.created_at.isoformat(),
            )
        )

    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{character_id}/events")
def get_character_events(
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
    event_type: Annotated[str | None, Query()] = None,
    run: Annotated[int | None, Query(ge=1)] = None,
    scene_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedResponse:
    """Return character events in sequence order.

    Filterable by event_type, run number, and scene_id. Results are paginated.

    Args:
        character: The authenticated user's character, resolved by dependency.
        db: Database session.
        event_type: Optional event type to filter by (e.g. ``"death"``).
        run: Optional run number to filter by.
        scene_id: Optional scene ID to filter by.
        limit: Maximum entries to return (default 50, max 200).
        offset: Number of entries to skip (default 0).

    Returns:
        Paginated list of event entries in seq order.

    Raises:
        HTTPException 401: If the request is not authenticated.
        HTTPException 403: If the character belongs to a different user.
        HTTPException 404: If the character does not exist or is deleted.
    """
    query = db.query(CharacterEvent).filter(CharacterEvent.character_id == character.id)

    if event_type is not None:
        query = query.filter(CharacterEvent.event_type == event_type)
    if run is not None:
        query = query.filter(CharacterEvent.run_number == run)
    if scene_id is not None:
        query = query.filter(CharacterEvent.scene_id == scene_id)

    query = query.order_by(CharacterEvent.seq)

    total = query.count()
    rows = query.offset(offset).limit(limit).all()

    items = [
        EventEntry(
            id=row.id,
            event_type=row.event_type,
            details=row.details,
            scene_id=row.scene_id,
            run_number=row.run_number,
            seq=row.seq,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]

    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{character_id}/runs")
def get_character_runs(
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> list[RunSummary]:
    """Return per-run summaries for a character.

    Each summary includes the run number, start time (from the first decision
    log entry in that run), outcome (death/in_progress/victory), death scene
    number if applicable, total decision count, and unique scenes visited.

    Args:
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        List of run summaries ordered by run number ascending.

    Raises:
        HTTPException 401: If the request is not authenticated.
        HTTPException 403: If the character belongs to a different user.
        HTTPException 404: If the character does not exist or is deleted.
    """
    # Query decision_log to get per-run stats
    run_stats = (
        db.query(
            DecisionLog.run_number,
            func.min(DecisionLog.created_at).label("started_at"),
            func.count(DecisionLog.id).label("decision_count"),
        )
        .filter(DecisionLog.character_id == character.id)
        .group_by(DecisionLog.run_number)
        .order_by(DecisionLog.run_number)
        .all()
    )

    # Query scene count per run (unique scenes visited = unique from_scene_ids)
    scene_visit_rows = (
        db.query(
            DecisionLog.run_number,
            func.count(func.distinct(DecisionLog.from_scene_id)).label("scenes_visited"),
        )
        .filter(DecisionLog.character_id == character.id)
        .group_by(DecisionLog.run_number)
        .all()
    )
    scenes_by_run = {row.run_number: row.scenes_visited for row in scene_visit_rows}

    # Query death events per run
    death_events = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.character_id == character.id,
            CharacterEvent.event_type == "death",
        )
        .all()
    )
    death_scene_by_run: dict[int, int | None] = {}
    for event in death_events:
        scene = db.query(Scene).filter(Scene.id == event.scene_id).first()
        death_scene_by_run[event.run_number] = scene.number if scene else None

    # Query victory events per run
    victory_run_numbers: set[int] = set()
    victory_events = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.character_id == character.id,
            CharacterEvent.event_type == "book_advance",
        )
        .all()
    )
    for event in victory_events:
        victory_run_numbers.add(event.run_number)

    # Also check replay events as a sign of victory
    replay_events = (
        db.query(CharacterEvent)
        .filter(
            CharacterEvent.character_id == character.id,
            CharacterEvent.event_type == "replay",
        )
        .all()
    )
    for event in replay_events:
        # The run that ended in victory is event.run_number - 1
        if event.run_number > 1:
            victory_run_numbers.add(event.run_number - 1)

    summaries: list[RunSummary] = []

    for row in run_stats:
        run_number = row.run_number
        is_dead = run_number in death_scene_by_run
        is_victory = run_number in victory_run_numbers

        if is_victory:
            outcome = "victory"
        elif is_dead:
            outcome = "death"
        else:
            outcome = "in_progress"

        summaries.append(
            RunSummary(
                run_number=run_number,
                started_at=row.started_at.isoformat() if row.started_at else None,
                outcome=outcome,
                death_scene_number=death_scene_by_run.get(run_number),
                decision_count=row.decision_count,
                scenes_visited=scenes_by_run.get(run_number, 0),
            )
        )

    # Include current run if no decision log entries yet
    current_run = character.current_run
    existing_run_numbers = {row.run_number for row in run_stats}
    if current_run not in existing_run_numbers:
        summaries.append(
            RunSummary(
                run_number=current_run,
                started_at=None,
                outcome="in_progress",
                death_scene_number=None,
                decision_count=0,
                scenes_visited=0,
            )
        )
        summaries.sort(key=lambda s: s.run_number)

    return summaries
