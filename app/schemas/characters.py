"""Pydantic schemas for character endpoints."""

from pydantic import BaseModel, Field


class RollRequest(BaseModel):
    """Request body for POST /characters/roll."""

    book_id: int = Field(..., gt=0)


class RollFormula(BaseModel):
    """Stat roll formula breakdown — shows the base plus the random component."""

    cs: str
    end: str


class RollResponse(BaseModel):
    """Response body for POST /characters/roll."""

    roll_token: str
    combat_skill_base: int
    endurance_base: int
    era: str
    formula: RollFormula


class CreateCharacterRequest(BaseModel):
    """Request body for POST /characters."""

    name: str = Field(..., min_length=1, max_length=100)
    book_id: int = Field(..., gt=0)
    roll_token: str
    discipline_ids: list[int] = Field(..., min_length=5, max_length=5)
    weapon_skill_type: str | None = None


class ActiveWizardInfo(BaseModel):
    """Summary of the wizard currently active on a character."""

    type: str
    step: str
    step_index: int
    total_steps: int


class CharacterResponse(BaseModel):
    """Response body for POST /characters."""

    id: int
    name: str
    combat_skill_base: int
    endurance_base: int
    endurance_max: int
    endurance_current: int
    gold: int
    meals: int
    death_count: int
    current_run: int
    version: int
    disciplines: list[str]
    active_wizard: ActiveWizardInfo | None


# ---------------------------------------------------------------------------
# Wizard step schemas
# ---------------------------------------------------------------------------


class WizardIncludedItem(BaseModel):
    """An item automatically included in the character's starting equipment."""

    item_name: str
    item_type: str
    note: str = "fixed"


class WizardAutoApplied(BaseModel):
    """Resources auto-applied during the equipment step (gold and meals)."""

    gold: int
    gold_formula: str
    meals: int


class WizardAvailableItem(BaseModel):
    """An item the player may choose from during the equipment step."""

    item_name: str
    item_type: str
    category: str


class WizardEquipmentStepResponse(BaseModel):
    """Response body for GET /characters/{id}/wizard when at the equipment step."""

    wizard_type: str
    step: str
    step_index: int
    total_steps: int
    included_items: list[WizardIncludedItem]
    auto_applied: WizardAutoApplied
    available_equipment: list[WizardAvailableItem]
    pick_limit: int


class WizardConfirmStepResponse(BaseModel):
    """Response body for GET /characters/{id}/wizard when at the confirm step."""

    wizard_type: str
    step: str
    step_index: int
    total_steps: int
    character_preview: CharacterResponse


class WizardEquipmentRequest(BaseModel):
    """Request body for POST /characters/{id}/wizard at the equipment step."""

    selected_items: list[str]
    version: int


class WizardConfirmRequest(BaseModel):
    """Request body for POST /characters/{id}/wizard at the confirm step."""

    confirm: bool
    version: int


class WizardCompleteResponse(BaseModel):
    """Response returned when the wizard is fully complete."""

    message: str
    wizard_complete: bool
    character: CharacterResponse


# ---------------------------------------------------------------------------
# Book advance wizard schemas
# ---------------------------------------------------------------------------


class AdvanceWizardBookInfo(BaseModel):
    """Summary of the book the character is advancing to."""

    id: int
    title: str


class AdvanceInitResponse(BaseModel):
    """Response body for POST /gameplay/{character_id}/advance (starts the wizard)."""

    wizard_type: str
    step: str
    step_index: int
    total_steps: int
    book: AdvanceWizardBookInfo


class WizardDisciplineItem(BaseModel):
    """An available discipline for selection during the pick_disciplines step."""

    id: int
    name: str
    description: str


class WizardDisciplineStepResponse(BaseModel):
    """Response body for GET wizard at the pick_disciplines step."""

    wizard_type: str
    step: str
    step_index: int
    total_steps: int
    available_disciplines: list[WizardDisciplineItem]
    disciplines_to_pick: int


class WizardInventoryItemInfo(BaseModel):
    """Item info returned during the inventory_adjust step."""

    item_name: str
    item_type: str
    is_equipped: bool = False


class WizardInventoryStepResponse(BaseModel):
    """Response body for GET wizard at the inventory_adjust step."""

    wizard_type: str
    step: str
    step_index: int
    total_steps: int
    current_weapons: list[WizardInventoryItemInfo]
    current_backpack: list[WizardInventoryItemInfo]
    current_special: list[WizardInventoryItemInfo]
    max_weapons: int
    max_backpack_items: int


class WizardDisciplineRequest(BaseModel):
    """Request body for POST wizard at the pick_disciplines step."""

    discipline_ids: list[int]
    weapon_skill_type: str | None = None
    version: int


class WizardInventoryRequest(BaseModel):
    """Request body for POST wizard at the inventory_adjust step."""

    keep_weapons: list[str]
    keep_backpack: list[str]
    version: int
