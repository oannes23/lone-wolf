"""Gameplay service — thin re-export facade for backward compatibility.

All business logic has been split into focused modules:
- app.services.scene_service      — get_scene_state and scene assembly helpers
- app.services.transition_service — transition_to_scene, process_choose
- app.services.item_service       — process_item_action, process_inventory_action, process_use_item
- app.services.roll_service       — process_roll

Import from the focused modules directly. This facade exists only so that
any remaining import sites that reference app.services.gameplay_service
continue to work during the migration period.
"""

from app.services.item_service import (
    process_inventory_action,
    process_item_action,
    process_use_item,
)
from app.services.roll_service import process_roll
from app.services.scene_service import get_scene_state
from app.services.transition_service import process_choose, transition_to_scene

__all__ = [
    "get_scene_state",
    "transition_to_scene",
    "process_choose",
    "process_item_action",
    "process_inventory_action",
    "process_use_item",
    "process_roll",
]
