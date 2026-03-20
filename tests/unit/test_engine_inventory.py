"""Tests for app/engine/inventory.py — inventory management engine module.

Covers all acceptance criteria from Story 3.5:
- can_pickup: weapon at limit (2 weapons) → False
- can_pickup: backpack at limit (8 items) → False
- can_pickup: mandatory overrides limit → True
- can_pickup: special always True
- pickup_item: success
- pickup_item: failure when at capacity
- drop_item: success
- drop_item: can't drop special items
- equip/unequip weapon toggle
- use_consumable: Healing Potion restores 4 END
- use_consumable: removes item after use
- use_consumable: non-consumable item fails
- endurance_max recalculation on item gain (Chainmail +4)
- endurance_max recalculation on item loss (endurance clamped down)
- is_over_capacity: True when over
"""

from __future__ import annotations

from app.engine.inventory import (
    ConsumeResult,
    DropResult,
    EquipResult,
    PickupResult,
    UnequipResult,
    can_pickup,
    drop_item,
    equip_weapon,
    is_over_capacity,
    pickup_item,
    recompute_endurance_max,
    unequip_weapon,
    use_consumable,
)
from app.engine.types import CharacterState, ItemState, SceneItemData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    character_item_id: int = 1,
    item_name: str = "Sword",
    item_type: str = "weapon",
    is_equipped: bool = False,
    game_object_id: int | None = None,
    properties: dict | None = None,
) -> ItemState:
    return ItemState(
        character_item_id=character_item_id,
        item_name=item_name,
        item_type=item_type,
        is_equipped=is_equipped,
        game_object_id=game_object_id,
        properties=properties or {},
    )


def _make_character(
    endurance_base: int = 25,
    endurance_max: int = 25,
    endurance_current: int = 25,
    items: list[ItemState] | None = None,
) -> CharacterState:
    return CharacterState(
        character_id=1,
        combat_skill_base=15,
        endurance_base=endurance_base,
        endurance_max=endurance_max,
        endurance_current=endurance_current,
        gold=10,
        meals=3,
        is_alive=True,
        disciplines=[],
        weapon_skill_category=None,
        items=items if items is not None else [],
        version=1,
        current_run=1,
        death_count=0,
        rule_overrides=None,
    )


def _make_scene_item(
    scene_item_id: int = 99,
    item_name: str = "Short Sword",
    item_type: str = "weapon",
    quantity: int = 1,
    action: str = "gain",
    is_mandatory: bool = False,
    game_object_id: int | None = None,
    properties: dict | None = None,
) -> SceneItemData:
    return SceneItemData(
        scene_item_id=scene_item_id,
        item_name=item_name,
        item_type=item_type,
        quantity=quantity,
        action=action,
        is_mandatory=is_mandatory,
        game_object_id=game_object_id,
        properties=properties or {},
    )


def _two_weapons() -> list[ItemState]:
    return [
        _make_item(character_item_id=1, item_name="Sword", item_type="weapon"),
        _make_item(character_item_id=2, item_name="Dagger", item_type="weapon"),
    ]


def _eight_backpack_items() -> list[ItemState]:
    return [
        _make_item(character_item_id=i, item_name=f"Item{i}", item_type="backpack")
        for i in range(1, 9)
    ]


# ---------------------------------------------------------------------------
# can_pickup
# ---------------------------------------------------------------------------


class TestCanPickup:
    def test_weapon_under_limit_is_allowed(self) -> None:
        state = _make_character(items=[_make_item(item_type="weapon")])
        assert can_pickup(state, "weapon") is True

    def test_weapon_at_limit_is_denied(self) -> None:
        """Two weapons carried → cannot pick up a third."""
        state = _make_character(items=_two_weapons())
        assert can_pickup(state, "weapon") is False

    def test_backpack_under_limit_is_allowed(self) -> None:
        items = [_make_item(character_item_id=i, item_type="backpack") for i in range(1, 5)]
        state = _make_character(items=items)
        assert can_pickup(state, "backpack") is True

    def test_backpack_at_limit_is_denied(self) -> None:
        """Eight backpack items carried → cannot pick up a ninth."""
        state = _make_character(items=_eight_backpack_items())
        assert can_pickup(state, "backpack") is False

    def test_mandatory_overrides_weapon_limit(self) -> None:
        """Mandatory items bypass slot checks regardless of current count."""
        state = _make_character(items=_two_weapons())
        assert can_pickup(state, "weapon", is_mandatory=True) is True

    def test_mandatory_overrides_backpack_limit(self) -> None:
        state = _make_character(items=_eight_backpack_items())
        assert can_pickup(state, "backpack", is_mandatory=True) is True

    def test_special_always_allowed(self) -> None:
        """Special items have no slot limit."""
        # load up with many special items
        specials = [
            _make_item(character_item_id=i, item_name=f"Special{i}", item_type="special")
            for i in range(1, 20)
        ]
        state = _make_character(items=specials)
        assert can_pickup(state, "special") is True

    def test_special_mandatory_also_allowed(self) -> None:
        state = _make_character()
        assert can_pickup(state, "special", is_mandatory=True) is True

    def test_empty_inventory_allows_weapon(self) -> None:
        state = _make_character()
        assert can_pickup(state, "weapon") is True

    def test_empty_inventory_allows_backpack(self) -> None:
        state = _make_character()
        assert can_pickup(state, "backpack") is True


