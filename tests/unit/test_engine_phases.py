"""Tests for app/engine/phases.py — phase sequence and automatic phase execution.

Covers all acceptance criteria from Story 3.4:
- compute_phase_sequence: basic scene with eat + combat + choices
- compute_phase_sequence: death scene returns empty
- compute_phase_sequence: phase_sequence_override replaces computed
- compute_phase_sequence: multi-enemy (2 encounters → 2 combat entries)
- compute_phase_sequence: over-capacity injects items phase
- compute_phase_sequence: conditional combat skipped
- compute_phase_sequence: scene-level random exits get random phase
- run_automatic_phase: eat with meals available
- run_automatic_phase: eat with Hunting discipline
- run_automatic_phase: eat without meals, no Hunting (-3 END)
- run_automatic_phase: death mid-eat (END too low)
- run_automatic_phase: heal after no combat (+1 END)
- run_automatic_phase: heal suppressed after combat
- run_automatic_phase: backpack_loss clears backpack items and meals
- run_automatic_phase: item_loss removes matching item
- run_automatic_phase: item_loss skip (item not found)
"""

from __future__ import annotations

from app.engine.phases import (
    Phase,
    compute_phase_sequence,
    run_automatic_phase,
    should_heal,
)
from app.engine.types import (
    CharacterState,
    ChoiceData,
    CombatEncounterData,
    ItemState,
    RandomOutcomeData,
    SceneContext,
    SceneItemData,
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
    endurance_current: int = 25,
    endurance_max: int = 25,
    endurance_base: int = 25,
    gold: int = 10,
    meals: int = 3,
    is_alive: bool = True,
    disciplines: list[str] | None = None,
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
        is_alive=is_alive,
        disciplines=disciplines or [],
        weapon_skill_category=None,
        items=items or [],
        version=1,
        current_run=1,
        death_count=0,
        rule_overrides=None,
    )


def _make_encounter(
    *,
    encounter_id: int = 1,
    ordinal: int = 1,
    enemy_cs: int = 15,
    enemy_end: int = 20,
    condition_type: str | None = None,
    condition_value: str | None = None,
) -> CombatEncounterData:
    return CombatEncounterData(
        encounter_id=encounter_id,
        enemy_name="Gourgaz",
        enemy_cs=enemy_cs,
        enemy_end=enemy_end,
        ordinal=ordinal,
        mindblast_immune=False,
        evasion_after_rounds=None,
        evasion_target=None,
        evasion_damage=0,
        condition_type=condition_type,
        condition_value=condition_value,
        modifiers=[],
    )


def _make_scene_item(
    *,
    scene_item_id: int = 1,
    item_name: str = "Laumspur",
    item_type: str = "backpack",
    quantity: int = 1,
    action: str = "gain",
    is_mandatory: bool = False,
) -> SceneItemData:
    return SceneItemData(
        scene_item_id=scene_item_id,
        item_name=item_name,
        item_type=item_type,
        quantity=quantity,
        action=action,
        is_mandatory=is_mandatory,
        game_object_id=None,
        properties={},
    )


