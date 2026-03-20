"""Wizard table models — data-driven wizard system for character creation and book advance."""

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

_STEP_TYPE_CHECK = (
    "step_type IN ("
    "'stat_roll', 'pick_disciplines', 'pick_equipment', 'pick_weapon_skill', "
    "'inventory_adjust', 'confirm'"
    ")"
)


class WizardTemplate(Base):
    """A named multi-step wizard definition (e.g., character_creation, book_advance)."""

    __tablename__ = "wizard_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    steps: Mapped[list["WizardTemplateStep"]] = relationship(
        "WizardTemplateStep", back_populates="template"
    )
    progress_records: Mapped[list["CharacterWizardProgress"]] = relationship(
        "CharacterWizardProgress", back_populates="wizard_template"
    )


class WizardTemplateStep(Base):
    """An ordered step within a wizard template."""

    __tablename__ = "wizard_template_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wizard_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    step_type: Mapped[str] = mapped_column(String(30), nullable=False)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint(_STEP_TYPE_CHECK, name="ck_wizard_template_steps_step_type"),
        Index("ix_wizard_template_steps_template_id", "template_id"),
    )

    # Relationships
    template: Mapped["WizardTemplate"] = relationship(
        "WizardTemplate", back_populates="steps"
    )


class CharacterWizardProgress(Base):
    """Tracks a character's progress through a wizard (creation or book advance)."""

    __tablename__ = "character_wizard_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=False,
    )
    wizard_template_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("wizard_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[DateTime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_character_wizard_progress_char_completed",
            "character_id",
            "completed_at",
        ),
    )

    # Relationships
    wizard_template: Mapped["WizardTemplate"] = relationship(
        "WizardTemplate", back_populates="progress_records"
    )
