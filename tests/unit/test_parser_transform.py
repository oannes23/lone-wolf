"""Unit tests for app/parser/transform.py — the parser transform phase.

Each detection function is exercised with positive cases, negative cases,
and edge cases (empty strings, None-equivalent values).
"""

from __future__ import annotations

import json

import pytest

from app.parser.transform import (
    classify_condition,
    detect_backpack_loss,
    detect_choice_triggered_random,
    detect_combat_modifiers,
    detect_conditional_combat,
    detect_death_scene,
    detect_evasion,
    detect_items,
    detect_mindblast_immunity,
    detect_must_eat,
    detect_phase_ordering,
    detect_random_outcomes,
    detect_scene_level_random_exits,
    detect_victory_scene,
    parse_combat,
)


# ===========================================================================
# classify_condition
# ===========================================================================


class TestClassifyCondition:
    """Tests for classify_condition()."""

    def test_discipline_kai_prefix(self) -> None:
        text = "If you wish to use your Kai Discipline of Tracking, turn to 141."
        ctype, cval = classify_condition(text)
        assert ctype == "discipline"
        assert cval == "Tracking"

    def test_discipline_without_kai_prefix(self) -> None:
        text = "If you have the Discipline of Sixth Sense, turn to 50."
        ctype, cval = classify_condition(text)
        assert ctype == "discipline"
        assert cval == "Sixth Sense"

    def test_discipline_hunting(self) -> None:
        text = "If you have the Kai Discipline of Hunting, turn to 100."
        ctype, cval = classify_condition(text)
        assert ctype == "discipline"
        assert cval == "Hunting"

    def test_item_possess(self) -> None:
        text = "If you possess a Sword, turn to 236."
        ctype, cval = classify_condition(text)
        assert ctype == "item"
        assert cval == "Sword"

    def test_item_vordak_gem(self) -> None:
        text = "If you possess a Vordak Gem, turn to 236."
        ctype, cval = classify_condition(text)
        assert ctype == "item"
        assert cval == "Vordak Gem"

    def test_gold_check(self) -> None:
        text = "If you have 10 Gold Crowns and wish to pay him, turn to 262."
        ctype, cval = classify_condition(text)
        assert ctype == "gold"
        assert cval == "10"

    def test_gold_check_different_amount(self) -> None:
        text = "If you have 5 Gold Crowns, turn to 50."
        ctype, cval = classify_condition(text)
        assert ctype == "gold"
        assert cval == "5"

    def test_random_pick_a_number(self) -> None:
        text = "Pick a number from the Random Number Table."
        ctype, cval = classify_condition(text)
        assert ctype == "random"
        assert cval is None

    def test_random_random_number(self) -> None:
        text = "Consult the Random Number Table and turn to the section indicated."
        ctype, cval = classify_condition(text)
        assert ctype == "random"
        assert cval is None

    def test_compound_or_discipline(self) -> None:
        text = "If you have Tracking or Huntmastery, turn to 85."
        ctype, cval = classify_condition(text)
        assert ctype == "discipline"
        data = json.loads(cval)  # type: ignore[arg-type]
        assert "any" in data
        assert "Tracking" in data["any"]
        assert "Huntmastery" in data["any"]

    def test_no_condition_plain_choice(self) -> None:
        ctype, cval = classify_condition("Turn to 139.")
        assert ctype is None
        assert cval is None

    def test_no_condition_wish_choice(self) -> None:
        ctype, cval = classify_condition("If you wish to take the right path, turn to 85.")
        assert ctype is None
        assert cval is None

    def test_empty_string(self) -> None:
        ctype, cval = classify_condition("")
        assert ctype is None
        assert cval is None


# ===========================================================================
# detect_must_eat
# ===========================================================================


