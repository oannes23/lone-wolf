"""Tests for app/engine/random.py — random roll resolution mechanics.

Covers all acceptance criteria from Story 3.6:
- resolve_phase_random: gold_change, endurance_change, meal_change effects
- resolve_phase_random: item_gain / item_loss noted in events
- resolve_phase_random: scene_redirect sets redirect field
- resolve_phase_random: roll not in any range → no outcome matched
- resolve_scene_exit_random: correct choice selected by roll
- resolve_scene_exit_random: out-of-range roll → None
- resolve_choice_triggered_random: correct band matched
- Multi-roll: get_roll_groups returns sorted unique groups
- Multi-roll: has_remaining_rolls correctly tracks completion
- Redirect wins: scene_redirect is set in result
"""

from __future__ import annotations

import pytest

from app.engine.random import (
    ChoiceRandomResult,
    get_roll_groups,
    has_remaining_rolls,
    resolve_choice_triggered_random,
    resolve_phase_random,
    resolve_scene_exit_random,
)
from app.engine.types import CharacterState, ChoiceData, RandomOutcomeData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_character(
    endurance_current: int = 25,
    endurance_max: int = 25,
    gold: int = 20,
    meals: int = 4,
) -> CharacterState:
    return CharacterState(
        character_id=1,
        combat_skill_base=15,
        endurance_base=25,
        endurance_max=endurance_max,
        endurance_current=endurance_current,
        gold=gold,
        meals=meals,
        is_alive=True,
        disciplines=[],
        weapon_skill_category=None,
        items=[],
        version=1,
        current_run=1,
        death_count=0,
        rule_overrides=None,
    )


def _make_outcome(
    outcome_id: int = 1,
    roll_group: int = 1,
    range_min: int = 0,
    range_max: int = 4,
    effect_type: str = "gold_change",
    effect_value: str = "3",
    narrative_text: str | None = "You found some gold.",
) -> RandomOutcomeData:
    return RandomOutcomeData(
        outcome_id=outcome_id,
        roll_group=roll_group,
        range_min=range_min,
        range_max=range_max,
        effect_type=effect_type,
        effect_value=effect_value,
        narrative_text=narrative_text,
    )


def _make_choice(
    choice_id: int = 1,
    target_scene_id: int | None = 42,
    condition_type: str | None = "random",
    condition_value: str | None = "0-4",
) -> ChoiceData:
    return ChoiceData(
        choice_id=choice_id,
        target_scene_id=target_scene_id,
        target_scene_number=42,
        display_text="Turn to 42.",
        condition_type=condition_type,
        condition_value=condition_value,
        has_random_outcomes=False,
    )


# ---------------------------------------------------------------------------
# resolve_phase_random — effect types
# ---------------------------------------------------------------------------


class TestResolvePhaseRandomGoldChange:
    def test_gold_change_applied(self) -> None:
        state = _make_character(gold=20)
        outcomes = [_make_outcome(effect_type="gold_change", effect_value="5")]
        result = resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        assert result.matched_outcome is not None
        assert result.matched_outcome.effect_type == "gold_change"
        effect = next(e for e in result.effects_applied if e["type"] == "gold_change")
        assert effect["delta"] == 5
        assert effect["actual"] == 5
        assert effect["new_gold"] == 25

    def test_gold_change_capped_at_50(self) -> None:
        state = _make_character(gold=48)
        outcomes = [_make_outcome(effect_type="gold_change", effect_value="10")]
        result = resolve_phase_random(outcomes, roll=0, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "gold_change")
        assert effect["actual"] == 2  # only 2 of 10 applied
        assert effect["new_gold"] == 50

    def test_gold_loss_applied(self) -> None:
        state = _make_character(gold=20)
        outcomes = [_make_outcome(effect_type="gold_change", effect_value="-7")]
        result = resolve_phase_random(outcomes, roll=1, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "gold_change")
        assert effect["delta"] == -7
        assert effect["new_gold"] == 13


