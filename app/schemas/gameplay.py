"""Pydantic schemas for gameplay endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Lifecycle request bodies
# ---------------------------------------------------------------------------


class RestartRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/restart."""

    version: int = Field(..., description="Optimistic lock version")


class ReplayRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/replay."""

    version: int = Field(..., description="Optimistic lock version")


# ---------------------------------------------------------------------------
# Random outcome band (for choice-triggered rolls)
# ---------------------------------------------------------------------------


class OutcomeBand(BaseModel):
    """One outcome band for a choice-triggered random roll."""

    range_min: int
    range_max: int
    target_scene_number: int
    narrative_text: str | None = None


# ---------------------------------------------------------------------------
# Choice random response (requires_roll path)
# ---------------------------------------------------------------------------


class ChoiceRandomResponse(BaseModel):
    """Returned when a chosen choice requires a random roll before transitioning.

    The client should call POST /gameplay/{id}/roll to resolve the outcome.
    """

    requires_roll: bool = True
    choice_id: int
    choice_text: str
    outcome_bands: list[OutcomeBand]
    version: int


# ---------------------------------------------------------------------------
# Phase result
# ---------------------------------------------------------------------------


class PhaseResult(BaseModel):
    """Result of an automatically-processed scene phase step.

    Included in ``phase_results`` on the scene response to inform the player
    what happened automatically (meal consumed, healing applied, item loss, etc.).
    """

    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(alias="type")
    result: str
    severity: str = "info"
    details: dict | None = None


# ---------------------------------------------------------------------------
# Pending item
# ---------------------------------------------------------------------------


class PendingItem(BaseModel):
    """A scene item awaiting the player's accept/decline decision."""

    id: int
    item_name: str
    item_type: str
    quantity: int = 1
    is_mandatory: bool


# ---------------------------------------------------------------------------
# Combat state
# ---------------------------------------------------------------------------


class CombatState(BaseModel):
    """Current state of an active combat encounter, returned during the combat phase."""

    encounter_id: int
    enemy_name: str
    enemy_cs: int
    enemy_end_remaining: int
    hero_end_remaining: int
    rounds_fought: int
    evasion_available: bool  # encounter supports evasion at all
    can_evade: bool  # rounds_fought >= evasion_after_rounds threshold
    evasion_after_rounds: int | None
    hero_effective_cs: int
    combat_ratio: int


# ---------------------------------------------------------------------------
# Choice info
# ---------------------------------------------------------------------------


class ChoiceInfo(BaseModel):
    """A player-navigable choice at a scene, with availability status."""

    id: int
    text: str
    available: bool
    condition: dict | None = None
    unavailability_reason: str | None = None
    has_random_outcomes: bool


# ---------------------------------------------------------------------------
# Scene response
# ---------------------------------------------------------------------------


class SceneResponse(BaseModel):
    """Full scene state response for GET /gameplay/{character_id}/scene."""

    scene_number: int
    narrative: str
    illustration_url: str | None = None
    phase: str | None
    phase_index: int | None = None
    phase_sequence: list[str]
    phase_results: list[PhaseResult]
    choices: list[ChoiceInfo]
    combat: CombatState | None
    pending_items: list[PendingItem]
    is_death: bool
    is_victory: bool
    is_alive: bool = True
    version: int


# ---------------------------------------------------------------------------
# Combat round request / response (Story 6.3)
# ---------------------------------------------------------------------------


class CombatRoundRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/combat/round."""

    use_psi_surge: bool = Field(default=False, description="Activate Psi-surge for this round")
    version: int = Field(..., description="Optimistic lock version")


class CombatRoundResponse(BaseModel):
    """Response for POST /gameplay/{character_id}/combat/round."""

    round_number: int
    random_number: int
    combat_ratio: int
    hero_damage: int | None  # None = instant kill
    enemy_damage: int | None  # None = instant kill
    hero_end_remaining: int
    enemy_end_remaining: int
    psi_surge_used: bool
    combat_over: bool
    result: str  # "win", "loss", "continue"
    evasion_available: bool
    can_evade: bool
    version: int


# ---------------------------------------------------------------------------
# Evade request / response (Story 6.3)
# ---------------------------------------------------------------------------


class EvadeRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/combat/evade."""

    version: int = Field(..., description="Optimistic lock version")


