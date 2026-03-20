"""Tests for app/engine/meters.py — bounded resource meter arithmetic.

Covers all acceptance criteria from Story 3.1:
- Death at endurance 0
- Gold overflow at 50
- Gold underflow at 0
- Meal cap at 8
- Healing cap at endurance_max
- endurance_max recalculation with item bonuses
- endurance_max with no bonus items
"""

from __future__ import annotations

import pytest

from app.engine.meters import (
    apply_endurance_delta,
    apply_gold_delta,
    apply_meal_delta,
    compute_endurance_max,
)
from app.engine.types import CharacterState, ItemState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(
    character_item_id: int = 1,
    item_name: str = "Sword",
    item_type: str = "weapon",
    is_equipped: bool = True,
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
    endurance_current: int = 25,
    endurance_max: int = 25,
    endurance_base: int = 25,
    gold: int = 10,
    meals: int = 3,
    items: list[ItemState] | None = None,
) -> CharacterState:
    return CharacterState(
        character_id=1,
        combat_skill_base=15,
        endurance_base=endurance_base,
        endurance_max=endurance_max,
        endurance_current=endurance_current,
        gold=gold,
        meals=meals,
        is_alive=True,
        disciplines=[],
        weapon_skill_category=None,
        items=items or [],
        version=1,
        current_run=1,
        death_count=0,
        rule_overrides=None,
    )


# ---------------------------------------------------------------------------
# apply_endurance_delta
# ---------------------------------------------------------------------------


class TestApplyEnduranceDelta:
    def test_normal_damage(self) -> None:
        state = _make_character(endurance_current=25, endurance_max=25)
        new_end, is_dead, events = apply_endurance_delta(state, -5)
        assert new_end == 20
        assert is_dead is False
        assert any(e["type"] == "endurance_change" for e in events)

    def test_death_exact_zero(self) -> None:
        """Taking exactly enough damage to reach 0 triggers death."""
        state = _make_character(endurance_current=5, endurance_max=25)
        new_end, is_dead, events = apply_endurance_delta(state, -5)
        assert new_end == 0
        assert is_dead is True
        assert any(e["type"] == "character_death" for e in events)

    def test_death_overkill_clamps_to_zero(self) -> None:
        """A delta that would take endurance below 0 clamps to 0 and marks death."""
        state = _make_character(endurance_current=3, endurance_max=25)
        new_end, is_dead, events = apply_endurance_delta(state, -10)
        assert new_end == 0
        assert is_dead is True

    def test_healing_within_max(self) -> None:
        state = _make_character(endurance_current=20, endurance_max=25)
        new_end, is_dead, events = apply_endurance_delta(state, 3)
        assert new_end == 23
        assert is_dead is False

    def test_healing_caps_at_endurance_max(self) -> None:
        """Healing cannot raise endurance above endurance_max."""
        state = _make_character(endurance_current=23, endurance_max=25)
        new_end, is_dead, events = apply_endurance_delta(state, 10)
        assert new_end == 25
        assert is_dead is False
        # The applied delta should reflect the capped amount
        change_event = next(e for e in events if e["type"] == "endurance_change")
        assert change_event["delta_applied"] == 2  # 25 - 23

    def test_healing_already_at_max_no_change(self) -> None:
        state = _make_character(endurance_current=25, endurance_max=25)
        new_end, is_dead, events = apply_endurance_delta(state, 5)
        assert new_end == 25
        change_event = next((e for e in events if e["type"] == "endurance_change"), None)
        # A change event is emitted even when delta_applied == 0
        assert change_event is not None
        assert change_event["delta_applied"] == 0

    def test_zero_delta_emits_no_events(self) -> None:
        """A delta of zero produces no events."""
        state = _make_character(endurance_current=25, endurance_max=25)
        new_end, is_dead, events = apply_endurance_delta(state, 0)
        assert new_end == 25
        assert is_dead is False
        assert events == []

    def test_event_contains_previous_and_new(self) -> None:
        state = _make_character(endurance_current=15, endurance_max=25)
        new_end, _, events = apply_endurance_delta(state, -7)
        change_event = next(e for e in events if e["type"] == "endurance_change")
        assert change_event["previous"] == 15
        assert change_event["new"] == 8


# ---------------------------------------------------------------------------
# apply_gold_delta
# ---------------------------------------------------------------------------


class TestApplyGoldDelta:
    def test_gain_gold_normal(self) -> None:
        state = _make_character(gold=10)
        new_gold, actual_delta = apply_gold_delta(state, 5)
        assert new_gold == 15
        assert actual_delta == 5

    def test_gold_overflow_caps_at_50(self) -> None:
        """Gaining gold beyond 50 caps at 50; actual_delta reflects true gain."""
        state = _make_character(gold=48)
        new_gold, actual_delta = apply_gold_delta(state, 10)
        assert new_gold == 50
        assert actual_delta == 2  # only 2 of the 10 actually applied

    def test_gold_already_at_cap(self) -> None:
        state = _make_character(gold=50)
        new_gold, actual_delta = apply_gold_delta(state, 5)
        assert new_gold == 50
        assert actual_delta == 0

    def test_gold_underflow_clamps_to_zero(self) -> None:
        """Losing more gold than carried clamps to 0."""
        state = _make_character(gold=3)
        new_gold, actual_delta = apply_gold_delta(state, -10)
        assert new_gold == 0
        assert actual_delta == -3  # only 3 lost

    def test_gold_already_at_zero(self) -> None:
        state = _make_character(gold=0)
        new_gold, actual_delta = apply_gold_delta(state, -5)
        assert new_gold == 0
        assert actual_delta == 0

    def test_gold_loss_normal(self) -> None:
        state = _make_character(gold=20)
        new_gold, actual_delta = apply_gold_delta(state, -7)
        assert new_gold == 13
        assert actual_delta == -7


