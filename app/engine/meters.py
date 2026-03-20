"""Meter arithmetic for the Lone Wolf game engine.

Pure functions that apply bounded deltas to character resource meters (endurance,
gold, meals). No side effects — callers are responsible for persisting results.
"""

from __future__ import annotations

from app.engine.types import CharacterState, ItemState

_GOLD_MAX = 50
_MEALS_MAX = 8


def compute_endurance_max(
    endurance_base: int, disciplines: list[str], items: list[ItemState]
) -> int:
    """Return the character's maximum endurance considering item and discipline bonuses.

    The ``endurance_bonus`` property is summed across ALL carried items regardless
    of equipped state. Items such as Chainmail Waistcoat (+4) and Helmet (+2)
    add to the maximum whether or not they are currently equipped.

    Lore-circle bonuses from disciplines are not yet implemented (Magnakai+ feature).
    The ``disciplines`` parameter is accepted now to establish the correct contract
    for downstream consumers.

    Args:
        endurance_base: The character's base endurance value from their record.
        disciplines: List of discipline names the character possesses.
        items: All items currently in the character's possession.

    Returns:
        The effective endurance maximum.
    """
    item_bonus = sum(
        int(item.properties.get("endurance_bonus", 0))
        for item in items
    )
    # TODO: Add lore_circle_end_bonus(disciplines) for Magnakai+ eras
    return endurance_base + item_bonus


def apply_endurance_delta(
    state: CharacterState, delta: int
) -> tuple[int, bool, list[dict]]:
    """Apply a signed delta to the character's current endurance.

    The new value is clamped to ``[0, endurance_max]``.  If it reaches 0 the
    character is considered dead.

    Args:
        state: Current character state snapshot.
        delta: Positive for healing, negative for damage.

    Returns:
        A three-tuple of:
        - ``new_endurance`` (int): The endurance value after applying the delta.
        - ``is_dead`` (bool): True when new_endurance reaches 0.
        - ``events`` (list[dict]): Descriptive event dicts for audit logging.
    """
    previous = state.endurance_current
    new_endurance = max(0, min(previous + delta, state.endurance_max))
    is_dead = new_endurance == 0

    events: list[dict] = []

    if delta != 0:
        events.append(
            {
                "type": "endurance_change",
                "previous": previous,
                "new": new_endurance,
                "delta_requested": delta,
                "delta_applied": new_endurance - previous,
            }
        )

    if is_dead:
        events.append({"type": "character_death", "endurance": new_endurance})

    return new_endurance, is_dead, events


def apply_gold_delta(state: CharacterState, delta: int) -> tuple[int, int]:
    """Apply a signed delta to the character's gold, capped at [0, 50].

    Args:
        state: Current character state snapshot.
        delta: Positive for gaining gold, negative for spending/losing gold.

    Returns:
        A two-tuple of:
        - ``new_gold`` (int): Gold after applying the delta.
        - ``actual_delta`` (int): The delta that was actually applied, which may
          differ from ``delta`` when the cap or floor would be exceeded.
    """
    previous = state.gold
    new_gold = max(0, min(previous + delta, _GOLD_MAX))
    actual_delta = new_gold - previous
    return new_gold, actual_delta


def apply_meal_delta(state: CharacterState, delta: int) -> tuple[int, int]:
    """Apply a signed delta to the character's meal count, capped at [0, 8].

    Args:
        state: Current character state snapshot.
        delta: Positive for gaining meals, negative for consuming/losing meals.

    Returns:
        A two-tuple of:
        - ``new_meals`` (int): Meal count after applying the delta.
        - ``actual_delta`` (int): The delta that was actually applied, which may
          differ from ``delta`` when the cap or floor would be exceeded.
    """
    previous = state.meals
    new_meals = max(0, min(previous + delta, _MEALS_MAX))
    actual_delta = new_meals - previous
    return new_meals, actual_delta
