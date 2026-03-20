"""Tests for app/engine/conditions.py — choice condition evaluation.

Covers all acceptance criteria from Story 3.3:
- check_condition: discipline present → True
- check_condition: discipline absent → False
- check_condition: item present → True
- check_condition: item absent → False
- check_condition: gold sufficient → True
- check_condition: gold insufficient → False
- check_condition: random → always True
- check_condition: None/none → always True
- check_condition: compound OR with one match → True
- check_condition: compound OR with no match → False
- filter_choices: unresolved choice (null target, no random) → path_unavailable
- filter_choices: condition-gated unavailable choice
- filter_choices: available choice
- filter_choices: mixed available and unavailable
- compute_gold_deduction: gold condition → returns amount
- compute_gold_deduction: non-gold condition → returns None
"""

from __future__ import annotations

import json

import pytest

from app.engine.conditions import check_condition, compute_gold_deduction, filter_choices
from app.engine.types import CharacterState, ChoiceData, ItemState

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
    disciplines: list[str] | None = None,
    items: list[ItemState] | None = None,
    gold: int = 10,
) -> CharacterState:
    return CharacterState(
        character_id=1,
        combat_skill_base=15,
        endurance_base=25,
        endurance_max=25,
        endurance_current=25,
        gold=gold,
        meals=3,
        is_alive=True,
        disciplines=disciplines or [],
        weapon_skill_category=None,
        items=items or [],
        version=1,
        current_run=1,
        death_count=0,
        rule_overrides=None,
    )


def _make_choice(
    choice_id: int = 1,
    target_scene_id: int | None = 2,
    target_scene_number: int = 2,
    display_text: str = "Go north",
    condition_type: str | None = None,
    condition_value: str | None = None,
    has_random_outcomes: bool = False,
) -> ChoiceData:
    return ChoiceData(
        choice_id=choice_id,
        target_scene_id=target_scene_id,
        target_scene_number=target_scene_number,
        display_text=display_text,
        condition_type=condition_type,
        condition_value=condition_value,
        has_random_outcomes=has_random_outcomes,
    )


# ---------------------------------------------------------------------------
# check_condition — None / "none"
# ---------------------------------------------------------------------------


class TestCheckConditionNone:
    def test_none_type_always_true(self) -> None:
        state = _make_character()
        assert check_condition(state, None, None) is True

    def test_string_none_type_always_true(self) -> None:
        state = _make_character()
        assert check_condition(state, "none", None) is True

    def test_none_type_ignores_value(self) -> None:
        """condition_value is irrelevant when condition_type is None."""
        state = _make_character()
        assert check_condition(state, None, "Tracking") is True


# ---------------------------------------------------------------------------
# check_condition — "discipline"
# ---------------------------------------------------------------------------


class TestCheckConditionDiscipline:
    def test_discipline_present_returns_true(self) -> None:
        state = _make_character(disciplines=["Tracking", "Camouflage"])
        assert check_condition(state, "discipline", "Tracking") is True

    def test_discipline_absent_returns_false(self) -> None:
        state = _make_character(disciplines=["Camouflage"])
        assert check_condition(state, "discipline", "Tracking") is False

    def test_discipline_empty_list_returns_false(self) -> None:
        state = _make_character(disciplines=[])
        assert check_condition(state, "discipline", "Tracking") is False

    def test_discipline_case_sensitive(self) -> None:
        """Discipline matching is case-sensitive."""
        state = _make_character(disciplines=["Tracking"])
        assert check_condition(state, "discipline", "tracking") is False

    def test_discipline_none_value_returns_false(self) -> None:
        state = _make_character(disciplines=["Tracking"])
        assert check_condition(state, "discipline", None) is False


# ---------------------------------------------------------------------------
# check_condition — "discipline" compound OR
# ---------------------------------------------------------------------------