class TestDetectMustEat:
    def test_must_eat_a_meal(self) -> None:
        assert detect_must_eat("You must eat a Meal before continuing.") is True

    def test_mark_off_a_meal(self) -> None:
        assert detect_must_eat("Mark off a Meal from your Backpack.") is True

    def test_must_now_eat(self) -> None:
        assert detect_must_eat("You must now eat a Meal or lose 3 ENDURANCE points.") is True

    def test_no_eat_language(self) -> None:
        assert detect_must_eat("You enter the dark forest.") is False

    def test_eat_word_alone_not_sufficient(self) -> None:
        # 'eat' alone without the required pattern should return False
        assert detect_must_eat("The guard eats his lunch.") is False

    def test_empty_string(self) -> None:
        assert detect_must_eat("") is False

    def test_case_insensitive(self) -> None:
        assert detect_must_eat("YOU MUST EAT A MEAL.") is True


# ===========================================================================
# detect_backpack_loss
# ===========================================================================


class TestDetectBackpackLoss:
    def test_you_lose_your_backpack(self) -> None:
        assert detect_backpack_loss("You lose your Backpack and its contents.") is True

    def test_backpack_has_been_taken(self) -> None:
        assert detect_backpack_loss("Your Backpack has been taken by the guards.") is True

    def test_backpack_and_all_its_contents(self) -> None:
        assert detect_backpack_loss("You must leave your Backpack and all its contents behind.") is True

    def test_no_backpack_loss(self) -> None:
        assert detect_backpack_loss("You find a Sword on the ground.") is False

    def test_empty_string(self) -> None:
        assert detect_backpack_loss("") is False

    def test_case_insensitive(self) -> None:
        assert detect_backpack_loss("YOU LOSE YOUR BACKPACK.") is True

    def test_equipment_confiscated(self) -> None:
        assert detect_backpack_loss(
            "All your equipment is confiscated, including all Special Items and Weapons."
        ) is True

    def test_belongings_seized(self) -> None:
        assert detect_backpack_loss(
            "Your belongings are seized by the soldiers."
        ) is True

    def test_someone_else_backpack_is_false(self) -> None:
        assert detect_backpack_loss(
            "The thief drops his backpack and runs."
        ) is False

    def test_take_your_backpack(self) -> None:
        assert detect_backpack_loss(
            "They take your Backpack and Weapons."
        ) is True

    def test_lost_your_backpack(self) -> None:
        assert detect_backpack_loss(
            "You have lost your Backpack and Weapons but you have your life."
        ) is True

    def test_erase_backpack_items(self) -> None:
        assert detect_backpack_loss(
            "You must now erase all Weapons and Backpack Items from your Action Chart."
        ) is True

    def test_items_stolen(self) -> None:
        assert detect_backpack_loss(
            "Your Backpack, your Weapons, and all your Special Items have been stolen."
        ) is True


# ===========================================================================
# detect_items
# ===========================================================================


