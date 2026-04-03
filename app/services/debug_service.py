"""Debug/playtest utilities for content inspection during playtesting."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@lru_cache(maxsize=16)
def _load_merge_report(book_slug: str) -> dict[int, list[str]]:
    """Load and index a merge report by scene number.

    Returns a dict mapping scene_number → list of conflict strings.
    Cached per slug since these files don't change at runtime.
    """
    path = _PROJECT_ROOT / f"merge_report_{book_slug}.json"
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    conflicts_by_scene: dict[int, list[str]] = {}
    for warning in data.get("merge_conflicts", []):
        match = re.search(r"\bscene=(\d+)\b", warning)
        if match:
            scene_num = int(match.group(1))
            conflicts_by_scene.setdefault(scene_num, []).append(warning)

    return conflicts_by_scene


def get_scene_merge_conflicts(book_slug: str, scene_number: int) -> list[str]:
    """Return merge conflict strings for a specific scene.

    Parameters
    ----------
    book_slug:
        Book slug (e.g. ``"01fftd"``).
    scene_number:
        Scene number within the book.

    Returns
    -------
    List of conflict description strings, or empty list if none.
    """
    return _load_merge_report(book_slug).get(scene_number, [])
