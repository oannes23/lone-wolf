"""Engine data transfer objects (DTOs) for the Lone Wolf game engine.

These dataclasses are the pure-Python boundary layer between the database-backed
service layer and the stateless game engine. No ORM models, no database sessions,
no FastAPI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_REDIRECT_DEPTH = 5


@dataclass
class ItemState:
    """Snapshot of a single item carried by a character."""

    character_item_id: int
    item_name: str
    item_type: str  # weapon, backpack, special
    is_equipped: bool
    game_object_id: int | None
    properties: dict  # from game_object.properties


@dataclass
class CharacterState:
    """Complete snapshot of a character's current state passed into engine functions.

    The service layer populates this from the database. Engine functions accept
    only this type — never ORM models.
    """

    character_id: int
    combat_skill_base: int
    endurance_base: int
    endurance_max: int
    endurance_current: int
    gold: int
    meals: int
    is_alive: bool
    disciplines: list[str]  # discipline names
    weapon_skill_category: str | None  # Weaponskill weapon category chosen at creation
    items: list[ItemState]
    version: int
    current_run: int
    death_count: int
    rule_overrides: dict | None
    era: str = "kai"  # era for CRT lookup and era-specific rules
    current_scene_id: int | None = None
    scene_phase: str | None = None  # current phase: items, combat, random, choices
    scene_phase_index: int | None = None
    active_combat_encounter_id: int | None = None


@dataclass
class ChoiceData:
    """A single navigable choice available to the player at a scene."""

    choice_id: int
    target_scene_id: int | None
    target_scene_number: int
    display_text: str
    condition_type: str | None
    condition_value: str | None
    has_random_outcomes: bool  # True if choice has choice_random_outcomes


@dataclass
class CombatModifierData:
    """A modifier that alters how a combat encounter is resolved."""

    modifier_type: str  # cs_bonus, cs_penalty, double_damage, undead, enemy_mindblast
    modifier_value: str | None
    condition: str | None


@dataclass
class CombatEncounterData:
    """One enemy encounter embedded in a scene."""

    encounter_id: int
    enemy_name: str
    enemy_cs: int
    enemy_end: int
    ordinal: int
    mindblast_immune: bool
    evasion_after_rounds: int | None
    evasion_target: int | None
    evasion_damage: int
    condition_type: str | None
    condition_value: str | None
    modifiers: list[CombatModifierData] = field(default_factory=list)


@dataclass
class SceneItemData:
    """An item the scene awards, removes, or offers to the player."""

    scene_item_id: int
    item_name: str
    item_type: str  # weapon, backpack, special, gold, meal
    quantity: int
    action: str  # gain, lose
    is_mandatory: bool
    game_object_id: int | None
    properties: dict


@dataclass
class RandomOutcomeData:
    """One row of a random-number-table outcome for a choice or scene event."""

    outcome_id: int
    roll_group: int
    range_min: int
    range_max: int
    effect_type: str  # gold_change, endurance_change, item_gain, item_loss, meal_change, scene_redirect
    effect_value: str
    narrative_text: str | None


@dataclass
class SceneContext:
    """Full context for rendering and processing a scene, assembled by the service layer."""

    scene_id: int
    book_id: int
    scene_number: int
    is_death: bool
    is_victory: bool
    must_eat: bool
    loses_backpack: bool
    phase_sequence_override: list[dict] | None  # e.g. [{"type": "combat", "encounter_id": 1}]
    choices: list[ChoiceData]
    combat_encounters: list[CombatEncounterData]
    scene_items: list[SceneItemData]
    random_outcomes: list[RandomOutcomeData]


@dataclass
class CombatContext:
    """Live state of an in-progress combat encounter, passed between engine calls."""

    encounter_id: int
    enemy_name: str
    enemy_cs: int
    enemy_end: int
    enemy_end_remaining: int
    mindblast_immune: bool
    evasion_after_rounds: int | None
    evasion_target: int | None
    evasion_damage: int
    modifiers: list[CombatModifierData]
    rounds_fought: int
