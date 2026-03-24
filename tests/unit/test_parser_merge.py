"""Unit tests for app/parser/merge.py.

Tests the reconciliation logic between manual heuristic extraction and LLM
structured extraction results.
"""

from __future__ import annotations

import pytest

from app.parser.merge import (
    merge_combat_encounters,
    merge_combat_modifiers,
    merge_conditions,
    merge_evasion,
    merge_items,
    merge_random_outcomes,
    merge_scene_flags,
)


# ---------------------------------------------------------------------------
# merge_combat_encounters
# ---------------------------------------------------------------------------


class TestMergeCombatEncounters:
    def test_llm_none_passes_through_manual(self) -> None:
        manual = [{"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1}]
        merged, warnings = merge_combat_encounters(manual, None, scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_llm_empty_passes_through_manual(self) -> None:
        manual = [{"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1}]
        merged, warnings = merge_combat_encounters(manual, [], scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_llm_wins_when_present(self) -> None:
        manual = [{"enemy_name": "Kraan", "enemy_cs": 15, "enemy_end": 20, "ordinal": 1}]
        llm = [{"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1}]
        merged, warnings = merge_combat_encounters(manual, llm, scene_number=1)
        assert len(merged) == 1
        assert merged[0]["enemy_name"] == "Kraan"
        assert merged[0]["enemy_cs"] == 16
        assert merged[0]["enemy_end"] == 24

    def test_stat_disagreement_generates_warning(self) -> None:
        manual = [{"enemy_name": "Kraan", "enemy_cs": 15, "enemy_end": 20, "ordinal": 1}]
        llm = [{"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1}]
        _, warnings = merge_combat_encounters(manual, llm, scene_number=5)
        assert len(warnings) == 1
        assert "MERGE_CONFLICT" in warnings[0]
        assert "combat_stats" in warnings[0]
        assert "winner=llm" in warnings[0]

    def test_manual_only_enemy_included(self) -> None:
        manual = [
            {"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1},
            {"enemy_name": "Giak", "enemy_cs": 10, "enemy_end": 12, "ordinal": 2},
        ]
        llm = [{"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1}]
        merged, warnings = merge_combat_encounters(manual, llm, scene_number=1)
        names = {e["enemy_name"] for e in merged}
        assert "Kraan" in names
        assert "Giak" in names
        assert any("manual_only" in w for w in warnings)

    def test_llm_only_enemy_included(self) -> None:
        manual = []
        llm = [{"enemy_name": "Helghast", "enemy_cs": 22, "enemy_end": 30, "ordinal": 1}]
        merged, warnings = merge_combat_encounters(manual, llm, scene_number=1)
        assert len(merged) == 1
        assert merged[0]["enemy_name"] == "Helghast"
        assert warnings == []

    def test_agreement_no_warnings(self) -> None:
        manual = [{"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1}]
        llm = [{"enemy_name": "Kraan", "enemy_cs": 16, "enemy_end": 24, "ordinal": 1}]
        _, warnings = merge_combat_encounters(manual, llm, scene_number=1)
        assert not any("combat_stats" in w for w in warnings)


# ---------------------------------------------------------------------------
# merge_items
# ---------------------------------------------------------------------------


class TestMergeItems:
    def test_llm_none_passes_through_manual(self) -> None:
        manual = [{"item_name": "Sword", "item_type": "weapon", "quantity": 1, "action": "gain"}]
        merged, warnings = merge_items(manual, None, scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_llm_items_preferred(self) -> None:
        manual = [{"item_name": "Sword", "item_type": "backpack", "quantity": 1, "action": "gain"}]
        llm = [{"item_name": "Sword", "item_type": "weapon", "quantity": 1, "action": "gain"}]
        merged, _ = merge_items(manual, llm, scene_number=1)
        assert len(merged) == 1
        assert merged[0]["item_type"] == "weapon"  # LLM type wins

    def test_union_deduplication(self) -> None:
        manual = [
            {"item_name": "Sword", "item_type": "weapon", "quantity": 1, "action": "gain"},
            {"item_name": "Rope", "item_type": "backpack", "quantity": 1, "action": "gain"},
        ]
        llm = [
            {"item_name": "Sword", "item_type": "weapon", "quantity": 1, "action": "gain"},
            {"item_name": "Gold Crowns", "item_type": "gold", "quantity": 5, "action": "gain"},
        ]
        merged, warnings = merge_items(manual, llm, scene_number=1)
        names = [i["item_name"] for i in merged]
        assert "Sword" in names
        assert "Gold Crowns" in names
        assert "Rope" in names
        assert len(merged) == 3
        # Rope was manual-only, should generate warning
        assert any("manual_only=Rope" in w for w in warnings)

    def test_quantity_disagreement_warning(self) -> None:
        manual = [{"item_name": "Gold Crowns", "item_type": "gold", "quantity": 3, "action": "gain"}]
        llm = [{"item_name": "Gold Crowns", "item_type": "gold", "quantity": 5, "action": "gain"}]
        merged, warnings = merge_items(manual, llm, scene_number=1)
        assert merged[0]["quantity"] == 5  # LLM wins
        assert any("item_quantity" in w for w in warnings)

    def test_empty_both(self) -> None:
        merged, warnings = merge_items([], [], scene_number=1)
        assert merged == []
        assert warnings == []

    def test_merge_items_llm_empty_list(self) -> None:
        """When LLM returns an empty list, manual item is included with a warning."""
        manual_item = {"item_name": "Sword", "item_type": "weapon", "quantity": 1, "action": "gain"}
        merged, warnings = merge_items([manual_item], [], scene_number=1)
        assert len(merged) == 1
        assert merged[0]["item_name"] == "Sword"
        assert any("manual_only=Sword" in w for w in warnings)


# ---------------------------------------------------------------------------
# merge_random_outcomes
# ---------------------------------------------------------------------------


class TestMergeRandomOutcomes:
    def test_llm_none_passes_through_manual(self) -> None:
        manual = [{"range_min": 0, "range_max": 4, "effect_type": "endurance_change", "effect_value": "-2"}]
        merged, warnings = merge_random_outcomes(manual, None, scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_llm_wins_when_present(self) -> None:
        manual = [{"range_min": 0, "range_max": 4}]
        llm = [
            {"range_min": 0, "range_max": 4, "effect_type": "endurance_change", "effect_value": "-2"},
            {"range_min": 5, "range_max": 9, "effect_type": "endurance_change", "effect_value": "-1"},
        ]
        merged, _ = merge_random_outcomes(manual, llm, scene_number=1)
        assert merged == llm

    def test_count_disagreement_warning(self) -> None:
        manual = [{"range_min": 0, "range_max": 9}]
        llm = [
            {"range_min": 0, "range_max": 4},
            {"range_min": 5, "range_max": 9},
        ]
        _, warnings = merge_random_outcomes(manual, llm, scene_number=1)
        assert len(warnings) == 1
        assert "manual_count=1" in warnings[0]
        assert "llm_count=2" in warnings[0]

    def test_llm_empty_falls_back_to_manual(self) -> None:
        manual = [{"range_min": 0, "range_max": 9}]
        merged, warnings = merge_random_outcomes(manual, [], scene_number=1)
        assert merged == manual
        assert warnings == []


# ---------------------------------------------------------------------------
# merge_evasion
# ---------------------------------------------------------------------------


class TestMergeEvasion:
    def test_llm_none_passes_through_manual(self) -> None:
        manual = (3, 85, 2)
        merged, warnings = merge_evasion(manual, None, scene_number=1)
        assert merged == (3, 85, 2)
        assert warnings == []

    def test_llm_wins_when_present(self) -> None:
        manual = (2, 85, 0)
        llm = {"rounds": 3, "target_scene": 85, "damage": 2}
        merged, warnings = merge_evasion(manual, llm, scene_number=1)
        assert merged == (3, 85, 2)
        assert any("MERGE_CONFLICT" in w for w in warnings)

    def test_agreement_no_warning(self) -> None:
        manual = (3, 85, 0)
        llm = {"rounds": 3, "target_scene": 85, "damage": 0}
        merged, warnings = merge_evasion(manual, llm, scene_number=1)
        assert merged == (3, 85, 0)
        assert warnings == []

    def test_both_none(self) -> None:
        merged, warnings = merge_evasion(None, None, scene_number=1)
        assert merged is None
        assert warnings == []

    def test_manual_none_llm_present(self) -> None:
        llm = {"rounds": 2, "target_scene": 100, "damage": 1}
        merged, warnings = merge_evasion(None, llm, scene_number=1)
        assert merged == (2, 100, 1)
        assert warnings == []

    def test_llm_empty_dict_falls_back_to_manual(self) -> None:
        manual = (3, 85, 0)
        merged, warnings = merge_evasion(manual, {}, scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_merge_evasion_missing_damage_key(self) -> None:
        """LLM evasion dict with no 'damage' key defaults damage to 0."""
        llm = {"rounds": 3, "target_scene": 85}
        merged, warnings = merge_evasion(None, llm, scene_number=1)
        assert merged == (3, 85, 0)


# ---------------------------------------------------------------------------
# merge_combat_modifiers
# ---------------------------------------------------------------------------


class TestMergeCombatModifiers:
    def test_llm_none_passes_through_manual(self) -> None:
        manual = [{"modifier_type": "undead", "value": None}]
        merged, warnings = merge_combat_modifiers(manual, None, scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_union_deduplication(self) -> None:
        manual = [
            {"modifier_type": "undead", "value": None},
            {"modifier_type": "cs_bonus", "value": 2},
        ]
        llm = [
            {"modifier_type": "undead", "value": None},
            {"modifier_type": "enemy_mindblast", "value": None},
        ]
        merged, warnings = merge_combat_modifiers(manual, llm, scene_number=1)
        types = {m["modifier_type"] for m in merged}
        assert types == {"undead", "enemy_mindblast", "cs_bonus"}
        # cs_bonus was manual-only
        assert any("manual_only=cs_bonus" in w for w in warnings)

    def test_empty_both(self) -> None:
        merged, warnings = merge_combat_modifiers([], [], scene_number=1)
        assert merged == []
        assert warnings == []

    def test_merge_combat_modifiers_llm_only_no_warning(self) -> None:
        """When only LLM provides a modifier (manual is empty), it is included without a warning."""
        llm_mod = {"modifier_type": "undead", "value": None}
        merged, warnings = merge_combat_modifiers([], [llm_mod], scene_number=1)
        assert len(merged) == 1
        assert merged[0]["modifier_type"] == "undead"
        assert warnings == []


# ---------------------------------------------------------------------------
# merge_conditions
# ---------------------------------------------------------------------------


class TestMergeConditions:
    def test_llm_none_passes_through_manual(self) -> None:
        manual = [
            {"ordinal": 1, "condition_type": "discipline", "condition_value": "Tracking"},
        ]
        merged, warnings = merge_conditions(manual, None, scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_llm_wins_per_choice(self) -> None:
        manual = [
            {"ordinal": 1, "condition_type": "item", "condition_value": "Sword"},
            {"ordinal": 2, "condition_type": None, "condition_value": None},
        ]
        llm_conds = [
            {"choice_ordinal": 1, "condition_type": "discipline", "condition_value": "Tracking"},
        ]
        merged, warnings = merge_conditions(manual, llm_conds, scene_number=1)
        # Choice 1: LLM wins
        assert merged[0]["condition_type"] == "discipline"
        assert merged[0]["condition_value"] == "Tracking"
        # Choice 2: no LLM condition, manual kept
        assert merged[1]["condition_type"] is None
        # Disagreement on choice 1
        assert any("MERGE_CONFLICT" in w for w in warnings)

    def test_no_llm_condition_keeps_manual(self) -> None:
        manual = [
            {"ordinal": 1, "condition_type": "gold", "condition_value": "10"},
        ]
        merged, warnings = merge_conditions(manual, [], scene_number=1)
        assert merged[0]["condition_type"] == "gold"
        assert warnings == []

    def test_merge_conditions_nonexistent_ordinal(self) -> None:
        """LLM condition for an ordinal that matches no manual choice is silently ignored."""
        manual = [
            {"ordinal": 1, "condition_type": None, "condition_value": None},
        ]
        llm_conds = [
            {"choice_ordinal": 99, "condition_type": "discipline", "condition_value": "Tracking"},
        ]
        merged, warnings = merge_conditions(manual, llm_conds, scene_number=1)
        # The manual choice for ordinal 1 is unchanged
        assert merged[0]["condition_type"] is None
        # No warnings emitted for the phantom ordinal
        assert warnings == []


# ---------------------------------------------------------------------------
# merge_scene_flags
# ---------------------------------------------------------------------------


class TestMergeSceneFlags:
    def test_llm_none_passes_through_manual(self) -> None:
        manual = {"must_eat": True, "loses_backpack": False, "is_death": False,
                  "is_victory": False, "mindblast_immune": False}
        merged, warnings = merge_scene_flags(manual, None, scene_number=1)
        assert merged == manual
        assert warnings == []

    def test_manual_true_wins(self) -> None:
        manual = {"must_eat": True, "loses_backpack": False, "is_death": False,
                  "is_victory": False, "mindblast_immune": False}
        llm = {"must_eat": False, "loses_backpack": False, "is_death": False,
               "is_victory": False, "mindblast_immune": False}
        merged, warnings = merge_scene_flags(manual, llm, scene_number=1)
        assert merged["must_eat"] is True  # Manual True preserved
        assert warnings == []  # No warning — manual True always wins silently

    def test_llm_catches_what_manual_missed(self) -> None:
        manual = {"must_eat": False, "loses_backpack": False, "is_death": False,
                  "is_victory": False, "mindblast_immune": False}
        llm = {"must_eat": False, "loses_backpack": True, "is_death": False,
               "is_victory": False, "mindblast_immune": False}
        merged, warnings = merge_scene_flags(manual, llm, scene_number=1)
        assert merged["loses_backpack"] is True  # LLM caught it
        assert len(warnings) == 1
        assert "loses_backpack" in warnings[0]
        assert "winner=llm" in warnings[0]

    def test_both_false_stays_false(self) -> None:
        manual = {"must_eat": False, "loses_backpack": False, "is_death": False,
                  "is_victory": False, "mindblast_immune": False}
        llm = {"must_eat": False, "loses_backpack": False, "is_death": False,
               "is_victory": False, "mindblast_immune": False}
        merged, warnings = merge_scene_flags(manual, llm, scene_number=1)
        assert all(v is False for v in merged.values())
        assert warnings == []

    def test_both_true_stays_true(self) -> None:
        manual = {"must_eat": True, "loses_backpack": False, "is_death": False,
                  "is_victory": False, "mindblast_immune": False}
        llm = {"must_eat": True, "loses_backpack": False, "is_death": False,
               "is_victory": False, "mindblast_immune": False}
        merged, warnings = merge_scene_flags(manual, llm, scene_number=1)
        assert merged["must_eat"] is True
        assert warnings == []

    def test_multiple_flags_mixed(self) -> None:
        manual = {"must_eat": True, "loses_backpack": False, "is_death": False,
                  "is_victory": False, "mindblast_immune": True}
        llm = {"must_eat": False, "loses_backpack": True, "is_death": True,
               "is_victory": False, "mindblast_immune": False}
        merged, warnings = merge_scene_flags(manual, llm, scene_number=1)
        assert merged["must_eat"] is True       # manual True wins
        assert merged["loses_backpack"] is True  # LLM catches
        assert merged["is_death"] is True        # LLM catches
        assert merged["is_victory"] is False     # both False
        assert merged["mindblast_immune"] is True # manual True wins
        # 2 warnings for LLM catches (loses_backpack, is_death)
        assert len(warnings) == 2
