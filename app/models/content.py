"""Content table models — parsed book data (books, scenes, choices, combat, etc.)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.taxonomy import GameObject

# ---------------------------------------------------------------------------
# Shared CHECK constraint expressions
# ---------------------------------------------------------------------------

_ERA_CHECK = "era IN ('kai', 'magnakai', 'grand_master', 'new_order')"
_SOURCE_CHECK = "source IN ('auto', 'manual')"
_ITEM_TYPE_CHECK = "item_type IN ('weapon', 'backpack', 'special', 'gold', 'meal')"
_ACTION_CHECK = "action IN ('gain', 'lose')"
_EFFECT_TYPE_CHECK = (
    "effect_type IN ("
    "'gold_change', 'endurance_change', 'item_gain', 'item_loss', 'meal_change', 'scene_redirect'"
    ")"
)
_MODIFIER_TYPE_CHECK = (
    "modifier_type IN ('cs_bonus', 'cs_penalty', 'double_damage', 'undead', 'enemy_mindblast', 'helghast')"
)
_CHOICE_CONDITION_TYPE_CHECK = (
    "condition_type IS NULL OR condition_type IN ('discipline', 'item', 'gold', 'random', 'none')"
)
_COMBAT_CONDITION_TYPE_CHECK = (
    "condition_type IS NULL OR condition_type IN ('discipline', 'item', 'none')"
)


class Book(Base):
    """A Lone Wolf book stub — metadata used by all downstream content tables."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    era: Mapped[str] = mapped_column(String(20), nullable=False)
    series: Mapped[str] = mapped_column(String(20), nullable=False)
    start_scene_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_total_picks: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint(_ERA_CHECK, name="ck_books_era"),
    )

    # Relationships
    scenes: Mapped[list[Scene]] = relationship("Scene", back_populates="book")


class Scene(Base):
    """A numbered passage within a book — the core gameplay unit."""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_object_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("game_objects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    book_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("books.id", ondelete="RESTRICT"),
        nullable=False,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    html_id: Mapped[str] = mapped_column(String(20), nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    is_death: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_victory: Mapped[bool] = mapped_column(Boolean, nullable=False)
    must_eat: Mapped[bool] = mapped_column(Boolean, nullable=False)
    loses_backpack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    illustration_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phase_sequence_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        UniqueConstraint("book_id", "number", name="uq_scenes_book_number"),
        CheckConstraint(_SOURCE_CHECK, name="ck_scenes_source"),
        Index("ix_scenes_book_number", "book_id", "number"),
    )

    # Relationships
    book: Mapped[Book] = relationship("Book", back_populates="scenes")
    game_object: Mapped[GameObject] = relationship("GameObject", foreign_keys=[game_object_id])
    choices: Mapped[list[Choice]] = relationship(
        "Choice", foreign_keys="Choice.scene_id", back_populates="scene"
    )
    combat_encounters: Mapped[list[CombatEncounter]] = relationship(
        "CombatEncounter", back_populates="scene"
    )
    scene_items: Mapped[list[SceneItem]] = relationship("SceneItem", back_populates="scene")
    random_outcomes: Mapped[list[RandomOutcome]] = relationship(
        "RandomOutcome", back_populates="scene"
    )
    game_object_appearances = relationship(
        "GameObjectSceneAppearance", back_populates="scene"
    )


class Choice(Base):
    """A player decision point within a scene."""

    __tablename__ = "choices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_scene_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    target_scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    display_text: Mapped[str] = mapped_column(Text, nullable=False)
    condition_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    condition_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        CheckConstraint(_CHOICE_CONDITION_TYPE_CHECK, name="ck_choices_condition_type"),
        CheckConstraint(_SOURCE_CHECK, name="ck_choices_source"),
        Index("ix_choices_scene_id", "scene_id"),
    )

    # Relationships
    scene: Mapped[Scene] = relationship(
        "Scene", foreign_keys=[scene_id], back_populates="choices"
    )
    random_outcomes: Mapped[list[ChoiceRandomOutcome]] = relationship(
        "ChoiceRandomOutcome", back_populates="choice"
    )


class ChoiceRandomOutcome(Base):
    """Outcome bands for choice-triggered random rolls."""

    __tablename__ = "choice_random_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    choice_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("choices.id", ondelete="RESTRICT"),
        nullable=False,
    )
    range_min: Mapped[int] = mapped_column(Integer, nullable=False)
    range_max: Mapped[int] = mapped_column(Integer, nullable=False)
    target_scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_scene_number: Mapped[int] = mapped_column(Integer, nullable=False)
    narrative_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        UniqueConstraint("choice_id", "range_min", "range_max", name="uq_cro_choice_range"),
        CheckConstraint(_SOURCE_CHECK, name="ck_cro_source"),
        Index("ix_choice_random_outcomes_choice_id", "choice_id"),
    )

    # Relationships
    choice: Mapped[Choice] = relationship("Choice", back_populates="random_outcomes")