# ---------------------------------------------------------------------------
# pickup_item
# ---------------------------------------------------------------------------


class TestPickupItem:
    def test_pickup_weapon_success(self) -> None:
        state = _make_character()
        scene_item = _make_scene_item(item_name="Broadsword", item_type="weapon")
        result = pickup_item(state, scene_item)

        assert isinstance(result, PickupResult)
        assert result.success is True
        assert result.reason is None
        assert result.item is not None
        assert result.item.item_name == "Broadsword"
        assert result.item.item_type == "weapon"
        assert result.item.is_equipped is False

    def test_pickup_emits_item_gained_event(self) -> None:
        state = _make_character()
        scene_item = _make_scene_item(item_name="Rope", item_type="backpack")
        result = pickup_item(state, scene_item)

        assert any(e["type"] == "item_gained" for e in result.events)

    def test_pickup_failure_weapon_at_capacity(self) -> None:
        state = _make_character(items=_two_weapons())
        scene_item = _make_scene_item(item_type="weapon")
        result = pickup_item(state, scene_item)

        assert result.success is False
        assert result.item is None
        assert result.reason is not None

    def test_pickup_failure_backpack_at_capacity(self) -> None:
        state = _make_character(items=_eight_backpack_items())
        scene_item = _make_scene_item(item_name="Potion", item_type="backpack")
        result = pickup_item(state, scene_item)

        assert result.success is False
        assert result.item is None

    def test_mandatory_pickup_succeeds_when_at_weapon_limit(self) -> None:
        state = _make_character(items=_two_weapons())
        scene_item = _make_scene_item(item_type="weapon", is_mandatory=True)
        result = pickup_item(state, scene_item)

        assert result.success is True
        assert result.item is not None

    def test_pickup_copies_properties(self) -> None:
        """Properties dict is deep-copied so mutations don't affect the original."""
        props = {"endurance_bonus": 4}
        state = _make_character()
        scene_item = _make_scene_item(
            item_name="Chainmail Waistcoat", item_type="backpack", properties=props
        )
        result = pickup_item(state, scene_item)

        assert result.item is not None
        assert result.item.properties == {"endurance_bonus": 4}
        # Mutating the returned copy doesn't change original
        result.item.properties["endurance_bonus"] = 99
        assert props["endurance_bonus"] == 4


# ---------------------------------------------------------------------------
# drop_item
# ---------------------------------------------------------------------------


class TestDropItem:
    def test_drop_weapon_success(self) -> None:
        sword = _make_item(character_item_id=10, item_name="Sword", item_type="weapon")
        state = _make_character(items=[sword])
        result = drop_item(state, 10)

        assert isinstance(result, DropResult)
        assert result.success is True
        assert result.dropped_item is not None
        assert result.dropped_item.item_name == "Sword"
        assert sword not in state.items

    def test_drop_removes_item_from_state(self) -> None:
        sword = _make_item(character_item_id=5, item_type="weapon")
        state = _make_character(items=[sword])
        drop_item(state, 5)
        assert len(state.items) == 0

    def test_drop_emits_item_lost_event(self) -> None:
        sword = _make_item(character_item_id=3, item_type="weapon")
        state = _make_character(items=[sword])
        result = drop_item(state, 3)

        assert any(e["type"] == "item_lost" for e in result.events)

    def test_drop_nonexistent_item_fails(self) -> None:
        state = _make_character()
        result = drop_item(state, 999)

        assert result.success is False
        assert result.dropped_item is None

    def test_cannot_drop_special_item(self) -> None:
        """Special items are permanently held and cannot be discarded."""
        crystal = _make_item(
            character_item_id=7, item_name="Crystal Star", item_type="special"
        )
        state = _make_character(items=[crystal])
        result = drop_item(state, 7)

        assert result.success is False
        assert result.dropped_item is None
        assert crystal in state.items  # item still in inventory

    def test_drop_item_with_endurance_bonus_updates_max(self) -> None:
        """Dropping an item with endurance_bonus reduces endurance_max."""
        chainmail = _make_item(
            character_item_id=1,
            item_name="Chainmail Waistcoat",
            item_type="backpack",
            properties={"endurance_bonus": 4},
        )
        state = _make_character(endurance_base=25, endurance_max=29, items=[chainmail])
        result = drop_item(state, 1)

        assert result.success is True
        assert result.endurance_max_changed is True
        assert result.new_endurance_max == 25  # 29 - 4

    def test_drop_item_without_endurance_bonus_no_max_change(self) -> None:
        sword = _make_item(character_item_id=2, item_type="weapon", properties={})
        state = _make_character(endurance_base=25, endurance_max=25, items=[sword])
        result = drop_item(state, 2)

        assert result.success is True
        assert result.endurance_max_changed is False
        assert result.new_endurance_max is None