class TestCheckConditionCompoundOr:
    def test_compound_or_one_match_returns_true(self) -> None:
        """Returns True when at least one discipline in the 'any' list is present."""
        state = _make_character(disciplines=["Tracking"])
        value = json.dumps({"any": ["Tracking", "Huntmastery"]})
        assert check_condition(state, "discipline", value) is True

    def test_compound_or_no_match_returns_false(self) -> None:
        """Returns False when none of the disciplines in 'any' are present."""
        state = _make_character(disciplines=["Camouflage"])
        value = json.dumps({"any": ["Tracking", "Huntmastery"]})
        assert check_condition(state, "discipline", value) is False

    def test_compound_or_all_match_returns_true(self) -> None:
        state = _make_character(disciplines=["Tracking", "Huntmastery"])
        value = json.dumps({"any": ["Tracking", "Huntmastery"]})
        assert check_condition(state, "discipline", value) is True

    def test_compound_or_empty_list_returns_false(self) -> None:
        state = _make_character(disciplines=["Tracking"])
        value = json.dumps({"any": []})
        assert check_condition(state, "discipline", value) is False

    def test_compound_or_case_sensitive(self) -> None:
        """Compound OR matching is also case-sensitive."""
        state = _make_character(disciplines=["Tracking"])
        value = json.dumps({"any": ["tracking", "huntmastery"]})
        assert check_condition(state, "discipline", value) is False


# ---------------------------------------------------------------------------
# check_condition — "item"
# ---------------------------------------------------------------------------


class TestCheckConditionItem:
    def test_item_present_returns_true(self) -> None:
        items = [_make_item(item_name="Rope")]
        state = _make_character(items=items)
        assert check_condition(state, "item", "Rope") is True

    def test_item_absent_returns_false(self) -> None:
        items = [_make_item(item_name="Sword")]
        state = _make_character(items=items)
        assert check_condition(state, "item", "Rope") is False

    def test_item_empty_inventory_returns_false(self) -> None:
        state = _make_character(items=[])
        assert check_condition(state, "item", "Rope") is False

    def test_item_case_sensitive(self) -> None:
        items = [_make_item(item_name="Rope")]
        state = _make_character(items=items)
        assert check_condition(state, "item", "rope") is False

    def test_item_none_value_returns_false(self) -> None:
        items = [_make_item(item_name="Rope")]
        state = _make_character(items=items)
        assert check_condition(state, "item", None) is False

    def test_item_unequipped_still_counts(self) -> None:
        """Items don't need to be equipped to satisfy an item condition."""
        items = [_make_item(item_name="Rope", is_equipped=False)]
        state = _make_character(items=items)
        assert check_condition(state, "item", "Rope") is True


# ---------------------------------------------------------------------------
# check_condition — "gold"
# ---------------------------------------------------------------------------


class TestCheckConditionGold:
    def test_gold_sufficient_returns_true(self) -> None:
        state = _make_character(gold=10)
        assert check_condition(state, "gold", "5") is True

    def test_gold_exact_threshold_returns_true(self) -> None:
        state = _make_character(gold=5)
        assert check_condition(state, "gold", "5") is True

    def test_gold_insufficient_returns_false(self) -> None:
        state = _make_character(gold=3)
        assert check_condition(state, "gold", "5") is False

    def test_gold_zero_threshold_always_true(self) -> None:
        state = _make_character(gold=0)
        assert check_condition(state, "gold", "0") is True

    def test_gold_none_value_returns_false(self) -> None:
        state = _make_character(gold=10)
        assert check_condition(state, "gold", None) is False


# ---------------------------------------------------------------------------
# check_condition — "random"
# ---------------------------------------------------------------------------


class TestCheckConditionRandom:
    def test_random_always_true(self) -> None:
        """Random-gated choices are always selectable."""
        state = _make_character()
        assert check_condition(state, "random", None) is True

    def test_random_always_true_with_value(self) -> None:
        state = _make_character()
        assert check_condition(state, "random", "some_value") is True


# ---------------------------------------------------------------------------
# filter_choices
# ---------------------------------------------------------------------------