class EvadeResponse(SceneResponse):
    """Response for POST /gameplay/{character_id}/combat/evade.

    Extends SceneResponse with the endurance damage taken during evasion.
    """

    evasion_damage: int


# ---------------------------------------------------------------------------
# Inventory item (shared sub-schema for item & inventory responses)
# ---------------------------------------------------------------------------


class InventoryItemOut(BaseModel):
    """A single item in the character's inventory for API responses."""

    character_item_id: int
    item_name: str
    item_type: str
    is_equipped: bool
    game_object_id: int | None


# ---------------------------------------------------------------------------
# POST /gameplay/{character_id}/item
# ---------------------------------------------------------------------------


class ItemActionRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/item."""

    scene_item_id: int = Field(..., gt=0, description="ID of the scene_items row")
    action: Literal["accept", "decline"] = Field(..., description="Accept or decline the item")
    version: int = Field(..., description="Optimistic lock version")


class ItemActionResponse(BaseModel):
    """Response body for POST /gameplay/{character_id}/item."""

    action: str
    # Present on accept
    item_name: str | None = None
    item_type: str | None = None
    character_item_id: int | None = None
    # Phase tracking
    pending_items_remaining: int
    phase_complete: bool
    # Current inventory
    inventory: list[InventoryItemOut]
    version: int


# ---------------------------------------------------------------------------
# POST /gameplay/{character_id}/inventory
# ---------------------------------------------------------------------------


class InventoryActionRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/inventory."""

    action: Literal["drop", "equip", "unequip"] = Field(
        ..., description="The inventory management action to perform"
    )
    character_item_id: int = Field(..., gt=0, description="ID of the character_items row")
    version: int = Field(..., description="Optimistic lock version")


class InventoryResponse(BaseModel):
    """Response body for POST /gameplay/{character_id}/inventory."""

    action: str
    inventory: list[InventoryItemOut]
    version: int


# ---------------------------------------------------------------------------
# POST /gameplay/{character_id}/use-item
# ---------------------------------------------------------------------------


class UseItemRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/use-item."""

    character_item_id: int = Field(..., gt=0, description="ID of the character_items row")
    version: int = Field(..., description="Optimistic lock version")


class UseItemResponse(BaseModel):
    """Response body for POST /gameplay/{character_id}/use-item."""

    effect_applied: dict | None
    endurance_current: int
    endurance_max: int
    inventory: list[InventoryItemOut]
    version: int


# ---------------------------------------------------------------------------
# POST /gameplay/{character_id}/roll
# ---------------------------------------------------------------------------


class RollRequest(BaseModel):
    """Request body for POST /gameplay/{character_id}/roll."""

    version: int = Field(..., description="Optimistic lock version")


class RollPhaseEffectResponse(BaseModel):
    """Response when a roll applies an in-scene phase effect (gold, END, item, redirect).

    Returned when ``random_type == "phase_effect"`` — the scene has ``random_outcomes``
    and the roll matched an outcome band.  When ``effect_type == "scene_redirect"`` the
    response also contains ``scene_number``, ``narrative``, and ``phase_results`` from
    the redirected scene.
    """

    random_type: Literal["phase_effect"] = "phase_effect"
    random_number: int
    outcome_text: str | None = None
    effect_type: str
    effect_applied: dict | None = None
    current_roll_group: int
    rolls_remaining: int
    phase_complete: bool
    requires_confirm: bool = True
    # Populated only when effect_type == "scene_redirect"
    scene_number: int | None = None
    narrative: str | None = None
    phase_results: list[PhaseResult] = Field(default_factory=list)
    version: int


class RollSceneTransitionResponse(BaseModel):
    """Response when a roll causes a scene transition (scene_exit or choice_outcome).

    Returned for ``random_type`` values ``"scene_exit"`` and ``"choice_outcome"``.
    """

    random_type: Literal["scene_exit", "choice_outcome"]
    random_number: int
    outcome_text: str | None = None
    scene_number: int
    narrative: str
    phase_results: list[PhaseResult]
    requires_confirm: bool = True
    version: int
