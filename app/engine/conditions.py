"""Choice condition evaluation for the Lone Wolf game engine.

Pure functions that determine whether a choice's condition is satisfied given
a character's current state. No side effects — callers are responsible for
acting on the results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.engine.types import CharacterState, ChoiceData


def check_condition(
    state: CharacterState,
    condition_type: str | None,
    condition_value: str | None,
) -> bool:
    """Evaluate whether a choice condition is satisfied by the character state.

    Supported condition types:
    - ``None`` or ``"none"`` — always True (unconditional choice).
    - ``"discipline"`` — True if ``condition_value`` is in ``state.disciplines``.
      Also supports a JSON compound OR object ``{"any": ["Name1", "Name2"]}``
      where True is returned if ANY of the listed discipline names are present.
    - ``"item"`` — True if any item in ``state.items`` has ``item_name``
      matching ``condition_value`` (case-sensitive).
    - ``"gold"`` — True if ``state.gold >= int(condition_value)``.
    - ``"random"`` — always True; random-gated choices are always selectable
      and their outcome is resolved at selection time.

    Args:
        state: Current character state snapshot.
        condition_type: The type of condition to evaluate, or None.
        condition_value: The value to evaluate against, or None.

    Returns:
        True if the condition is satisfied (or absent), False otherwise.
    """
    if condition_type is None or condition_type == "none":
        return True

    if condition_type == "random":
        return True

    if condition_type == "discipline":
        return _check_discipline(state, condition_value)

    if condition_type == "item":
        if condition_value is None:
            return False
        return any(item.item_name == condition_value for item in state.items)

    if condition_type == "gold":
        if condition_value is None:
            return False
        return state.gold >= int(condition_value)

    # Unknown condition types default to False (safe / restrictive).
    return False


def _check_discipline(state: CharacterState, condition_value: str | None) -> bool:
    """Evaluate a discipline condition, including compound OR forms.

    A plain string value is matched directly against ``state.disciplines``.
    A JSON object of the form ``{"any": ["Name1", "Name2", ...]}`` returns
    True if ANY of the listed names are present in ``state.disciplines``.

    Args:
        state: Current character state snapshot.
        condition_value: Discipline name or JSON compound condition, or None.

    Returns:
        True if the condition is satisfied, False otherwise.
    """
    if condition_value is None:
        return False

    # Attempt to parse as a compound OR condition.
    if condition_value.startswith("{"):
        try:
            parsed = json.loads(condition_value)
        except json.JSONDecodeError:
            return False
        if isinstance(parsed, dict) and "any" in parsed:
            names = parsed["any"]
            if isinstance(names, list):
                return any(name in state.disciplines for name in names)
        return False

    # Plain discipline name — case-sensitive direct match.
    return condition_value in state.disciplines


@dataclass
class ChoiceWithAvailability:
    """A choice paired with its availability status for the current character state.

    Attributes:
        choice: The original choice data.
        available: True if the character can select this choice right now.
        reason: Human-readable reason the choice is unavailable, or None if available.
    """

    choice: ChoiceData
    available: bool
    reason: str | None  # None if available, descriptive string if not


def filter_choices(
    choices: list[ChoiceData], state: CharacterState
) -> list[ChoiceWithAvailability]:
    """Evaluate each choice against the character state and return availability.

    A choice is unavailable for one of two reasons:
    1. ``path_unavailable`` — the choice has no ``target_scene_id`` AND
       ``has_random_outcomes`` is False.  This represents an unresolved stub
       in the scene data.
    2. Condition not met — the choice's condition type/value is not satisfied
       by the current character state.

    Available choices have ``reason=None``.

    Args:
        choices: Ordered list of choices to evaluate.
        state: Current character state snapshot.

    Returns:
        List of :class:`ChoiceWithAvailability` in the same order as ``choices``.
    """
    results: list[ChoiceWithAvailability] = []

    for choice in choices:
        # Unresolved path — no target and no random resolution mechanism.
        if choice.target_scene_id is None and not choice.has_random_outcomes:
            results.append(
                ChoiceWithAvailability(
                    choice=choice,
                    available=False,
                    reason="path_unavailable",
                )
            )
            continue

        # Evaluate condition.
        if check_condition(state, choice.condition_type, choice.condition_value):
            results.append(ChoiceWithAvailability(choice=choice, available=True, reason=None))
        else:
            reason = _build_unavailable_reason(choice.condition_type, choice.condition_value)
            results.append(
                ChoiceWithAvailability(choice=choice, available=False, reason=reason)
            )

    return results


def _build_unavailable_reason(
    condition_type: str | None, condition_value: str | None
) -> str:
    """Build a descriptive reason string for an unmet condition.

    Args:
        condition_type: The condition type that was not met.
        condition_value: The condition value that was not met.

    Returns:
        A short human-readable description of the unmet requirement.
    """
    if condition_type == "discipline":
        return f"requires_discipline:{condition_value}"
    if condition_type == "item":
        return f"requires_item:{condition_value}"
    if condition_type == "gold":
        return f"requires_gold:{condition_value}"
    return f"condition_not_met:{condition_type}"


def compute_gold_deduction(choice: ChoiceData) -> int | None:
    """Return the gold amount to deduct when this choice is selected, if any.

    Only choices with ``condition_type == "gold"`` impose a gold cost on
    selection.  The cost is the exact threshold from ``condition_value``.

    Args:
        choice: The choice being selected by the player.

    Returns:
        The integer gold amount to deduct, or None if this choice has no
        gold cost.
    """
    if choice.condition_type == "gold" and choice.condition_value is not None:
        return int(choice.condition_value)
    return None
