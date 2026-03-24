"""LLM enrichment phase of the parser pipeline.

Uses Claude Haiku to:
- Rewrite raw choice text from CYOA books, removing page-number references
  ("turn to N") while preserving the player-facing action and decision wording.
  (Story 5.3)
- Perform unified structured scene analysis via :func:`analyze_scene`, which
  combines entity extraction, relationship inference, and game mechanics
  detection (combat encounters, items, random outcomes, evasion, combat
  modifiers, choice conditions, and scene flags) into a single LLM call.
  Results are validated and returned as a :class:`~app.parser.types.SceneAnalysisData`.
- Extract named entities from scene narrative text individually via
  :func:`extract_entities`. (Story 5.4 — superseded by analyze_scene for
  full pipeline runs; retained for targeted entity-only passes.)
- Infer tagged relationships between entities individually via
  :func:`infer_relationships`. (Story 5.4 — superseded by analyze_scene for
  full pipeline runs; retained for targeted use.)

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

# IMPORTANT: Bump the version constants below when the corresponding prompt
# template changes, otherwise stale cached results will be served silently.
_CHOICE_REWRITE_VERSION = "v1"


def _cache_key(raw_text: str, scene_narrative: str) -> str:
    """Return a deterministic SHA-256 hex digest cache key for choice rewriting.

    Includes a version prefix so that prompt template changes invalidate the
    cache automatically when the version is bumped.

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
    content = f"{_CHOICE_REWRITE_VERSION}|{prompt}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


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
# Anthropic client resolution
# ---------------------------------------------------------------------------


def _resolve_client(client: object | None, context: str = "") -> object | None:
    """Resolve or lazily create an Anthropic client.

    When *client* is already provided, returns it unchanged.  Otherwise
    attempts ``anthropic.Anthropic()`` using the ``ANTHROPIC_API_KEY`` env
    var.  Returns ``None`` on any failure (missing package, missing key, etc.).

    Args:
        client: An existing Anthropic client instance, or ``None``.
        context: Optional label for the error log message (e.g. ``"choice rewrite"``).

    Returns:
        The resolved client, or ``None`` on failure.
    """
    if client is not None:
        return client
    try:
        import anthropic  # noqa: PLC0415

        return anthropic.Anthropic()
    except Exception as exc:  # noqa: BLE001
        ctx = f" ({context})" if context else ""
        logger.error("Failed to create Anthropic client%s: %s", ctx, exc)
        return None


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

    client = _resolve_client(client, "choice rewrite")
    if client is None:
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


# IMPORTANT: Bump when the entity extraction prompt template changes.
_ENTITY_EXTRACT_VERSION = "v1"


def _entity_cache_key(narrative: str, book_id: int) -> str:
    """Return a deterministic cache key for entity extraction.

    Args:
        narrative: Scene narrative (first 1000 chars are used in the prompt).
        book_id: Numeric book identifier.

    Returns:
        A 64-character lowercase hex string.
    """
    content = f"{_ENTITY_EXTRACT_VERSION}|book:{book_id}|entity_extract|{narrative[:1000]}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# IMPORTANT: Bump when the relationship inference prompt template changes.
_RELATIONSHIP_VERSION = "v1"