class TestResolvePhaseRandomEnduranceChange:
    def test_endurance_damage_applied(self) -> None:
        state = _make_character(endurance_current=25, endurance_max=25)
        outcomes = [_make_outcome(effect_type="endurance_change", effect_value="-5")]
        result = resolve_phase_random(outcomes, roll=3, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "endurance_change")
        assert effect["delta"] == -5
        assert effect["new_endurance"] == 20
        assert effect["is_dead"] is False

    def test_endurance_healing_applied(self) -> None:
        state = _make_character(endurance_current=15, endurance_max=25)
        outcomes = [_make_outcome(effect_type="endurance_change", effect_value="4")]
        result = resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "endurance_change")
        assert effect["new_endurance"] == 19
        assert effect["is_dead"] is False

    def test_endurance_death_flagged(self) -> None:
        state = _make_character(endurance_current=3, endurance_max=25)
        outcomes = [_make_outcome(effect_type="endurance_change", effect_value="-10")]
        result = resolve_phase_random(outcomes, roll=0, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "endurance_change")
        assert effect["new_endurance"] == 0
        assert effect["is_dead"] is True
        assert any(e["type"] == "character_death" for e in result.events)

    def test_endurance_change_emits_events(self) -> None:
        state = _make_character(endurance_current=20, endurance_max=25)
        outcomes = [_make_outcome(effect_type="endurance_change", effect_value="-3")]
        result = resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        assert any(e["type"] == "endurance_change" for e in result.events)


class TestResolvePhaseRandomMealChange:
    def test_meal_gain_applied(self) -> None:
        state = _make_character(meals=3)
        outcomes = [_make_outcome(effect_type="meal_change", effect_value="2")]
        result = resolve_phase_random(outcomes, roll=1, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "meal_change")
        assert effect["delta"] == 2
        assert effect["new_meals"] == 5

    def test_meal_loss_applied(self) -> None:
        state = _make_character(meals=4)
        outcomes = [_make_outcome(effect_type="meal_change", effect_value="-1")]
        result = resolve_phase_random(outcomes, roll=0, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "meal_change")
        assert effect["actual"] == -1
        assert effect["new_meals"] == 3

    def test_meal_capped_at_8(self) -> None:
        state = _make_character(meals=7)
        outcomes = [_make_outcome(effect_type="meal_change", effect_value="5")]
        result = resolve_phase_random(outcomes, roll=4, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "meal_change")
        assert effect["actual"] == 1
        assert effect["new_meals"] == 8


class TestResolvePhaseRandomItemEvents:
    def test_item_gain_noted_in_events(self) -> None:
        state = _make_character()
        outcomes = [_make_outcome(effect_type="item_gain", effect_value="Dagger")]
        result = resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        assert any(e["type"] == "item_gain" and e["item_name"] == "Dagger" for e in result.events)
        assert any(
            e["type"] == "item_gain" and e["item_name"] == "Dagger"
            for e in result.effects_applied
        )

    def test_item_gain_does_not_modify_inventory(self) -> None:
        """item_gain must not touch state.items — that is the service layer's job."""
        state = _make_character()
        original_items = list(state.items)
        outcomes = [_make_outcome(effect_type="item_gain", effect_value="Dagger")]
        resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        assert state.items == original_items

    def test_item_loss_noted_in_events(self) -> None:
        state = _make_character()
        outcomes = [_make_outcome(effect_type="item_loss", effect_value="Rope")]
        result = resolve_phase_random(outcomes, roll=3, roll_group=1, state=state)

        assert any(e["type"] == "item_loss" and e["item_name"] == "Rope" for e in result.events)
        assert any(
            e["type"] == "item_loss" and e["item_name"] == "Rope" for e in result.effects_applied
        )

    def test_item_loss_does_not_modify_inventory(self) -> None:
        state = _make_character()
        original_items = list(state.items)
        outcomes = [_make_outcome(effect_type="item_loss", effect_value="Rope")]
        resolve_phase_random(outcomes, roll=0, roll_group=1, state=state)

        assert state.items == original_items


class TestResolvePhaseRandomSceneRedirect:
    def test_scene_redirect_sets_redirect(self) -> None:
        state = _make_character()
        outcomes = [_make_outcome(effect_type="scene_redirect", effect_value="99")]
        result = resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        assert result.scene_redirect == 99

    def test_scene_redirect_in_effects_applied(self) -> None:
        state = _make_character()
        outcomes = [_make_outcome(effect_type="scene_redirect", effect_value="120")]
        result = resolve_phase_random(outcomes, roll=1, roll_group=1, state=state)

        effect = next(e for e in result.effects_applied if e["type"] == "scene_redirect")
        assert effect["target_scene_id"] == 120

    def test_no_redirect_for_non_redirect_effects(self) -> None:
        state = _make_character()
        outcomes = [_make_outcome(effect_type="gold_change", effect_value="3")]
        result = resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        assert result.scene_redirect is None


