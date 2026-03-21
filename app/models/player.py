"""Player table models — users, characters, inventory, decisions, combat history, and events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.content import Discipline

# ---------------------------------------------------------------------------
# Shared CHECK constraint expressions
# ---------------------------------------------------------------------------

_SCENE_PHASE_CHECK = (
    "scene_phase IS NULL OR scene_phase IN ('items', 'combat', 'random', 'choices')"
)
_CHARACTER_ITEM_TYPE_CHECK = "item_type IN ('weapon', 'backpack', 'special')"
_ACTION_TYPE_CHECK = (
    "action_type IN ("
    "'choice', 'combat_win', 'combat_evasion', 'random', 'death', 'restart', 'replay'"
    ")"
)
_EVENT_TYPE_CHECK = (
    "event_type IN ("
    "'item_pickup', 'item_decline', 'item_loss', 'item_loss_skip', 'item_consumed', "
    "'meal_consumed', 'meal_penalty', 'gold_change', 'endurance_change', 'healing', "
    "'combat_start', 'combat_end', 'combat_skipped', 'evasion', 'death', 'restart', "
    "'replay', 'discipline_gained', 'book_advance', 'random_roll', 'backpack_loss'"
    ")"
)


class User(Base):
    """A registered player account."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    max_characters: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    password_changed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    characters: Mapped[list["Character"]] = relationship("Character", back_populates="user")


class Character(Base):
    """A player's character — tracks all game state for one playthrough."""

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    book_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("books.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_scene_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    scene_phase: Mapped[str | None] = mapped_column(String(20), nullable=True)
    scene_phase_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_combat_encounter_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("combat_encounters.id", ondelete="SET NULL"),
        nullable=True,
    )
    active_wizard_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("character_wizard_progress.id", ondelete="SET NULL"),
        nullable=True,
    )
    pending_choice_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("choices.id", ondelete="RESTRICT"),
        nullable=True,
    )
    combat_skill_base: Mapped[int] = mapped_column(Integer, nullable=False)
    endurance_base: Mapped[int] = mapped_column(Integer, nullable=False)
    endurance_max: Mapped[int] = mapped_column(Integer, nullable=False)
    endurance_current: Mapped[int] = mapped_column(Integer, nullable=False)
    gold: Mapped[int] = mapped_column(Integer, nullable=False)
    meals: Mapped[int] = mapped_column(Integer, nullable=False)
    is_alive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)
    death_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_run: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rule_overrides: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_SCENE_PHASE_CHECK, name="ck_characters_scene_phase"),
        CheckConstraint("gold >= 0 AND gold <= 50", name="ck_characters_gold"),
        CheckConstraint("meals >= 0 AND meals <= 8", name="ck_characters_meals"),
        CheckConstraint("endurance_current >= 0", name="ck_characters_endurance_current"),
        CheckConstraint(
            "(scene_phase IS NULL AND scene_phase_index IS NULL) "
            "OR (scene_phase IS NOT NULL AND scene_phase_index IS NOT NULL)",
            name="ck_characters_phase_consistency",
        ),
        Index("ix_characters_user_id", "user_id"),
        Index("ix_characters_user_id_is_deleted", "user_id", "is_deleted"),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="characters")
    disciplines: Mapped[list["CharacterDiscipline"]] = relationship(
        "CharacterDiscipline", back_populates="character"
    )
    items: Mapped[list["CharacterItem"]] = relationship(
        "CharacterItem", back_populates="character"
    )
    book_starts: Mapped[list["CharacterBookStart"]] = relationship(
        "CharacterBookStart", back_populates="character"
    )
    decision_log: Mapped[list["DecisionLog"]] = relationship(
        "DecisionLog", back_populates="character"
    )
    combat_rounds: Mapped[list["CombatRound"]] = relationship(
        "CombatRound", back_populates="character"
    )
    events: Mapped[list["CharacterEvent"]] = relationship(
        "CharacterEvent",
        foreign_keys="CharacterEvent.character_id",
        back_populates="character",
    )


class CharacterDiscipline(Base):
    """A discipline possessed by a character."""

    __tablename__ = "character_disciplines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    discipline_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("disciplines.id", ondelete="RESTRICT"),
        nullable=False,
    )
    weapon_category: Mapped[str | None] = mapped_column(String(30), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "character_id", "discipline_id", name="uq_character_disciplines_char_disc"
        ),
        Index("ix_character_disciplines_char_disc", "character_id", "discipline_id"),
    )

    # Relationships
    character: Mapped["Character"] = relationship(
        "Character", back_populates="disciplines"
    )
    discipline: Mapped["Discipline"] = relationship("Discipline")