def _relationship_cache_key(entities: list[dict], scene_number: int | str) -> str:
    """Return a deterministic cache key for relationship inference.

    Args:
        entities: Entity list whose names contribute to the key.
        scene_number: Scene identifier.

    Returns:
        A 64-character lowercase hex string.
    """
    names = sorted(e.get("name", "") for e in entities)
    content = f"{_RELATIONSHIP_VERSION}|scene:{scene_number}|rel_infer|{','.join(names)}"
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

    .. deprecated::
        Use :func:`analyze_scene` instead, which combines entity extraction
        with relationship inference and structured mechanics detection in a
        single LLM call.

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
    import warnings as _warnings  # noqa: PLC0415

    _warnings.warn(
        "extract_entities() is deprecated; use analyze_scene() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

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

    client = _resolve_client(client, "entity extraction")
    if client is None:
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

    .. deprecated::
        Use :func:`analyze_scene` instead, which includes relationship
        inference as part of the unified scene analysis.

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
    import warnings as _warnings  # noqa: PLC0415

    _warnings.warn(
        "infer_relationships() is deprecated; use analyze_scene() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

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

    client = _resolve_client(client, "relationship inference")
    if client is None:
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
# Scene analysis — unified structured extraction
# ---------------------------------------------------------------------------

_SCENE_ANALYSIS_VERSION = "v3"

_SCENE_ANALYSIS_SYSTEM = """\
You are analyzing a passage from a Lone Wolf choose-your-own-adventure gamebook.
Extract ALL game mechanics from the passage and return ONLY valid JSON matching this schema.
Do not include mechanics that are not clearly present in the text.

Schema:
{
  "entities": [{"kind": "character|location|creature|organization", "name": "...", "description": "...", "aliases": []}],
  "relationships": [{"source_name": "...", "target_name": "...", "tags": ["spatial", "located_in"]}],
  "combat_encounters": [{"enemy_name": "...", "combat_skill": 16, "endurance": 24, "ordinal": 1, "mindblast_immune": false, "condition_type": "discipline|item|null", "condition_value": "Camouflage|null"}],
  "items": [{"item_name": "...", "item_type": "weapon|backpack|special|gold|meal", "quantity": 1, "action": "gain|lose"}],
  "random_outcomes": [{"range_min": 0, "range_max": 4, "effect_type": "endurance_change|gold_change|scene_redirect|item_gain|item_loss|meal_change", "effect_value": "...", "narrative_text": "...", "roll_group": 0}],
  "evasion": {"rounds": 3, "target_scene": 85, "damage": 0},
  "combat_modifiers": [{"modifier_type": "cs_bonus|cs_penalty|double_damage|undead|enemy_mindblast|helghast", "value": 2}],
  "conditions": [{"choice_ordinal": 1, "condition_type": "discipline|item|gold|random", "condition_value": "Tracking"}],
  "scene_flags": {"must_eat": false, "loses_backpack": false, "is_death": false, "is_victory": false, "mindblast_immune": false}
}

Rules:
- combat_encounters: Only extract if explicit stats with COMBAT SKILL and ENDURANCE numbers appear. For multi-enemy scenes, assign ordinal 1, 2, 3... in the order enemies are fought. Set mindblast_immune to true if the enemy is immune to Mindblast. Set condition_type/condition_value if the combat only occurs under certain conditions (e.g. "If you do not have Camouflage, you must fight" → condition_type: "discipline", condition_value: "Camouflage").
- items: Include Gold Crowns with exact quantities. Meals as item_type "meal". Named weapons/equipment as appropriate types. If no specific quantity is given, omit the item.
- item_type: "weapon" for swords/axes/daggers/etc, "backpack" for general items, "special" for unique quest items, "gold" for Gold Crowns, "meal" for meals/food/rations.
- action: "gain" if the player receives/finds/takes the item, "lose" if taken away or lost.
- random_outcomes: Only if the text describes a Random Number Table with numbered outcome bands (0-9 ranges). Use roll_group 0 for the first table, 1 for a second independent table in the same scene, etc.
- effect_value: For scene_redirect use the target scene number as a string. For endurance/gold/meal changes use a signed integer string (e.g. "-3", "+2").
- evasion: Only if explicit evasion/escape rules are stated. Use rounds: 0 if evasion is allowed from the start of combat. Set evasion to null if none.
- combat_modifiers: value is the numeric modifier (e.g. 2 for "+2 CS bonus"), or null for flags like undead/double_damage/helghast.
- conditions: Extract gate conditions from the choice text (e.g. "If you have the Kai Discipline of Tracking"). For OR conditions use JSON: {"any": ["Tracking", "Huntmastery"]}.
- entities: Only clearly named entities, not generic references like "the guard" or "a merchant".
- scene_flags: is_death = true if the scene ends the adventure in failure with no outgoing choices. is_victory = true if the scene completes the book/quest successfully. must_eat = true if the player must eat a meal. loses_backpack = true if the player loses their backpack contents. mindblast_immune = true if a combat enemy is immune to Mindblast. Default all to false.
- Return empty arrays [] and null for absent fields. Do not invent mechanics not present in the text.

Example — simple scene:
Input: "You arrive at a small village. A merchant offers to sell you a Meal for 1 Gold Crown. If you have the Kai Discipline of Sixth Sense, turn to 141. If you wish to continue north, turn to 85."
Choices: ["1. If you have the Kai Discipline of Sixth Sense, turn to 141.", "2. If you wish to continue north, turn to 85."]
Output: {"entities": [{"kind": "location", "name": "Village", "description": "A small village with a merchant", "aliases": []}], "relationships": [], "combat_encounters": [], "items": [], "random_outcomes": [], "evasion": null, "combat_modifiers": [], "conditions": [{"choice_ordinal": 1, "condition_type": "discipline", "condition_value": "Sixth Sense"}], "scene_flags": {"must_eat": false, "loses_backpack": false, "is_death": false, "is_victory": false, "mindblast_immune": false}}

Example — combat scene with evasion and items:
Input: "A Kraan swoops from the sky. It is immune to Mindblast. You must fight it. Kraan: COMBAT SKILL 16 ENDURANCE 24. You may evade combat after 3 rounds by turning to 85, but you lose 2 ENDURANCE points. You find a Sword and 7 Gold Crowns. You must eat a Meal here."
Output: {"entities": [{"kind": "creature", "name": "Kraan", "description": "A flying reptilian creature", "aliases": []}], "relationships": [], "combat_encounters": [{"enemy_name": "Kraan", "combat_skill": 16, "endurance": 24, "ordinal": 1}], "items": [{"item_name": "Sword", "item_type": "weapon", "quantity": 1, "action": "gain"}, {"item_name": "Gold Crowns", "item_type": "gold", "quantity": 7, "action": "gain"}], "random_outcomes": [], "evasion": {"rounds": 3, "target_scene": 85, "damage": 2}, "combat_modifiers": [], "conditions": [], "scene_flags": {"must_eat": true, "loses_backpack": false, "is_death": false, "is_victory": false, "mindblast_immune": true}}"""

_SCENE_ANALYSIS_USER = """\
Book {book_number}, Scene {scene_number}:

{narrative}

Choices:
{choices_text}

Return JSON:"""

_VALID_ITEM_TYPES = frozenset({"weapon", "backpack", "special", "gold", "meal"})
_VALID_ACTIONS = frozenset({"gain", "lose"})
_VALID_EFFECT_TYPES = frozenset({
    "endurance_change", "gold_change", "scene_redirect",
    "item_gain", "item_loss", "meal_change",
})
_VALID_MODIFIER_TYPES = frozenset({
    "cs_bonus", "cs_penalty", "double_damage", "undead", "enemy_mindblast", "helghast",
})
_VALID_CONDITION_TYPES = frozenset({"discipline", "item", "gold", "random"})
_VALID_FLAG_KEYS = frozenset({
    "must_eat", "loses_backpack", "is_death", "is_victory", "mindblast_immune",
})


def _scene_analysis_cache_key(
    narrative: str, book_id: int, scene_number: int,
) -> str:
    """Return a deterministic cache key for unified scene analysis.

    The key encodes the schema version (``_SCENE_ANALYSIS_VERSION``), book,
    scene, and the first 3000 characters of the narrative.  Changing the
    version string invalidates all prior cache entries.

    Args:
        narrative: Scene narrative text (first 3000 chars are used).
        book_id: Numeric book identifier.
        scene_number: Scene number within the book.

    Returns:
        A 64-character lowercase hex string.
    """
    content = (
        f"{_SCENE_ANALYSIS_VERSION}|book:{book_id}|scene:{scene_number}"
        f"|scene_analysis|{narrative[:3000]}"
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _coerce_int(val: object) -> int | None:
    """Coerce a value to int if possible (handles LLM returning 16.0 as float)."""
    if isinstance(val, int) and not isinstance(val, bool):
        return val
    if isinstance(val, float) and val == int(val):
        return int(val)
    return None


def _validate_scene_analysis(raw: object) -> dict | None:
    """Validate and normalize a parsed scene analysis JSON object.

    Each section is validated independently using the ``_VALID_*`` frozensets
    defined in this module.  Invalid or malformed entries within a section are
    silently dropped rather than failing the whole result — the function is
    permissive about individual fields so that a partially valid LLM response
    still yields useful output.

    Validated sections (all present as keys on the returned dict):

    - ``entities`` — kind/name validated; deduplication against the catalog is
      done by the caller (:func:`analyze_scene`).
    - ``relationships`` — source_name/target_name required.
    - ``combat_encounters`` — enemy_name, combat_skill, endurance required and
      typed.
    - ``items`` — item_name, item_type, action validated against allowlists.
    - ``random_outcomes`` — range_min/max integers, effect_type validated.
    - ``evasion`` — rounds/target_scene integers required; ``None`` if absent
      or malformed.
    - ``combat_modifiers`` — modifier_type validated against allowlist.
    - ``conditions`` — condition_type validated; choice_ordinal must be int.
    - ``scene_flags`` — all five boolean flags normalized; missing flags default
      to ``False``.

    Args:
        raw: Parsed Python object from :func:`_parse_json_llm`.

    Returns:
        A cleaned dict with all expected section keys, or ``None`` if *raw*
        is not a dict.
    """
    if not isinstance(raw, dict):
        return None

    result: dict = {}

    # Entities — reuse existing filter
    raw_entities = raw.get("entities", [])
    if isinstance(raw_entities, list):
        validated: list[dict] = []
        for e in raw_entities:
            if not isinstance(e, dict):
                continue
            name = e.get("name", "").strip()
            kind = e.get("kind", "").lower()
            if name and kind in _ENTITY_KINDS:
                aliases = e.get("aliases", [])
                if not isinstance(aliases, list):
                    aliases = []
                validated.append({
                    "kind": kind, "name": name,
                    "description": e.get("description", ""),
                    "aliases": aliases,
                })
        result["entities"] = validated
    else:
        result["entities"] = []

    # Relationships
    raw_rels = raw.get("relationships", [])
    if isinstance(raw_rels, list):
        result["relationships"] = _filter_relationships(raw_rels)
    else:
        result["relationships"] = []

    # Combat encounters
    raw_combats = raw.get("combat_encounters", [])
    validated_combats: list[dict] = []
    if isinstance(raw_combats, list):
        for c in raw_combats:
            if not isinstance(c, dict):
                continue
            name = c.get("enemy_name", "").strip()
            cs = _coerce_int(c.get("combat_skill"))
            end = _coerce_int(c.get("endurance"))
            if name and cs is not None and end is not None:
                enc: dict = {
                    "enemy_name": name,
                    "enemy_cs": cs,
                    "enemy_end": end,
                    "ordinal": c.get("ordinal", 1),
                    "mindblast_immune": bool(c.get("mindblast_immune", False)),
                }
                # Optional conditional combat fields
                cond_type = c.get("condition_type")
                if cond_type and cond_type in _VALID_CONDITION_TYPES:
                    cond_val = c.get("condition_value")
                    enc["condition_type"] = cond_type
                    enc["condition_value"] = str(cond_val) if cond_val else None
                else:
                    enc["condition_type"] = None
                    enc["condition_value"] = None
                validated_combats.append(enc)
    result["combat_encounters"] = validated_combats

    # Items
    raw_items = raw.get("items", [])
    validated_items: list[dict] = []
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            iname = item.get("item_name", "").strip()
            itype = item.get("item_type", "").lower()
            action = item.get("action", "").lower()
            if iname and itype in _VALID_ITEM_TYPES and action in _VALID_ACTIONS:
                validated_items.append({
                    "item_name": iname,
                    "item_type": itype,
                    "quantity": _coerce_int(item.get("quantity")) or 1,
                    "action": action,
                })
    result["items"] = validated_items

    # Random outcomes
    raw_outcomes = raw.get("random_outcomes", [])
    validated_outcomes: list[dict] = []
    if isinstance(raw_outcomes, list):
        for o in raw_outcomes:
            if not isinstance(o, dict):
                continue
            rmin = _coerce_int(o.get("range_min"))
            rmax = _coerce_int(o.get("range_max"))
            etype = o.get("effect_type", "")
            if rmin is not None and rmax is not None and etype in _VALID_EFFECT_TYPES:
                validated_outcomes.append({
                    "range_min": rmin,
                    "range_max": rmax,
                    "effect_type": etype,
                    "effect_value": str(o.get("effect_value", "")),
                    "narrative_text": o.get("narrative_text"),
                    "roll_group": _coerce_int(o.get("roll_group")) or 0,
                })
    result["random_outcomes"] = validated_outcomes

    # Evasion
    raw_evasion = raw.get("evasion")
    if isinstance(raw_evasion, dict):
        rounds = _coerce_int(raw_evasion.get("rounds"))
        target = _coerce_int(raw_evasion.get("target_scene"))
        if rounds is not None and target is not None:
            damage = _coerce_int(raw_evasion.get("damage"))
            result["evasion"] = {
                "rounds": rounds,
                "target_scene": target,
                "damage": damage if damage is not None else 0,
            }
        else:
            result["evasion"] = None
    else:
        result["evasion"] = None

    # Combat modifiers
    raw_mods = raw.get("combat_modifiers", [])
    validated_mods: list[dict] = []
    if isinstance(raw_mods, list):
        for m in raw_mods:
            if not isinstance(m, dict):
                continue
            mtype = m.get("modifier_type", "")
            if mtype in _VALID_MODIFIER_TYPES:
                val = m.get("value")
                validated_mods.append({
                    "modifier_type": mtype,
                    "value": val if isinstance(val, int) else None,
                })
    result["combat_modifiers"] = validated_mods

    # Conditions
    raw_conditions = raw.get("conditions", [])
    validated_conditions: list[dict] = []
    if isinstance(raw_conditions, list):
        for cond in raw_conditions:
            if not isinstance(cond, dict):
                continue
            ctype = cond.get("condition_type", "")
            cval = cond.get("condition_value")
            ordinal = cond.get("choice_ordinal")
            if ctype in _VALID_CONDITION_TYPES and isinstance(ordinal, int):
                # condition_value can be str, dict, or None
                if isinstance(cval, dict):
                    cval = json.dumps(cval)
                elif cval is not None:
                    cval = str(cval)
                validated_conditions.append({
                    "choice_ordinal": ordinal,
                    "condition_type": ctype,
                    "condition_value": cval,
                })
    result["conditions"] = validated_conditions

    # Scene flags
    raw_flags = raw.get("scene_flags", {})
    if isinstance(raw_flags, dict):
        result["scene_flags"] = {
            k: bool(raw_flags.get(k, False)) for k in _VALID_FLAG_KEYS
        }
    else:
        result["scene_flags"] = {k: False for k in _VALID_FLAG_KEYS}

    return result


def analyze_scene(
    narrative: str,
    choices_raw: list[str],
    book_id: int,
    scene_number: int,
    existing_catalog: dict,
    client: object | None = None,
    skip_llm: bool = False,
    no_cache: bool = False,
) -> "SceneAnalysisData | None":
    """Perform comprehensive scene analysis using Claude Haiku.

    Combines entity extraction, relationship inference, and structured game
    mechanics extraction into a single LLM call.  Replaces separate calls to
    :func:`extract_entities` and :func:`infer_relationships` with a unified
    prompt that also detects combat encounters, items, conditions, random
    outcomes, evasion rules, combat modifiers, and scene flags.

    Args:
        narrative: Plain-text narrative of the scene.
        choices_raw: List of raw choice texts for the scene (used for
            condition extraction).
        book_id: Numeric book identifier.
        scene_number: Scene number within the book.
        existing_catalog: Dict mapping lower-cased entity name to entity data.
            Entities already in the catalog are excluded from the result.
        client: Optional pre-configured Anthropic client.
        skip_llm: When ``True`` return ``None`` without calling the LLM.
        no_cache: When ``True`` bypass the file-based response cache.

    Returns:
        A :class:`~app.parser.types.SceneAnalysisData` with the full
        structured extraction, or ``None`` on skip/error/empty narrative.
    """
    from app.parser.types import SceneAnalysisData  # noqa: PLC0415

    if skip_llm:
        return None

    if not narrative or not narrative.strip():
        return None

    key = _scene_analysis_cache_key(narrative, book_id, scene_number)

    if not no_cache:
        cached_raw = _get_cached(key)
        if cached_raw is not None:
            logger.debug("Cache hit for scene analysis (book %d, scene %d)", book_id, scene_number)
            parsed = _parse_json_llm(cached_raw)
            validated = _validate_scene_analysis(parsed)
            if validated is not None:
                # Filter entities against catalog
                validated["entities"] = _filter_new_entities(
                    validated["entities"], existing_catalog,
                )
                return SceneAnalysisData(**validated)

    client = _resolve_client(client, "scene analysis")
    if client is None:
        return None

    # Build choices text for the prompt
    if choices_raw:
        choices_text = "\n".join(
            f"{i + 1}. {text}" for i, text in enumerate(choices_raw)
        )
    else:
        choices_text = "(no choices — this may be a death or victory scene)"

    user_prompt = _SCENE_ANALYSIS_USER.format(
        book_number=book_id,
        scene_number=scene_number,
        narrative=narrative[:3000],
        choices_text=choices_text,
    )

    try:
        message = client.messages.create(  # type: ignore[union-attr]
            model=_MODEL,
            max_tokens=4096,
            system=_SCENE_ANALYSIS_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw_text: str = message.content[0].text.strip()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Scene analysis LLM call failed for book %d scene %d: %s",
            book_id, scene_number, exc,
        )
        return None

    if not no_cache:
        _set_cached(key, raw_text, user_prompt)

    parsed_data = _parse_json_llm(raw_text)
    validated = _validate_scene_analysis(parsed_data)
    if validated is None:
        logger.warning(
            "Scene analysis returned invalid data for book %d scene %d",
            book_id, scene_number,
        )
        return None

    # Filter entities against existing catalog
    validated["entities"] = _filter_new_entities(
        validated["entities"], existing_catalog,
    )

    return SceneAnalysisData(**validated)


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