class TestResolvePhaseRandomNoMatch:
    def test_roll_not_in_any_range_returns_no_match(self) -> None:
        state = _make_character()
        # Outcome covers 0-4; roll 8 is outside the range
        outcomes = [_make_outcome(range_min=0, range_max=4)]
        result = resolve_phase_random(outcomes, roll=8, roll_group=1, state=state)

        assert result.matched_outcome is None
        assert result.effects_applied == []
        assert result.events == []
        assert result.scene_redirect is None
        assert result.narrative_text is None

    def test_roll_matches_in_correct_group_only(self) -> None:
        state = _make_character()
        outcome_g1 = _make_outcome(outcome_id=1, roll_group=1, range_min=0, range_max=9)
        outcome_g2 = _make_outcome(
            outcome_id=2,
            roll_group=2,
            range_min=0,
            range_max=9,
            effect_type="endurance_change",
            effect_value="-3",
        )
        # Resolving group 2; roll 5 falls in group 2 only
        result = resolve_phase_random([outcome_g1, outcome_g2], roll=5, roll_group=2, state=state)

        assert result.matched_outcome is not None
        assert result.matched_outcome.outcome_id == 2

    def test_empty_outcomes_returns_no_match(self) -> None:
        state = _make_character()
        result = resolve_phase_random([], roll=5, roll_group=1, state=state)

        assert result.matched_outcome is None

    def test_narrative_text_included_when_matched(self) -> None:
        state = _make_character()
        outcomes = [_make_outcome(narrative_text="A bolt of lightning strikes you!")]
        result = resolve_phase_random(outcomes, roll=2, roll_group=1, state=state)

        assert result.narrative_text == "A bolt of lightning strikes you!"

    def test_narrative_text_none_when_no_match(self) -> None:
        state = _make_character()
        outcomes = [_make_outcome(range_min=0, range_max=3)]
        result = resolve_phase_random(outcomes, roll=9, roll_group=1, state=state)

        assert result.narrative_text is None


# ---------------------------------------------------------------------------
# resolve_scene_exit_random
# ---------------------------------------------------------------------------


class TestResolveSceneExitRandom:
    def test_correct_choice_selected(self) -> None:
        choices = [
            _make_choice(choice_id=1, target_scene_id=10, condition_value="0-4"),
            _make_choice(choice_id=2, target_scene_id=20, condition_value="5-9"),
        ]
        result = resolve_scene_exit_random(choices, roll=7)
        assert result == 20

    def test_low_boundary_match(self) -> None:
        choices = [_make_choice(target_scene_id=5, condition_value="0-4")]
        assert resolve_scene_exit_random(choices, roll=0) == 5

    def test_high_boundary_match(self) -> None:
        choices = [_make_choice(target_scene_id=5, condition_value="0-4")]
        assert resolve_scene_exit_random(choices, roll=4) == 5

    def test_out_of_range_roll_returns_none(self) -> None:
        choices = [_make_choice(target_scene_id=10, condition_value="0-4")]
        result = resolve_scene_exit_random(choices, roll=7)
        assert result is None

    def test_empty_choices_returns_none(self) -> None:
        assert resolve_scene_exit_random([], roll=5) is None

    def test_none_condition_value_skipped(self) -> None:
        choices = [
            _make_choice(choice_id=1, target_scene_id=10, condition_value=None),
            _make_choice(choice_id=2, target_scene_id=20, condition_value="5-9"),
        ]
        assert resolve_scene_exit_random(choices, roll=6) == 20

    def test_first_matching_choice_wins(self) -> None:
        """If two ranges overlap, the first is selected."""
        choices = [
            _make_choice(choice_id=1, target_scene_id=10, condition_value="0-9"),
            _make_choice(choice_id=2, target_scene_id=20, condition_value="5-9"),
        ]
        assert resolve_scene_exit_random(choices, roll=7) == 10


# ---------------------------------------------------------------------------
# resolve_choice_triggered_random
# ---------------------------------------------------------------------------


