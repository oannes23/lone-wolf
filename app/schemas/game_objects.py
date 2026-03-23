"""Pydantic schemas for game object endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class FirstAppearance(BaseModel):
    """Structured first-appearance info linking a game object to a book."""

    book_id: int
    book_title: str


class GameObjectSummary(BaseModel):
    """Minimal game object representation for list responses."""

    id: int
    name: str
    kind: str
    description: str | None
    aliases: list[str]
    first_appearance: FirstAppearance | None


class RefTarget(BaseModel):
    """Target side of a tagged game object reference."""

    id: int
    name: str
    kind: str


class GameObjectRef(BaseModel):
    """A single tagged directional reference between two game objects."""

    target: RefTarget
    tags: list[str]
    metadata: dict | None = None


class GameObjectDetail(BaseModel):
    """Full game object detail including properties and tagged refs."""

    id: int
    name: str
    kind: str
    description: str | None
    aliases: list[str]
    properties: dict
    first_appearance: FirstAppearance | None
    refs: list[GameObjectRef]