# ---------------------------------------------------------------------------
# equip_weapon / unequip_weapon
# ---------------------------------------------------------------------------


class TestEquipUnequipWeapon:
    def test_equip_weapon_success(self) -> None:
        sword = _make_item(character_item_id=1, item_type="weapon", is_equipped=False)
        state = _make_character(items=[sword])
        result = equip_weapon(state, 1)

        assert isinstance(result, EquipResult)
        assert result.success is True
        assert result.reason is None
        assert sword.is_equipped is True

    def test_equip_emits_event(self) -> None:
        sword = _make_item(character_item_id=1, item_type="weapon", is_equipped=False)
        state = _make_character(items=[sword])
        result = equip_weapon(state, 1)

        assert any(e["type"] == "weapon_equipped" for e in result.events)

    def test_equip_nonexistent_item_fails(self) -> None:
        state = _make_character()
        result = equip_weapon(state, 999)

        assert result.success is False
        assert result.reason == "item_not_found"

    def test_equip_non_weapon_fails(self) -> None:
        rope = _make_item(character_item_id=1, item_name="Rope", item_type="backpack")
        state = _make_character(items=[rope])
        result = equip_weapon(state, 1)

        assert result.success is False
        assert result.reason is not None
        assert rope.is_equipped is False

    def test_unequip_weapon_success(self) -> None:
        sword = _make_item(character_item_id=1, item_type="weapon", is_equipped=True)
        state = _make_character(items=[sword])
        result = unequip_weapon(state, 1)

        assert isinstance(result, UnequipResult)
        assert result.success is True
        assert result.reason is None
        assert sword.is_equipped is False

    def test_unequip_emits_event(self) -> None:
        sword = _make_item(character_item_id=1, item_type="weapon", is_equipped=True)
        state = _make_character(items=[sword])
        result = unequip_weapon(state, 1)

        assert any(e["type"] == "weapon_unequipped" for e in result.events)

    def test_unequip_nonexistent_item_fails(self) -> None:
        state = _make_character()
        result = unequip_weapon(state, 999)

        assert result.success is False

    def test_unequip_non_weapon_fails(self) -> None:
        rope = _make_item(character_item_id=1, item_name="Rope", item_type="backpack")
        state = _make_character(items=[rope])
        result = unequip_weapon(state, 1)

        assert result.success is False

    def test_unequip_already_unequipped_fails(self) -> None:
        sword = _make_item(character_item_id=1, item_type="weapon", is_equipped=False)
        state = _make_character(items=[sword])
        result = unequip_weapon(state, 1)

        assert result.success is False
        assert result.reason is not None

    def test_equip_then_unequip_toggle(self) -> None:
        """Round-trip: equip then unequip leaves item unequipped."""
        sword = _make_item(character_item_id=1, item_type="weapon", is_equipped=False)
        state = _make_character(items=[sword])

        equip_result = equip_weapon(state, 1)
        assert equip_result.success is True
        assert sword.is_equipped is True

        unequip_result = unequip_weapon(state, 1)
        assert unequip_result.success is True
        assert sword.is_equipped is False


# ---------------------------------------------------------------------------
# use_consumable
# ---------------------------------------------------------------------------


