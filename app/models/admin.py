"""Admin table models — admin accounts and player-submitted reports."""

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

_REPORT_STATUS_CHECK = (
    "status IN ('open', 'triaging', 'resolved', 'wont_fix')"
)


class AdminUser(Base):
    """An administrator account — separate from player accounts."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    resolved_reports: Mapped[list["Report"]] = relationship(
        "Report",
        foreign_keys="Report.resolved_by",
        back_populates="resolver",
    )


class Report(Base):
    """A player-submitted bug or content report."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    character_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("characters.id", ondelete="RESTRICT"),
        nullable=True,
    )
    scene_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("scenes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    tags: Mapped[str] = mapped_column(Text, nullable=False)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("admin_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        CheckConstraint(_REPORT_STATUS_CHECK, name="ck_reports_status"),
        Index("ix_reports_status_created_at", "status", "created_at"),
    )

    # Relationships
    resolver: Mapped["AdminUser | None"] = relationship(
        "AdminUser",
        foreign_keys=[resolved_by],
        back_populates="resolved_reports",
    )