def _make_choice(
    *,
    choice_id: int = 1,
    target_scene_id: int | None = 100,
    target_scene_number: int = 100,
    display_text: str = "Go north.",
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


def _make_random_outcome(
    *,
    outcome_id: int = 1,
    roll_group: int = 1,
    range_min: int = 0,
    range_max: int = 9,
    effect_type: str = "endurance_change",
    effect_value: str = "-3",
) -> RandomOutcomeData:
    return RandomOutcomeData(
        outcome_id=outcome_id,
        roll_group=roll_group,
        range_min=range_min,
        range_max=range_max,
        effect_type=effect_type,
        effect_value=effect_value,
        narrative_text=None,
    )


def _make_scene(
    *,
    scene_id: int = 1,
    is_death: bool = False,
    is_victory: bool = False,
    must_eat: bool = False,
    loses_backpack: bool = False,
    phase_sequence_override: list[dict] | None = None,
    choices: list[ChoiceData] | None = None,
    combat_encounters: list[CombatEncounterData] | None = None,
    scene_items: list[SceneItemData] | None = None,
    random_outcomes: list[RandomOutcomeData] | None = None,
) -> SceneContext:
    return SceneContext(
        scene_id=scene_id,
        book_id=1,
        scene_number=scene_id,
        is_death=is_death,
        is_victory=is_victory,
        must_eat=must_eat,
        loses_backpack=loses_backpack,
        phase_sequence_override=phase_sequence_override,
        choices=choices or [_make_choice()],
        combat_encounters=combat_encounters or [],
        scene_items=scene_items or [],
        random_outcomes=random_outcomes or [],
    )


# ---------------------------------------------------------------------------
# compute_phase_sequence tests
# ---------------------------------------------------------------------------


class TestComputePhaseSequence:
    def test_basic_scene_eat_combat_choices(self) -> None:
        """Scene with must_eat + 1 combat encounter → eat, combat, heal, choices."""
        scene = _make_scene(
            must_eat=True,
            combat_encounters=[_make_encounter()],
        )
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        phase_types = [p.type for p in phases]
        assert "eat" in phase_types
        assert "combat" in phase_types
        assert "heal" in phase_types
        assert "choices" in phase_types
        # Order: eat before combat, combat before heal, heal before choices
        assert phase_types.index("eat") < phase_types.index("combat")
        assert phase_types.index("combat") < phase_types.index("heal")
        assert phase_types.index("heal") < phase_types.index("choices")

    def test_death_scene_returns_empty(self) -> None:
        """Death scenes bypass all phases — return empty list."""
        scene = _make_scene(is_death=True, must_eat=True, combat_encounters=[_make_encounter()])
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert phases == []

    def test_phase_sequence_override_replaces_computed(self) -> None:
        """When phase_sequence_override is set, use it verbatim."""
        override = [
            {"type": "eat"},
            {"type": "choices"},
        ]
        scene = _make_scene(
            must_eat=True,
            phase_sequence_override=override,
            combat_encounters=[_make_encounter()],
        )
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert len(phases) == 2
        assert phases[0].type == "eat"
        assert phases[1].type == "choices"

    def test_phase_sequence_override_with_encounter_id(self) -> None:
        """Override entries forward encounter_id to the Phase object."""
        override = [
            {"type": "combat", "encounter_id": 42},
            {"type": "choices"},
        ]
        scene = _make_scene(phase_sequence_override=override)
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert phases[0].type == "combat"
        assert phases[0].encounter_id == 42

    def test_multi_enemy_two_encounters_two_combat_entries(self) -> None:
        """Two combat encounters → two separate combat phase entries."""
        encounters = [
            _make_encounter(encounter_id=1, ordinal=1),
            _make_encounter(encounter_id=2, ordinal=2),
        ]
        scene = _make_scene(combat_encounters=encounters)
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        combat_phases = [p for p in phases if p.type == "combat"]
        assert len(combat_phases) == 2
        assert combat_phases[0].encounter_id == 1
        assert combat_phases[1].encounter_id == 2

    def test_multi_enemy_ordered_by_ordinal(self) -> None:
        """Encounters are sorted by ordinal regardless of list order."""
        encounters = [
            _make_encounter(encounter_id=2, ordinal=2),
            _make_encounter(encounter_id=1, ordinal=1),
        ]
        scene = _make_scene(combat_encounters=encounters)
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        combat_phases = [p for p in phases if p.type == "combat"]
        assert combat_phases[0].encounter_id == 1
        assert combat_phases[1].encounter_id == 2

    def test_over_capacity_injects_items_phase(self) -> None:
        """When character is over weapon capacity and no items phase exists, inject one."""
        # 3 weapons → over the 2-weapon limit
        items = [
            _make_item(character_item_id=i, item_name=f"Sword{i}", item_type="weapon")
            for i in range(1, 4)
        ]
        state = _make_state(items=items)
        # Scene has no item gains (no items phase would normally appear)
        scene = _make_scene()
        phases = compute_phase_sequence(scene, state)
        phase_types = [p.type for p in phases]
        assert "items" in phase_types

    def test_over_capacity_no_duplicate_items_phase(self) -> None:
        """Over-capacity does not inject a second items phase when one already exists."""
        items = [
            _make_item(character_item_id=i, item_name=f"Sword{i}", item_type="weapon")
            for i in range(1, 4)
        ]
        state = _make_state(items=items)
        scene = _make_scene(
            scene_items=[_make_scene_item(item_type="backpack", action="gain")]
        )
        phases = compute_phase_sequence(scene, state)
        items_count = sum(1 for p in phases if p.type == "items")
        assert items_count == 1

    def test_conditional_combat_skipped_when_condition_met(self) -> None:
        """Encounter with discipline condition is skipped when hero has that discipline."""
        encounter = _make_encounter(condition_type="discipline", condition_value="Sixth Sense")
        scene = _make_scene(combat_encounters=[encounter])
        state = _make_state(disciplines=["Sixth Sense"])
        phases = compute_phase_sequence(scene, state)
        combat_phases = [p for p in phases if p.type == "combat"]
        assert combat_phases == []

    def test_conditional_combat_included_when_condition_not_met(self) -> None:
        """Encounter condition not met → combat phase included."""
        encounter = _make_encounter(condition_type="discipline", condition_value="Sixth Sense")
        scene = _make_scene(combat_encounters=[encounter])
        state = _make_state(disciplines=[])
        phases = compute_phase_sequence(scene, state)
        combat_phases = [p for p in phases if p.type == "combat"]
        assert len(combat_phases) == 1

    def test_scene_level_random_exits_get_random_phase(self) -> None:
        """All choices random-gated → random phase is included."""
        choices = [
            _make_choice(choice_id=1, condition_type="random"),
            _make_choice(choice_id=2, condition_type="random"),
        ]
        scene = _make_scene(choices=choices, random_outcomes=[])
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert any(p.type == "random" for p in phases)

    def test_random_outcomes_on_scene_get_random_phase(self) -> None:
        """Scene with random_outcomes entries → random phase included."""
        scene = _make_scene(random_outcomes=[_make_random_outcome()])
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert any(p.type == "random" for p in phases)

    def test_no_random_when_no_random_outcomes_and_choices_not_all_random(self) -> None:
        """No random phase when scene has no random outcomes and choices are not all random."""
        scene = _make_scene(random_outcomes=[], choices=[_make_choice()])
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert not any(p.type == "random" for p in phases)

    def test_heal_always_present(self) -> None:
        """heal phase always appears in the sequence for non-death scenes."""
        scene = _make_scene()
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert any(p.type == "heal" for p in phases)

    def test_choices_always_last(self) -> None:
        """choices phase is always the final phase."""
        scene = _make_scene(must_eat=True, combat_encounters=[_make_encounter()])
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert phases[-1].type == "choices"

    def test_backpack_loss_phase_included(self) -> None:
        """loses_backpack=True → backpack_loss phase is first."""
        scene = _make_scene(loses_backpack=True)
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert phases[0].type == "backpack_loss"

    def test_item_loss_phase_included(self) -> None:
        """Scene with lose action on non-gold/meal item → item_loss phase present."""
        scene = _make_scene(
            scene_items=[_make_scene_item(item_type="backpack", action="lose")]
        )
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert any(p.type == "item_loss" for p in phases)

    def test_gold_lose_does_not_trigger_item_loss_phase(self) -> None:
        """Gold and meal loses do not trigger the item_loss phase."""
        scene = _make_scene(
            scene_items=[_make_scene_item(item_type="gold", action="lose")]
        )
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert not any(p.type == "item_loss" for p in phases)

    def test_gold_gain_does_not_trigger_items_phase(self) -> None:
        """Gold gains are auto-applied, not presented as player pickup decisions."""
        scene = _make_scene(
            scene_items=[_make_scene_item(item_type="gold", action="gain")]
        )
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert not any(p.type == "items" for p in phases)

    def test_meal_gain_does_not_trigger_items_phase(self) -> None:
        """Meal gains are auto-applied, not presented as player pickup decisions."""
        scene = _make_scene(
            scene_items=[_make_scene_item(item_type="meal", action="gain")]
        )
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        assert not any(p.type == "items" for p in phases)

    def test_minimal_scene_has_heal_and_choices(self) -> None:
        """A plain scene with no special flags has at minimum heal + choices."""
        scene = _make_scene()
        state = _make_state()
        phases = compute_phase_sequence(scene, state)
        phase_types = [p.type for p in phases]
        assert "heal" in phase_types
        assert "choices" in phase_types


# ---------------------------------------------------------------------------
# should_heal tests
# ---------------------------------------------------------------------------


class TestShouldHeal:
    def test_no_combat_heals(self) -> None:
        assert should_heal(combat_occurred=False) is True

    def test_combat_suppresses_heal(self) -> None:
        assert should_heal(combat_occurred=True) is False


# ---------------------------------------------------------------------------
# run_automatic_phase: eat
# ---------------------------------------------------------------------------


class TestRunAutomaticPhaseEat:
    def test_eat_with_meals_available_consumes_one(self) -> None:
        """Consuming a meal reduces meals by 1."""
        state = _make_state(meals=3)
        scene = _make_scene(must_eat=True)
        phase = Phase(type="eat")
        result = run_automatic_phase(phase, state, scene)
        assert result.phase_type == "eat"
        assert result.severity == "info"
        assert result.state_changes.get("meals") == 2
        assert any(e["type"] == "meal_consumed" for e in result.events)

    def test_eat_with_single_meal_reduces_to_zero(self) -> None:
        """Last meal is consumed, leaving 0."""
        state = _make_state(meals=1)
        scene = _make_scene()
        phase = Phase(type="eat")
        result = run_automatic_phase(phase, state, scene)
        assert result.state_changes.get("meals") == 0

    def test_eat_with_hunting_discipline_no_penalty(self) -> None:
        """Hunting discipline: no meals needed, no endurance penalty."""
        state = _make_state(meals=0, disciplines=["Hunting"])
        scene = _make_scene(must_eat=True)
        phase = Phase(type="eat")
        result = run_automatic_phase(phase, state, scene)
        assert result.severity == "info"
        assert "endurance_current" not in result.state_changes
        assert any(e["type"] == "hunting_forage" for e in result.events)

    def test_eat_without_meals_no_hunting_minus_3_end(self) -> None:
        """No meals, no Hunting → lose 3 END."""
        state = _make_state(meals=0, endurance_current=20, endurance_max=25)
        scene = _make_scene(must_eat=True)
        phase = Phase(type="eat")
        result = run_automatic_phase(phase, state, scene)
        assert result.severity == "warn"
        assert result.state_changes.get("endurance_current") == 17

    def test_eat_death_mid_phase(self) -> None:
        """Starvation penalty kills character at low END → danger severity + is_alive=False."""
        state = _make_state(meals=0, endurance_current=2, endurance_max=25)
        scene = _make_scene(must_eat=True)
        phase = Phase(type="eat")
        result = run_automatic_phase(phase, state, scene)
        assert result.severity == "danger"
        assert result.state_changes.get("endurance_current") == 0
        assert result.state_changes.get("is_alive") is False
        assert any(e["type"] == "character_death" for e in result.events)

    def test_eat_death_exact_threshold(self) -> None:
        """Exactly 3 END remaining → starvation kills exactly at 0."""
        state = _make_state(meals=0, endurance_current=3, endurance_max=25)
        scene = _make_scene(must_eat=True)
        phase = Phase(type="eat")
        result = run_automatic_phase(phase, state, scene)
        assert result.severity == "danger"
        assert result.state_changes.get("endurance_current") == 0


# ---------------------------------------------------------------------------
# run_automatic_phase: heal
# ---------------------------------------------------------------------------


class TestRunAutomaticPhaseHeal:
    def test_heal_after_no_combat_adds_one_end(self) -> None:
        """Healing discipline + no combat → +1 END."""
        state = _make_state(
            disciplines=["Healing"], endurance_current=20, endurance_max=25
        )
        scene = _make_scene()
        phase = Phase(type="heal", metadata={"combat_occurred": False})
        result = run_automatic_phase(phase, state, scene)
        assert result.severity == "info"
        assert result.state_changes.get("endurance_current") == 21

    def test_heal_no_discipline_no_effect(self) -> None:
        """Without Healing discipline, no state change occurs."""
        state = _make_state(disciplines=[], endurance_current=20, endurance_max=25)
        scene = _make_scene()
        phase = Phase(type="heal", metadata={"combat_occurred": False})
        result = run_automatic_phase(phase, state, scene)
        assert result.state_changes == {}

    def test_heal_suppressed_after_combat(self) -> None:
        """Healing suppressed when combat occurred this scene."""
        state = _make_state(
            disciplines=["Healing"], endurance_current=20, endurance_max=25
        )
        scene = _make_scene()
        phase = Phase(type="heal", metadata={"combat_occurred": True})
        result = run_automatic_phase(phase, state, scene)
        assert result.state_changes == {}
        assert any(e["type"] == "heal_suppressed" for e in result.events)

    def test_heal_default_metadata_no_combat(self) -> None:
        """When metadata is absent, combat_occurred defaults to False → healing fires."""
        state = _make_state(
            disciplines=["Healing"], endurance_current=18, endurance_max=25
        )
        scene = _make_scene()
        phase = Phase(type="heal")
        result = run_automatic_phase(phase, state, scene)
        assert result.state_changes.get("endurance_current") == 19

    def test_heal_caps_at_endurance_max(self) -> None:
        """Healing cannot raise endurance above endurance_max."""
        state = _make_state(
            disciplines=["Healing"], endurance_current=25, endurance_max=25
        )
        scene = _make_scene()
        phase = Phase(type="heal", metadata={"combat_occurred": False})
        result = run_automatic_phase(phase, state, scene)
        # Still returns 25, no overflow
        assert result.state_changes.get("endurance_current") == 25


# ---------------------------------------------------------------------------
# run_automatic_phase: backpack_loss
# ---------------------------------------------------------------------------


class TestRunAutomaticPhaseBackpackLoss:
    def test_backpack_loss_clears_backpack_items_and_meals(self) -> None:
        """All backpack items removed and meals reset to 0."""
        items = [
            _make_item(character_item_id=1, item_name="Sword", item_type="weapon"),
            _make_item(character_item_id=2, item_name="Rope", item_type="backpack"),
            _make_item(character_item_id=3, item_name="Laumspur", item_type="backpack"),
        ]
        state = _make_state(items=items, meals=3)
        scene = _make_scene(loses_backpack=True)
        phase = Phase(type="backpack_loss")
        result = run_automatic_phase(phase, state, scene)

        assert result.phase_type == "backpack_loss"
        assert result.severity == "danger"
        assert result.state_changes["meals"] == 0
        remaining = result.state_changes["items"]
        assert all(i.item_type != "backpack" for i in remaining)
        assert len(remaining) == 1  # only the weapon
        assert any(e["type"] == "item_lost" for e in result.events)
        assert any(e["type"] == "meals_lost" for e in result.events)

    def test_backpack_loss_no_backpack_items(self) -> None:
        """Backpack loss with no backpack items still resets meals."""
        items = [_make_item(item_type="weapon")]
        state = _make_state(items=items, meals=2)
        scene = _make_scene()
        phase = Phase(type="backpack_loss")
        result = run_automatic_phase(phase, state, scene)
        assert result.state_changes["meals"] == 0
        assert len(result.state_changes["items"]) == 1

    def test_backpack_loss_no_meals_no_meals_lost_event(self) -> None:
        """If meals=0 before backpack loss, no meals_lost event is emitted."""
        state = _make_state(items=[], meals=0)
        scene = _make_scene()
        phase = Phase(type="backpack_loss")
        result = run_automatic_phase(phase, state, scene)
        assert not any(e["type"] == "meals_lost" for e in result.events)


# ---------------------------------------------------------------------------
# run_automatic_phase: item_loss
# ---------------------------------------------------------------------------


class TestRunAutomaticPhaseItemLoss:
    def test_item_loss_removes_matching_item(self) -> None:
        """item_loss phase removes the matching item from the character's inventory."""
        items = [
            _make_item(character_item_id=1, item_name="Rope", item_type="backpack"),
            _make_item(character_item_id=2, item_name="Sword", item_type="weapon"),
        ]
        state = _make_state(items=items)
        scene = _make_scene(
            scene_items=[_make_scene_item(item_name="Rope", item_type="backpack", action="lose")]
        )
        phase = Phase(type="item_loss")
        result = run_automatic_phase(phase, state, scene)

        remaining = result.state_changes["items"]
        assert all(i.item_name != "Rope" for i in remaining)
        assert len(remaining) == 1
        assert any(e["type"] == "item_lost" and e["item_name"] == "Rope" for e in result.events)

    def test_item_loss_skip_when_item_not_in_inventory(self) -> None:
        """If the item is not in inventory, log item_loss_skip event."""
        state = _make_state(items=[])
        scene = _make_scene(
            scene_items=[_make_scene_item(item_name="Torch", item_type="backpack", action="lose")]
        )
        phase = Phase(type="item_loss")
        result = run_automatic_phase(phase, state, scene)
        assert any(e["type"] == "item_loss_skip" for e in result.events)
        skip_event = next(e for e in result.events if e["type"] == "item_loss_skip")
        assert skip_event["item_name"] == "Torch"

    def test_item_loss_multiple_items(self) -> None:
        """Multiple lose items in scene — all are processed."""
        items = [
            _make_item(character_item_id=1, item_name="Rope", item_type="backpack"),
            _make_item(character_item_id=2, item_name="Torch", item_type="backpack"),
            _make_item(character_item_id=3, item_name="Sword", item_type="weapon"),
        ]
        state = _make_state(items=items)
        scene = _make_scene(
            scene_items=[
                _make_scene_item(
                    scene_item_id=1, item_name="Rope", item_type="backpack", action="lose"
                ),
                _make_scene_item(
                    scene_item_id=2, item_name="Torch", item_type="backpack", action="lose"
                ),
            ]
        )
        phase = Phase(type="item_loss")
        result = run_automatic_phase(phase, state, scene)
        remaining = result.state_changes["items"]
        assert len(remaining) == 1
        assert remaining[0].item_name == "Sword"

    def test_item_loss_ignores_gold_and_meal_scene_items(self) -> None:
        """Gold and meal lose scene items are not processed in item_loss phase."""
        items = [_make_item(item_name="Rope", item_type="backpack")]
        state = _make_state(items=items)
        scene = _make_scene(
            scene_items=[
                _make_scene_item(item_name="Gold", item_type="gold", action="lose"),
                _make_scene_item(item_name="Meal", item_type="meal", action="lose"),
            ]
        )
        phase = Phase(type="item_loss")
        result = run_automatic_phase(phase, state, scene)
        # No items removed (gold/meal are filtered out)
        remaining = result.state_changes["items"]
        assert len(remaining) == 1