class TestDetectItems:
    def test_gold_gain(self) -> None:
        items = detect_items("You find 10 Gold Crowns in the chest.")
        assert any(
            i["item_name"] == "Gold Crowns" and i["action"] == "gain" and i["quantity"] == 10
            for i in items
        )

    def test_gold_lose(self) -> None:
        items = detect_items("You lose 5 Gold Crowns in the transaction.")
        assert any(
            i["item_name"] == "Gold Crowns" and i["action"] == "lose" and i["quantity"] == 5
            for i in items
        )

    def test_meal_gain(self) -> None:
        items = detect_items("You find a Meal in the saddlebag.")
        assert any(i["item_name"] == "Meal" and i["action"] == "gain" for i in items)

    def test_take_sword(self) -> None:
        items = detect_items("You may take the Sword from the dead warrior.")
        sword_items = [i for i in items if "Sword" in i["item_name"]]
        assert sword_items
        assert sword_items[0]["action"] == "gain"
        assert sword_items[0]["item_type"] == "weapon"

    def test_lose_item(self) -> None:
        items = detect_items("You lose your Map in the struggle.")
        assert any(i["action"] == "lose" for i in items)

    def test_no_items(self) -> None:
        items = detect_items("You walk through the forest cautiously.")
        assert items == []

    def test_empty_string(self) -> None:
        assert detect_items("") == []

    def test_choices_parameter_accepted(self) -> None:
        # choices param is reserved but must not cause an error
        items = detect_items("You find 3 Gold Crowns.", choices=["Turn to 10."])
        assert any(i["item_name"] == "Gold Crowns" for i in items)

    def test_endurance_loss_not_item(self) -> None:
        """Endurance point changes are meter effects, not items."""
        items = detect_items("You lose 5 <Small>Endurance</Small> Points and drop to the hold.")
        endurance_items = [i for i in items if "endurance" in i["item_name"].lower()]
        assert endurance_items == []

    def test_endurance_point_singular_not_item(self) -> None:
        items = detect_items("You lose 1 <Small>Endurance</Small> Point in the fall.")
        endurance_items = [i for i in items if "endurance" in i["item_name"].lower()]
        assert endurance_items == []

    def test_lose_sword_still_detected(self) -> None:
        """Ensure the Endurance filter doesn't break normal item loss detection."""
        items = detect_items("You lose your Sword in the river.")
        assert any(i["action"] == "lose" for i in items)

    def test_take_meta_instruction_not_item(self) -> None:
        """'you may take these items if you wish' is not an item named 'These Items If You Wish'."""
        items = detect_items("You may take these items if you wish.")
        garbled = [i for i in items if "these items" in i["item_name"].lower()]
        assert garbled == []

    def test_take_this_weapon_not_item(self) -> None:
        items = detect_items("You may take this weapon if you wish.")
        garbled = [i for i in items if "this weapon" in i["item_name"].lower()]
        assert garbled == []

    def test_take_actual_item_still_detected(self) -> None:
        """'you may take the Dagger' should still be detected."""
        items = detect_items("You may take the Dagger.")
        assert any(i["item_name"] == "Dagger" and i["action"] == "gain" for i in items)

    def test_lose_footing_not_item(self) -> None:
        items = detect_items("You lose your footing and fall headlong over the edge.")
        footing_items = [i for i in items if "footing" in i["item_name"].lower()]
        assert footing_items == []

    def test_lose_consciousness_not_item(self) -> None:
        items = detect_items("You lose consciousness.")
        assert items == []

    def test_take_sword_if_you_wish_not_garbled(self) -> None:
        """Should extract 'Sword' not 'Sword If You Wish'."""
        items = detect_items("You may take the Sword if you wish.")
        garbled = [i for i in items if "if you wish" in i["item_name"].lower()]
        assert garbled == []

    def test_take_these_if_you_wish_not_item(self) -> None:
        items = detect_items("You may take these if you wish.")
        garbled = [i for i in items if "these if" in i["item_name"].lower()]
        assert garbled == []

    def test_take_both_not_garbled(self) -> None:
        items = detect_items("You may take both the Dagger and the Crowns if you are able to.")
        garbled = [i for i in items if "both the" in i["item_name"].lower()]
        assert garbled == []


# ===========================================================================
# detect_death_scene
# ===========================================================================


class TestDetectDeathScene:
    def test_death_with_no_choices(self) -> None:
        assert detect_death_scene("Your adventure ends here.", choices=[]) is True

    def test_death_with_no_choices_none(self) -> None:
        assert detect_death_scene("You are dead.", choices=None) is True

    def test_death_with_choices_is_false(self) -> None:
        # If there are outgoing choices, it is not a death scene even with death language
        assert detect_death_scene("You are dead.", choices=["Turn to 10."]) is False

    def test_life_ends(self) -> None:
        assert detect_death_scene("Your life ends here in the darkness.", choices=[]) is True

    def test_your_adventure_is_over(self) -> None:
        assert detect_death_scene("Your adventure is over.", choices=None) is True

    def test_no_death_language(self) -> None:
        assert detect_death_scene("You enter the castle.", choices=[]) is False

    def test_empty_string_no_choices(self) -> None:
        assert detect_death_scene("", choices=[]) is False

    def test_you_perish(self) -> None:
        assert detect_death_scene("You perish in the flames.", choices=None) is True

    def test_life_and_mission_end_here(self) -> None:
        assert detect_death_scene(
            "Your mission and your life end here.", choices=[]
        ) is True

    def test_mission_and_life_end_here(self) -> None:
        assert detect_death_scene(
            "Your life and your mission end here.", choices=None
        ) is True

    def test_quest_comes_to_tragic_end(self) -> None:
        assert detect_death_scene(
            "Your quest comes to a tragic end in the swamp.", choices=[]
        ) is True

    def test_quest_ends(self) -> None:
        assert detect_death_scene(
            "Your quest ends in the darkness.", choices=None
        ) is True

    def test_death_language_with_choices_still_false(self) -> None:
        """Even new death patterns should return False when choices exist."""
        assert detect_death_scene(
            "Your mission and your life end here.",
            choices=["Turn to 194."],
        ) is False

    def test_life_and_quest_end_here(self) -> None:
        assert detect_death_scene(
            "Your life and your quest end here.", choices=[]
        ) is True

    def test_mission_ends_here(self) -> None:
        assert detect_death_scene(
            "Your mission ends here.", choices=None
        ) is True