class CombatEncounter(Base):
    """A combat encounter embedded in a scene."""

    __tablename__ = "combat_encounters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    foe_game_object_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("game_objects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    enemy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    enemy_cs: Mapped[int] = mapped_column(Integer, nullable=False)
    enemy_end: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    mindblast_immune: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evasion_after_rounds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evasion_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evasion_damage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    condition_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    condition_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        CheckConstraint(_COMBAT_CONDITION_TYPE_CHECK, name="ck_combat_encounters_condition_type"),
        CheckConstraint(_SOURCE_CHECK, name="ck_combat_encounters_source"),
        Index("ix_combat_encounters_scene_id", "scene_id"),
    )

    # Relationships
    scene: Mapped[Scene] = relationship("Scene", back_populates="combat_encounters")
    foe_game_object: Mapped[GameObject | None] = relationship(
        "GameObject", foreign_keys=[foe_game_object_id]
    )
    modifiers: Mapped[list[CombatModifier]] = relationship(
        "CombatModifier", back_populates="combat_encounter"
    )


class CombatModifier(Base):
    """Special combat rules that apply to a specific encounter."""

    __tablename__ = "combat_modifiers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    combat_encounter_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("combat_encounters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    modifier_type: Mapped[str] = mapped_column(String(30), nullable=False)
    modifier_value: Mapped[str | None] = mapped_column(String(100), nullable=True)
    condition: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        CheckConstraint(_MODIFIER_TYPE_CHECK, name="ck_combat_modifiers_modifier_type"),
        CheckConstraint(_SOURCE_CHECK, name="ck_combat_modifiers_source"),
    )

    # Relationships
    combat_encounter: Mapped[CombatEncounter] = relationship(
        "CombatEncounter", back_populates="modifiers"
    )


class CombatResults(Base):
    """Era-scoped Combat Results Table (CRT) — 130 rows per era."""

    __tablename__ = "combat_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    era: Mapped[str] = mapped_column(String(20), nullable=False)
    random_number: Mapped[int] = mapped_column(Integer, nullable=False)
    combat_ratio_min: Mapped[int] = mapped_column(Integer, nullable=False)
    combat_ratio_max: Mapped[int] = mapped_column(Integer, nullable=False)
    enemy_loss: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hero_loss: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(_ERA_CHECK, name="ck_combat_results_era"),
        Index("ix_combat_results_lookup", "era", "random_number", "combat_ratio_min"),
    )


class Discipline(Base):
    """An era-scoped Kai/Magnakai/Grand Master discipline."""

    __tablename__ = "disciplines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    era: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    html_id: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    mechanical_effect: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("era", "name", name="uq_disciplines_era_name"),
        CheckConstraint(_ERA_CHECK, name="ck_disciplines_era"),
    )


class SceneItem(Base):
    """An item that can be gained or lost during a scene."""

    __tablename__ = "scene_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    game_object_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("game_objects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    phase_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        CheckConstraint(_ITEM_TYPE_CHECK, name="ck_scene_items_item_type"),
        CheckConstraint(_ACTION_CHECK, name="ck_scene_items_action"),
        CheckConstraint(_SOURCE_CHECK, name="ck_scene_items_source"),
    )

    # Relationships
    scene: Mapped[Scene] = relationship("Scene", back_populates="scene_items")
    game_object: Mapped[GameObject | None] = relationship(
        "GameObject", foreign_keys=[game_object_id]
    )


class RandomOutcome(Base):
    """Outcome bands for phase-based random rolls in a scene."""

    __tablename__ = "random_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    roll_group: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    range_min: Mapped[int] = mapped_column(Integer, nullable=False)
    range_max: Mapped[int] = mapped_column(Integer, nullable=False)
    effect_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effect_value: Mapped[str] = mapped_column(String(200), nullable=False)
    narrative_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "scene_id", "roll_group", "range_min", "range_max",
            name="uq_random_outcomes_scene_roll_range",
        ),
        CheckConstraint(_EFFECT_TYPE_CHECK, name="ck_random_outcomes_effect_type"),
        CheckConstraint(_SOURCE_CHECK, name="ck_random_outcomes_source"),
        Index("ix_random_outcomes_scene_roll_group", "scene_id", "roll_group"),
    )

    # Relationships
    scene: Mapped[Scene] = relationship("Scene", back_populates="random_outcomes")


class WeaponCategory(Base):
    """Maps weapon names to weapon categories for Weaponskill/Weaponmastery matching."""

    __tablename__ = "weapon_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    weapon_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        Index("ix_weapon_categories_category", "category"),
    )
