"""Pydantic schemas for book endpoints."""

from pydantic import BaseModel


class BookListItem(BaseModel):
    """A summary row returned by GET /books."""

    id: int
    number: int
    slug: str
    title: str
    era: str
    start_scene_number: int


class DisciplineInfo(BaseModel):
    """A single discipline entry included in book detail and rules responses."""

    id: int
    name: str
    description: str


class BookDetail(BookListItem):
    """Full book detail returned by GET /books/{book_id}.

    Extends BookListItem with aggregate scene count, the discipline list for
    the book's era, and the max discipline picks allowed across the series.
    """

    scene_count: int
    max_total_picks: int
    disciplines: list[DisciplineInfo]


class EquipmentRulesSummary(BaseModel):
    """High-level equipment rules derived from weapon category data."""

    weapon_categories: list[str]
    starting_equipment_note: str


class CombatRulesSummary(BaseModel):
    """Summary of combat rules for the book's era."""

    era: str
    combat_ratio_explained: str
    random_number_range: str


class BookRulesResponse(BaseModel):
    """Response for GET /books/{book_id}/rules.

    Aggregates discipline descriptions, equipment rules, and a combat rules
    summary for display to the player before they start.
    """

    disciplines: list[DisciplineInfo]
    equipment_rules: EquipmentRulesSummary
    combat_rules: CombatRulesSummary