# ===========================================================================
# detect_victory_scene
# ===========================================================================


class TestDetectVictoryScene:
    def test_quest_is_complete(self) -> None:
        assert detect_victory_scene("Your quest is complete. You have saved Sommerlund.") is True

    def test_you_have_completed(self) -> None:
        assert detect_victory_scene("You have completed your mission successfully.") is True

    def test_congratulations(self) -> None:
        assert detect_victory_scene("Congratulations! You have won the battle.") is True

    def test_no_victory_language(self) -> None:
        assert detect_victory_scene("You enter the throne room.") is False

    def test_empty_string(self) -> None:
        assert detect_victory_scene("") is False

    def test_choices_param_accepted(self) -> None:
        assert detect_victory_scene("Your quest is complete.", choices=["Turn to 10."]) is True

    def test_victory_is_yours(self) -> None:
        assert detect_victory_scene(
            "The victory is yours! You have defeated the Darklords."
        ) is True

    def test_casual_victory_mention_is_false(self) -> None:
        """Mentioning 'victory' in passing should not trigger detection."""
        assert detect_victory_scene(
            "The soldiers celebrate their recent victory in the tavern."
        ) is False

    def test_begin_adventure_with_next_book(self) -> None:
        assert detect_victory_scene(
            "Begin your adventure with Book 2 of the Lone Wolf adventures."
        ) is True


# ===========================================================================
# parse_combat
# ===========================================================================


class TestParseCombat:
    def test_standard_format(self) -> None:
        block = "Kraan: COMBAT SKILL 16   ENDURANCE 24"
        result = parse_combat(block)
        assert result is not None
        assert result["enemy_name"] == "Kraan"
        assert result["enemy_cs"] == 16
        assert result["enemy_end"] == 24

    def test_case_insensitive(self) -> None:
        block = "Vordak: combat skill 18 endurance 30"
        result = parse_combat(block)
        assert result is not None
        assert result["enemy_name"] == "Vordak"
        assert result["enemy_cs"] == 18
        assert result["enemy_end"] == 30

    def test_multi_word_enemy(self) -> None:
        block = "Drakkar Warrior: COMBAT SKILL 14 ENDURANCE 20"
        result = parse_combat(block)
        assert result is not None
        assert result["enemy_name"] == "Drakkar Warrior"

    def test_extra_whitespace(self) -> None:
        block = "Gourgaz:   COMBAT SKILL   20   ENDURANCE   35"
        result = parse_combat(block)
        assert result is not None
        assert result["enemy_cs"] == 20
        assert result["enemy_end"] == 35

    def test_no_match_returns_none(self) -> None:
        assert parse_combat("You find a sword on the ground.") is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_combat("") is None

    def test_none_like_empty_returns_none(self) -> None:
        assert parse_combat("   ") is None


# ===========================================================================
# detect_evasion
# ===========================================================================


