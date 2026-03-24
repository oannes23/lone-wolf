"""Item service — scene item pickup/decline, inventory management, and consumable use."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.engine.inventory import can_pickup, drop_item, equip_weapon, unequip_weapon, use_consumable
from app.engine.types import SceneItemData
from app.events import log_character_event
from app.models.content import SceneItem
from app.models.player import Character, CharacterItem
from app.models.taxonomy import GameObject
from app.services.state_builder import build_character_state, recalculate_endurance_max
from app.services.transition_service import (
    count_pending_items,
    increment_version,
)


def _load_game_object_properties(db: Session, game_object_id: int | None) -> dict:
    """Return the parsed properties dict for a game object, or empty dict.

    Args:
        db: Active database session.
        game_object_id: Primary key of the game object, or None.

    Returns:
        Parsed properties dict, or empty dict if not found.
    """
    if game_object_id is None:
        return {}
    obj = db.query(GameObject).filter(GameObject.id == game_object_id).first()
    if obj is None:
        return {}
    try:
        return json.loads(obj.properties)
    except (json.JSONDecodeError, TypeError):
        return {}


def _inventory_out(character_id: int, db: Session) -> list[dict]:
    """Return the current inventory as a list of dicts for API responses.

    Queries the DB directly to avoid stale relationship cache on the character
    ORM object.

    Args:
        character_id: Primary key of the character.
        db: Database session.

    Returns:
        List of inventory item dicts matching ``InventoryItemOut``.
    """
    items = (
        db.query(CharacterItem)
        .filter(CharacterItem.character_id == character_id)
        .all()
    )
    return [
        {
            "character_item_id": ci.id,
            "item_name": ci.item_name,
            "item_type": ci.item_type,
            "is_equipped": ci.is_equipped,
            "game_object_id": ci.game_object_id,
        }
        for ci in items
    ]


def _advance_phase_if_complete(character: Character, pending_remaining: int) -> None:
    """Advance from 'items' phase when all pending items are resolved.

    If there are no more pending items and the character is in the 'items'
    phase, advance the phase to 'choices'.  The caller must handle further
    phase progression if needed.

    Args:
        character: The ORM character instance (mutated in place).
        pending_remaining: Number of pending items still to resolve.
    """
    if pending_remaining == 0 and character.scene_phase == "items":
        # Advance to choices phase — the simplest next phase
        character.scene_phase = "choices"
        character.scene_phase_index = 0


def process_item_action(
    db: Session,
    character: Character,
    scene_item_id: int,
    action: str,
) -> dict:
    """Accept or decline a pending scene item.

    Accept flow:
    - Validates slot capacity (400 INVENTORY_FULL unless mandatory).
    - Creates a new ``CharacterItem`` row.
    - Recalculates ``endurance_max``.
    - Logs an ``item_pickup`` event.

    Decline flow:
    - Rejects mandatory items (400 ITEM_MANDATORY).
    - Logs an ``item_decline`` event.

    After processing, if all items are resolved and the character is in the
    'items' phase, the phase is advanced.

    Args:
        db: Database session (caller owns the transaction).
        character: The ORM character instance (mutated in place).
        scene_item_id: Primary key of the ``scene_items`` row to process.
        action: One of ``"accept"`` or ``"decline"``.

    Returns:
        A dict matching the ``ItemActionResponse`` schema.

    Raises:
        LookupError: If the scene_item_id is not found.
        ValueError: For business-rule violations (inventory full, mandatory decline).
    """
    # Load the scene item
    scene_item = db.query(SceneItem).filter(SceneItem.id == scene_item_id).first()
    if scene_item is None:
        raise LookupError(f"scene_item {scene_item_id} not found")

    # Validate the scene item belongs to the character's current scene
    if scene_item.scene_id != character.current_scene_id:
        raise ValueError("scene_item does not belong to the character's current scene")

    # Expire the items relationship to ensure fresh data (avoids stale ORM cache
    # when a previous request in the same session deleted items)
    db.expire(character, ["items"])

    # Build character state DTO
    state = build_character_state(db, character)

    new_character_item_id: int | None = None

    if action == "accept":
        # Construct scene item DTO
        props = _load_game_object_properties(db, scene_item.game_object_id)
        scene_item_data = SceneItemData(
            scene_item_id=scene_item.id,
            item_name=scene_item.item_name,
            item_type=scene_item.item_type,
            quantity=scene_item.quantity,
            action=scene_item.action,
            is_mandatory=scene_item.is_mandatory,
            game_object_id=scene_item.game_object_id,
            properties=props,
        )

        # Check capacity
        if not can_pickup(state, scene_item.item_type, scene_item.is_mandatory):
            raise ValueError(
                f"INVENTORY_FULL: cannot carry more "
                f"{'weapons' if scene_item.item_type == 'weapon' else 'backpack items'}"
            )

        # Create the CharacterItem row
        new_item = CharacterItem(
            character_id=character.id,
            game_object_id=scene_item.game_object_id,
            item_name=scene_item.item_name,
            item_type=scene_item.item_type,
            is_equipped=False,
        )
        db.add(new_item)
        db.flush()
        new_character_item_id = new_item.id

        # Recalculate endurance_max — build a fresh item list after adding the new row
        recalculate_endurance_max(db, character)

        # Log event
        log_character_event(
            db,
            character,
            "item_pickup",
            character.current_scene_id,
            phase=character.scene_phase,
            details={
                "scene_item_id": scene_item.id,
                "item_name": scene_item.item_name,
                "item_type": scene_item.item_type,
                "is_mandatory": scene_item.is_mandatory,
            },
        )

    elif action == "decline":
        if scene_item.is_mandatory:
            raise ValueError("ITEM_MANDATORY: cannot decline a mandatory item")

        # Log event
        log_character_event(
            db,
            character,
            "item_decline",
            character.current_scene_id,
            phase=character.scene_phase,
            details={
                "scene_item_id": scene_item.id,
                "item_name": scene_item.item_name,
                "item_type": scene_item.item_type,
            },
        )
    else:
        raise ValueError(f"Unknown action: {action}")

    # Count pending items after this action
    pending_remaining = count_pending_items(character, db)

    # Advance phase if complete
    phase_complete = pending_remaining == 0
    _advance_phase_if_complete(character, pending_remaining)

    # Increment version and flush all pending changes
    increment_version(character, db)
    db.flush()

    inventory = _inventory_out(character.id, db)

    result: dict = {
        "action": action,
        "pending_items_remaining": pending_remaining,
        "phase_complete": phase_complete,
        "inventory": inventory,
        "version": character.version,
    }

    if action == "accept":
        result["item_name"] = scene_item.item_name
        result["item_type"] = scene_item.item_type
        result["character_item_id"] = new_character_item_id

    return result


def process_inventory_action(
    db: Session,
    character: Character,
    character_item_id: int,
    action: str,
) -> dict:
    """Manage the character's inventory: drop, equip, or unequip an item.

    Drop:
    - Removes the item from ``character_items``.
    - Recalculates ``endurance_max`` and clamps ``endurance_current``.
    - Logs an ``item_loss`` event.

    Equip:
    - Sets ``is_equipped = True`` on the weapon.
    - Validates the item is a weapon.

    Unequip:
    - Sets ``is_equipped = False`` on the weapon.

    All operations are available in any scene phase including 'items'.

    Args:
        db: Database session (caller owns the transaction).
        character: The ORM character instance (mutated in place).
        character_item_id: Primary key of the ``character_items`` row.
        action: One of ``"drop"``, ``"equip"``, or ``"unequip"``.

    Returns:
        A dict matching the ``InventoryResponse`` schema.

    Raises:
        LookupError: If character_item_id is not found.
        ValueError: For business-rule violations (not a weapon, special item drop, etc.).
    """
    # Verify the item belongs to this character
    ci = (
        db.query(CharacterItem)
        .filter(
            CharacterItem.id == character_item_id,
            CharacterItem.character_id == character.id,
        )
        .first()
    )
    if ci is None:
        raise LookupError(f"character_item {character_item_id} not found")

    # Expire the items relationship to ensure fresh data (avoids stale ORM cache)
    db.expire(character, ["items"])

    state = build_character_state(db, character)

    if action == "drop":
        result = drop_item(state, character_item_id)
        if not result.success:
            raise ValueError(result.events[0]["reason"] if result.events else "drop failed")

        # Persist: delete the item row
        db.delete(ci)
        db.flush()

        # Recalculate endurance using a fresh direct query (avoids stale relationship cache)
        recalculate_endurance_max(db, character)

        # Log event
        log_character_event(
            db,
            character,
            "item_loss",
            character.current_scene_id,
            phase=character.scene_phase,
            details={
                "item_name": ci.item_name,
                "item_type": ci.item_type,
                "reason": "player_dropped",
            },
        )

    elif action == "equip":
        result = equip_weapon(state, character_item_id)
        if not result.success:
            raise ValueError(result.reason or "equip failed")

        # Persist: set is_equipped = True on the target
        ci.is_equipped = True
        db.flush()

    elif action == "unequip":
        result = unequip_weapon(state, character_item_id)
        if not result.success:
            raise ValueError(result.reason or "unequip failed")

        # Persist: set is_equipped = False
        ci.is_equipped = False
        db.flush()

    else:
        raise ValueError(f"Unknown action: {action}")

    # Increment version and flush all pending changes
    increment_version(character, db)
    db.flush()

    inventory = _inventory_out(character.id, db)

    return {
        "action": action,
        "inventory": inventory,
        "version": character.version,
    }


def process_use_item(
    db: Session,
    character: Character,
    character_item_id: int,
) -> dict:
    """Use a consumable item from the character's inventory.

    Blocked during combat phase. Applies the item's effect (e.g.
    ``endurance_restore``), removes the item, recalculates ``endurance_max``,
    and logs an ``item_consumed`` event.

    Args:
        db: Database session (caller owns the transaction).
        character: The ORM character instance (mutated in place).
        character_item_id: Primary key of the ``character_items`` row.

    Returns:
        A dict matching the ``UseItemResponse`` schema.

    Raises:
        ValueError: If in combat phase, item not found, or item not consumable.
    """
    # Block during combat
    if character.scene_phase == "combat":
        raise ValueError("WRONG_PHASE: cannot use items during combat")

    # Verify the item belongs to this character
    ci = (
        db.query(CharacterItem)
        .filter(
            CharacterItem.id == character_item_id,
            CharacterItem.character_id == character.id,
        )
        .first()
    )
    if ci is None:
        raise LookupError(f"character_item {character_item_id} not found")

    # Expire the items relationship to ensure fresh data (avoids stale ORM cache)
    db.expire(character, ["items"])

    # Check consumable in properties
    props = _load_game_object_properties(db, ci.game_object_id)
    if not props.get("consumable", False):
        raise ValueError("ITEM_NOT_CONSUMABLE: this item cannot be used")

    # Build state and apply via engine
    state = build_character_state(db, character)

    consume_result = use_consumable(state, character_item_id)
    if not consume_result.success:
        raise ValueError(consume_result.reason or "use_consumable failed")

    # Persist state mutations from engine (endurance_current was updated by engine)
    character.endurance_current = state.endurance_current

    # Remove the item from character_items
    db.delete(ci)
    db.flush()

    # Recalculate endurance_max with item removed (use direct query, not relationship)
    recalculate_endurance_max(db, character)

    # Log event
    log_character_event(
        db,
        character,
        "item_consumed",
        character.current_scene_id,
        phase=character.scene_phase,
        details={
            "item_name": ci.item_name,
            "effect_applied": consume_result.effect_applied,
        },
    )

    # Increment version and flush all pending changes
    increment_version(character, db)
    db.flush()

    inventory = _inventory_out(character.id, db)

    return {
        "effect_applied": consume_result.effect_applied,
        "endurance_current": character.endurance_current,
        "endurance_max": character.endurance_max,
        "inventory": inventory,
        "version": character.version,
    }
