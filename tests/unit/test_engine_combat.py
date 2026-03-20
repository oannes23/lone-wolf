"""Tests for app/engine/combat.py — combat resolution engine.

Covers all acceptance criteria from Story 3.2:
- effective_combat_skill with every modifier path
- ratio_to_bracket
- CRT lookup including instant-kill rows
- resolve_combat_round (normal, instant kill, psi-surge)
- evade_combat (success, too-early, death during evasion)
- should_fight (conditional discipline/item bypass)
- apply_special_weapon_effects (Sommerswerd, combat_bonus_vs_special)
"""

from __future__ import annotations

import pytest

from app.engine.combat import (
    EvadeResult,
    RoundResult,
    apply_special_weapon_effects,
    effective_combat_skill,
    evade_combat,
    lookup_crt,
    ratio_to_bracket,
    resolve_combat_round,
    should_fight,
)
from app.engine.types import (
    CharacterState,
    CombatContext,
    CombatEncounterData,
    CombatModifierData,
    ItemState,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_item(
    *,
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


def _make_state(
    *,
    combat_skill_base: int = 15,
    endurance_current: int = 25,
    endurance_max: int = 25,
    disciplines: list[str] | None = None,
    weapon_skill_category: str | None = None,
    items: list[ItemState] | None = None,
) -> CharacterState:
    return CharacterState(
        character_id=1,
        combat_skill_base=combat_skill_base,
        endurance_base=25,
        endurance_max=endurance_max,
        endurance_current=endurance_current,
        gold=10,
        meals=3,
        is_alive=True,
        disciplines=disciplines or [],
        weapon_skill_category=weapon_skill_category,
        items=items or [],
        version=1,
        current_run=1,
        death_count=0,
        rule_overrides=None,
    )


def _make_encounter(
    *,
    enemy_cs: int = 15,
    enemy_end: int = 20,
    enemy_end_remaining: int = 20,
    mindblast_immune: bool = False,
    evasion_after_rounds: int | None = None,
    evasion_target: int | None = None,
    evasion_damage: int = 0,
    modifiers: list[CombatModifierData] | None = None,
    rounds_fought: int = 0,
) -> CombatContext:
    return CombatContext(
        encounter_id=1,
        enemy_name="Gourgaz",
        enemy_cs=enemy_cs,
        enemy_end=enemy_end,
        enemy_end_remaining=enemy_end_remaining,
        mindblast_immune=mindblast_immune,
        evasion_after_rounds=evasion_after_rounds,
        evasion_target=evasion_target,
        evasion_damage=evasion_damage,
        modifiers=modifiers or [],
        rounds_fought=rounds_fought,
    )


def _make_encounter_data(
    *,
    condition_type: str | None = None,
    condition_value: str | None = None,
    enemy_cs: int = 15,
    enemy_end: int = 20,
) -> CombatEncounterData:
    return CombatEncounterData(
        encounter_id=1,
        enemy_name="Gourgaz",
        enemy_cs=enemy_cs,
        enemy_end=enemy_end,
        ordinal=1,
        mindblast_immune=False,
        evasion_after_rounds=None,
        evasion_target=None,
        evasion_damage=0,
        condition_type=condition_type,
        condition_value=condition_value,
        modifiers=[],
    )


# Minimal CRT for testing: random numbers 0–9, ratio bands -9 to +9
def _make_crt_rows() -> list[dict]:
    """Build a minimal deterministic CRT for tests.

    Columns: random_number, combat_ratio_min, combat_ratio_max, enemy_loss, hero_loss
    All rows here use ratio_min=-99, ratio_max=99 for simplicity so we only
    need to vary the random_number to control outcomes.
    """
    return [
        # rn=0: hero takes heavy damage, enemy light
        {"random_number": 0, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": 2, "hero_loss": 6},
        # rn=1: balanced
        {"random_number": 1, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": 3, "hero_loss": 4},
        # rn=2: hero advantage
        {"random_number": 2, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": 5, "hero_loss": 3},
        # rn=3: hero kills enemy instantly
        {"random_number": 3, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": None, "hero_loss": 3},
        # rn=4: hero is killed instantly
        {"random_number": 4, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": 4, "hero_loss": None},
        # rn=5: both killed (rare)
        {"random_number": 5, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": None, "hero_loss": None},
        # rn=6–9: normal outcomes for ratio-bracketed lookups
        {"random_number": 6, "combat_ratio_min": -99, "combat_ratio_max": 0,
         "enemy_loss": 1, "hero_loss": 5},
        {"random_number": 6, "combat_ratio_min": 1, "combat_ratio_max": 99,
         "enemy_loss": 4, "hero_loss": 2},
        {"random_number": 7, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": 3, "hero_loss": 3},
        {"random_number": 8, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": 4, "hero_loss": 2},
        {"random_number": 9, "combat_ratio_min": -99, "combat_ratio_max": 99,
         "enemy_loss": 6, "hero_loss": 0},
    ]


# ---------------------------------------------------------------------------
# effective_combat_skill tests
# ---------------------------------------------------------------------------


class TestEffectiveCombatSkill:
    def test_base_with_equipped_weapon_no_bonuses(self) -> None:
        """Armed hero with no special bonuses returns base CS."""
        state = _make_state(combat_skill_base=15, items=[_make_item()])
        encounter = _make_encounter()
        assert effective_combat_skill(state, encounter) == 15

    def test_unarmed_penalty(self) -> None:
        """No equipped weapon incurs -4 penalty."""
        state = _make_state(combat_skill_base=15, items=[])
        encounter = _make_encounter()
        assert effective_combat_skill(state, encounter) == 11

    def test_unarmed_even_with_unequipped_weapon(self) -> None:
        """Having a weapon in inventory that is NOT equipped still triggers the penalty."""
        state = _make_state(
            combat_skill_base=15,
            items=[_make_item(is_equipped=False)],
        )
        encounter = _make_encounter()
        assert effective_combat_skill(state, encounter) == 11

    def test_mindblast_bonus(self) -> None:
        """Mindblast discipline adds +2 when enemy is not immune."""
        state = _make_state(
            combat_skill_base=15,
            disciplines=["Mindblast"],
            items=[_make_item()],
        )
        encounter = _make_encounter(mindblast_immune=False)
        assert effective_combat_skill(state, encounter) == 17

    def test_mindblast_blocked_by_immunity(self) -> None:
        """Mindblast has no effect against mindblast-immune enemies."""
        state = _make_state(
            combat_skill_base=15,
            disciplines=["Mindblast"],
            items=[_make_item()],
        )
        encounter = _make_encounter(mindblast_immune=True)
        assert effective_combat_skill(state, encounter) == 15

    def test_enemy_mindblast_penalty(self) -> None:
        """Enemy Mindblast modifier reduces hero CS by 2."""
        state = _make_state(combat_skill_base=15, items=[_make_item()])
        modifier = CombatModifierData(
            modifier_type="enemy_mindblast", modifier_value=None, condition=None
        )
        encounter = _make_encounter(modifiers=[modifier])
        assert effective_combat_skill(state, encounter) == 13

    def test_mindshield_negates_enemy_mindblast(self) -> None:
        """Mindshield discipline prevents the -2 from enemy_mindblast."""
        state = _make_state(
            combat_skill_base=15,
            disciplines=["Mindshield"],
            items=[_make_item()],
        )
        modifier = CombatModifierData(
            modifier_type="enemy_mindblast", modifier_value=None, condition=None
        )
        encounter = _make_encounter(modifiers=[modifier])
        assert effective_combat_skill(state, encounter) == 15

    def test_weaponskill_bonus(self) -> None:
        """Weaponskill adds +2 when equipped weapon category matches chosen category."""
        sword = _make_item(properties={"category": "sword", "combat_bonus": 0})
        state = _make_state(
            combat_skill_base=15,
            weapon_skill_category="sword",
            disciplines=["Weaponskill"],
            items=[sword],
        )
        encounter = _make_encounter()
        assert effective_combat_skill(state, encounter) == 17

    def test_weaponskill_no_bonus_wrong_category(self) -> None:
        """Weaponskill does not apply when categories differ."""
        sword = _make_item(properties={"category": "sword", "combat_bonus": 0})
        state = _make_state(
            combat_skill_base=15,
            weapon_skill_category="axe",
            items=[sword],
        )
        encounter = _make_encounter()
        assert effective_combat_skill(state, encounter) == 15

    def test_equipped_weapon_combat_bonus(self) -> None:
        """Equipped weapon's combat_bonus is added to CS."""
        sword = _make_item(properties={"combat_bonus": 3})
        state = _make_state(combat_skill_base=15, items=[sword])
        encounter = _make_encounter()
        assert effective_combat_skill(state, encounter) == 18

    def test_special_item_combat_bonus(self) -> None:
        """Special items contribute their combat_bonus regardless of equipped state."""
        weapon = _make_item(character_item_id=1, item_type="weapon", properties={"combat_bonus": 0})
        special = _make_item(
            character_item_id=2,
            item_name="Silver Helm",
            item_type="special",
            is_equipped=False,
            properties={"combat_bonus": 2},
        )
        state = _make_state(combat_skill_base=15, items=[weapon, special])
        encounter = _make_encounter()
        assert effective_combat_skill(state, encounter) == 17

    def test_encounter_cs_bonus_modifier(self) -> None:
        """cs_bonus encounter modifier adds to CS."""
        state = _make_state(combat_skill_base=15, items=[_make_item()])
        modifier = CombatModifierData(
            modifier_type="cs_bonus", modifier_value="3", condition=None
        )
        encounter = _make_encounter(modifiers=[modifier])
        assert effective_combat_skill(state, encounter) == 18

    def test_encounter_cs_penalty_modifier(self) -> None:
        """cs_penalty encounter modifier subtracts from CS."""
        state = _make_state(combat_skill_base=15, items=[_make_item()])
        modifier = CombatModifierData(
            modifier_type="cs_penalty", modifier_value="2", condition=None
        )
        encounter = _make_encounter(modifiers=[modifier])
        assert effective_combat_skill(state, encounter) == 13

    def test_combat_bonus_vs_special_replaces_base_in_cs(self) -> None:
        """combat_bonus_vs_special replaces base combat_bonus in CS calculation."""
        # Base bonus +2, vs_special bonus +5 when fighting undead
        sword = _make_item(properties={
            "combat_bonus": 2,
            "combat_bonus_vs_special": 5,
            "special_vs": "undead",
        })
        undead_mod = CombatModifierData(
            modifier_type="undead", modifier_value=None, condition=None
        )
        state = _make_state(combat_skill_base=15, items=[sword])
        encounter = _make_encounter(modifiers=[undead_mod])
        # 15 + 5 (vs_special replaces base 2) = 20
        assert effective_combat_skill(state, encounter) == 20

    def test_combat_bonus_vs_special_no_match_uses_base(self) -> None:
        """Without matching modifier, base combat_bonus is used."""
        sword = _make_item(properties={
            "combat_bonus": 2,
            "combat_bonus_vs_special": 5,
            "special_vs": "undead",
        })
        state = _make_state(combat_skill_base=15, items=[sword])
        encounter = _make_encounter()  # no undead modifier
        # 15 + 2 (base bonus, no match) = 17
        assert effective_combat_skill(state, encounter) == 17

    def test_combined_all_bonuses(self) -> None:
        """All positive modifiers stack correctly."""
        # Base 15 + weapon +2 + weaponskill +2 + Mindblast +2 + special +1 + cs_bonus +1 = 23
        sword = _make_item(properties={"category": "sword", "combat_bonus": 2})
        special = _make_item(
            character_item_id=2,
            item_name="Gem",
            item_type="special",
            is_equipped=False,
            properties={"combat_bonus": 1},
        )
        cs_mod = CombatModifierData(modifier_type="cs_bonus", modifier_value="1", condition=None)
        state = _make_state(
            combat_skill_base=15,
            disciplines=["Mindblast", "Weaponskill"],
            weapon_skill_category="sword",
            items=[sword, special],
        )
        encounter = _make_encounter(mindblast_immune=False, modifiers=[cs_mod])
        assert effective_combat_skill(state, encounter) == 23


# ---------------------------------------------------------------------------
# ratio_to_bracket tests
# ---------------------------------------------------------------------------


class TestRatioToBracket:
    def test_positive_ratio(self) -> None:
        assert ratio_to_bracket(18, 15) == 3

    def test_negative_ratio(self) -> None:
        assert ratio_to_bracket(12, 15) == -3

    def test_zero_ratio(self) -> None:
        assert ratio_to_bracket(15, 15) == 0

    def test_large_positive(self) -> None:
        assert ratio_to_bracket(25, 10) == 15

    def test_large_negative(self) -> None:
        assert ratio_to_bracket(10, 25) == -15


# ---------------------------------------------------------------------------
# lookup_crt tests
# ---------------------------------------------------------------------------


class TestLookupCRT:
    def setup_method(self) -> None:
        self.rows = _make_crt_rows()

    def test_normal_lookup(self) -> None:
        enemy_loss, hero_loss = lookup_crt(self.rows, combat_ratio=0, random_number=2)
        assert enemy_loss == 5
        assert hero_loss == 3

    def test_enemy_instant_kill(self) -> None:
        """Row with enemy_loss=None means enemy is instantly killed."""
        enemy_loss, hero_loss = lookup_crt(self.rows, combat_ratio=0, random_number=3)
        assert enemy_loss is None
        assert hero_loss == 3

    def test_hero_instant_kill(self) -> None:
        """Row with hero_loss=None means hero is instantly killed."""
        enemy_loss, hero_loss = lookup_crt(self.rows, combat_ratio=0, random_number=4)
        assert enemy_loss == 4
        assert hero_loss is None

    def test_both_instant_kill(self) -> None:
        enemy_loss, hero_loss = lookup_crt(self.rows, combat_ratio=0, random_number=5)
        assert enemy_loss is None
        assert hero_loss is None

    def test_ratio_bracket_negative(self) -> None:
        """rn=6 with ratio <= 0 returns different result than ratio > 0."""
        el_low, hl_low = lookup_crt(self.rows, combat_ratio=-2, random_number=6)
        el_high, hl_high = lookup_crt(self.rows, combat_ratio=2, random_number=6)
        assert (el_low, hl_low) == (1, 5)
        assert (el_high, hl_high) == (4, 2)

    def test_ratio_bracket_positive(self) -> None:
        el, hl = lookup_crt(self.rows, combat_ratio=5, random_number=6)
        assert (el, hl) == (4, 2)

    def test_no_matching_row_raises(self) -> None:
        with pytest.raises(ValueError, match="No CRT row found"):
            lookup_crt(self.rows, combat_ratio=0, random_number=99)


# ---------------------------------------------------------------------------
# resolve_combat_round tests
# ---------------------------------------------------------------------------


class TestResolveCombatRound:
    def setup_method(self) -> None:
        self.crt = _make_crt_rows()

    def test_normal_round(self) -> None:
        state = _make_state(endurance_current=25, items=[_make_item()])
        encounter = _make_encounter(enemy_end_remaining=20)
        result = resolve_combat_round(state, encounter, self.crt, random_number=2)
        # rn=2 → enemy_loss=5, hero_loss=3
        assert result.hero_damage == 3
        assert result.enemy_damage == 5
        assert result.hero_end_remaining == 22
        assert result.enemy_end_remaining == 15
        assert result.hero_dead is False
        assert result.enemy_dead is False
        assert result.psi_surge_used is False

    def test_hero_instant_kill(self) -> None:
        state = _make_state(endurance_current=25, items=[_make_item()])
        encounter = _make_encounter(enemy_end_remaining=20)
        result = resolve_combat_round(state, encounter, self.crt, random_number=4)
        # rn=4 → hero_loss=None
        assert result.hero_damage is None
        assert result.hero_dead is True
        assert result.hero_end_remaining == 0

    def test_enemy_instant_kill(self) -> None:
        state = _make_state(endurance_current=25, items=[_make_item()])
        encounter = _make_encounter(enemy_end_remaining=20)
        result = resolve_combat_round(state, encounter, self.crt, random_number=3)
        # rn=3 → enemy_loss=None
        assert result.enemy_damage is None
        assert result.enemy_dead is True
        assert result.enemy_end_remaining == 0

    def test_enemy_reduced_to_zero_marks_dead(self) -> None:
        state = _make_state(endurance_current=25, items=[_make_item()])
        encounter = _make_encounter(enemy_end_remaining=3)
        result = resolve_combat_round(state, encounter, self.crt, random_number=2)
        # rn=2 → enemy_loss=5, enemy only has 3 end
        assert result.enemy_end_remaining == 0
        assert result.enemy_dead is True

    def test_psi_surge_adds_cs_bonus_and_costs_end(self) -> None:
        """Psi-surge: hero gains +4 CS but pays 2 END (added to hero_loss after CRT)."""
        state = _make_state(
            combat_skill_base=15,
            endurance_current=25,
            disciplines=["Psi-surge"],
            items=[_make_item()],
        )
        encounter = _make_encounter(enemy_cs=15, enemy_end_remaining=20)

        result_normal = resolve_combat_round(state, encounter, self.crt, random_number=7)
        result_surge = resolve_combat_round(
            state, encounter, self.crt, random_number=7, use_psi_surge=True
        )

        # Surge result should have 2 fewer end from the cost (before combat damage)
        # rn=7 → enemy_loss=3, hero_loss=3
        assert result_surge.psi_surge_used is True
        # Hero pays 2 for surge + 3 for combat = 5 total
        assert result_surge.hero_end_remaining == 25 - 2 - 3

    def test_psi_surge_does_not_affect_non_surge_result(self) -> None:
        state = _make_state(endurance_current=25, items=[_make_item()])
        encounter = _make_encounter(enemy_end_remaining=20)
        result = resolve_combat_round(state, encounter, self.crt, random_number=7)
        assert result.psi_surge_used is False
        # rn=7 → hero_loss=3
        assert result.hero_end_remaining == 22


# ---------------------------------------------------------------------------
# evade_combat tests
# ---------------------------------------------------------------------------


class TestEvadeCombat:
    def test_successful_evasion(self) -> None:
        state = _make_state(endurance_current=20)
        encounter = _make_encounter(
            evasion_after_rounds=2,
            evasion_target=150,
            evasion_damage=2,
            rounds_fought=2,
        )
        result = evade_combat(state, encounter)
        assert result.success is True
        assert result.hero_dead is False
        assert result.hero_end_remaining == 18
        assert result.target_scene_id == 150
        assert result.evasion_damage == 2

    def test_evasion_too_early(self) -> None:
        """Cannot evade before the required number of rounds."""
        state = _make_state(endurance_current=20)
        encounter = _make_encounter(
            evasion_after_rounds=3,
            evasion_target=150,
            evasion_damage=2,
            rounds_fought=1,
        )
        result = evade_combat(state, encounter)
        assert result.success is False
        assert result.evasion_damage == 0

    def test_evasion_damage_kills_hero(self) -> None:
        """If evasion damage kills the hero, the evasion fails."""
        state = _make_state(endurance_current=2)
        encounter = _make_encounter(
            evasion_after_rounds=1,
            evasion_target=200,
            evasion_damage=5,  # more than remaining endurance
            rounds_fought=1,
        )
        result = evade_combat(state, encounter)
        assert result.success is False
        assert result.hero_dead is True
        assert result.hero_end_remaining == 0
        assert result.target_scene_id is None

    def test_evasion_no_evasion_target(self) -> None:
        """Evasion with None evasion_after_rounds is denied."""
        state = _make_state(endurance_current=20)
        encounter = _make_encounter(
            evasion_after_rounds=None,
            evasion_target=None,
            evasion_damage=0,
            rounds_fought=5,
        )
        result = evade_combat(state, encounter)
        assert result.success is False

    def test_evasion_zero_damage(self) -> None:
        """Evasion with zero damage still succeeds."""
        state = _make_state(endurance_current=15)
        encounter = _make_encounter(
            evasion_after_rounds=0,
            evasion_target=100,
            evasion_damage=0,
            rounds_fought=0,
        )
        result = evade_combat(state, encounter)
        assert result.success is True
        assert result.hero_end_remaining == 15


# ---------------------------------------------------------------------------
# should_fight tests
# ---------------------------------------------------------------------------


class TestShouldFight:
    def test_no_condition_always_fight(self) -> None:
        state = _make_state()
        encounter = _make_encounter_data(condition_type=None, condition_value=None)
        assert should_fight(state, encounter) is True

    def test_discipline_condition_hero_has_it(self) -> None:
        """If hero has the required discipline, combat is skipped."""
        state = _make_state(disciplines=["Sixth Sense"])
        encounter = _make_encounter_data(
            condition_type="discipline", condition_value="Sixth Sense"
        )
        assert should_fight(state, encounter) is False

    def test_discipline_condition_hero_lacks_it(self) -> None:
        """If hero lacks the required discipline, combat must happen."""
        state = _make_state(disciplines=["Mindblast"])
        encounter = _make_encounter_data(
            condition_type="discipline", condition_value="Sixth Sense"
        )
        assert should_fight(state, encounter) is True

    def test_item_condition_hero_has_it(self) -> None:
        """If hero carries the required item, combat is skipped."""
        torch = _make_item(item_name="Torch", item_type="backpack")
        state = _make_state(items=[torch])
        encounter = _make_encounter_data(condition_type="item", condition_value="Torch")
        assert should_fight(state, encounter) is False

    def test_item_condition_hero_lacks_it(self) -> None:
        """If hero lacks the required item, combat must happen."""
        state = _make_state(items=[])
        encounter = _make_encounter_data(condition_type="item", condition_value="Torch")
        assert should_fight(state, encounter) is True

    def test_unknown_condition_type_must_fight(self) -> None:
        """Unknown condition types default to must fight."""
        state = _make_state()
        encounter = _make_encounter_data(
            condition_type="unknown_type", condition_value="something"
        )
        assert should_fight(state, encounter) is True


# ---------------------------------------------------------------------------
# apply_special_weapon_effects tests
# ---------------------------------------------------------------------------


class TestApplySpecialWeaponEffects:
    def test_no_special_effects_returns_damage_unchanged(self) -> None:
        result = apply_special_weapon_effects(5, {}, [])
        assert result == 5

    def test_instant_kill_none_unchanged(self) -> None:
        """None (instant kill) passes through all effect logic unchanged."""
        result = apply_special_weapon_effects(
            None,
            {"damage_multiplier": 2, "special_vs": "undead"},
            [CombatModifierData(modifier_type="undead", modifier_value=None, condition=None)],
        )
        assert result is None

    def test_sommerswerd_doubles_damage_vs_undead(self) -> None:
        """Sommerswerd damage_multiplier=2 doubles enemy_damage when special_vs matches."""
        props = {"damage_multiplier": 2, "special_vs": "undead", "combat_bonus": 4}
        undead_mod = CombatModifierData(
            modifier_type="undead", modifier_value=None, condition=None
        )
        result = apply_special_weapon_effects(5, props, [undead_mod])
        assert result == 10

    def test_sommerswerd_no_effect_without_undead_modifier(self) -> None:
        """Sommerswerd damage_multiplier does not apply without matching modifier."""
        props = {"damage_multiplier": 2, "special_vs": "undead", "combat_bonus": 4}
        result = apply_special_weapon_effects(5, props, [])
        assert result == 5

    def test_damage_multiplier_requires_special_vs(self) -> None:
        """damage_multiplier without special_vs does not apply."""
        props = {"damage_multiplier": 2, "combat_bonus": 4}
        undead_mod = CombatModifierData(
            modifier_type="undead", modifier_value=None, condition=None
        )
        result = apply_special_weapon_effects(5, props, [undead_mod])
        assert result == 5

    def test_combat_bonus_vs_special_now_handled_in_effective_cs(self) -> None:
        """combat_bonus_vs_special replacement is handled in effective_combat_skill, not here."""
        # apply_special_weapon_effects no longer handles combat_bonus_vs_special
        # (it was moved to _get_weapon_cs_bonus in effective_combat_skill)
        props = {
            "combat_bonus": 2,
            "combat_bonus_vs_special": 4,
            "special_vs": "undead",
        }
        undead_mod = CombatModifierData(
            modifier_type="undead", modifier_value=None, condition=None
        )
        # No damage adjustment for bonus — only damage_multiplier applies here
        result = apply_special_weapon_effects(5, props, [undead_mod])
        assert result == 5  # no multiplier, so unchanged

    def test_combat_bonus_vs_special_no_matching_modifier(self) -> None:
        """combat_bonus_vs_special is not applied when encounter lacks the matching modifier."""
        props = {
            "combat_bonus": 2,
            "combat_bonus_vs_special": 4,
            "special_vs": "undead",
        }
        result = apply_special_weapon_effects(5, props, [])
        assert result == 5

    def test_sommerswerd_multiplier_only_in_apply_special(self) -> None:
        """apply_special_weapon_effects only handles damage_multiplier, not CS bonus replacement."""
        props = {
            "damage_multiplier": 2,
            "combat_bonus": 2,
            "combat_bonus_vs_special": 4,
            "special_vs": "undead",
        }
        undead_mod = CombatModifierData(
            modifier_type="undead", modifier_value=None, condition=None
        )
        # Only multiplier applies here: 5 * 2 = 10
        # combat_bonus_vs_special is handled in effective_combat_skill via _get_weapon_cs_bonus
        result = apply_special_weapon_effects(5, props, [undead_mod])
        assert result == 10
