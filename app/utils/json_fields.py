"""Shared JSON field parsing utilities.

Database columns that store JSON as text strings need defensive parsing.
These helpers provide consistent parsing across routers and UI layers.
"""

import json


def parse_json_list(raw: str | None) -> list[str]:
    """Parse a JSON-encoded string into a list of strings.

    Returns an empty list on parse error or if the value is not a list.
    """
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return value
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def parse_json_dict(raw: str | None) -> dict:
    """Parse a JSON-encoded string into a dict.

    Returns an empty dict on parse error or if the value is not a dict.
    """
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def parse_json_dict_or_none(raw: str | None) -> dict | None:
    """Parse a JSON-encoded string into a dict, returning None if absent/invalid."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        if isinstance(value, dict):
            return value
    except (json.JSONDecodeError, TypeError):
        pass
    return None
