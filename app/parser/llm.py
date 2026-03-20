"""LLM enrichment phase of the parser pipeline.

Uses Claude Haiku to:
- Rewrite raw choice text from CYOA books, removing page-number references
  ("turn to N") while preserving the player-facing action and decision wording.
  (Story 5.3)
- Extract named entities from scene narrative text. (Story 5.4)
- Infer tagged relationships between entities. (Story 5.4)

This module is standalone — it is never imported by the API at runtime.
Results are cached to ``.parser_cache/`` to avoid redundant API calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(".parser_cache")
_MODEL = "claude-haiku-4-5-20251001"

_PROMPT_TEMPLATE = """\
Rewrite this choice from a choose-your-own-adventure book to remove page number references.
Keep the action/decision clear. Do not add information that isn't in the original.

Scene context: {scene_context}

Original choice: {raw_text}

Rewritten choice (no page numbers):"""


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(raw_text: str, scene_narrative: str) -> str:
    """Return a deterministic SHA-256 hex digest cache key for the given inputs.

    The key is derived from the full prompt template rendered with the provided
    inputs, so any change to the text or narrative produces a different key.

    Args:
        raw_text: The raw choice text from the book.
        scene_narrative: The narrative context for the scene.

    Returns:
        A 64-character lowercase hex string.
    """
    prompt = _PROMPT_TEMPLATE.format(
        scene_context=scene_narrative[:500],
        raw_text=raw_text,
    )
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _get_cached(cache_key: str) -> str | None:
    """Load a cached LLM response from ``.parser_cache/{cache_key}.json``.

    Args:
        cache_key: Hex digest returned by :func:`_cache_key`.

    Returns:
        The cached ``response`` string, or ``None`` if no cache entry exists.
    """
    cache_file = _CACHE_DIR / f"{cache_key}.json"
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return str(data["response"])
    except (json.JSONDecodeError, KeyError, OSError) as exc:
        logger.warning("Failed to read cache file %s: %s", cache_file, exc)
        return None


def _set_cached(cache_key: str, result: str, prompt: str) -> None:
    """Save an LLM response to ``.parser_cache/{cache_key}.json``.

    The cache entry includes the prompt, response, timestamp (ISO-8601 UTC),
    and model identifier so entries can be audited later.

    Args:
        cache_key: Hex digest returned by :func:`_cache_key`.
        result: The LLM response text to cache.
        prompt: The full prompt that produced this response.
    """
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _CACHE_DIR / f"{cache_key}.json"
    entry = {
        "prompt": prompt,
        "response": result,
        "timestamp": datetime.now(UTC).isoformat(),
        "model": _MODEL,
    }
    try:
        cache_file.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write cache file %s: %s", cache_file, exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rewrite_choice(
    raw_text: str,
    scene_narrative: str,
    client: object | None = None,
    skip_llm: bool = False,
    no_cache: bool = False,
) -> str:
    """Rewrite a single choice to remove page-number references.

    When ``skip_llm`` is ``True`` the function returns ``raw_text`` unchanged.
    When ``no_cache`` is ``True`` the cache is bypassed for both reads and
    writes. On any LLM API error the function falls back to ``raw_text``.

    Args:
        raw_text: The raw choice text extracted from the XHTML source.
        scene_narrative: Narrative text of the scene owning this choice, used
            as context for the LLM rewrite.
        client: An ``anthropic.Anthropic`` client instance.  When ``None`` a
            new client is created using the ``ANTHROPIC_API_KEY`` environment
            variable.
        skip_llm: If ``True``, skip the LLM call and return ``raw_text`` as-is.
        no_cache: If ``True``, bypass the file-based response cache.

    Returns:
        The rewritten display text (or ``raw_text`` on skip/error).
    """
    if skip_llm:
        return raw_text

    prompt = _PROMPT_TEMPLATE.format(
        scene_context=scene_narrative[:500],
        raw_text=raw_text,
    )
    key = _cache_key(raw_text, scene_narrative)

    if not no_cache:
        cached = _get_cached(key)
        if cached is not None:
            logger.debug("Cache hit for choice: %r", raw_text[:60])
            return cached

    # Resolve or create the Anthropic client
    if client is None:
        try:
            import anthropic

            client = anthropic.Anthropic()
        except Exception as exc:
            logger.error("Failed to create Anthropic client: %s", exc)
            return raw_text

    try:
        # client is typed as object to avoid a hard import at module level;
        # we access the messages API via attribute access.
        message = client.messages.create(  # type: ignore[union-attr]
            model=_MODEL,
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        result: str = message.content[0].text.strip()
    except Exception as exc:
        logger.error("LLM rewrite failed for choice %r: %s", raw_text[:60], exc)
        return raw_text

    if not no_cache:
        _set_cached(key, result, prompt)

    return result


def rewrite_choices_batch(
    choices: list[object],
    scene_narrative: str,
    skip_llm: bool = False,
    no_cache: bool = False,
    client: object | None = None,
) -> list[str]:
    """Rewrite all choices for a scene and return display texts in order.

    This is a convenience wrapper that calls :func:`rewrite_choice` for every
    element in *choices*.  Each element is expected to have a ``raw_text``
    attribute (i.e. a :class:`~app.parser.types.ChoiceData` instance).

    Args:
        choices: List of :class:`~app.parser.types.ChoiceData` instances.
        scene_narrative: Narrative text of the owning scene.
        skip_llm: Passed through to :func:`rewrite_choice`.
        no_cache: Passed through to :func:`rewrite_choice`.
        client: Passed through to :func:`rewrite_choice`.

    Returns:
        A list of rewritten display strings in the same order as *choices*.
    """
    results: list[str] = []
    for choice in choices:
        raw_text: str = getattr(choice, "raw_text", "")
        display_text = rewrite_choice(
            raw_text=raw_text,
            scene_narrative=scene_narrative,
            client=client,
            skip_llm=skip_llm,
            no_cache=no_cache,
        )
        results.append(display_text)
    return results


# ---------------------------------------------------------------------------
# Entity extraction (Story 5.4)
# ---------------------------------------------------------------------------

_ENTITY_KINDS = frozenset({"character", "location", "creature", "organization"})

_ENTITY_PROMPT_TEMPLATE = """\
Extract named entities from this Lone Wolf gamebook passage.
For each entity, provide: kind (character/location/creature/organization), name, brief description, and any aliases.

