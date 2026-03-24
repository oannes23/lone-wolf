"""Gameplay router — scene navigation, lifecycle endpoints, and book advance wizard initiation."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_owned_character, verify_version
from app.models.player import Character
from app.schemas.characters import AdvanceInitResponse, AdvanceWizardBookInfo
from app.schemas.gameplay import (
    ChoiceRandomResponse,
    CombatRoundRequest,
    CombatRoundResponse,
    EvadeRequest,
    EvadeResponse,
    InventoryActionRequest,
    InventoryResponse,
    ItemActionRequest,
    ItemActionResponse,
    ReplayRequest,
    RestartRequest,
    RollPhaseEffectResponse,
    RollRequest,
    RollSceneTransitionResponse,
    SceneResponse,
    UseItemRequest,
    UseItemResponse,
)
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

router = APIRouter(prefix="/gameplay", tags=["gameplay"])


class AdvanceRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/advance."""

    version: int = Field(..., description="Optimistic lock version")


class ChooseRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/choose."""

    choice_id: int = Field(..., description="ID of the choice to make")
    version: int = Field(..., description="Optimistic lock version")


@router.get("/{character_id}/scene", response_model=SceneResponse)
def get_scene(
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> SceneResponse:
    """Get the current scene state for a character.

    Assembles narrative, phase info, choices, combat state, and pending items
    from the current scene and character state.

    Args:
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Full scene state as a SceneResponse.

    Raises:
        HTTPException 404: If the character has no current scene.
    """
    try:
        return get_scene_state(db=db, character=character)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{character_id}/choose")
def choose(
    body: ChooseRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> SceneResponse | ChoiceRandomResponse:
    """Make a choice to navigate to the next scene.

    Validates the choice against the character's current state, deducts gold
    for gold-gated choices, and either triggers a random roll (for choices with
    random outcomes) or transitions the character to the target scene running
    all automatic phases.

    Args:
        body: Request body with choice_id and version.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Full scene state (SceneResponse) after transition, or a
        ChoiceRandomResponse if the choice requires a random roll first.

    Raises:
        HTTPException 409: VERSION_MISMATCH, WRONG_PHASE, PENDING_ITEMS,
            COMBAT_UNRESOLVED.
        HTTPException 400: CHOICE_UNAVAILABLE, INVALID_CHOICE.
        HTTPException 404: If the choice or target scene is not found.
    """
    verify_version(character, body.version)

    try:
        result = process_choose(db=db, character=character, choice_id=body.choice_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        for error_code in ("WRONG_PHASE", "PENDING_ITEMS", "COMBAT_UNRESOLVED"):
            if msg.startswith(error_code):
                return JSONResponse(
                    status_code=409,
                    content={"detail": msg, "error_code": error_code},
                )
        for error_code in ("CHOICE_UNAVAILABLE", "PATH_UNAVAILABLE", "INVALID_CHOICE"):
            if msg.startswith(error_code):
                return JSONResponse(
                    status_code=400,
                    content={"detail": msg, "error_code": error_code},
                )
        raise HTTPException(status_code=400, detail=msg) from exc

    if result["type"] == "requires_roll":
        return ChoiceRandomResponse(
            requires_roll=True,
            choice_id=result["choice_id"],
            choice_text=result["choice_text"],
            outcome_bands=result["outcome_bands"],
            version=result["version"],
        )
    return result["scene_response"]


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
                content={"detail": msg, "error_code": "WIZARD_ACTIVE"},
            )
        return JSONResponse(
            status_code=409,
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


@router.post("/{character_id}/restart", response_model=SceneResponse)
def restart_character_endpoint(
    body: RestartRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> SceneResponse:
    """Restart a dead character from their book start snapshot.

    Validates that the character is dead, restores stats, items, and disciplines
    from the CharacterBookStart snapshot, increments death_count and current_run,
    and places the character at the book's start scene.

    Args:
        body: Request body with the required version field.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Full scene state at the book's start scene.

    Raises:
        HTTPException 400: If the character is alive (must be dead to restart).
        HTTPException 409: If version does not match.
        HTTPException 422: If version is missing.
    """
    verify_version(character, body.version)

    try:
        return restart(db=db, character=character)
    except ValueError as exc:
        msg = str(exc)
        if "CHARACTER_ALIVE" in msg:
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "CHARACTER_ALIVE"},
            )
        raise HTTPException(status_code=400, detail=msg) from exc


@router.post("/{character_id}/replay", response_model=SceneResponse)
def replay_character_endpoint(
    body: ReplayRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> SceneResponse:
    """Replay a book from the start after reaching a victory scene.

    Validates that the character is at a victory scene and has no active advance
    wizard, restores stats, items, and disciplines from the CharacterBookStart
    snapshot, increments current_run only (death_count unchanged), and places
    the character at the book's start scene.

    Args:
        body: Request body with the required version field.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Full scene state at the book's start scene.

    Raises:
        HTTPException 400: If the character is not at a victory scene.
        HTTPException 409: If an advance wizard is active (WIZARD_ACTIVE), or
            if version does not match.
        HTTPException 422: If version is missing.
    """
    verify_version(character, body.version)

    try:
        return replay(db=db, character=character)
    except ValueError as exc:
        msg = str(exc)
        if "WIZARD_ACTIVE" in msg:
            return JSONResponse(
                status_code=409,
                content={"detail": msg, "error_code": "WIZARD_ACTIVE"},
            )
        if "NOT_AT_VICTORY" in msg:
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "NOT_AT_VICTORY"},
            )
        raise HTTPException(status_code=400, detail=msg) from exc


@router.post("/{character_id}/combat/round", response_model=CombatRoundResponse)
def combat_round(
    body: CombatRoundRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> CombatRoundResponse:
    """Resolve one round of combat for the active encounter.

    Server-generates the random number (0-9), looks up the Combat Results Table,
    applies damage to both sides, and persists the CombatRound row.

    - If the hero dies: marks character dead, logs death event with
      parent_event_id pointing to the combat_end event.
    - If the enemy dies: checks for more enemies (advances to next encounter)
      or advances the scene phase past combat.
    - If psi_surge is requested and the character has Psi-surge discipline:
      +4 CS this round, hero takes +2 extra END cost.

    Args:
        body: Request body with use_psi_surge flag and version.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Round details including both damage values, endurance remainders,
        combat_over flag, result ("win"/"loss"/"continue"), and evasion state.

    Raises:
        HTTPException 409: VERSION_MISMATCH or WRONG_PHASE.
        HTTPException 400: If the character is dead or has no active encounter.
    """
    # Version check
    verify_version(character, body.version)

    # Phase check
    if character.scene_phase != "combat":
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"Character is in '{character.scene_phase}' phase, not 'combat'.",
                "error_code": "WRONG_PHASE",
            },
        )

    # Alive check
    if not character.is_alive:
        raise HTTPException(status_code=400, detail="Character is dead.")

    try:
        return resolve_round(db=db, character=character, use_psi_surge=body.use_psi_surge)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{character_id}/combat/evade", response_model=EvadeResponse)
def combat_evade(
    body: EvadeRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> EvadeResponse:
    """Attempt to evade the active combat encounter.

    Evasion is only allowed once ``rounds_fought >= evasion_after_rounds``.
    The hero takes ``evasion_damage`` endurance loss regardless of outcome.

    - If evasion_damage kills the hero: character dies at the current scene
      (no transition). Returns scene response with is_alive=False.
    - On survival: transitions to the evasion target scene, runs all automatic
      phases, and returns the new scene state.

    Args:
        body: Request body with version.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        EvadeResponse (SceneResponse + evasion_damage field).

    Raises:
        HTTPException 409: VERSION_MISMATCH or WRONG_PHASE.
        HTTPException 400: Evasion not yet allowed, no active encounter,
            or character is dead.
    """
    # Version check
    verify_version(character, body.version)

    # Phase check
    if character.scene_phase != "combat":
        return JSONResponse(
            status_code=409,
            content={
                "detail": f"Character is in '{character.scene_phase}' phase, not 'combat'.",
                "error_code": "WRONG_PHASE",
            },
        )

    # Alive check
    if not character.is_alive:
        raise HTTPException(status_code=400, detail="Character is dead.")

    try:
        evasion_damage, hero_died = resolve_evasion(db=db, character=character)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Assemble scene response
    scene_response = get_scene_state(db=db, character=character)

    return EvadeResponse(
        scene_number=scene_response.scene_number,
        narrative=scene_response.narrative,
        illustration_url=scene_response.illustration_url,
        phase=scene_response.phase,
        phase_index=scene_response.phase_index,
        phase_sequence=scene_response.phase_sequence,
        phase_results=scene_response.phase_results,
        choices=scene_response.choices,
        combat=scene_response.combat,
        pending_items=scene_response.pending_items,
        is_death=scene_response.is_death,
        is_victory=scene_response.is_victory,
        is_alive=scene_response.is_alive,
        version=scene_response.version,
        evasion_damage=evasion_damage,
    )


@router.post("/{character_id}/item", status_code=200, response_model=ItemActionResponse)
def item_action(
    body: ItemActionRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> ItemActionResponse:
    """Accept or decline a pending scene item.

    Accept adds the item to the character's inventory (subject to slot limits)
    and logs an ``item_pickup`` event.  Decline logs an ``item_decline`` event.
    Mandatory items cannot be declined.

    When all pending items are resolved and the character is in the 'items'
    phase, the phase is automatically advanced.

    Args:
        body: ``scene_item_id``, ``action`` (accept|decline), and ``version``.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Item details, pending_items_remaining, phase_complete flag, inventory.

    Raises:
        HTTPException 400: If inventory is full (INVENTORY_FULL) or the item
            is mandatory and the action is decline (ITEM_MANDATORY).
        HTTPException 404: If the scene_item_id is not found.
        HTTPException 409: If the version does not match (VERSION_MISMATCH).
    """
    verify_version(character, body.version)

    try:
        result = process_item_action(
            db=db,
            character=character,
            scene_item_id=body.scene_item_id,
            action=body.action,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("INVENTORY_FULL"):
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "INVENTORY_FULL"},
            )
        if msg.startswith("ITEM_MANDATORY"):
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "ITEM_MANDATORY"},
            )
        raise HTTPException(status_code=400, detail=msg) from exc

    return ItemActionResponse(**result)


@router.post("/{character_id}/inventory", status_code=200, response_model=InventoryResponse)
def inventory_action(
    body: InventoryActionRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> InventoryResponse:
    """Manage a character's inventory: drop, equip, or unequip an item.

    Available in any scene phase (including the items phase for swapping).
    Drop removes the item and recalculates endurance_max.  Equip/unequip
    toggle the ``is_equipped`` flag on a weapon.  Only weapons may be
    equipped.

    Args:
        body: ``action`` (drop|equip|unequip), ``character_item_id``, ``version``.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Current inventory and updated version.

    Raises:
        HTTPException 400: If the operation is invalid (e.g., equip a non-weapon).
        HTTPException 404: If the character_item_id is not found.
        HTTPException 409: If the version does not match (VERSION_MISMATCH).
    """
    verify_version(character, body.version)

    try:
        result = process_inventory_action(
            db=db,
            character=character,
            character_item_id=body.character_item_id,
            action=body.action,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return InventoryResponse(**result)


@router.post("/{character_id}/use-item", status_code=200, response_model=UseItemResponse)
def use_item(
    body: UseItemRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> UseItemResponse:
    """Use a consumable item from the character's inventory.

    Blocked during combat phase (400 WRONG_PHASE).  The item must have
    ``consumable: true`` in its game_object properties (400 ITEM_NOT_CONSUMABLE).

    Applies the item's effect (e.g. Healing Potion restores endurance), removes
    the item, and recalculates ``endurance_max``.  Logs an ``item_consumed`` event.

    Args:
        body: ``character_item_id`` and ``version``.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        Effect details, updated endurance values, inventory, and version.

    Raises:
        HTTPException 400: If in combat (WRONG_PHASE) or item not consumable
            (ITEM_NOT_CONSUMABLE).
        HTTPException 404: If the character_item_id is not found.
        HTTPException 409: If the version does not match (VERSION_MISMATCH).
    """
    verify_version(character, body.version)

    try:
        result = process_use_item(
            db=db,
            character=character,
            character_item_id=body.character_item_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("WRONG_PHASE"):
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "WRONG_PHASE"},
            )
        if msg.startswith("ITEM_NOT_CONSUMABLE"):
            return JSONResponse(
                status_code=400,
                content={"detail": msg, "error_code": "ITEM_NOT_CONSUMABLE"},
            )
        raise HTTPException(status_code=400, detail=msg) from exc

    return UseItemResponse(**result)


@router.post(
    "/{character_id}/roll",
    status_code=200,
)
def roll(
    body: RollRequest,
    character: Character = Depends(get_owned_character),
    db: Session = Depends(get_db),
) -> RollPhaseEffectResponse | RollSceneTransitionResponse:
    """Resolve a random roll for the character.

    Dispatches to one of three handlers based on character state:

    - **Choice-triggered random**: ``pending_choice_id`` is set — resolves the
      outcome bands for the pending choice and transitions to the target scene.
    - **Phase-based random**: ``scene_phase='random'`` and the scene has
      ``random_outcomes`` — applies an in-scene effect (gold, END, item, redirect).
      For multi-roll scenes the player calls ``/roll`` again when
      ``rolls_remaining > 0``.  A ``scene_redirect`` outcome completes the heal
      phase first then transitions.
    - **Scene-level random exit**: ``scene_phase='random'`` and all choices have
      ``condition_type='random'`` — matches the roll against choice ranges and
      transitions.

    Args:
        body: Request body with the required version field.
        character: The authenticated user's character, resolved by dependency.
        db: Database session.

    Returns:
        ``RollPhaseEffectResponse`` for in-scene effects, or
        ``RollSceneTransitionResponse`` for scene transitions.

    Raises:
        HTTPException 409: VERSION_MISMATCH, NOT_IN_RANDOM_PHASE,
            REDIRECT_DEPTH_EXCEEDED.
    """
    import random as _random

    # Version check
    verify_version(character, body.version)

    # Server-generated random number
    random_number = _random.randint(0, 9)

    try:
        result = process_roll(db=db, character=character, random_number=random_number)
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("NOT_IN_RANDOM_PHASE"):
            return JSONResponse(
                status_code=409,
                content={"detail": msg, "error_code": "NOT_IN_RANDOM_PHASE"},
            )
        if msg.startswith("REDIRECT_DEPTH_EXCEEDED"):
            return JSONResponse(
                status_code=409,
                content={"detail": msg, "error_code": "REDIRECT_DEPTH_EXCEEDED"},
            )
        raise HTTPException(status_code=400, detail=msg) from exc

    random_type = result.get("random_type")
    if random_type == "phase_effect":
        return RollPhaseEffectResponse(**result)
    return RollSceneTransitionResponse(**result)
