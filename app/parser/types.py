"""Plain dataclasses for parser extraction results.

No ORM dependencies — these types are used only within the parser pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BookData:
    """Metadata extracted from a single XHTML book file."""

    slug: str
    number: int
    era: str
    title: str
    xhtml_path: Path


@dataclass
class SceneData:
    """A numbered scene extracted from a book's XHTML."""

    number: int
    html_id: str
    narrative: str
    illustration_path: str | None = None
    choices: list[ChoiceData] = field(default_factory=list)
    combat_encounters: list[CombatData] = field(default_factory=list)


@dataclass
class ChoiceData:
    """A player choice extracted from a scene."""

    raw_text: str
    target_scene_number: int
    ordinal: int


@dataclass
class CombatData:
    """A combat encounter extracted from a scene."""

    enemy_name: str
    enemy_cs: int
    enemy_end: int
    ordinal: int


@dataclass
class CRTRow:
    """A single row in the Combat Results Table."""

    random_number: int
    combat_ratio_min: int
    combat_ratio_max: int
    enemy_loss: int | None
    hero_loss: int | None


@dataclass
class DisciplineData:
    """A discipline extracted from the book front matter."""

    name: str
    html_id: str
    description: str


@dataclass
class EquipmentData:
    """An equipment item extracted from the starting equipment section."""

    item_name: str
    item_type: str
    quantity: int


@dataclass
class SceneAnalysisData:
    """Structured extraction results from LLM scene analysis.

    Combines entity extraction, relationship inference, and game mechanics
    detection into a single LLM call result.
    """

    entities: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    combat_encounters: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    random_outcomes: list[dict] = field(default_factory=list)
    evasion: dict | None = None
    combat_modifiers: list[dict] = field(default_factory=list)
    conditions: list[dict] = field(default_factory=list)
    scene_flags: dict = field(default_factory=dict)


@dataclass
class EnrichmentResult:
    """Result of the LLM enrichment + merge phase in the parser pipeline."""

    choice_dicts: list[dict] = field(default_factory=list)
    entity_game_objects: list[dict] = field(default_factory=list)
    entity_refs: list[dict] = field(default_factory=list)
    encounter_dicts: list[dict] = field(default_factory=list)
    item_dicts: list[dict] = field(default_factory=list)
    random_outcome_dicts: list[dict] = field(default_factory=list)
    llm_call_count: int = 0
    warnings: list[str] = field(default_factory=list)