class TestUseConsumable:
    def test_healing_potion_restores_endurance(self) -> None:
        """Healing Potion with endurance_restore=4 adds 4 to current endurance."""
        potion = _make_item(
            character_item_id=20,
            item_name="Healing Potion",
            item_type="backpack",
            properties={"consumable": True, "endurance_restore": 4},
        )
        state = _make_character(
            endurance_base=25, endurance_max=25, endurance_current=18, items=[potion]
        )
        result = use_consumable(state, 20)

        assert isinstance(result, ConsumeResult)
        assert result.success is True
        assert result.effect_applied == {"endurance_restore": 4}
        assert state.endurance_current == 22  # 18 + 4

    def test_use_consumable_removes_item(self) -> None:
        """Item is removed from inventory after use."""
        potion = _make_item(
            character_item_id=21,
            item_name="Healing Potion",
            item_type="backpack",
            properties={"consumable": True, "endurance_restore": 4},
        )
        state = _make_character(endurance_current=20, items=[potion])
        use_consumable(state, 21)

        assert potion not in state.items

    def test_use_consumable_emits_item_consumed_event(self) -> None:
        potion = _make_item(
            character_item_id=22,
            item_name="Healing Potion",
            item_type="backpack",
            properties={"consumable": True, "endurance_restore": 4},
        )
        state = _make_character(endurance_current=20, items=[potion])
        result = use_consumable(state, 22)

        assert any(e["type"] == "item_consumed" for e in result.events)

    def test_healing_capped_at_endurance_max(self) -> None:
        """Healing cannot exceed endurance_max."""
        potion = _make_item(
            character_item_id=23,
            item_name="Healing Potion",
            item_type="backpack",
            properties={"consumable": True, "endurance_restore": 10},
        )
        state = _make_character(
            endurance_base=25, endurance_max=25, endurance_current=22, items=[potion]
        )
        use_consumable(state, 23)

        assert state.endurance_current == 25  # capped at max

    def test_non_consumable_item_fails(self) -> None:
        """Items without consumable=True cannot be 'used'."""
        rope = _make_item(
            character_item_id=30,
            item_name="Rope",
            item_type="backpack",
            properties={},
        )
        state = _make_character(items=[rope])
        result = use_consumable(state, 30)

        assert result.success is False
        assert result.reason is not None
        assert rope in state.items  # item unchanged

    def test_use_nonexistent_item_fails(self) -> None:
        state = _make_character()
        result = use_consumable(state, 999)

        assert result.success is False
        assert result.reason is not None

    def test_use_consumable_no_endurance_restore(self) -> None:
        """A consumable with no endurance_restore still succeeds but applies no heal."""
        item = _make_item(
            character_item_id=40,
            item_name="Strange Herb",
            item_type="backpack",
            properties={"consumable": True},  # no endurance_restore key
        )
        state = _make_character(endurance_current=20, items=[item])
        result = use_consumable(state, 40)

        assert result.success is True
        assert state.endurance_current == 20  # unchanged
        assert item not in state.items


# ---------------------------------------------------------------------------
# recompute_endurance_max
# ---------------------------------------------------------------------------


class TestRecomputeEnduranceMax:
    def test_gain_chainmail_increases_max(self) -> None:
        """Adding Chainmail Waistcoat (+4) raises endurance_max by 4."""
        chainmail = _make_item(
            character_item_id=1,
            item_name="Chainmail Waistcoat",
            item_type="backpack",
            properties={"endurance_bonus": 4},
        )
        state = _make_character(endurance_base=25, endurance_max=25, items=[chainmail])
        new_max = recompute_endurance_max(state)

        assert new_max == 29

    def test_no_items_returns_base(self) -> None:
        state = _make_character(endurance_base=25, endurance_max=25)
        assert recompute_endurance_max(state) == 25

    def test_endurance_should_be_clamped_when_max_drops(self) -> None:
        """Demonstrates the clamp requirement: after dropping Chainmail, if
        endurance_current was 28 (above the new max of 25), the caller must
        clamp it. recompute_endurance_max returns the new max for that purpose."""
        chainmail = _make_item(
            character_item_id=1,
            item_name="Chainmail Waistcoat",
            item_type="backpack",
            properties={"endurance_bonus": 4},
        )
        state = _make_character(
            endurance_base=25,
            endurance_max=29,
            endurance_current=28,  # above base max
            items=[chainmail],
        )

        # Simulate drop: remove item, recompute
        state.items.remove(chainmail)
        new_max = recompute_endurance_max(state)

        assert new_max == 25
        # The caller is responsible for clamping: state.endurance_current > new_max
        assert state.endurance_current > new_max  # proves clamp is needed


# ---------------------------------------------------------------------------
# is_over_capacity
# ---------------------------------------------------------------------------


class TestIsOverCapacity:
    def test_not_over_capacity_empty(self) -> None:
        state = _make_character()
        assert is_over_capacity(state) is False

    def test_not_over_capacity_at_limits(self) -> None:
        items = _two_weapons() + _eight_backpack_items()
        state = _make_character(items=items)
        assert is_over_capacity(state) is False

    def test_over_capacity_too_many_weapons(self) -> None:
        items = [
            _make_item(character_item_id=i, item_type="weapon") for i in range(1, 4)
        ]
        state = _make_character(items=items)
        assert is_over_capacity(state) is True

    def test_over_capacity_too_many_backpack_items(self) -> None:
        items = [
            _make_item(character_item_id=i, item_type="backpack") for i in range(1, 10)
        ]
        state = _make_character(items=items)
        assert is_over_capacity(state) is True

    def test_not_over_capacity_many_special_items(self) -> None:
        """Special items don't count toward any limit."""
        specials = [
            _make_item(character_item_id=i, item_type="special") for i in range(1, 20)
        ]
        state = _make_character(items=specials)
        assert is_over_capacity(state) is False