Return as JSON array. Only include entities that are clearly named (not generic like "the guard" or "the door").

Passage: {narrative}"""


def _entity_cache_key(narrative: str, book_id: int) -> str:
    """Return a deterministic cache key for entity extraction.

    Args:
        narrative: Scene narrative (first 1000 chars are used in the prompt).
        book_id: Numeric book identifier.

    Returns:
        A 64-character lowercase hex string.
    """
    content = f"book:{book_id}|entity_extract|{narrative[:1000]}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _relationship_cache_key(entities: list[dict], scene_number: int | str) -> str:
    """Return a deterministic cache key for relationship inference.

    Args:
        entities: Entity list whose names contribute to the key.
        scene_number: Scene identifier.

    Returns:
        A 64-character lowercase hex string.
    """
    names = sorted(e.get("name", "") for e in entities)
    content = f"scene:{scene_number}|rel_infer|{','.join(names)}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_json_llm(text: str) -> object:
    """Parse a JSON value from an LLM response, stripping markdown fences.

    Returns the parsed Python object, or ``None`` on parse failure.

    Args:
        text: Raw text returned by the LLM.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner: list[str] = []
        for line in lines[1:]:
            if line.strip() == "```":
                break
            inner.append(line)
        stripped = "\n".join(inner).strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse LLM JSON response: %s — raw: %.200s", exc, text)
        return None


def _filter_new_entities(raw_entities: list, existing_catalog: dict) -> list[dict]:
    """Filter and validate raw entity dicts from LLM output.

    Removes entities already in the catalog (case-insensitive name match),
    those with unknown kinds, or those missing a name.

    Args:
        raw_entities: List of raw entity dicts from the LLM.
        existing_catalog: Dict mapping lower-cased name → entity data.

    Returns:
        A list of validated, deduplicated entity dicts.
    """
    results: list[dict] = []
    for entity in raw_entities:
        if not isinstance(entity, dict):
            continue
        name: str = entity.get("name", "").strip()
        if not name:
            continue
        if name.lower() in existing_catalog:
            logger.debug("Skipping duplicate entity %r (already in catalog)", name)
            continue
        kind = entity.get("kind", "").lower()
        if kind not in _ENTITY_KINDS:
            logger.debug("Unknown entity kind %r for %r; skipping", kind, name)
            continue
        aliases = entity.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = []
        results.append(
            {
                "kind": kind,
                "name": name,
                "description": entity.get("description", ""),
                "aliases": aliases,
            }
        )
    return results