class TestResolveChoiceTriggeredRandom:
    def _bands(self) -> list[dict]:
        return [
            {
                "range_min": 0,
                "range_max": 4,
                "target_scene_id": 50,
                "target_scene_number": 50,
                "narrative_text": "You fail.",
            },
            {
                "range_min": 5,
                "range_max": 9,
                "target_scene_id": 60,
                "target_scene_number": 60,
                "narrative_text": "You succeed.",
            },
        ]

    def test_correct_band_matched_low(self) -> None:
        result = resolve_choice_triggered_random(self._bands(), roll=2)
        assert isinstance(result, ChoiceRandomResult)
        assert result.target_scene_id == 50
        assert result.target_scene_number == 50
        assert result.roll == 2

    def test_correct_band_matched_high(self) -> None:
        result = resolve_choice_triggered_random(self._bands(), roll=7)
        assert result.target_scene_id == 60
        assert result.narrative_text == "You succeed."

    def test_boundary_values(self) -> None:
        assert resolve_choice_triggered_random(self._bands(), roll=0).target_scene_id == 50
        assert resolve_choice_triggered_random(self._bands(), roll=4).target_scene_id == 50
        assert resolve_choice_triggered_random(self._bands(), roll=5).target_scene_id == 60
        assert resolve_choice_triggered_random(self._bands(), roll=9).target_scene_id == 60

    def test_no_band_match_raises(self) -> None:
        """A roll that falls in a gap between bands raises ValueError."""
        bands = [
            {"range_min": 0, "range_max": 3, "target_scene_id": 10, "target_scene_number": 10,
             "narrative_text": None},
            {"range_min": 6, "range_max": 9, "target_scene_id": 20, "target_scene_number": 20,
             "narrative_text": None},
        ]
        with pytest.raises(ValueError, match="Roll 5 did not match any outcome band"):
            resolve_choice_triggered_random(bands, roll=5)

    def test_narrative_text_none_handled(self) -> None:
        bands = [
            {
                "range_min": 0,
                "range_max": 9,
                "target_scene_id": 30,
                "target_scene_number": 30,
                "narrative_text": None,
            }
        ]
        result = resolve_choice_triggered_random(bands, roll=3)
        assert result.narrative_text is None

    def test_events_empty(self) -> None:
        result = resolve_choice_triggered_random(self._bands(), roll=1)
        assert result.events == []


# ---------------------------------------------------------------------------
# Multi-roll helpers: get_roll_groups / has_remaining_rolls
# ---------------------------------------------------------------------------


class TestGetRollGroups:
    def test_sorted_unique_groups(self) -> None:
        outcomes = [
            _make_outcome(outcome_id=1, roll_group=3),
            _make_outcome(outcome_id=2, roll_group=1),
            _make_outcome(outcome_id=3, roll_group=2),
            _make_outcome(outcome_id=4, roll_group=1),  # duplicate
        ]
        assert get_roll_groups(outcomes) == [1, 2, 3]

    def test_single_group(self) -> None:
        outcomes = [_make_outcome(roll_group=1)]
        assert get_roll_groups(outcomes) == [1]

    def test_empty_outcomes(self) -> None:
        assert get_roll_groups([]) == []

    def test_non_sequential_groups(self) -> None:
        outcomes = [
            _make_outcome(outcome_id=1, roll_group=10),
            _make_outcome(outcome_id=2, roll_group=5),
        ]
        assert get_roll_groups(outcomes) == [5, 10]


class TestHasRemainingRolls:
    def test_all_groups_incomplete(self) -> None:
        outcomes = [
            _make_outcome(outcome_id=1, roll_group=1),
            _make_outcome(outcome_id=2, roll_group=2),
        ]
        has_more, next_group = has_remaining_rolls(outcomes, completed_groups=[])
        assert has_more is True
        assert next_group == 1

    def test_one_group_completed(self) -> None:
        outcomes = [
            _make_outcome(outcome_id=1, roll_group=1),
            _make_outcome(outcome_id=2, roll_group=2),
        ]
        has_more, next_group = has_remaining_rolls(outcomes, completed_groups=[1])
        assert has_more is True
        assert next_group == 2

    def test_all_groups_completed(self) -> None:
        outcomes = [
            _make_outcome(outcome_id=1, roll_group=1),
            _make_outcome(outcome_id=2, roll_group=2),
        ]
        has_more, next_group = has_remaining_rolls(outcomes, completed_groups=[1, 2])
        assert has_more is False
        assert next_group is None

    def test_empty_outcomes_no_remaining(self) -> None:
        has_more, next_group = has_remaining_rolls([], completed_groups=[])
        assert has_more is False
        assert next_group is None

    def test_single_group_not_yet_rolled(self) -> None:
        outcomes = [_make_outcome(roll_group=1)]
        has_more, next_group = has_remaining_rolls(outcomes, completed_groups=[])
        assert has_more is True
        assert next_group == 1

    def test_single_group_already_rolled(self) -> None:
        outcomes = [_make_outcome(roll_group=1)]
        has_more, next_group = has_remaining_rolls(outcomes, completed_groups=[1])
        assert has_more is False
        assert next_group is None

    def test_next_group_is_lowest_unresolved(self) -> None:
        outcomes = [
            _make_outcome(outcome_id=1, roll_group=1),
            _make_outcome(outcome_id=2, roll_group=2),
            _make_outcome(outcome_id=3, roll_group=3),
        ]
        has_more, next_group = has_remaining_rolls(outcomes, completed_groups=[1])
        assert has_more is True
        assert next_group == 2