# ---------------------------------------------------------------------------
# apply_meal_delta
# ---------------------------------------------------------------------------


class TestApplyMealDelta:
    def test_gain_meals_normal(self) -> None:
        state = _make_character(meals=3)
        new_meals, actual_delta = apply_meal_delta(state, 2)
        assert new_meals == 5
        assert actual_delta == 2

    def test_meal_cap_at_8(self) -> None:
        """Cannot carry more than 8 meals."""
        state = _make_character(meals=6)
        new_meals, actual_delta = apply_meal_delta(state, 5)
        assert new_meals == 8
        assert actual_delta == 2

    def test_meal_already_at_cap(self) -> None:
        state = _make_character(meals=8)
        new_meals, actual_delta = apply_meal_delta(state, 1)
        assert new_meals == 8
        assert actual_delta == 0

    def test_meal_underflow_clamps_to_zero(self) -> None:
        state = _make_character(meals=1)
        new_meals, actual_delta = apply_meal_delta(state, -5)
        assert new_meals == 0
        assert actual_delta == -1

    def test_meal_already_at_zero(self) -> None:
        state = _make_character(meals=0)
        new_meals, actual_delta = apply_meal_delta(state, -1)
        assert new_meals == 0
        assert actual_delta == 0

    def test_eat_a_meal(self) -> None:
        state = _make_character(meals=4)
        new_meals, actual_delta = apply_meal_delta(state, -1)
        assert new_meals == 3
        assert actual_delta == -1


# ---------------------------------------------------------------------------
# compute_endurance_max
# ---------------------------------------------------------------------------


class TestComputeEnduranceMax:
    def test_no_bonus_items(self) -> None:
        """Base endurance unchanged when no items have endurance_bonus."""
        items = [_make_item(properties={}), _make_item(2, "Rope", "backpack")]
        result = compute_endurance_max(25, [], items)
        assert result == 25

    def test_empty_item_list(self) -> None:
        result = compute_endurance_max(25, [], [])
        assert result == 25

    def test_chainmail_waistcoat_bonus(self) -> None:
        """Chainmail Waistcoat adds +4 to endurance_max."""
        items = [
            _make_item(1, "Chainmail Waistcoat", "backpack", properties={"endurance_bonus": 4}),
        ]
        result = compute_endurance_max(25, [], items)
        assert result == 29

    def test_helmet_bonus(self) -> None:
        """Helmet adds +2 to endurance_max."""
        items = [
            _make_item(1, "Helmet", "backpack", properties={"endurance_bonus": 2}),
        ]
        result = compute_endurance_max(25, [], items)
        assert result == 27

    def test_chainmail_and_helmet_combined(self) -> None:
        """Both Chainmail Waistcoat (+4) and Helmet (+2) stack."""
        items = [
            _make_item(1, "Chainmail Waistcoat", "backpack", properties={"endurance_bonus": 4}),
            _make_item(2, "Helmet", "backpack", properties={"endurance_bonus": 2}),
        ]
        result = compute_endurance_max(25, [], items)
        assert result == 31

    def test_unequipped_item_still_counts(self) -> None:
        """Endurance bonuses apply to ALL carried items, not just equipped ones."""
        items = [
            _make_item(
                1,
                "Chainmail Waistcoat",
                "backpack",
                is_equipped=False,
                properties={"endurance_bonus": 4},
            ),
        ]
        result = compute_endurance_max(25, [], items)
        assert result == 29

    def test_mixed_items_only_bonus_ones_counted(self) -> None:
        """Items without endurance_bonus contribute 0."""
        items = [
            _make_item(1, "Sword", "weapon", properties={}),
            _make_item(2, "Chainmail Waistcoat", "backpack", properties={"endurance_bonus": 4}),
            _make_item(3, "Meal", "backpack", properties={}),
        ]
        result = compute_endurance_max(25, [], items)
        assert result == 29

    def test_zero_endurance_base(self) -> None:
        """Edge case: zero base still accumulates item bonuses correctly."""
        items = [
            _make_item(1, "Chainmail Waistcoat", "backpack", properties={"endurance_bonus": 4}),
        ]
        result = compute_endurance_max(0, [], items)
        assert result == 4

    @pytest.mark.parametrize(
        "base,expected",
        [
            (20, 20),
            (25, 25),
            (32, 32),
        ],
    )
    def test_various_base_values_no_items(self, base: int, expected: int) -> None:
        result = compute_endurance_max(base, [], [])
        assert result == expected
