"""State builder — pure DTO construction helpers shared across services.

Extracted from gameplay_service to break the circular import cycle between
gameplay_service and combat_service.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.engine.meters import compute_endurance_max
from app.engine.types import (
    CharacterState,
    ChoiceData,
    CombatEncounterData,
    CombatModifierData,
    ItemState,
    RandomOutcomeData,
    SceneContext,
    SceneItemData,
)
from app.models.content import Scene
from app.models.player import Character, CharacterItem
from app.models.taxonomy import GameObject


def _build_item_states(db: Session, character_items: list) -> list[ItemState]:
    """Build a list of ItemState DTOs from a list of CharacterItem ORM rows.

    Batch-loads GameObjects to avoid N+1 queries, parses properties JSON,
    and returns one ItemState per item.

    Args:
        db: Active database session.
        character_items: List of CharacterItem ORM instances.

    Returns:
        List of :class:`ItemState` dataclasses in the same order as the input.
    """
    game_object_ids = [
        ci.game_object_id
        for ci in character_items
        if ci.game_object_id is not None
    ]

    go_lookup: dict[int, GameObject] = {}
    if game_object_ids:
        game_objects = (
            db.query(GameObject)
            .filter(GameObject.id.in_(game_object_ids))
            .all()
        )
        go_lookup = {go.id: go for go in game_objects}

    items: list[ItemState] = []
    for ci in character_items:
        if ci.game_object_id is not None and ci.game_object_id in go_lookup:
            go = go_lookup[ci.game_object_id]
            try:
                properties = json.loads(go.properties) if isinstance(go.properties, str) else go.properties
            except (json.JSONDecodeError, TypeError, AttributeError):
                properties = {}
        else:
            properties = {}

        items.append(
            ItemState(
                character_item_id=ci.id,
                item_name=ci.item_name,
                item_type=ci.item_type,
                is_equipped=ci.is_equipped,
                game_object_id=ci.game_object_id,
                properties=properties,
            )
        )

    return items


def build_character_state(db: Session, character: Character) -> CharacterState:
    """Construct an engine-layer CharacterState DTO from a Character ORM model.

    Fixes N+1: collects all game_object_ids from character items in one pass,
    then does a single batch query for the corresponding GameObjects.

    Args:
        db: Active database session.
        character: The character ORM model.

    Returns:
        A fully populated :class:`CharacterState` dataclass.
    """
    # Collect discipline names
    disciplines: list[str] = []
    weapon_skill_category: str | None = None
    for cd in character.disciplines:
        disciplines.append(cd.discipline.name)
        if cd.weapon_category is not None:
            weapon_skill_category = cd.weapon_category

    # Build item states via shared helper (batch-loads GameObjects)
    items = _build_item_states(db, character.items)

    # Parse rule_overrides
    try:
        rule_overrides = (
            json.loads(character.rule_overrides)
            if character.rule_overrides
            else None
        )
    except (json.JSONDecodeError, TypeError, AttributeError):
        rule_overrides = None

    return CharacterState(
        character_id=character.id,
        combat_skill_base=character.combat_skill_base,
        endurance_base=character.endurance_base,
        endurance_max=character.endurance_max,
        endurance_current=character.endurance_current,
        gold=character.gold,
        meals=character.meals,
        is_alive=character.is_alive,
        disciplines=disciplines,
        weapon_skill_category=weapon_skill_category,
        items=items,
        version=character.version,
        current_run=character.current_run,
        death_count=character.death_count,
        rule_overrides=rule_overrides,
        current_scene_id=character.current_scene_id,
        scene_phase=character.scene_phase,
        scene_phase_index=character.scene_phase_index,
        active_combat_encounter_id=character.active_combat_encounter_id,
    )


def build_scene_context(scene: Scene) -> SceneContext:
    """Build a SceneContext DTO from a Scene ORM model.

    Args:
        scene: The scene ORM model with all relationships loaded.

    Returns:
        A fully populated :class:`SceneContext` dataclass for engine functions.
    """
    # Parse phase_sequence_override if present.
    phase_sequence_override: list[dict] | None = None
    if scene.phase_sequence_override:
        try:
            parsed = json.loads(scene.phase_sequence_override)
            if isinstance(parsed, list):
                phase_sequence_override = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    choices = [
        ChoiceData(
            choice_id=c.id,
            target_scene_id=c.target_scene_id,
            target_scene_number=c.target_scene_number,
            display_text=c.display_text,
            condition_type=c.condition_type,
            condition_value=c.condition_value,
            has_random_outcomes=bool(c.random_outcomes),
        )
        for c in scene.choices
    ]

    combat_encounters = [
        CombatEncounterData(
            encounter_id=enc.id,
            enemy_name=enc.enemy_name,
            enemy_cs=enc.enemy_cs,
            enemy_end=enc.enemy_end,
            ordinal=enc.ordinal,
            mindblast_immune=enc.mindblast_immune,
            evasion_after_rounds=enc.evasion_after_rounds,
            evasion_target=enc.evasion_target,
            evasion_damage=enc.evasion_damage,
            condition_type=enc.condition_type,
            condition_value=enc.condition_value,
            modifiers=[
                CombatModifierData(
                    modifier_type=m.modifier_type,
                    modifier_value=m.modifier_value,
                    condition=m.condition,
                )
                for m in enc.modifiers
            ],
        )
        for enc in scene.combat_encounters
    ]

    scene_items = [
        SceneItemData(
            scene_item_id=si.id,
            item_name=si.item_name,
            item_type=si.item_type,
            quantity=si.quantity,
            action=si.action,
            is_mandatory=si.is_mandatory,
            game_object_id=si.game_object_id,
            properties={},  # properties not needed for phase logic
        )
        for si in scene.scene_items
    ]

    random_outcomes = [
        RandomOutcomeData(
            outcome_id=ro.id,
            roll_group=ro.roll_group,
            range_min=ro.range_min,
            range_max=ro.range_max,
            effect_type=ro.effect_type,
            effect_value=ro.effect_value,
            narrative_text=ro.narrative_text,
        )
        for ro in scene.random_outcomes
    ]

    return SceneContext(
        scene_id=scene.id,
        book_id=scene.book_id,
        scene_number=scene.number,
        is_death=scene.is_death,
        is_victory=scene.is_victory,
        must_eat=scene.must_eat,
        loses_backpack=scene.loses_backpack,
        phase_sequence_override=phase_sequence_override,
        choices=choices,
        combat_encounters=combat_encounters,
        scene_items=scene_items,
        random_outcomes=random_outcomes,
    )


def mark_character_dead(character: Character) -> None:
    """Clear all transient state and mark a character as dead.

    Sets ``is_alive`` to False and clears ``scene_phase``,
    ``scene_phase_index``, ``active_combat_encounter_id``, and
    ``pending_choice_id``.  The caller is responsible for flushing the
    session and incrementing the version counter.

    Args:
        character: The character ORM model to mark dead (mutated in place).
    """
    character.is_alive = False
    character.scene_phase = None
    character.scene_phase_index = None
    character.active_combat_encounter_id = None
    character.pending_choice_id = None


def recalculate_endurance_max(db: Session, character: Character) -> None:
    """Recalculate and persist ``endurance_max`` after an item change.

    Queries all remaining ``CharacterItem`` rows for the character using a
    direct DB query (avoiding stale ORM relationship caches), batch-loads the
    corresponding ``GameObject`` properties, builds an ``ItemState`` list, and
    calls :func:`app.engine.meters.compute_endurance_max`.

    If ``endurance_current`` exceeds the new max it is clamped down.

    Args:
        db: Active database session.
        character: The character ORM model (mutated in place).
    """
    remaining_items = (
        db.query(CharacterItem)
        .filter(CharacterItem.character_id == character.id)
        .all()
    )

    # Build item states via shared helper (batch-loads GameObjects)
    item_states = _build_item_states(db, remaining_items)

    new_max = compute_endurance_max(character.endurance_base, [], item_states)
    character.endurance_max = new_max
    if character.endurance_current > new_max:
        character.endurance_current = new_max
