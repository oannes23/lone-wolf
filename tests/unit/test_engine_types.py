"""Basic construction tests for engine DTOs.

Verifies that all dataclasses can be instantiated with expected values and that
the MAX_REDIRECT_DEPTH sentinel is present with the correct value.
"""

from __future__ import annotations

from app.engine.types import (
    MAX_REDIRECT_DEPTH,
    CharacterState,
    ChoiceData,
    CombatContext,
    CombatEncounterData,
    CombatModifierData,
    ItemState,
    RandomOutcomeData,
    SceneContext,
    SceneItemData,
)


def _make_item(
    character_item_id: int = 1,
    item_name: str = "Sword",
    item_type: str = "weapon",
    is_equipped: bool = True,
    game_object_id: int | None = 10,
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
        disciplines=["mindblast", "animal_kinship"],
        weapon_skill_category="sword",
        items=items or [],
        version=1,
        current_run=1,
        death_count=0,
        rule_overrides=None,
    )


# ---------------------------------------------------------------------------
# MAX_REDIRECT_DEPTH
# ---------------------------------------------------------------------------


def test_max_redirect_depth_value() -> None:
    assert MAX_REDIRECT_DEPTH == 5


# ---------------------------------------------------------------------------
# ItemState
# ---------------------------------------------------------------------------


def test_item_state_construction() -> None:
    item = _make_item(properties={"endurance_bonus": 4})
    assert item.character_item_id == 1
    assert item.item_name == "Sword"
    assert item.item_type == "weapon"
    assert item.is_equipped is True
    assert item.game_object_id == 10
    assert item.properties == {"endurance_bonus": 4}


def test_item_state_no_game_object() -> None:
    item = _make_item(game_object_id=None)
    assert item.game_object_id is None


# ---------------------------------------------------------------------------
# CharacterState
# ---------------------------------------------------------------------------


def test_character_state_construction() -> None:
    char = _make_character()
    assert char.character_id == 1
    assert char.combat_skill_base == 15
    assert char.endurance_current == 25
    assert char.gold == 10
    assert char.meals == 3
    assert char.is_alive is True
    assert char.disciplines == ["mindblast", "animal_kinship"]
    assert char.weapon_skill_category == "sword"
    assert char.items == []
    assert char.version == 1
    assert char.current_run == 1
    assert char.death_count == 0
    assert char.rule_overrides is None


def test_character_state_with_items() -> None:
    items = [_make_item(1, "Axe", "weapon"), _make_item(2, "Laumspur", "backpack")]
    char = _make_character(items=items)
    assert len(char.items) == 2


# ---------------------------------------------------------------------------
# ChoiceData
# ---------------------------------------------------------------------------


def test_choice_data_construction() -> None:
    choice = ChoiceData(
        choice_id=5,
        target_scene_id=42,
        target_scene_number=42,
        display_text="Turn to 42",
        condition_type=None,
        condition_value=None,
        has_random_outcomes=False,
    )
    assert choice.choice_id == 5
    assert choice.target_scene_number == 42
    assert choice.has_random_outcomes is False


def test_choice_data_with_random_outcomes() -> None:
    choice = ChoiceData(
        choice_id=6,
        target_scene_id=None,
        target_scene_number=0,
        display_text="Pick a number",
        condition_type="discipline",
        condition_value="mindblast",
        has_random_outcomes=True,
    )
    assert choice.has_random_outcomes is True
    assert choice.condition_type == "discipline"


# ---------------------------------------------------------------------------
# CombatModifierData
# ---------------------------------------------------------------------------


def test_combat_modifier_data_construction() -> None:
    mod = CombatModifierData(
        modifier_type="cs_bonus",
        modifier_value="2",
        condition=None,
    )
    assert mod.modifier_type == "cs_bonus"
    assert mod.modifier_value == "2"
    assert mod.condition is None


# ---------------------------------------------------------------------------
# CombatEncounterData
# ---------------------------------------------------------------------------


def test_combat_encounter_data_construction() -> None:
    enc = CombatEncounterData(
        encounter_id=1,
        enemy_name="Gourgaz",
        enemy_cs=20,
        enemy_end=30,
        ordinal=1,
        mindblast_immune=True,
        evasion_after_rounds=None,
        evasion_target=None,
        evasion_damage=0,
        condition_type=None,
        condition_value=None,
    )
    assert enc.enemy_name == "Gourgaz"
    assert enc.mindblast_immune is True
    assert enc.modifiers == []


def test_combat_encounter_data_with_modifiers() -> None:
    mods = [CombatModifierData("undead", None, None)]
    enc = CombatEncounterData(
        encounter_id=2,
        enemy_name="Skeleton",
        enemy_cs=12,
        enemy_end=16,
        ordinal=1,
        mindblast_immune=False,
        evasion_after_rounds=3,
        evasion_target=100,
        evasion_damage=0,
        condition_type=None,
        condition_value=None,
        modifiers=mods,
    )
    assert len(enc.modifiers) == 1
    assert enc.modifiers[0].modifier_type == "undead"


# ---------------------------------------------------------------------------
# SceneItemData
# ---------------------------------------------------------------------------


def test_scene_item_data_construction() -> None:
    si = SceneItemData(
        scene_item_id=1,
        item_name="Gold",
        item_type="gold",
        quantity=5,
        action="gain",
        is_mandatory=True,
        game_object_id=None,
        properties={},
    )
    assert si.item_type == "gold"
    assert si.action == "gain"
    assert si.is_mandatory is True


# ---------------------------------------------------------------------------
# RandomOutcomeData
# ---------------------------------------------------------------------------


def test_random_outcome_data_construction() -> None:
    ro = RandomOutcomeData(
        outcome_id=1,
        roll_group=1,
        range_min=0,
        range_max=4,
        effect_type="endurance_change",
        effect_value="-3",
        narrative_text="You are hit for 3 Endurance points.",
    )
    assert ro.range_min == 0
    assert ro.range_max == 4
    assert ro.effect_type == "endurance_change"


# ---------------------------------------------------------------------------
# SceneContext
# ---------------------------------------------------------------------------


def test_scene_context_construction() -> None:
    sc = SceneContext(
        scene_id=1,
        book_id=1,
        scene_number=1,
        is_death=False,
        is_victory=False,
        must_eat=False,
        loses_backpack=False,
        phase_sequence_override=None,
        choices=[],
        combat_encounters=[],
        scene_items=[],
        random_outcomes=[],
    )
    assert sc.scene_number == 1
    assert sc.is_death is False
    assert sc.choices == []


# ---------------------------------------------------------------------------
# CombatContext
# ---------------------------------------------------------------------------


def test_combat_context_construction() -> None:
    ctx = CombatContext(
        encounter_id=1,
        enemy_name="Vordak",
        enemy_cs=18,
        enemy_end=22,
        enemy_end_remaining=22,
        mindblast_immune=True,
        evasion_after_rounds=None,
        evasion_target=None,
        evasion_damage=0,
        modifiers=[],
        rounds_fought=0,
    )
    assert ctx.enemy_name == "Vordak"
    assert ctx.enemy_end_remaining == 22
    assert ctx.rounds_fought == 0