class CharacterItem(Base):
    """An item currently held by a character."""

    __tablename__ = "character_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    game_object_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("game_objects.id", ondelete="RESTRICT"),
        nullable=True,
    )
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_equipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint(_CHARACTER_ITEM_TYPE_CHECK, name="ck_character_items_item_type"),
        Index("ix_character_items_char_type", "character_id", "item_type"),
    )

    # Relationships
    character: Mapped["Character"] = relationship("Character", back_populates="items")


class CharacterBookStart(Base):
    """Snapshot of character state at the start of each book (for death-restart)."""

    __tablename__ = "character_book_starts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    book_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("books.id", ondelete="RESTRICT"),
        nullable=False,
    )
    combat_skill_base: Mapped[int] = mapped_column(Integer, nullable=False)
    endurance_base: Mapped[int] = mapped_column(Integer, nullable=False)
    endurance_max: Mapped[int] = mapped_column(Integer, nullable=False)
    endurance_current: Mapped[int] = mapped_column(Integer, nullable=False)
    gold: Mapped[int] = mapped_column(Integer, nullable=False)
    meals: Mapped[int] = mapped_column(Integer, nullable=False)
    items_json: Mapped[str] = mapped_column(Text, nullable=False)
    disciplines_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "character_id", "book_id", name="uq_character_book_starts_char_book"
        ),
    )

    # Relationships
    character: Mapped["Character"] = relationship(
        "Character", back_populates="book_starts"
    )


class DecisionLog(Base):
    """Full navigation history for a character, tagged by run number."""

    __tablename__ = "decision_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    choice_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("choices.id", ondelete="RESTRICT"),
        nullable=True,
    )
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_ACTION_TYPE_CHECK, name="ck_decision_log_action_type"),
        Index(
            "ix_decision_log_char_run_created",
            "character_id", "run_number", "created_at",
        ),
        Index("ix_decision_log_char_run", "character_id", "run_number"),
    )

    # Relationships
    character: Mapped["Character"] = relationship(
        "Character", back_populates="decision_log"
    )


class CombatRound(Base):
    """Round-by-round combat history for a character encounter."""

    __tablename__ = "combat_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    combat_encounter_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("combat_encounters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    random_number: Mapped[int] = mapped_column(Integer, nullable=False)
    combat_ratio: Mapped[int] = mapped_column(Integer, nullable=False)
    enemy_loss: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hero_loss: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enemy_end_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    hero_end_remaining: Mapped[int] = mapped_column(Integer, nullable=False)
    psi_surge_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "character_id", "combat_encounter_id", "run_number", "round_number",
            name="uq_combat_rounds_char_enc_run_round",
        ),
        Index(
            "ix_combat_rounds_char_enc_run_round",
            "character_id", "combat_encounter_id", "run_number", "round_number",
        ),
    )

    # Relationships
    character: Mapped["Character"] = relationship(
        "Character", back_populates="combat_rounds"
    )


class CharacterEvent(Base):
    """Generic state-change audit trail — one row per phase step completion."""

    __tablename__ = "character_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scene_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    phase: Mapped[str | None] = mapped_column(String(20), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    operations: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_event_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("character_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_EVENT_TYPE_CHECK, name="ck_character_events_event_type"),
        Index("ix_character_events_char_scene_created", "character_id", "scene_id", "created_at"),
        Index("ix_character_events_char_event_type", "character_id", "event_type"),
        Index("ix_character_events_char_seq", "character_id", "seq"),
        Index("ix_character_events_parent_event_id", "parent_event_id"),
    )

    # Relationships
    character: Mapped["Character"] = relationship(
        "Character",
        foreign_keys=[character_id],
        back_populates="events",
    )
    children: Mapped[list["CharacterEvent"]] = relationship(
        "CharacterEvent",
        foreign_keys=[parent_event_id],
        back_populates="parent",
    )
    parent: Mapped["CharacterEvent | None"] = relationship(
        "CharacterEvent",
        foreign_keys=[parent_event_id],
        back_populates="children",
        remote_side=[id],
    )