class TestFilterChoices:
    def test_available_choice_returns_available_true(self) -> None:
        """A choice with no condition and a valid target is available."""
        choices = [_make_choice(condition_type=None)]
        state = _make_character()
        results = filter_choices(choices, state)
        assert len(results) == 1
        assert results[0].available is True
        assert results[0].reason is None

    def test_unresolved_choice_null_target_no_random(self) -> None:
        """A choice with null target_scene_id and no random outcomes is unavailable."""
        choices = [_make_choice(target_scene_id=None, has_random_outcomes=False)]
        state = _make_character()
        results = filter_choices(choices, state)
        assert results[0].available is False
        assert results[0].reason == "path_unavailable"

    def test_null_target_with_random_outcomes_is_evaluated(self) -> None:
        """A choice with no target but has_random_outcomes=True passes to condition check."""
        choices = [
            _make_choice(target_scene_id=None, has_random_outcomes=True, condition_type=None)
        ]
        state = _make_character()
        results = filter_choices(choices, state)
        assert results[0].available is True
        assert results[0].reason is None

    def test_condition_gated_choice_unavailable(self) -> None:
        """A choice whose condition is not met is marked unavailable."""
        choices = [_make_choice(condition_type="discipline", condition_value="Tracking")]
        state = _make_character(disciplines=[])
        results = filter_choices(choices, state)
        assert results[0].available is False
        assert "Tracking" in results[0].reason

    def test_condition_gated_choice_available(self) -> None:
        """A choice whose condition is met is marked available."""
        choices = [_make_choice(condition_type="discipline", condition_value="Tracking")]
        state = _make_character(disciplines=["Tracking"])
        results = filter_choices(choices, state)
        assert results[0].available is True
        assert results[0].reason is None

    def test_mixed_available_and_unavailable(self) -> None:
        """Mixed list preserves order and evaluates each choice independently."""
        choices = [
            _make_choice(choice_id=1, condition_type=None),
            _make_choice(choice_id=2, condition_type="discipline", condition_value="Tracking"),
            _make_choice(choice_id=3, target_scene_id=None, has_random_outcomes=False),
            _make_choice(choice_id=4, condition_type="item", condition_value="Rope"),
        ]
        items = [_make_item(item_name="Rope")]
        state = _make_character(disciplines=[], items=items)
        results = filter_choices(choices, state)

        assert len(results) == 4
        assert results[0].available is True   # no condition
        assert results[1].available is False  # Tracking absent
        assert results[2].available is False  # path_unavailable
        assert results[3].available is True   # has Rope

    def test_preserves_original_choice_reference(self) -> None:
        """The choice field in each result is the original ChoiceData object."""
        choice = _make_choice(choice_id=42)
        results = filter_choices([choice], _make_character())
        assert results[0].choice is choice

    def test_empty_choices_returns_empty(self) -> None:
        results = filter_choices([], _make_character())
        assert results == []

    def test_gold_condition_unavailable_reason(self) -> None:
        choices = [_make_choice(condition_type="gold", condition_value="20")]
        state = _make_character(gold=5)
        results = filter_choices(choices, state)
        assert results[0].available is False
        assert "20" in results[0].reason

    def test_item_condition_unavailable_reason(self) -> None:
        choices = [_make_choice(condition_type="item", condition_value="Rope")]
        state = _make_character(items=[])
        results = filter_choices(choices, state)
        assert results[0].available is False
        assert "Rope" in results[0].reason


# ---------------------------------------------------------------------------
# compute_gold_deduction
# ---------------------------------------------------------------------------


class TestComputeGoldDeduction:
    def test_gold_condition_returns_amount(self) -> None:
        choice = _make_choice(condition_type="gold", condition_value="15")
        assert compute_gold_deduction(choice) == 15

    def test_gold_condition_zero_amount(self) -> None:
        choice = _make_choice(condition_type="gold", condition_value="0")
        assert compute_gold_deduction(choice) == 0

    def test_non_gold_condition_returns_none(self) -> None:
        choice = _make_choice(condition_type="discipline", condition_value="Tracking")
        assert compute_gold_deduction(choice) is None

    def test_no_condition_returns_none(self) -> None:
        choice = _make_choice(condition_type=None, condition_value=None)
        assert compute_gold_deduction(choice) is None

    def test_item_condition_returns_none(self) -> None:
        choice = _make_choice(condition_type="item", condition_value="Rope")
        assert compute_gold_deduction(choice) is None

    def test_random_condition_returns_none(self) -> None:
        choice = _make_choice(condition_type="random", condition_value=None)
        assert compute_gold_deduction(choice) is None

    @pytest.mark.parametrize("amount", ["1", "5", "10", "50"])
    def test_various_gold_amounts(self, amount: str) -> None:
        choice = _make_choice(condition_type="gold", condition_value=amount)
        assert compute_gold_deduction(choice) == int(amount)
