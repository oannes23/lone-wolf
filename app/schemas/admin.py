"""Pydantic schemas for admin user management and content CRUD endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UpdateMaxCharactersRequest(BaseModel):
    """Request body for PUT /admin/users/{id}."""

    max_characters: int = Field(ge=1)


class UserAdminResponse(BaseModel):
    """Response body for PUT /admin/users/{id}."""

    id: int
    username: str
    email: str
    max_characters: int


class CharacterAdminResponse(BaseModel):
    """Response body for PUT /admin/characters/{id}/restore."""

    id: int
    name: str
    is_deleted: bool


# ---------------------------------------------------------------------------
# Content CRUD schemas — books
# ---------------------------------------------------------------------------


class BookCreateRequest(BaseModel):
    """Request body for POST /admin/books."""

    slug: str
    number: int
    title: str
    era: str
    series: str = "lone_wolf"
    start_scene_number: int = 1
    max_total_picks: int


class BookUpdateRequest(BaseModel):
    """Request body for PUT /admin/books/{id}."""

    slug: str | None = None
    number: int | None = None
    title: str | None = None
    era: str | None = None
    series: str | None = None
    start_scene_number: int | None = None
    max_total_picks: int | None = None


class BookAdminResponse(BaseModel):
    """Response body for book admin endpoints."""

    id: int
    slug: str
    number: int
    title: str
    era: str
    series: str
    start_scene_number: int
    max_total_picks: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — scenes
# ---------------------------------------------------------------------------


class SceneCreateRequest(BaseModel):
    """Request body for POST /admin/scenes."""

    book_id: int
    number: int
    html_id: str
    narrative: str
    is_death: bool = False
    is_victory: bool = False
    must_eat: bool = False
    loses_backpack: bool = False
    illustration_path: str | None = None
    phase_sequence_override: str | None = None
    game_object_id: int | None = None


class SceneUpdateRequest(BaseModel):
    """Request body for PUT /admin/scenes/{id}."""

    book_id: int | None = None
    number: int | None = None
    html_id: str | None = None
    narrative: str | None = None
    is_death: bool | None = None
    is_victory: bool | None = None
    must_eat: bool | None = None
    loses_backpack: bool | None = None
    illustration_path: str | None = None
    phase_sequence_override: str | None = None
    game_object_id: int | None = None


class SceneAdminResponse(BaseModel):
    """Response body for scene admin endpoints."""

    id: int
    book_id: int
    number: int
    html_id: str
    narrative: str
    is_death: bool
    is_victory: bool
    must_eat: bool
    loses_backpack: bool
    illustration_path: str | None
    phase_sequence_override: str | None
    game_object_id: int | None
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — choices
# ---------------------------------------------------------------------------


class ChoiceCreateRequest(BaseModel):
    """Request body for POST /admin/choices."""

    scene_id: int
    target_scene_id: int | None = None
    target_scene_number: int
    raw_text: str
    display_text: str
    condition_type: str | None = None
    condition_value: str | None = None
    ordinal: int


class ChoiceUpdateRequest(BaseModel):
    """Request body for PUT /admin/choices/{id}."""

    scene_id: int | None = None
    target_scene_id: int | None = None
    target_scene_number: int | None = None
    raw_text: str | None = None
    display_text: str | None = None
    condition_type: str | None = None
    condition_value: str | None = None
    ordinal: int | None = None


class ChoiceAdminResponse(BaseModel):
    """Response body for choice admin endpoints."""

    id: int
    scene_id: int
    target_scene_id: int | None
    target_scene_number: int
    raw_text: str
    display_text: str
    condition_type: str | None
    condition_value: str | None
    ordinal: int
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — combat encounters
# ---------------------------------------------------------------------------


class CombatEncounterCreateRequest(BaseModel):
    """Request body for POST /admin/combat-encounters."""

    scene_id: int
    foe_game_object_id: int | None = None
    enemy_name: str
    enemy_cs: int
    enemy_end: int
    ordinal: int
    mindblast_immune: bool = False
    evasion_after_rounds: int | None = None
    evasion_target: int | None = None
    evasion_damage: int = 0
    condition_type: str | None = None
    condition_value: str | None = None


class CombatEncounterUpdateRequest(BaseModel):
    """Request body for PUT /admin/combat-encounters/{id}."""

    scene_id: int | None = None
    foe_game_object_id: int | None = None
    enemy_name: str | None = None
    enemy_cs: int | None = None
    enemy_end: int | None = None
    ordinal: int | None = None
    mindblast_immune: bool | None = None
    evasion_after_rounds: int | None = None
    evasion_target: int | None = None
    evasion_damage: int | None = None
    condition_type: str | None = None
    condition_value: str | None = None


class CombatEncounterAdminResponse(BaseModel):
    """Response body for combat encounter admin endpoints."""

    id: int
    scene_id: int
    foe_game_object_id: int | None
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
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — combat modifiers
# ---------------------------------------------------------------------------


class CombatModifierCreateRequest(BaseModel):
    """Request body for POST /admin/combat-modifiers."""

    combat_encounter_id: int
    modifier_type: str
    modifier_value: str | None = None
    condition: str | None = None


class CombatModifierUpdateRequest(BaseModel):
    """Request body for PUT /admin/combat-modifiers/{id}."""

    combat_encounter_id: int | None = None
    modifier_type: str | None = None
    modifier_value: str | None = None
    condition: str | None = None


class CombatModifierAdminResponse(BaseModel):
    """Response body for combat modifier admin endpoints."""

    id: int
    combat_encounter_id: int
    modifier_type: str
    modifier_value: str | None
    condition: str | None
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — scene items
# ---------------------------------------------------------------------------


class SceneItemCreateRequest(BaseModel):
    """Request body for POST /admin/scene-items."""

    scene_id: int
    game_object_id: int | None = None
    item_name: str
    item_type: str
    quantity: int = 1
    action: str
    is_mandatory: bool = False
    phase_ordinal: int


class SceneItemUpdateRequest(BaseModel):
    """Request body for PUT /admin/scene-items/{id}."""

    scene_id: int | None = None
    game_object_id: int | None = None
    item_name: str | None = None
    item_type: str | None = None
    quantity: int | None = None
    action: str | None = None
    is_mandatory: bool | None = None
    phase_ordinal: int | None = None


class SceneItemAdminResponse(BaseModel):
    """Response body for scene item admin endpoints."""

    id: int
    scene_id: int
    game_object_id: int | None
    item_name: str
    item_type: str
    quantity: int
    action: str
    is_mandatory: bool
    phase_ordinal: int
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — disciplines
# ---------------------------------------------------------------------------


class DisciplineCreateRequest(BaseModel):
    """Request body for POST /admin/disciplines."""

    era: str
    name: str
    html_id: str
    description: str
    mechanical_effect: str | None = None


class DisciplineUpdateRequest(BaseModel):
    """Request body for PUT /admin/disciplines/{id}."""

    era: str | None = None
    name: str | None = None
    html_id: str | None = None
    description: str | None = None
    mechanical_effect: str | None = None


class DisciplineAdminResponse(BaseModel):
    """Response body for discipline admin endpoints."""

    id: int
    era: str
    name: str
    html_id: str
    description: str
    mechanical_effect: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — book transition rules
# ---------------------------------------------------------------------------


class BookTransitionRuleCreateRequest(BaseModel):
    """Request body for POST /admin/book-transition-rules."""

    from_book_id: int
    to_book_id: int
    max_weapons: int
    max_backpack_items: int
    special_items_carry: bool
    gold_carries: bool
    new_disciplines_count: int
    base_cs_override: int | None = None
    base_end_override: int | None = None
    notes: str | None = None


class BookTransitionRuleUpdateRequest(BaseModel):
    """Request body for PUT /admin/book-transition-rules/{id}."""

    from_book_id: int | None = None
    to_book_id: int | None = None
    max_weapons: int | None = None
    max_backpack_items: int | None = None
    special_items_carry: bool | None = None
    gold_carries: bool | None = None
    new_disciplines_count: int | None = None
    base_cs_override: int | None = None
    base_end_override: int | None = None
    notes: str | None = None


class BookTransitionRuleAdminResponse(BaseModel):
    """Response body for book transition rule admin endpoints."""

    id: int
    from_book_id: int
    to_book_id: int
    max_weapons: int
    max_backpack_items: int
    special_items_carry: bool
    gold_carries: bool
    new_disciplines_count: int
    base_cs_override: int | None
    base_end_override: int | None
    notes: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — weapon categories
# ---------------------------------------------------------------------------


class WeaponCategoryCreateRequest(BaseModel):
    """Request body for POST /admin/weapon-categories."""

    weapon_name: str
    category: str


class WeaponCategoryUpdateRequest(BaseModel):
    """Request body for PUT /admin/weapon-categories/{id}."""

    weapon_name: str | None = None
    category: str | None = None


class WeaponCategoryAdminResponse(BaseModel):
    """Response body for weapon category admin endpoints."""

    id: int
    weapon_name: str
    category: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — game objects
# ---------------------------------------------------------------------------


class GameObjectCreateRequest(BaseModel):
    """Request body for POST /admin/game-objects."""

    kind: str
    name: str
    description: str | None = None
    aliases: str = "[]"
    properties: str = "{}"
    first_book_id: int | None = None


class GameObjectUpdateRequest(BaseModel):
    """Request body for PUT /admin/game-objects/{id}."""

    kind: str | None = None
    name: str | None = None
    description: str | None = None
    aliases: str | None = None
    properties: str | None = None
    first_book_id: int | None = None


class GameObjectAdminResponse(BaseModel):
    """Response body for game object admin endpoints."""

    id: int
    kind: str
    name: str
    description: str | None
    aliases: str
    properties: str
    first_book_id: int | None
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — game object refs
# ---------------------------------------------------------------------------


class GameObjectRefCreateRequest(BaseModel):
    """Request body for POST /admin/game-object-refs."""

    source_id: int
    target_id: int
    tags: str
    metadata: str | None = None


class GameObjectRefUpdateRequest(BaseModel):
    """Request body for PUT /admin/game-object-refs/{id}."""

    source_id: int | None = None
    target_id: int | None = None
    tags: str | None = None
    metadata: str | None = None


class GameObjectRefAdminResponse(BaseModel):
    """Response body for game object ref admin endpoints."""

    id: int
    source_id: int
    target_id: int
    tags: str
    metadata: str | None = Field(None, alias="metadata_")
    source: str

    model_config = {"from_attributes": True, "populate_by_name": True}


# ---------------------------------------------------------------------------
# Content CRUD schemas — book starting equipment
# ---------------------------------------------------------------------------


class BookStartingEquipmentCreateRequest(BaseModel):
    """Request body for POST /admin/book-starting-equipment."""

    book_id: int
    game_object_id: int | None = None
    item_name: str
    item_type: str
    category: str
    is_default: bool = False


class BookStartingEquipmentUpdateRequest(BaseModel):
    """Request body for PUT /admin/book-starting-equipment/{id}."""

    book_id: int | None = None
    game_object_id: int | None = None
    item_name: str | None = None
    item_type: str | None = None
    category: str | None = None
    is_default: bool | None = None


class BookStartingEquipmentAdminResponse(BaseModel):
    """Response body for book starting equipment admin endpoints."""

    id: int
    book_id: int
    game_object_id: int | None
    item_name: str
    item_type: str
    category: str
    is_default: bool
    source: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Wizard templates — read-only (no create/update schemas needed)
# ---------------------------------------------------------------------------


class WizardTemplateAdminResponse(BaseModel):
    """Response body for wizard template admin endpoints (read-only)."""

    id: int
    name: str
    description: str | None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Admin report schemas
# ---------------------------------------------------------------------------


class AdminReportResponse(BaseModel):
    """Response body for an admin report."""

    id: int
    user_id: int
    character_id: int | None
    scene_id: int | None
    tags: list[str]
    free_text: str | None
    status: str
    admin_notes: str | None
    resolved_by: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminReportDetailResponse(AdminReportResponse):
    """Report detail including linked scene summary."""

    scene_narrative: str | None = None
    scene_number: int | None = None


class UpdateReportRequest(BaseModel):
    """Request body for PUT /admin/reports/{id}."""

    status: str | None = None
    admin_notes: str | None = None
    resolved_by: int | None = None


class ReportTagStats(BaseModel):
    """Per-tag report count."""

    tag: str
    count: int


class ReportStatusStats(BaseModel):
    """Per-status report count."""

    status: str
    count: int


class AdminReportStatsResponse(BaseModel):
    """Response body for GET /admin/reports/stats."""

    total: int
    by_tag: list[ReportTagStats]
    by_status: list[ReportStatusStats]
    resolution_rate: float


# ---------------------------------------------------------------------------
# Admin character event schemas
# ---------------------------------------------------------------------------


class CharacterEventAdminResponse(BaseModel):
    """Response body for character events in admin event viewer."""

    id: int
    character_id: int
    scene_id: int
    run_number: int
    event_type: str
    phase: str | None
    details: str | None
    seq: int
    operations: str | None
    parent_event_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
