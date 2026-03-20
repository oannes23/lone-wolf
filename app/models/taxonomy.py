"""Taxonomy models: game object knowledge graph and book transition/equipment tables."""

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


class GameObject(Base):
    """Canonical named entity in the Lone Wolf universe (character, item, location, etc.)."""

    __tablename__ = "game_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    properties: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    first_book_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="RESTRICT"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    # Relationships
    first_book = relationship("Book", foreign_keys=[first_book_id])
    outgoing_refs = relationship(
        "GameObjectRef",
        foreign_keys="GameObjectRef.source_id",
        back_populates="source_obj",
    )
    incoming_refs = relationship(
        "GameObjectRef",
        foreign_keys="GameObjectRef.target_id",
        back_populates="target_obj",
    )

    __table_args__ = (
        UniqueConstraint("name", "kind", name="uq_game_objects_name_kind"),
        CheckConstraint(
            "kind IN ('character', 'location', 'creature', 'organization', 'item', 'foe', 'scene')",
            name="ck_game_objects_kind",
        ),
        CheckConstraint(
            "source IN ('auto', 'manual')",
            name="ck_game_objects_source",
        ),
        Index("ix_game_objects_kind", "kind"),
        Index("ix_game_objects_kind_name", "kind", "name"),
    )


class GameObjectRef(Base):
    """Tagged directional reference between two game objects (ops.md pattern)."""

    __tablename__ = "game_object_refs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("game_objects.id", ondelete="RESTRICT"), nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("game_objects.id", ondelete="RESTRICT"), nullable=False
    )
    tags: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    # Relationships
    source_obj = relationship(
        "GameObject", foreign_keys=[source_id], back_populates="outgoing_refs"
    )
    target_obj = relationship(
        "GameObject", foreign_keys=[target_id], back_populates="incoming_refs"
    )

    __table_args__ = (
        CheckConstraint(
            "source IN ('auto', 'manual')",
            name="ck_game_object_refs_source",
        ),
        Index("ix_game_object_refs_source_id", "source_id"),
        Index("ix_game_object_refs_target_id", "target_id"),
    )


class BookTransitionRule(Base):
    """Carry-over rules when a character advances from one book to the next."""

    __tablename__ = "book_transition_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="RESTRICT"), nullable=False
    )
    to_book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="RESTRICT"), nullable=False
    )
    max_weapons: Mapped[int] = mapped_column(Integer, nullable=False)
    max_backpack_items: Mapped[int] = mapped_column(Integer, nullable=False)
    special_items_carry: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gold_carries: Mapped[bool] = mapped_column(Boolean, nullable=False)
    new_disciplines_count: Mapped[int] = mapped_column(Integer, nullable=False)
    base_cs_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_end_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    from_book = relationship("Book", foreign_keys=[from_book_id])
    to_book = relationship("Book", foreign_keys=[to_book_id])

    __table_args__ = (
        UniqueConstraint("from_book_id", "to_book_id", name="uq_book_transition_rules_from_to"),
    )


class BookStartingEquipment(Base):
    """Equipment available for character creation or book advance for a given book."""

    __tablename__ = "book_starting_equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("books.id", ondelete="RESTRICT"), nullable=False
    )
    game_object_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("game_objects.id", ondelete="RESTRICT"), nullable=True
    )
    item_name: Mapped[str] = mapped_column(String(100), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)

    # Relationships
    book = relationship("Book", foreign_keys=[book_id])
    game_object = relationship("GameObject", foreign_keys=[game_object_id])

    __table_args__ = (
        CheckConstraint(
            "item_type IN ('weapon', 'backpack', 'special', 'gold', 'meal')",
            name="ck_book_starting_equipment_item_type",
        ),
        CheckConstraint(
            "source IN ('auto', 'manual')",
            name="ck_book_starting_equipment_source",
        ),
        Index("ix_book_starting_equipment_book_id", "book_id"),
    )
