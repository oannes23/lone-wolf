"""UI gameplay router — scene display, choice submission, and lifecycle actions.

These routes are at /ui/game/* and serve HTMX + Jinja2 HTML pages.
They call the same service layer as the JSON API — no internal HTTP calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Report
from app.models.player import Character, User
from app.schemas.reports import VALID_TAGS
from app.limiter import limiter
from app.services.combat_service import resolve_evasion, resolve_round
from app.services.item_service import (
    process_inventory_action,
    process_item_action,
    process_use_item,
)
from app.services.roll_service import process_roll
from app.services.scene_service import get_scene_state
from app.services.transition_service import process_choose, transition_to_scene
from app.services.lifecycle_service import replay, restart
from app.services.wizard_service import init_book_advance_wizard
from app.ui_dependencies import get_current_ui_user, templates

router = APIRouter(prefix="/ui/game", tags=["ui-gameplay"])


# ---------------------------------------------------------------------------
# UI-layer character ownership dependency (cookie auth)
# ---------------------------------------------------------------------------


def _get_ui_owned_character(
    character_id: int,
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> Character:
    """Resolve a character by ID that belongs to the authenticated UI user.

    Args:
        character_id: The character's primary key from the URL path.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        The ``Character`` ORM instance.

    Raises:
        HTTPException 404: If the character does not exist or is soft-deleted.
        HTTPException 403: If the character belongs to a different user.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted:
        raise HTTPException(status_code=404, detail="Character not found")
    if character.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your character")
    return character


# ---------------------------------------------------------------------------
# GET /ui/game/{character_id} — scene display
# ---------------------------------------------------------------------------