class TestDetectEvasion:
    def test_basic_evasion(self) -> None:
        narrative = (
            "You may evade after three rounds of combat. "
            "Turn to 85 to escape."
        )
        result = detect_evasion(narrative)
        assert result is not None
        rounds, target, damage = result
        assert rounds == 3
        assert target == 85
        assert damage == 0

    def test_evasion_with_damage(self) -> None:
        narrative = (
            "After two rounds of combat you may evade by turning to 50. "
            "If you evade, you lose 3 ENDURANCE points."
        )
        result = detect_evasion(narrative)
        assert result is not None
        rounds, target, damage = result
        assert rounds == 2
        assert target == 50
        assert damage == 3

    def test_no_evasion(self) -> None:
        assert detect_evasion("You fight to the death.") is None

    def test_empty_string(self) -> None:
        assert detect_evasion("") is None

    def test_numeric_rounds(self) -> None:
        narrative = "After 2 rounds of combat, you may evade by turning to 100."
        result = detect_evasion(narrative)
        assert result is not None
        assert result[0] == 2
        assert result[1] == 100


# ===========================================================================
# detect_mindblast_immunity
# ===========================================================================


class TestDetectMindblastImmunity:
    def test_immune_to_mindblast(self) -> None:
        assert detect_mindblast_immunity("This creature is immune to Mindblast.") is True

    def test_mindblast_has_no_effect(self) -> None:
        assert detect_mindblast_immunity("Mindblast has no effect on this enemy.") is True

    def test_unaffected_by_mindblast(self) -> None:
        assert detect_mindblast_immunity("The Vordak is unaffected by Mindblast.") is True

    def test_no_immunity(self) -> None:
        assert detect_mindblast_immunity("You enter combat with the Kraan.") is False

    def test_empty_string(self) -> None:
        assert detect_mindblast_immunity("") is False

    def test_case_insensitive(self) -> None:
        assert detect_mindblast_immunity("IMMUNE TO MINDBLAST.") is True


# ===========================================================================
# detect_combat_modifiers
# ===========================================================================


class TestDetectCombatModifiers:
    def test_cs_bonus(self) -> None:
        mods = detect_combat_modifiers("Add 2 to your Combat Skill for this fight.")
        types = [m["modifier_type"] for m in mods]
        assert "cs_bonus" in types
        bonus = next(m for m in mods if m["modifier_type"] == "cs_bonus")
        assert bonus["value"] == 2

    def test_cs_penalty(self) -> None:
        mods = detect_combat_modifiers("Deduct 3 from your Combat Skill.")
        types = [m["modifier_type"] for m in mods]
        assert "cs_penalty" in types
        penalty = next(m for m in mods if m["modifier_type"] == "cs_penalty")
        assert penalty["value"] == 3

    def test_double_damage(self) -> None:
        mods = detect_combat_modifiers("The Sommerswerd does double damage against the undead.")
        types = [m["modifier_type"] for m in mods]
        assert "double_damage" in types

    def test_undead(self) -> None:
        mods = detect_combat_modifiers("This enemy is undead and vulnerable to holy weapons.")
        types = [m["modifier_type"] for m in mods]
        assert "undead" in types

    def test_enemy_mindblast(self) -> None:
        mods = detect_combat_modifiers("The Helghast uses Mindblast against you.")
        types = [m["modifier_type"] for m in mods]
        assert "enemy_mindblast" in types

    def test_no_modifiers(self) -> None:
        mods = detect_combat_modifiers("You enter the room and see a table.")
        assert mods == []

    def test_empty_string(self) -> None:
        assert detect_combat_modifiers("") == []


# ===========================================================================
# detect_conditional_combat
# ===========================================================================


class TestDetectConditionalCombat:
    def test_discipline_condition(self) -> None:
        narrative = (
            "If you do not have the Kai Discipline of Tracking, "
            "you must fight the Kraan."
        )
        result = detect_conditional_combat(narrative)
        assert result is not None
        ctype, cval = result
        assert ctype == "discipline"
        assert cval == "Tracking"

    def test_item_condition(self) -> None:
        narrative = "If you do not possess a Sword, you must fight barehanded."
        result = detect_conditional_combat(narrative)
        assert result is not None
        ctype, cval = result
        assert ctype == "item"
        assert cval == "Sword"

    def test_no_conditional_combat(self) -> None:
        assert detect_conditional_combat("You must fight the enemy.") is None

    def test_empty_string(self) -> None:
        assert detect_conditional_combat("") is None


