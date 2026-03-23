"""UI characters router — character creation flow, character list, sheet, and history.

These routes are at /ui/characters/* and serve HTMX + Jinja2 HTML pages.
They call the same service layer as the JSON API — no internal HTTP calls.
"""

import random
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.limiter import limiter
from app.models.content import Book, Choice, Discipline, Scene, WeaponCategory
from app.models.player import Character, DecisionLog, User
from app.models.wizard import CharacterWizardProgress, WizardTemplateStep
from app.routers.characters import get_active_wizard_info
from app.schemas.characters import CharacterDetailResponse, CharacterDisciplineInfo, CharacterItemInfo
from app.services.auth_service import create_roll_token
from app.services.character_service import create_character
from app.services.wizard_service import (
    get_wizard_state,
    handle_confirm_step,
    handle_discipline_step,
    handle_equipment_step,
    handle_inventory_adjust_step,
)
from app.ui_dependencies import get_current_ui_user, templates

router = APIRouter(prefix="/ui/characters", tags=["ui-characters"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_book1(db: Session) -> Book | None:
    """Return Book 1 (the only supported book for new characters)."""
    return db.query(Book).filter(Book.number == 1).first()


def _list_characters_for_user(db: Session, user: User) -> list[Character]:
    """Return all non-deleted characters for a user."""
    return (
        db.query(Character)
        .filter(
            Character.user_id == user.id,
            Character.is_deleted == False,  # noqa: E712
        )
        .all()
    )


def _get_owned_character(db: Session, user: User, character_id: int) -> Character | None:
    """Return a character owned by the user, or None if not found/not owned/deleted."""
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted:
        return None
    if character.user_id != user.id:
        return None
    return character


async def _render_create_error(
    request: Request,
    db: Session,
    error: str,
    roll_token: str,
    book_id: int,
) -> HTMLResponse:
    """Re-render the create form with an error message."""
    disciplines = (
        db.query(Discipline).filter(Discipline.era == "kai").order_by(Discipline.name).all()
    )
    weapon_categories_rows = db.query(WeaponCategory).order_by(WeaponCategory.category).all()
    seen: set[str] = set()
    unique_categories: list[str] = []
    for wc in weapon_categories_rows:
        if wc.category not in seen:
            seen.add(wc.category)
            unique_categories.append(wc.category)

    return templates.TemplateResponse(
        request,
        "characters/create.html",
        {
            "roll_token": roll_token,
            "book_id": book_id,
            "disciplines": disciplines,
            "weapon_categories": unique_categories,
            "error": error,
        },
        status_code=400,
    )


# ---------------------------------------------------------------------------
# Character list
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def character_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the character list page."""
    characters = _list_characters_for_user(db, current_user)

    enriched = []
    for char in characters:
        book = db.query(Book).filter(Book.id == char.book_id).first()
        book_title = book.title if book else f"Book {char.book_id}"
        current_scene_number: int | None = None
        if char.current_scene_id is not None:
            scene = db.query(Scene).filter(Scene.id == char.current_scene_id).first()
            if scene:
                current_scene_number = scene.number
        enriched.append({
            "id": char.id,
            "name": char.name,
            "book_title": book_title,
            "combat_skill": char.combat_skill_base,
            "endurance": char.endurance_current,
            "endurance_max": char.endurance_max,
            "is_alive": char.is_alive,
            "death_count": char.death_count,
            "current_scene_number": current_scene_number,
            "has_active_wizard": char.active_wizard_id is not None,
        })

    return templates.TemplateResponse(
        request,
        "characters/list.html",
        {"characters": enriched},
    )


# ---------------------------------------------------------------------------
# Roll stats
# ---------------------------------------------------------------------------


@router.get("/roll", response_class=HTMLResponse)
@limiter.limit("20/minute")
def roll_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the stat-roll page with a fresh set of stats."""
    book = _get_book1(db)
    if book is None:
        return templates.TemplateResponse(
            request,
            "characters/roll.html",
            {"error": "No book available. Please contact an administrator.", "roll": None},
        )

    cs_bonus = random.randint(0, 9)
    end_bonus = random.randint(0, 9)
    cs = 10 + cs_bonus
    end = 20 + end_bonus
    roll_token = create_roll_token(user_id=current_user.id, cs=cs, end=end, book_id=book.id)

    return templates.TemplateResponse(
        request,
        "characters/roll.html",
        {
            "roll": {
                "combat_skill": cs,
                "endurance": end,
                "cs_formula": f"10 + {cs_bonus}",
                "end_formula": f"20 + {end_bonus}",
                "roll_token": roll_token,
                "book_id": book.id,
            },
            "error": None,
        },
    )


@router.post("/roll", response_class=HTMLResponse)
@limiter.limit("20/minute")
def roll_reroll(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Re-roll stats — returns an HTMX fragment replacing #stats-display."""
    book = _get_book1(db)
    if book is None:
        return HTMLResponse(
            content='<div id="stats-display"><p>Book not found.</p></div>',
            status_code=500,
        )

    cs_bonus = random.randint(0, 9)
    end_bonus = random.randint(0, 9)
    cs = 10 + cs_bonus
    end = 20 + end_bonus
    roll_token = create_roll_token(user_id=current_user.id, cs=cs, end=end, book_id=book.id)

    return templates.TemplateResponse(
        request,
        "characters/partials/stats_display.html",
        {
            "roll": {
                "combat_skill": cs,
                "endurance": end,
                "cs_formula": f"10 + {cs_bonus}",
                "end_formula": f"20 + {end_bonus}",
                "roll_token": roll_token,
                "book_id": book.id,
            },
        },
    )


# ---------------------------------------------------------------------------
# Create character form
# ---------------------------------------------------------------------------


@router.get("/create", response_class=HTMLResponse)
def create_page(
    request: Request,
    roll_token: str = "",
    book_id: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the character creation form (name + disciplines)."""
    disciplines = (
        db.query(Discipline).filter(Discipline.era == "kai").order_by(Discipline.name).all()
    )
    weapon_categories_rows = db.query(WeaponCategory).order_by(WeaponCategory.category).all()
    seen: set[str] = set()
    unique_categories: list[str] = []
    for wc in weapon_categories_rows:
        if wc.category not in seen:
            seen.add(wc.category)
            unique_categories.append(wc.category)

    return templates.TemplateResponse(
        request,
        "characters/create.html",
        {
            "roll_token": roll_token,
            "book_id": book_id,
            "disciplines": disciplines,
            "weapon_categories": unique_categories,
            "error": None,
        },
    )


@router.post("/create", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def create_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Handle character creation form submission (async to support multi-value fields).

    Reads ``discipline_ids`` as a repeated form field. On success, redirects to
    the wizard page for the new character. On failure, re-renders the form
    with an error message.
    """
    form = await request.form()

    name = str(form.get("name", "")).strip()
    book_id_raw = form.get("book_id", "0")
    roll_token = str(form.get("roll_token", ""))
    weapon_skill_type_raw = str(form.get("weapon_skill_type", "")).strip()
    weapon_skill_type: str | None = weapon_skill_type_raw if weapon_skill_type_raw else None

    try:
        book_id = int(book_id_raw)
    except (TypeError, ValueError):
        book_id = 0

    # Multi-value discipline_ids field
    discipline_id_strs = form.getlist("discipline_ids")
    discipline_ids: list[int] = []
    for raw in discipline_id_strs:
        try:
            discipline_ids.append(int(raw))
        except (TypeError, ValueError):
            pass

    # Client-side validation for better UX
    if not name:
        return await _render_create_error(request, db, "Character name is required.", roll_token, book_id)
    if len(name) > 100:
        return await _render_create_error(request, db, "Name must be 100 characters or fewer.", roll_token, book_id)
    if len(discipline_ids) != 5:
        return await _render_create_error(
            request,
            db,
            f"You must choose exactly 5 disciplines (you chose {len(discipline_ids)}).",
            roll_token,
            book_id,
        )

    try:
        character = create_character(
            db=db,
            user=current_user,
            name=name,
            book_id=book_id,
            roll_token=roll_token,
            discipline_ids=discipline_ids,
            weapon_skill_type=weapon_skill_type,
        )
    except LookupError as exc:
        return await _render_create_error(request, db, str(exc), roll_token, book_id)
    except ValueError as exc:
        msg = str(exc)
        if "INVALID_ROLL_TOKEN" in msg:
            # Roll token expired or invalid — send back to roll page
            return RedirectResponse(url="/ui/characters/roll", status_code=303)
        return await _render_create_error(request, db, msg, roll_token, book_id)

    return RedirectResponse(url=f"/ui/characters/{character.id}/wizard", status_code=303)


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


@router.get("/{character_id}/wizard", response_class=HTMLResponse)
def wizard_get(
    character_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the appropriate wizard step template for the character."""
    character = _get_owned_character(db, current_user, character_id)
    if character is None:
        return RedirectResponse(url="/ui/characters", status_code=303)

    if character.active_wizard_id is None:
        # No active wizard — redirect to game (placeholder URL)
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        state = get_wizard_state(db, character)
    except (LookupError, ValueError):
        return RedirectResponse(url="/ui/characters", status_code=303)

    step = state.get("step", "")

    if step == "pick_equipment":
        return templates.TemplateResponse(
            request,
            "characters/wizard_equipment.html",
            {
                "character_id": character_id,
                "version": character.version,
                "included_items": state.get("included_items", []),
                "auto_applied": state.get("auto_applied", {}),
                "available_equipment": state.get("available_equipment", []),
                "pick_limit": state.get("pick_limit", 2),
                "step_index": state.get("step_index", 0),
                "total_steps": state.get("total_steps", 1),
            },
        )

    elif step == "confirm":
        # Determine which confirm template based on wizard type
        wizard_type = state.get("wizard_type", "character_creation")
        template_name = (
            "characters/wizard_advance_confirm.html"
            if wizard_type == "book_advance"
            else "characters/wizard_confirm.html"
        )
        preview = state.get("character_preview", {})
        return templates.TemplateResponse(
            request,
            template_name,
            {
                "character_id": character_id,
                "version": character.version,
                "preview": preview,
                "wizard": state,
                "step_index": state.get("step_index", 0),
                "total_steps": state.get("total_steps", 1),
            },
        )

    elif step == "pick_disciplines":
        current_disciplines = state.get("current_disciplines", [])
        return templates.TemplateResponse(
            request,
            "characters/wizard_disciplines.html",
            {
                "character_id": character_id,
                "version": character.version,
                "wizard": state,
                "current_disciplines": current_disciplines,
                "has_weaponskill": state.get("has_weaponskill", False),
                "weapon_categories": state.get("weapon_categories", []),
            },
        )

    elif step == "inventory_adjust":
        return templates.TemplateResponse(
            request,
            "characters/wizard_inventory.html",
            {
                "character_id": character_id,
                "version": character.version,
                "wizard": state,
            },
        )

    else:
        # Unknown step — redirect to list
        return RedirectResponse(url="/ui/characters", status_code=303)


@router.post("/{character_id}/wizard", response_class=HTMLResponse)
async def wizard_post(
    character_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Submit the current wizard step and redirect to next step or character list."""
    character = _get_owned_character(db, current_user, character_id)
    if character is None:
        return RedirectResponse(url="/ui/characters", status_code=303)

    form = await request.form()
    step = str(form.get("step", ""))
    version_raw = form.get("version", "")
    try:
        version = int(version_raw)
    except (TypeError, ValueError):
        return RedirectResponse(url=f"/ui/characters/{character_id}/wizard", status_code=303)

    if step == "pick_equipment":
        selected_items = list(form.getlist("selected_items"))
        try:
            handle_equipment_step(
                db=db,
                character=character,
                selected_items=selected_items,
                version=version,
            )
        except (LookupError, ValueError):
            return RedirectResponse(
                url=f"/ui/characters/{character_id}/wizard",
                status_code=303,
            )
        return RedirectResponse(url=f"/ui/characters/{character_id}/wizard", status_code=303)

    elif step == "confirm":
        try:
            handle_confirm_step(db=db, character=character, version=version)
        except (LookupError, ValueError):
            return RedirectResponse(
                url=f"/ui/characters/{character_id}/wizard",
                status_code=303,
            )
        return RedirectResponse(url="/ui/characters", status_code=303)

    elif step == "pick_disciplines":
        discipline_id_raw = form.get("discipline_id", "")
        weapon_skill_type_raw = str(form.get("weapon_skill_type", "")).strip()
        weapon_skill_type: str | None = weapon_skill_type_raw if weapon_skill_type_raw else None
        try:
            discipline_ids = [int(discipline_id_raw)] if discipline_id_raw else []
        except (TypeError, ValueError):
            discipline_ids = []
        try:
            handle_discipline_step(
                db=db,
                character=character,
                discipline_ids=discipline_ids,
                weapon_skill_type=weapon_skill_type,
                version=version,
            )
        except (LookupError, ValueError):
            return RedirectResponse(
                url=f"/ui/characters/{character_id}/wizard",
                status_code=303,
            )
        return RedirectResponse(url=f"/ui/characters/{character_id}/wizard", status_code=303)

    elif step == "inventory_adjust":
        keep_weapons = list(form.getlist("keep_weapons"))
        keep_backpack = list(form.getlist("keep_backpack"))
        try:
            handle_inventory_adjust_step(
                db=db,
                character=character,
                keep_weapons=keep_weapons,
                keep_backpack=keep_backpack,
                version=version,
            )
        except (LookupError, ValueError):
            return RedirectResponse(
                url=f"/ui/characters/{character_id}/wizard",
                status_code=303,
            )
        return RedirectResponse(url=f"/ui/characters/{character_id}/wizard", status_code=303)

    else:
        return RedirectResponse(url=f"/ui/characters/{character_id}/wizard", status_code=303)


# ---------------------------------------------------------------------------
# Character sheet (Story 8.6)
# ---------------------------------------------------------------------------

_HISTORY_PAGE_SIZE = 50


def _get_owned_character_or_404(db: Session, user: User, character_id: int) -> Character:
    """Return a character owned by the user; raise HTTP 404/403 if not accessible."""
    character = (
        db.query(Character)
        .filter(Character.id == character_id, Character.is_deleted == False)  # noqa: E712
        .first()
    )
    if character is None:
        raise HTTPException(status_code=404, detail="Character not found")
    if character.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not your character")
    return character


def _build_character_detail_ctx(db: Session, character: Character) -> CharacterDetailResponse:
    """Build a CharacterDetailResponse from an ORM Character instance."""
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


@router.get("/{character_id}/sheet", response_class=HTMLResponse)
def character_sheet(
    request: Request,
    character_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the character sheet page."""
    character = _get_owned_character_or_404(db, current_user, character_id)
    detail = _build_character_detail_ctx(db, character)

    return templates.TemplateResponse(
        request,
        "characters/sheet.html",
        {"character": detail},
    )


# ---------------------------------------------------------------------------
# Character history (Story 8.6)
# ---------------------------------------------------------------------------


@router.get("/{character_id}/history", response_class=HTMLResponse)
def character_history(
    request: Request,
    character_id: int,
    run: Annotated[int | None, Query(ge=1)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    partial: Annotated[int, Query()] = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_ui_user),
) -> HTMLResponse:
    """Render the character decision history page.

    Supports run filter (?run=N) and HTMX "Load More" pagination (?partial=1).
    When the request is an HTMX partial load (offset > 0 or partial=1), only the
    table row fragment is returned for appending to the existing table body.
    """
    character = _get_owned_character_or_404(db, current_user, character_id)

    query = db.query(DecisionLog).filter(DecisionLog.character_id == character.id)
    if run is not None:
        query = query.filter(DecisionLog.run_number == run)
    query = query.order_by(DecisionLog.created_at)

    total = query.count()
    rows = query.offset(offset).limit(_HISTORY_PAGE_SIZE).all()

    # Load related scene and choice data
    scene_ids: set[int] = set()
    choice_ids: set[int] = set()
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

    history = []
    for row in rows:
        from_scene = scenes_by_id.get(row.from_scene_id)
        to_scene = scenes_by_id.get(row.to_scene_id)
        choice = choices_by_id.get(row.choice_id) if row.choice_id else None
        history.append(
            {
                "run_number": row.run_number,
                "scene_number": from_scene.number if from_scene else None,
                "choice_text": choice.display_text if choice else None,
                "target_scene_number": to_scene.number if to_scene else None,
                "action_type": row.action_type,
                "created_at": row.created_at.isoformat(),
            }
        )

    next_offset = offset + _HISTORY_PAGE_SIZE
    has_more = next_offset < total

    # Determine distinct run numbers for the filter dropdown
    run_rows = (
        db.query(DecisionLog.run_number)
        .filter(DecisionLog.character_id == character.id)
        .distinct()
        .order_by(DecisionLog.run_number)
        .all()
    )
    runs = [r[0] for r in run_rows]

    # HTMX partial: return only table rows for "Load More" appending
    is_htmx_partial = bool(partial) or (offset > 0 and request.headers.get("HX-Request"))
    if is_htmx_partial:
        return templates.TemplateResponse(
            request,
            "characters/history_rows.html",
            {"history": history},
        )

    return templates.TemplateResponse(
        request,
        "characters/history.html",
        {
            "character": character,
            "history": history,
            "runs": runs,
            "selected_run": run,
            "has_more": has_more,
            "next_offset": next_offset,
        },
    )