def extract_entities(
    narrative: str,
    book_id: int,
    existing_catalog: dict,
    client: object | None = None,
    skip_entities: bool = False,
    no_cache: bool = False,
) -> list[dict]:
    """Extract named entities from a scene narrative using Claude Haiku.

    Entities are deduplicated against *existing_catalog* (case-insensitive on
    name) so that previously seen entities are not returned again.

    Each returned entity dict has the shape::

        {
            "kind": "character" | "location" | "creature" | "organization",
            "name": str,
            "description": str,
            "aliases": list[str],
        }

    Args:
        narrative: Plain-text narrative of the scene.
        book_id: Numeric book identifier (used in the LLM system prompt and cache key).
        existing_catalog: Dict mapping lower-cased entity name → entity data.
            Entities whose names already appear in this catalog are excluded.
        client: Optional pre-configured Anthropic client.  When ``None`` a new
            client is constructed using the ``ANTHROPIC_API_KEY`` env var.
        skip_entities: When ``True`` return an empty list without calling the LLM.
        no_cache: When ``True`` bypass the file-based response cache.

    Returns:
        A list of entity dicts for newly discovered entities not in the
        existing catalog.  Returns an empty list on any LLM or parse failure.
    """
    if skip_entities:
        return []

    if not narrative or not narrative.strip():
        return []

    key = _entity_cache_key(narrative, book_id)

    if not no_cache:
        cached_raw = _get_cached(key)
        if cached_raw is not None:
            logger.debug("Cache hit for entity extraction (book %d)", book_id)
            parsed = _parse_json_llm(cached_raw)
            if isinstance(parsed, list):
                return _filter_new_entities(parsed, existing_catalog)

    # Resolve or create the Anthropic client
    if client is None:
        try:
            import anthropic  # noqa: PLC0415

            client = anthropic.Anthropic()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to create Anthropic client: %s", exc)
            return []

    prompt = _ENTITY_PROMPT_TEMPLATE.format(narrative=narrative[:1000])

    try:
        message = client.messages.create(  # type: ignore[union-attr]
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text: str = message.content[0].text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Entity extraction LLM call failed for book %d: %s", book_id, exc)
        return []

    if not no_cache:
        _set_cached(key, raw_text, prompt)

    parsed_data = _parse_json_llm(raw_text)
    if not isinstance(parsed_data, list):
        logger.warning(
            "Entity extraction returned non-list for book %d; got %r",
            book_id,
            type(parsed_data),
        )
        return []

    return _filter_new_entities(parsed_data, existing_catalog)


# ---------------------------------------------------------------------------
# Relationship inference (Story 5.4)
# ---------------------------------------------------------------------------

_RELATIONSHIP_PROMPT_TEMPLATE = """\
Identify relationships between the following entities from a Lone Wolf gamebook scene.

Scene {scene_number} narrative snippet: {narrative_snippet}

Entities:
{entities_json}

Return a JSON array of relationships. Each relationship has:
- "source_name": name of the source entity
- "target_name": name of the target entity
- "tags": list of relationship tags (e.g. ["appearance", "combatant"], ["spatial", "located_in"], ["faction", "member_of"])

Only return relationships clearly supported by the scene text."""


def _filter_relationships(raw_rels: list) -> list[dict]:
    """Validate and filter raw relationship dicts from LLM output.

    Args:
        raw_rels: List of raw relationship dicts from the LLM.

    Returns:
        A list of validated relationship dicts with source_name, target_name, and tags.
    """
    results: list[dict] = []
    for rel in raw_rels:
        if not isinstance(rel, dict):
            continue
        source = rel.get("source_name", "").strip()
        target = rel.get("target_name", "").strip()
        if not source or not target:
            continue
        tags = rel.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        results.append({"source_name": source, "target_name": target, "tags": tags})
    return results


def infer_relationships(
    entities: list[dict],
    scene_context: dict,
    client: object | None = None,
    no_cache: bool = False,
) -> list[dict]:
    """Infer tagged relationships between entities using Claude Haiku.

    Returns a list of ref dicts following the tagged ref pattern::

        {
            "source_name": str,
            "target_name": str,
            "tags": list[str],
        }

    Tags follow the project tagged ref conventions, for example:
    ``["appearance", "combatant"]`` or ``["spatial", "located_in"]``.

    Args:
        entities: List of entity dicts (as returned by :func:`extract_entities`).
        scene_context: Dict with scene metadata.  Expected keys: ``scene_number``
            (int or str) and ``narrative`` (str).
        client: Optional pre-configured Anthropic client.
        no_cache: When ``True`` bypass the file-based response cache.

    Returns:
        A list of relationship ref dicts.  Returns an empty list when fewer than
        2 entities are provided, or on LLM / parse failure.
    """
    if len(entities) < 2:
        return []

    scene_number = scene_context.get("scene_number", "unknown")
    narrative_snippet = str(scene_context.get("narrative", ""))[:500]

    key = _relationship_cache_key(entities, scene_number)

    if not no_cache:
        cached_raw = _get_cached(key)
        if cached_raw is not None:
            logger.debug("Cache hit for relationship inference (scene %s)", scene_number)
            parsed = _parse_json_llm(cached_raw)
            if isinstance(parsed, list):
                return _filter_relationships(parsed)

    # Resolve or create the Anthropic client
    if client is None:
        try:
            import anthropic  # noqa: PLC0415

            client = anthropic.Anthropic()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to create Anthropic client: %s", exc)
            return []

    entities_json = json.dumps(
        [{"name": e.get("name"), "kind": e.get("kind")} for e in entities],
        indent=2,
    )
    prompt = _RELATIONSHIP_PROMPT_TEMPLATE.format(
        scene_number=scene_number,
        narrative_snippet=narrative_snippet,
        entities_json=entities_json,
    )

    try:
        message = client.messages.create(  # type: ignore[union-attr]
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text: str = message.content[0].text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Relationship inference LLM call failed for scene %s: %s", scene_number, exc
        )
        return []

    if not no_cache:
        _set_cached(key, raw_text, prompt)

    parsed_data = _parse_json_llm(raw_text)
    if not isinstance(parsed_data, list):
        logger.warning("Relationship inference returned non-list; got %r", type(parsed_data))
        return []

    return _filter_relationships(parsed_data)


# ---------------------------------------------------------------------------
# Game object creation helpers (Story 5.4)
# ---------------------------------------------------------------------------


def create_item_game_object(item_data: dict) -> dict:
    """Create a game_object dict for kind='item' from raw item data.

    Args:
        item_data: Dict with at minimum ``item_name`` and ``item_type`` keys.
            Optional keys: ``quantity``, ``description``.

    Returns:
        A game_object dict with ``kind``, ``name``, ``item_type``,
        ``quantity``, and ``description`` keys.
    """
    return {
        "kind": "item",
        "name": item_data.get("item_name", ""),
        "item_type": item_data.get("item_type", "backpack"),
        "quantity": item_data.get("quantity", 1),
        "description": item_data.get("description", ""),
    }


def create_foe_game_object(combat_data: dict) -> dict:
    """Create a game_object dict for kind='foe' from raw combat data.

    Args:
        combat_data: Dict with ``enemy_name``, ``enemy_cs``, and ``enemy_end``
            keys (as produced by the extract phase).  Optional: ``ordinal``,
            ``description``.

    Returns:
        A game_object dict with ``kind``, ``name``, ``combat_skill``,
        ``endurance``, ``ordinal``, and ``description`` keys.
    """
    return {
        "kind": "foe",
        "name": combat_data.get("enemy_name", ""),
        "combat_skill": combat_data.get("enemy_cs", 0),
        "endurance": combat_data.get("enemy_end", 0),
        "ordinal": combat_data.get("ordinal", 1),
        "description": combat_data.get("description", ""),
    }


def create_scene_game_object(scene_data: dict) -> dict:
    """Create a game_object dict for kind='scene' from raw scene data.

    Args:
        scene_data: Dict with at minimum ``number`` and ``html_id`` keys.
            Optional keys: ``narrative``, ``illustration_path``.

    Returns:
        A game_object dict with ``kind``, ``scene_number``, ``html_id``,
        ``narrative_snippet``, and ``illustration_path`` keys.
    """
    narrative = scene_data.get("narrative", "")
    return {
        "kind": "scene",
        "scene_number": scene_data.get("number", 0),
        "html_id": scene_data.get("html_id", ""),
        "narrative_snippet": narrative[:200] if narrative else "",
        "illustration_path": scene_data.get("illustration_path"),
    }