@router.get("/{character_id}", response_class=HTMLResponse)
def scene_page(
    request: Request,
    character: Character = Depends(_get_ui_owned_character),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Render the current scene for a character.

    Assembles narrative, phase results, choices, and special states (death,
    victory) and renders the scene template.

    Args:
        request: The incoming HTTP request.
        character: The authenticated user's character.
        db: Database session.

    Returns:
        Rendered ``gameplay/scene.html`` template.
    """
    try:
        scene_data = get_scene_state(db=db, character=character)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return templates.TemplateResponse(
        request,
        "gameplay/scene.html",
        {
            "character": character,
            "scene": scene_data,
            "valid_tags": sorted(VALID_TAGS),
        },
    )


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/choose — submit a choice
# ---------------------------------------------------------------------------


@router.post("/{character_id}/choose")
@limiter.limit("30/minute")
def choose_submit(
    request: Request,
    character_id: int,
    choice_id: int = Form(...),
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle a player's choice selection.

    Validates the choice, processes the transition (or roll requirement), and
    redirects back to the scene page.  The scene page will render the updated
    state after the redirect.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        choice_id: The chosen choice's ID from the form.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    # Version check — on mismatch, redirect back (scene will be current)
    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        process_choose(db=db, character=character, choice_id=choice_id)
    except (ValueError, LookupError):
        pass  # On any error redirect back — scene will show current state

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/restart — restart after death
# ---------------------------------------------------------------------------


@router.post("/{character_id}/restart")
@limiter.limit("10/minute")
def restart_submit(
    request: Request,
    character_id: int,
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle a restart request for a dead character.

    Restores stats and items from the book start snapshot, increments
    death_count and current_run, and redirects to the scene page.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        restart(db=db, character=character)
    except ValueError:
        pass

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/replay — replay book after victory
# ---------------------------------------------------------------------------


@router.post("/{character_id}/replay")
@limiter.limit("10/minute")
def replay_submit(
    request: Request,
    character_id: int,
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Handle a replay request after reaching a victory scene.

    Restores stats and items from the book start snapshot, increments
    current_run, and redirects to the scene page.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        replay(db=db, character=character)
    except ValueError:
        pass

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/advance — start book advance wizard
# ---------------------------------------------------------------------------


@router.post("/{character_id}/advance")
@limiter.limit("10/minute")
def advance_submit(
    request: Request,
    character_id: int,
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Start the book advance wizard after reaching a victory scene.

    Initializes the advance wizard and redirects to the wizard page.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        init_book_advance_wizard(db=db, character=character)
    except ValueError:
        pass  # Redirect back to scene on any error (scene will show current state)

    return RedirectResponse(url=f"/ui/characters/{character_id}/wizard", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/combat/round — resolve one combat round
# ---------------------------------------------------------------------------


@router.post("/{character_id}/combat/round")
@limiter.limit("60/minute")
def combat_round_submit(
    request: Request,
    character_id: int,
    version: int = Form(...),
    use_psi_surge: bool = Form(default=False),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Resolve one round of combat and redirect back to the scene.

    Validates the character is in combat phase, calls the combat service to
    resolve the round, then redirects to the scene page where the updated
    combat state will be rendered.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        version: The optimistic lock version from the form.
        use_psi_surge: Whether to activate Psi-surge for this round.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    # Version mismatch — redirect back silently
    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    # Phase check
    if character.scene_phase != "combat":
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    if not character.is_alive:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        resolve_round(db=db, character=character, use_psi_surge=use_psi_surge)
    except ValueError:
        pass  # On any error just redirect back

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/combat/evasion — attempt evasion
# ---------------------------------------------------------------------------


@router.post("/{character_id}/combat/evasion")
@limiter.limit("30/minute")
def combat_evasion_submit(
    request: Request,
    character_id: int,
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Attempt to evade combat and redirect back to the scene.

    Validates evasion eligibility, applies evasion damage, handles death if it
    occurs, and (on survival) transitions the character to the evasion target
    scene.  Always redirects back to the scene page to display the result.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    if character.scene_phase != "combat":
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    if not character.is_alive:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        resolve_evasion(db=db, character=character)
    except ValueError:
        pass  # Evasion not yet allowed or other error — redirect back

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/roll — resolve a random roll
# ---------------------------------------------------------------------------


@router.post("/{character_id}/roll")
@limiter.limit("60/minute")
def roll_submit(
    request: Request,
    character_id: int,
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Resolve a random roll and redirect back to the scene.

    Handles all three roll types: choice-triggered random (pending_choice_id set),
    phase-based random (scene_phase='random' with random_outcomes), and
    scene-level random exit (all choices have condition_type='random').

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    import random as _random

    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    # Must be in random phase or have a pending choice
    if character.scene_phase != "random" and character.pending_choice_id is None:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    random_number = _random.randint(0, 9)

    try:
        process_roll(db=db, character=character, random_number=random_number)
    except ValueError:
        pass  # On any error just redirect back

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/item/accept — accept a pending scene item
# ---------------------------------------------------------------------------


@router.post("/{character_id}/item/accept")
@limiter.limit("60/minute")
def item_accept_submit(
    request: Request,
    character_id: int,
    scene_item_id: int = Form(...),
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Accept a pending scene item and redirect back to the scene.

    Adds the item to the character's inventory, logs an item_pickup event,
    and advances the phase when all pending items are resolved.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        scene_item_id: The scene_items row primary key from the form.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        process_item_action(
            db=db,
            character=character,
            scene_item_id=scene_item_id,
            action="accept",
        )
    except (LookupError, ValueError):
        pass  # On any error redirect back — scene will show current state

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/item/decline — decline a pending scene item
# ---------------------------------------------------------------------------


@router.post("/{character_id}/item/decline")
@limiter.limit("60/minute")
def item_decline_submit(
    request: Request,
    character_id: int,
    scene_item_id: int = Form(...),
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Decline a pending scene item and redirect back to the scene.

    Logs an item_decline event and advances the phase when all pending items
    are resolved.  Mandatory items cannot be declined and will redirect back
    without change.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        scene_item_id: The scene_items row primary key from the form.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        process_item_action(
            db=db,
            character=character,
            scene_item_id=scene_item_id,
            action="decline",
        )
    except (LookupError, ValueError):
        pass  # Mandatory items raise ValueError — redirect back silently

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/item/drop — drop an inventory item
# ---------------------------------------------------------------------------


@router.post("/{character_id}/item/drop")
@limiter.limit("60/minute")
def item_drop_submit(
    request: Request,
    character_id: int,
    character_item_id: int = Form(...),
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Drop an item from the character's inventory and redirect back to the scene.

    Removes the item, recalculates endurance_max, and logs an item_loss event.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        character_item_id: The character_items row primary key from the form.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        process_inventory_action(
            db=db,
            character=character,
            character_item_id=character_item_id,
            action="drop",
        )
    except (LookupError, ValueError):
        pass

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/item/equip — equip a weapon
# ---------------------------------------------------------------------------


@router.post("/{character_id}/item/equip")
@limiter.limit("60/minute")
def item_equip_submit(
    request: Request,
    character_id: int,
    character_item_id: int = Form(...),
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Equip a weapon from the character's inventory and redirect back to the scene.

    Sets is_equipped on the weapon item.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        character_item_id: The character_items row primary key from the form.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        process_inventory_action(
            db=db,
            character=character,
            character_item_id=character_item_id,
            action="equip",
        )
    except (LookupError, ValueError):
        pass

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/item/unequip — unequip a weapon
# ---------------------------------------------------------------------------


@router.post("/{character_id}/item/unequip")
@limiter.limit("60/minute")
def item_unequip_submit(
    request: Request,
    character_id: int,
    character_item_id: int = Form(...),
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Unequip a weapon from the character's inventory and redirect back to the scene.

    Clears is_equipped on the weapon item.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        character_item_id: The character_items row primary key from the form.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        process_inventory_action(
            db=db,
            character=character,
            character_item_id=character_item_id,
            action="unequip",
        )
    except (LookupError, ValueError):
        pass

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/item/use — use a consumable item
# ---------------------------------------------------------------------------


@router.post("/{character_id}/item/use")
@limiter.limit("60/minute")
def item_use_submit(
    request: Request,
    character_id: int,
    character_item_id: int = Form(...),
    version: int = Form(...),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Use a consumable item from the character's inventory and redirect back to the scene.

    Applies the item's effect (e.g. Healing Potion restores endurance), removes
    the item, recalculates endurance_max, and logs an item_consumed event.
    Blocked during combat phase — redirects back silently.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        character_item_id: The character_items row primary key from the form.
        version: The optimistic lock version from the form.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        303 redirect to ``/ui/game/{character_id}``.
    """
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Character not found")

    if version != character.version:
        return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)

    try:
        process_use_item(
            db=db,
            character=character,
            character_item_id=character_item_id,
        )
    except (LookupError, ValueError):
        pass  # Blocked in combat or not consumable — redirect back silently

    return RedirectResponse(url=f"/ui/game/{character_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /ui/game/{character_id}/report — submit a bug report (HTMX partial)
# ---------------------------------------------------------------------------


@router.post("/{character_id}/report", response_class=HTMLResponse)
def report_submit(
    request: Request,
    character_id: int,
    tags: list[str] = Form(default=[]),
    free_text: str = Form(default=""),
    scene_id: int = Form(default=0),
    current_user: User = Depends(get_current_ui_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Handle bug report form submission via HTMX.

    Creates a Report record linked to the authenticated user and returns
    a success partial HTML response swapped in by HTMX.

    Args:
        request: The incoming HTTP request.
        character_id: The character's primary key from the URL path.
        tags: Selected bug category tags from the form checkboxes.
        free_text: Free-text description of the bug.
        scene_id: The scene ID where the bug occurred.
        current_user: The authenticated user from the session cookie.
        db: Database session.

    Returns:
        HTML success message partial for HTMX to swap in.
    """
    # Verify character ownership
    character = db.query(Character).filter(Character.id == character_id).first()
    if not character or character.is_deleted or character.user_id != current_user.id:
        return HTMLResponse(
            content='<div class="alert alert-error" role="alert">Character not found.</div>',
        )

    # Filter to valid tags only
    valid_submitted = [t for t in tags if t in VALID_TAGS]

    now = datetime.now(timezone.utc)
    report = Report(
        user_id=current_user.id,
        character_id=character.id,
        scene_id=scene_id if scene_id else None,
        tags=json.dumps(valid_submitted),
        free_text=free_text.strip() or None,
        status="open",
        created_at=now,
        updated_at=now,
    )
    db.add(report)
    db.flush()

    return HTMLResponse(
        content=(
            '<div class="alert alert-success" role="alert">'
            "Report submitted. Thank you for the feedback."
            "</div>"
        ),
    )
