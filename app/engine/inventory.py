"""Inventory management for the Lone Wolf game engine.

Pure functions that handle item pickup, drop, equip/unequip, and consumption.
No database access, no FastAPI dependencies — only standard library and
app.engine imports.

Slot constraints:
- Weapons: max 2 (item_type="weapon")
- Backpack: max 8 (item_type="backpack")
- Special: unlimited (item_type="special")
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from app.engine.meters import apply_endurance_delta, compute_endurance_max
from app.engine.types import CharacterState, ItemState, SceneItemData

_WEAPON_LIMIT = 2
_BACKPACK_LIMIT = 8


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PickupResult:
    """Result of attempting to pick up an item."""

    success: bool
    item: ItemState | None  # the new item if success
    reason: str | None  # failure reason
    events: list[dict] = field(default_factory=list)


@dataclass
class DropResult:
    """Result of attempting to drop an item."""

    success: bool
    dropped_item: ItemState | None
    endurance_max_changed: bool
    new_endurance_max: int | None
    events: list[dict] = field(default_factory=list)


@dataclass
class EquipResult:
    """Result of attempting to equip a weapon."""

    success: bool
    reason: str | None
    events: list[dict] = field(default_factory=list)


@dataclass
class UnequipResult:
    """Result of attempting to unequip a weapon."""

    success: bool
    reason: str | None
    events: list[dict] = field(default_factory=list)


@dataclass
class ConsumeResult:
    """Result of attempting to use a consumable item."""

    success: bool
    reason: str | None
    effect_applied: dict | None  # e.g. {"endurance_restore": 4}
    events: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Capacity helpers
# ---------------------------------------------------------------------------


def _count_weapons(items: list[ItemState]) -> int:
    """Return the number of weapon-type items in the list."""
    return sum(1 for item in items if item.item_type == "weapon")


def _count_backpack(items: list[ItemState]) -> int:
    """Return the number of backpack-type items in the list."""
    return sum(1 for item in items if item.item_type == "backpack")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def can_pickup(state: CharacterState, item_type: str, is_mandatory: bool = False) -> bool:
    """Return whether the character can pick up another item of the given type.

    Mandatory items override slot limits — they are always accepted.

    Args:
        state: Current character state snapshot.
        item_type: One of "weapon", "backpack", or "special".
        is_mandatory: When True the item bypasses all slot checks.

    Returns:
        True when the pickup is permitted, False when a slot limit would be exceeded.
    """
    if is_mandatory:
        return True
    if item_type == "weapon":
        return _count_weapons(state.items) < _WEAPON_LIMIT
    if item_type == "backpack":
        return _count_backpack(state.items) < _BACKPACK_LIMIT
    # special items have no limit
    return True


def pickup_item(state: CharacterState, item: SceneItemData) -> PickupResult:
    """Attempt to add a scene item to the character's inventory.

    The item is only added if ``can_pickup`` returns True for the item's type
    and mandatory flag. The function does not mutate *state.items* — the
    caller is responsible for persisting the returned ``ItemState`` to the
    character's record.

    Args:
        state: Current character state snapshot.
        item: The scene item being offered to the player.

    Returns:
        A ``PickupResult`` with success/failure information and the new
        ``ItemState`` if the pickup was permitted.
    """
    if not can_pickup(state, item.item_type, item.is_mandatory):
        return PickupResult(
            success=False,
            item=None,
            reason=f"Inventory full: cannot carry more than "
            f"{_WEAPON_LIMIT if item.item_type == 'weapon' else _BACKPACK_LIMIT} "
            f"{item.item_type} items",
            events=[],
        )

    new_item = ItemState(
        character_item_id=item.scene_item_id,  # placeholder; service layer assigns real id
        item_name=item.item_name,
        item_type=item.item_type,
        is_equipped=False,
        game_object_id=item.game_object_id,
        properties=copy.deepcopy(item.properties),
    )

    events: list[dict] = [
        {
            "type": "item_gained",
            "item_name": new_item.item_name,
            "item_type": new_item.item_type,
            "is_mandatory": item.is_mandatory,
        }
    ]

    return PickupResult(success=True, item=new_item, reason=None, events=events)


def drop_item(state: CharacterState, character_item_id: int) -> DropResult:
    """Remove an item from the character's inventory by its ID.

    Special items cannot be dropped. If dropping the item changes the
    ``endurance_max`` (e.g., losing an item with an ``endurance_bonus``),
    the new maximum is reported and the caller should clamp
    ``endurance_current`` accordingly.

    This function mutates *state.items* in place for efficiency. The caller
    must persist the change.

    Args:
        state: Current character state snapshot (items list is mutated).
        character_item_id: The ID of the item to remove.

    Returns:
        A ``DropResult`` with success/failure information and endurance impact.
    """
    target = next((i for i in state.items if i.character_item_id == character_item_id), None)

    if target is None:
        return DropResult(
            success=False,
            dropped_item=None,
            endurance_max_changed=False,
            new_endurance_max=None,
            events=[{"type": "item_drop_failed", "reason": "item_not_found"}],
        )

    if target.item_type == "special":
        return DropResult(
            success=False,
            dropped_item=None,
            endurance_max_changed=False,
            new_endurance_max=None,
            events=[{"type": "item_drop_failed", "reason": "cannot_drop_special_items"}],
        )

    old_max = compute_endurance_max(state.endurance_base, state.disciplines, state.items)
    state.items.remove(target)
    new_max = compute_endurance_max(state.endurance_base, state.disciplines, state.items)

    max_changed = new_max != old_max
    events: list[dict] = [
        {
            "type": "item_lost",
            "item_name": target.item_name,
            "item_type": target.item_type,
        }
    ]
    if max_changed:
        events.append(
            {
                "type": "endurance_max_changed",
                "previous": old_max,
                "new": new_max,
            }
        )

    return DropResult(
        success=True,
        dropped_item=target,
        endurance_max_changed=max_changed,
        new_endurance_max=new_max if max_changed else None,
        events=events,
    )


def equip_weapon(state: CharacterState, character_item_id: int) -> EquipResult:
    """Mark a weapon in the character's inventory as equipped.

    Only items with ``item_type == "weapon"`` may be equipped. The function
    mutates the matching ``ItemState`` in place.

    Args:
        state: Current character state snapshot.
        character_item_id: The ID of the weapon to equip.

    Returns:
        An ``EquipResult`` describing success or the failure reason.
    """
    target = next((i for i in state.items if i.character_item_id == character_item_id), None)

    if target is None:
        return EquipResult(
            success=False,
            reason="item_not_found",
            events=[],
        )

    if target.item_type != "weapon":
        return EquipResult(
            success=False,
            reason=f"Cannot equip '{target.item_name}': not a weapon (type={target.item_type})",
            events=[],
        )

    target.is_equipped = True

    return EquipResult(
        success=True,
        reason=None,
        events=[{"type": "weapon_equipped", "item_name": target.item_name}],
    )


def unequip_weapon(state: CharacterState, character_item_id: int) -> UnequipResult:
    """Mark an equipped weapon as unequipped.

    The item must exist and be a weapon that is currently equipped.

    Args:
        state: Current character state snapshot.
        character_item_id: The ID of the weapon to unequip.

    Returns:
        An ``UnequipResult`` describing success or the failure reason.
    """
    target = next((i for i in state.items if i.character_item_id == character_item_id), None)

    if target is None:
        return UnequipResult(
            success=False,
            reason="item_not_found",
            events=[],
        )

    if target.item_type != "weapon":
        return UnequipResult(
            success=False,
            reason=f"Cannot unequip '{target.item_name}': not a weapon (type={target.item_type})",
            events=[],
        )

    if not target.is_equipped:
        return UnequipResult(
            success=False,
            reason=f"'{target.item_name}' is not currently equipped",
            events=[],
        )

    target.is_equipped = False

    return UnequipResult(
        success=True,
        reason=None,
        events=[{"type": "weapon_unequipped", "item_name": target.item_name}],
    )


def use_consumable(state: CharacterState, character_item_id: int) -> ConsumeResult:
    """Use a consumable item, apply its effect, and remove it from inventory.

    The item's ``properties`` dict must contain ``"consumable": true``.
    Currently supported effects:

    - ``endurance_restore`` (int): Heal the character by this amount (capped
      at ``endurance_max``).

    This function mutates *state* in place: it removes the item from
    ``state.items`` and updates ``state.endurance_current`` when a healing
    effect is applied.

    Args:
        state: Current character state snapshot (mutated in place).
        character_item_id: The ID of the consumable item to use.

    Returns:
        A ``ConsumeResult`` describing the outcome and any effect applied.
    """
    target = next((i for i in state.items if i.character_item_id == character_item_id), None)

    if target is None:
        return ConsumeResult(
            success=False,
            reason="item_not_found",
            effect_applied=None,
            events=[],
        )

    if not target.properties.get("consumable", False):
        return ConsumeResult(
            success=False,
            reason=f"'{target.item_name}' is not a consumable item",
            effect_applied=None,
            events=[],
        )

    events: list[dict] = []
    effect_applied: dict = {}

    # Apply effect based on properties (e.g., {"effect": "endurance_restore", "amount": 4})
    effect = target.properties.get("effect")
    amount = int(target.properties.get("amount", 0))

    # Also support legacy direct key format (e.g., {"endurance_restore": 4})
    if effect is None:
        restore = target.properties.get("endurance_restore", 0)
        if restore:
            effect = "endurance_restore"
            amount = int(restore)

    if effect == "endurance_restore" and amount:
        new_end, _is_dead, end_events = apply_endurance_delta(state, amount)
        state.endurance_current = new_end
        effect_applied["endurance_restore"] = amount
        events.extend(end_events)

    # Remove the consumed item
    state.items.remove(target)
    events.append(
        {
            "type": "item_consumed",
            "item_name": target.item_name,
        }
    )

    return ConsumeResult(
        success=True,
        reason=None,
        effect_applied=effect_applied or None,
        events=events,
    )


def recompute_endurance_max(state: CharacterState) -> int:
    """Recompute and return the character's effective endurance maximum.

    Delegates to ``compute_endurance_max`` using the character's current
    item list.  If the new maximum is lower than ``endurance_current``, the
    caller should clamp ``endurance_current`` to the new maximum.

    Args:
        state: Current character state snapshot.

    Returns:
        The newly computed endurance maximum.
    """
    return compute_endurance_max(state.endurance_base, state.disciplines, state.items)


def is_over_capacity(state: CharacterState) -> bool:
    """Return True if the character is carrying more items than the slot limits allow.

    This can occur after mandatory item grants or story-driven inventory changes.

    Args:
        state: Current character state snapshot.

    Returns:
        True when weapon count > 2 or backpack count > 8.
    """
    return (
        _count_weapons(state.items) > _WEAPON_LIMIT
        or _count_backpack(state.items) > _BACKPACK_LIMIT
    )