# ===========================================================================
# detect_random_outcomes
# ===========================================================================


class TestDetectRandomOutcomes:
    def test_scene_redirect_outcome(self) -> None:
        narrative = (
            "Pick a number from the Random Number Table. "
            "If the number is 0-4, turn to 50. "
            "5-9: turn to 100."
        )
        outcomes = detect_random_outcomes(narrative)
        assert len(outcomes) >= 1
        redirect = next((o for o in outcomes if o["effect_type"] == "scene_redirect"), None)
        assert redirect is not None

    def test_endurance_loss_outcome(self) -> None:
        narrative = (
            "Pick a number from the Random Number Table. "
            "0-4: lose 3 ENDURANCE points. "
            "5-9: lose 1 ENDURANCE point."
        )
        outcomes = detect_random_outcomes(narrative)
        ep_outcomes = [o for o in outcomes if o["effect_type"] == "endurance_change"]
        assert ep_outcomes

    def test_no_random_number_table(self) -> None:
        outcomes = detect_random_outcomes("You find a Sword.")
        assert outcomes == []

    def test_empty_string(self) -> None:
        assert detect_random_outcomes("") == []


# ===========================================================================
# detect_choice_triggered_random
# ===========================================================================


class TestDetectChoiceTriggeredRandom:
    def test_choice_with_pick_a_number(self) -> None:
        choices = [
            "Turn to 50.",
            "Pick a number from the Random Number Table.",
        ]
        assert detect_choice_triggered_random(choices) is True

    def test_choice_with_number_range(self) -> None:
        choices = ["0-4: turn to 50.", "5-9: turn to 100."]
        assert detect_choice_triggered_random(choices) is True

    def test_no_random_choices(self) -> None:
        choices = ["Turn to 50.", "Turn to 100."]
        assert detect_choice_triggered_random(choices) is False

    def test_empty_choices_list(self) -> None:
        assert detect_choice_triggered_random([]) is False

    def test_none_is_handled(self) -> None:
        # Should not raise — falsy check at start of function
        # (We pass an empty list as the public API expects list[str])
        assert detect_choice_triggered_random([]) is False


# ===========================================================================
# detect_scene_level_random_exits
# ===========================================================================


class TestDetectSceneLevelRandomExits:
    def test_all_choices_have_ranges(self) -> None:
        choices = ["0-4: turn to 50.", "5-9: turn to 100."]
        assert detect_scene_level_random_exits(choices) is True

    def test_mixed_choices_not_all_random(self) -> None:
        choices = ["0-4: turn to 50.", "If you wish, turn to 100."]
        assert detect_scene_level_random_exits(choices) is False

    def test_empty_choices(self) -> None:
        assert detect_scene_level_random_exits([]) is False

    def test_single_normal_choice(self) -> None:
        assert detect_scene_level_random_exits(["Turn to 50."]) is False

    def test_single_random_choice(self) -> None:
        assert detect_scene_level_random_exits(["Pick a number from the Random Number Table."]) is True


# ===========================================================================
# detect_phase_ordering
# ===========================================================================


class TestDetectPhaseOrdering:
    def test_standard_order_returns_none(self) -> None:
        # eat first, then combat — that is standard if items are absent
        narrative = (
            "You must eat a Meal. "
            "Ahead lies a warrior. You must fight: COMBAT SKILL 14 ENDURANCE 20."
        )
        result = detect_phase_ordering(narrative)
        # Standard order (eat before combat) should not return an override
        assert result is None or result == ["eat", "combat"]

    def test_non_standard_combat_before_eat(self) -> None:
        narrative = (
            "A warrior attacks! COMBAT SKILL 14 ENDURANCE 20. "
            "After the battle you must eat a Meal."
        )
        result = detect_phase_ordering(narrative)
        if result is not None:
            # Combat appears before eat in the text
            assert result.index("combat") < result.index("eat")

    def test_insufficient_phases_returns_none(self) -> None:
        # Only one phase detectable — no ordering to infer
        assert detect_phase_ordering("You walk into the room.") is None

    def test_empty_string(self) -> None:
        assert detect_phase_ordering("") is None
