"""Orchestration pipeline for the Lone Wolf book parser.

Runs the full extract → transform → LLM enrich → load sequence for a single
XHTML book file.  All stages are coordinated here; individual stages are kept
in their own modules (extract, transform, llm, load).

Usage::

    from app.parser.pipeline import run_pipeline, PipelineResult

    result = run_pipeline("/path/to/01fftd.xhtml", options={})
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from app.database import SessionLocal
from app.parser.extract import (
    _parse_xhtml,
    copy_illustrations,
    extract_book_metadata,
    extract_crt,
    extract_disciplines,
    extract_scenes,
    extract_starting_equipment,
)
from app.parser.transform import (
    classify_condition,
    detect_backpack_loss,
    detect_combat_modifiers,
    detect_death_scene,
    detect_evasion,
    detect_items,
    detect_mindblast_immunity,
    detect_must_eat,
    detect_random_outcomes,
    detect_victory_scene,
)
from app.parser.types import BookData, SceneData

logger = logging.getLogger(__name__)

# Where illustrations are copied to under the project root
_DEFAULT_ILLUSTRATIONS_DEST = Path("static/images")


@dataclass
class PipelineResult:
    """Result of a single pipeline run for one book.

    Attributes:
        book_data: Extracted book metadata.
        counts: Dict of entity type → count for the loaded/processed rows.
        warnings: List of warning strings collected during the run.
    """

    book_data: BookData
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal transform helpers
# ---------------------------------------------------------------------------


def _transform_scenes(scenes: list[SceneData]) -> tuple[list[dict], list[dict], list[str]]:
    """Transform extracted scenes into load-ready dicts.

    Returns:
        (scene_dicts, encounter_dicts, warnings)
    """
    scene_dicts: list[dict] = []
    encounter_dicts: list[dict] = []
    warnings: list[str] = []

    for scene in scenes:
        choice_texts = [c.raw_text for c in scene.choices]

        must_eat = detect_must_eat(scene.narrative)
        loses_backpack = detect_backpack_loss(scene.narrative)
        is_death = detect_death_scene(scene.narrative, choice_texts)
        is_victory = detect_victory_scene(scene.narrative, choice_texts)
        evasion = detect_evasion(scene.narrative)
        mindblast_immune = detect_mindblast_immunity(scene.narrative)
        combat_modifiers = detect_combat_modifiers(scene.narrative)
        random_outcomes = detect_random_outcomes(scene.narrative)

        scene_dict: dict = {
            "number": scene.number,
            "html_id": scene.html_id,
            "narrative": scene.narrative,
            "illustration_path": scene.illustration_path,
            "is_death": is_death,
            "is_victory": is_victory,
            "must_eat": must_eat,
            "loses_backpack": loses_backpack,
            "source": "auto",
            "_random_outcomes": random_outcomes,
            "_mindblast_immune": mindblast_immune,
        }
        scene_dicts.append(scene_dict)

        for combat in scene.combat_encounters:
            enc_dict: dict = {
                "scene_number": scene.number,
                "enemy_name": combat.enemy_name,
                "enemy_cs": combat.enemy_cs,
                "enemy_end": combat.enemy_end,
                "ordinal": combat.ordinal,
                "mindblast_immune": mindblast_immune,
                "condition_type": None,
                "condition_value": None,
                "source": "auto",
                "modifiers": [
                    {
                        "modifier_type": m["modifier_type"],
                        "modifier_value": m.get("value"),
                        "condition": None,
                        "source": "auto",
                    }
                    for m in combat_modifiers
                ],
            }
            if evasion is not None:
                enc_dict["evasion_after_rounds"] = evasion[0]
                enc_dict["evasion_target"] = evasion[1]
                enc_dict["evasion_damage"] = evasion[2]
            else:
                enc_dict["evasion_after_rounds"] = None
                enc_dict["evasion_target"] = None
                enc_dict["evasion_damage"] = 0
            encounter_dicts.append(enc_dict)

    return scene_dicts, encounter_dicts, warnings


def _transform_choices(
    scenes: list[SceneData],
) -> tuple[list[dict], list[str]]:
    """Transform extracted choices into load-ready dicts (before LLM rewrite).

    Returns:
        (choice_dicts, warnings)
    """
    choice_dicts: list[dict] = []
    warnings: list[str] = []

    for scene in scenes:
        for choice in scene.choices:
            condition_type, condition_value = classify_condition(choice.raw_text)
            choice_dict: dict = {
                "scene_number": scene.number,
                "target_scene_number": choice.target_scene_number,
                "raw_text": choice.raw_text,
                "display_text": choice.raw_text,  # overwritten after LLM step
                "condition_type": condition_type,
                "condition_value": condition_value,
                "ordinal": choice.ordinal,
                "source": "auto",
            }
            choice_dicts.append(choice_dict)

    return choice_dicts, warnings


def _transform_items(scene_dicts: list[dict]) -> tuple[list[dict], list[str]]:
    """Detect items from scene narratives and return load-ready item dicts.

    Returns:
        (item_dicts, warnings)
    """
    item_dicts: list[dict] = []
    warnings: list[str] = []

    for scene in scene_dicts:
        detected = detect_items(scene["narrative"])
        for ordinal, item in enumerate(detected):
            item_dict: dict = {
                "scene_number": scene["number"],
                "item_name": item["item_name"],
                "item_type": item["item_type"],
                "quantity": item.get("quantity", 1),
                "action": item["action"],
                "is_mandatory": False,
                "phase_ordinal": ordinal,
                "source": "auto",
            }
            item_dicts.append(item_dict)

    return item_dicts, warnings


def _format_effect_value(effect_type: str, raw_value: str) -> str:
    """Convert a flat effect_value string to the JSON format expected by the DB.

    The LLM produces simple strings (e.g. ``"85"``, ``"-3"``, ``"Sword"``).
    The load phase expects JSON objects (e.g. ``{"scene_number": 85}``).

    Args:
        effect_type: The effect type (e.g. ``"scene_redirect"``).
        raw_value: The raw string value from the LLM or manual extraction.

    Returns:
        A JSON-encoded string suitable for the ``effect_value`` DB column.
    """
    import json as _json  # noqa: PLC0415

    raw = raw_value.strip() if raw_value else ""

    if effect_type == "scene_redirect" and raw:
        try:
            return _json.dumps({"scene_number": int(raw)})
        except (ValueError, TypeError):
            return raw

    if effect_type in ("endurance_change", "gold_change", "meal_change") and raw:
        try:
            return _json.dumps({"amount": int(raw)})
        except (ValueError, TypeError):
            return raw

    if effect_type in ("item_gain", "item_loss") and raw:
        return _json.dumps({"item_name": raw})

    return raw


def _collect_random_outcomes(scene_dicts: list[dict]) -> list[dict]:
    """Flatten per-scene random outcomes from the _random_outcomes key."""
    outcome_dicts: list[dict] = []
    for scene in scene_dicts:
        for ordinal, outcome in enumerate(scene.get("_random_outcomes", [])):
            etype = outcome["effect_type"]
            raw_val = str(outcome.get("effect_value", ""))
            outcome_dict: dict = {
                "scene_number": scene["number"],
                "roll_group": 0,
                "range_min": outcome["range_min"],
                "range_max": outcome["range_max"],
                "effect_type": etype,
                "effect_value": _format_effect_value(etype, raw_val),
                "narrative_text": outcome.get("narrative_text"),
                "ordinal": ordinal,
                "source": "auto",
            }
            outcome_dicts.append(outcome_dict)
    return outcome_dicts


# ---------------------------------------------------------------------------
# LLM enrichment
# ---------------------------------------------------------------------------


def _enrich_with_llm(
    scenes: list[SceneData],
    choice_dicts: list[dict],
    scene_dicts: list[dict],
    encounter_dicts: list[dict],
    item_dicts: list[dict],
    random_outcome_dicts: list[dict],
    book_id: int,
    skip_llm: bool,
    skip_entities: bool,
    skip_choice_rewrite: bool,
    no_cache: bool,
    client: object | None,
) -> "EnrichmentResult":
    """Run LLM rewrite + scene analysis over all scenes, merging with manual results.

    When ``skip_llm`` is True, ALL LLM calls are skipped.
    When ``skip_entities`` is True, only choice rewriting runs (no scene analysis).
    When ``skip_choice_rewrite`` is True, only scene analysis runs (no choice rewriting).
    This allows ``entities_only`` mode to work correctly.

    Returns:
        An :class:`~app.parser.types.EnrichmentResult` with all merged data.
    """
    from app.parser.llm import (
        analyze_scene,
        rewrite_choice,
    )
    from app.parser.merge import (
        merge_combat_encounters,
        merge_combat_modifiers,
        merge_conditions,
        merge_evasion,
        merge_items,
        merge_random_outcomes,
        merge_scene_flags,
    )

    warnings: list[str] = []
    llm_call_count = 0
    entity_game_objects: list[dict] = []
    entity_refs: list[dict] = []

    # Build a choice lookup by (scene_number, ordinal) for fast update
    choice_lookup: dict[tuple[int, int], dict] = {
        (c["scene_number"], c["ordinal"]): c for c in choice_dicts
    }

    # Build per-scene indexes for manual extraction results
    encounters_by_scene: dict[int, list[dict]] = {}
    for enc in encounter_dicts:
        encounters_by_scene.setdefault(enc["scene_number"], []).append(enc)

    items_by_scene: dict[int, list[dict]] = {}
    for item in item_dicts:
        items_by_scene.setdefault(item["scene_number"], []).append(item)

    outcomes_by_scene: dict[int, list[dict]] = {}
    for outcome in random_outcome_dicts:
        outcomes_by_scene.setdefault(outcome["scene_number"], []).append(outcome)

    scene_dict_by_number: dict[int, dict] = {s["number"]: s for s in scene_dicts}

    # Per-scene entity catalog accumulated across the book
    entity_catalog: dict[str, dict] = {}

    # Collect merged results to replace the originals
    merged_encounters: list[dict] = []
    merged_items: list[dict] = []
    merged_outcomes: list[dict] = []

    for scene in scenes:
        sn = scene.number

        # LLM choice rewrite (skipped when skip_llm or skip_choice_rewrite)
        skip_rewrite = skip_llm or skip_choice_rewrite
        for choice in scene.choices:
            display_text = rewrite_choice(
                raw_text=choice.raw_text,
                scene_narrative=scene.narrative,
                client=client,
                skip_llm=skip_rewrite,
                no_cache=no_cache,
            )
            key = (scene.number, choice.ordinal)
            if key in choice_lookup:
                choice_lookup[key]["display_text"] = display_text
            if not skip_rewrite:
                llm_call_count += 1

        # Scene analysis (replaces entity extraction + relationship inference).
        # Skipped when skip_entities=True OR skip_llm=True (no LLM calls at all).
        # The skip_choice_rewrite flag does NOT suppress scene analysis — this
        # allows entities_only mode to work correctly.
        analysis = None
        if not skip_entities and not skip_llm:
            choices_raw = [c.raw_text for c in scene.choices]
            analysis = analyze_scene(
                narrative=scene.narrative,
                choices_raw=choices_raw,
                book_id=book_id,
                scene_number=sn,
                existing_catalog=entity_catalog,
                client=client,
                skip_llm=False,
                no_cache=no_cache,
            )
            if analysis is not None:
                llm_call_count += 1

        # Process entities and relationships from analysis
        if analysis is not None:
            for ent in analysis.entities:
                entity_catalog[ent["name"].lower()] = ent
                entity_game_objects.append({
                    "kind": ent["kind"],
                    "name": ent["name"],
                    "description": ent.get("description", ""),
                    "aliases": str(ent.get("aliases", [])),
                    "properties": "{}",
                    "source": "auto",
                })

            for rel in analysis.relationships:
                src_name = rel["source_name"]
                tgt_name = rel["target_name"]
                src_ent = entity_catalog.get(src_name.lower())
                tgt_ent = entity_catalog.get(tgt_name.lower())
                if src_ent and tgt_ent:
                    entity_refs.append({
                        "source_kind": src_ent["kind"],
                        "source_name": src_name,
                        "target_kind": tgt_ent["kind"],
                        "target_name": tgt_name,
                        "tags": str(rel.get("tags", [])),
                        "metadata_": None,
                        "source": "auto",
                    })
                else:
                    warnings.append(
                        f"Relationship {src_name!r} → {tgt_name!r}: entity not in catalog"
                    )

        # --- Merge manual + LLM structured extraction ---
        manual_encounters = encounters_by_scene.get(sn, [])
        manual_items = items_by_scene.get(sn, [])
        manual_outcomes = outcomes_by_scene.get(sn, [])
        scene_dict = scene_dict_by_number.get(sn, {})

        llm_encounters = analysis.combat_encounters if analysis else None
        llm_items = analysis.items if analysis else None
        llm_outcomes = analysis.random_outcomes if analysis else None
        llm_evasion = analysis.evasion if analysis else None
        llm_modifiers = analysis.combat_modifiers if analysis else None
        llm_conditions = analysis.conditions if analysis else None
        llm_flags = analysis.scene_flags if analysis else None

        # Scene flags — merge first so mindblast_immune is available for encounters
        manual_flags = {
            "must_eat": scene_dict.get("must_eat", False),
            "loses_backpack": scene_dict.get("loses_backpack", False),
            "is_death": scene_dict.get("is_death", False),
            "is_victory": scene_dict.get("is_victory", False),
            "mindblast_immune": scene_dict.get("_mindblast_immune", False),
        }
        m_flags, w = merge_scene_flags(manual_flags, llm_flags, sn)
        warnings.extend(w)

        # Guard: a scene with outgoing choices cannot be a death scene
        has_choices = any(c["scene_number"] == sn for c in choice_dicts)
        if m_flags.get("is_death") and has_choices:
            m_flags["is_death"] = False
            warnings.append(
                f"MERGE_OVERRIDE scene={sn} field=is_death: "
                f"overridden to False — scene has outgoing choices"
            )

        if scene_dict:
            scene_dict["must_eat"] = m_flags.get("must_eat", False)
            scene_dict["loses_backpack"] = m_flags.get("loses_backpack", False)
            scene_dict["is_death"] = m_flags.get("is_death", False)
            scene_dict["is_victory"] = m_flags.get("is_victory", False)

        # Combat encounters
        m_enc, w = merge_combat_encounters(manual_encounters, llm_encounters, sn)
        warnings.extend(w)

        # Evasion — extract manual evasion from encounter dicts
        manual_evasion = None
        for enc in manual_encounters:
            if enc.get("evasion_after_rounds") is not None:
                manual_evasion = (
                    enc["evasion_after_rounds"],
                    enc.get("evasion_target"),
                    enc.get("evasion_damage", 0),
                )
                break

        merged_evasion, w = merge_evasion(manual_evasion, llm_evasion, sn)
        warnings.extend(w)

        # Combat modifiers — extract manual modifiers from encounter dicts
        manual_modifiers = []
        for enc in manual_encounters:
            for mod in enc.get("modifiers", []):
                manual_modifiers.append(mod)

        m_mods, w = merge_combat_modifiers(manual_modifiers, llm_modifiers, sn)
        warnings.extend(w)

        # Rebuild encounter dicts with merged data (uses merged mindblast_immune)
        for enc in m_enc:
            enc_dict: dict = {
                "scene_number": sn,
                "enemy_name": enc.get("enemy_name", ""),
                "enemy_cs": enc.get("enemy_cs", 0),
                "enemy_end": enc.get("enemy_end", 0),
                "ordinal": enc.get("ordinal", 1),
                "mindblast_immune": enc.get("mindblast_immune", m_flags.get("mindblast_immune", False)),
                "condition_type": enc.get("condition_type"),
                "condition_value": enc.get("condition_value"),
                "source": "auto",
                "modifiers": [
                    {
                        "modifier_type": m.get("modifier_type", ""),
                        "modifier_value": m.get("value", m.get("modifier_value")),
                        "condition": None,
                        "source": "auto",
                    }
                    for m in m_mods
                ],
            }
            if merged_evasion is not None:
                enc_dict["evasion_after_rounds"] = merged_evasion[0]
                enc_dict["evasion_target"] = merged_evasion[1]
                enc_dict["evasion_damage"] = merged_evasion[2]
            else:
                enc_dict["evasion_after_rounds"] = None
                enc_dict["evasion_target"] = None
                enc_dict["evasion_damage"] = 0
            merged_encounters.append(enc_dict)

        # Items
        m_items, w = merge_items(manual_items, llm_items, sn)
        warnings.extend(w)
        for ordinal, item in enumerate(m_items):
            merged_items.append({
                "scene_number": sn,
                "item_name": item.get("item_name", ""),
                "item_type": item.get("item_type", "backpack"),
                "quantity": item.get("quantity", 1),
                "action": item.get("action", "gain"),
                "is_mandatory": False,
                "phase_ordinal": ordinal,
                "source": "auto",
            })

        # Random outcomes
        m_outcomes, w = merge_random_outcomes(manual_outcomes, llm_outcomes, sn)
        warnings.extend(w)
        for ordinal, outcome in enumerate(m_outcomes):
            etype = outcome.get("effect_type", "")
            raw_val = str(outcome.get("effect_value", ""))
            merged_outcomes.append({
                "scene_number": sn,
                "roll_group": outcome.get("roll_group", 0),
                "range_min": outcome.get("range_min", 0),
                "range_max": outcome.get("range_max", 9),
                "effect_type": etype,
                "effect_value": _format_effect_value(etype, raw_val),
                "narrative_text": outcome.get("narrative_text"),
                "ordinal": ordinal,
                "source": "auto",
            })

        # Conditions — merge into choice_dicts in-place
        scene_choices = [c for c in choice_dicts if c["scene_number"] == sn]
        if scene_choices:
            _, w = merge_conditions(scene_choices, llm_conditions, sn)
            warnings.extend(w)

    from app.parser.types import EnrichmentResult  # noqa: PLC0415

    return EnrichmentResult(
        choice_dicts=choice_dicts,
        entity_game_objects=entity_game_objects,
        entity_refs=entity_refs,
        encounter_dicts=merged_encounters,
        item_dicts=merged_items,
        random_outcome_dicts=merged_outcomes,
        llm_call_count=llm_call_count,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_pipeline(
    book_path: str | Path,
    options: dict,
) -> PipelineResult:
    """Orchestrate the full parse pipeline for a single XHTML book file.

    Pipeline stages:
    1. Extract book metadata, scenes, choices, combat, CRT, disciplines,
       starting equipment.
    2. Transform: classify conditions, detect must_eat/backpack_loss/death/
       victory, detect combat modifiers, evasion, items, random outcomes.
    3. LLM enrich + merge (unless ``skip_llm`` is True): rewrite choice
       display_text; run unified scene analysis (:func:`~app.parser.llm.analyze_scene`)
       to extract entities, relationships, combat encounters, items, random
       outcomes, evasion, combat modifiers, choice conditions, and scene flags;
       then merge LLM results with manual transform results via
       :mod:`app.parser.merge`.
    4. Load into database (unless ``dry_run`` is True).
    5. Copy illustrations.

    Args:
        book_path: Path to the XHTML source file for this book.
        options: Dict of pipeline options.  Supported keys:

            - ``dry_run`` (bool): Skip DB writes.  Default False.
            - ``skip_llm`` (bool): Skip all LLM calls.  Default False.
            - ``skip_entities`` (bool): Skip entity extraction only.  Default False.
            - ``entities_only`` (bool): Only run entity extraction.  Default False.
            - ``no_cache`` (bool): Bypass LLM cache.  Default False.
            - ``reset`` (bool): Drop existing book content before loading.
              Default False.
            - ``illustrations_dest`` (str|Path): Destination root for images.
              Default ``static/images``.
            - ``db_session``: Pre-created SQLAlchemy Session (for testing).
              If absent, a new session is created from ``SessionLocal``.
            - ``llm_client``: Pre-created Anthropic client (for testing).
            - ``merge_report`` (bool): When True, the caller (``seed_db.py``)
              writes a ``merge_report_{slug}.json`` summarising manual vs LLM
              conflicts.  This key is not consumed by ``run_pipeline`` itself —
              it is read by the ``seed_db`` CLI after the pipeline returns.
              Default False.

    Returns:
        A :class:`PipelineResult` with the book data, row counts, and warnings.
    """
    book_path = Path(book_path)
    warnings: list[str] = []

    dry_run: bool = bool(options.get("dry_run", False))
    skip_llm: bool = bool(options.get("skip_llm", False))
    skip_entities: bool = bool(options.get("skip_entities", False))
    entities_only: bool = bool(options.get("entities_only", False))
    no_cache: bool = bool(options.get("no_cache", False))
    illustrations_dest = Path(options.get("illustrations_dest", _DEFAULT_ILLUSTRATIONS_DEST))
    llm_client = options.get("llm_client")
    db_session = options.get("db_session")

    # ------------------------------------------------------------------
    # Stage 1: Extract
    # ------------------------------------------------------------------
    logger.info("Extract: %s", book_path.name)

    book_data = extract_book_metadata(book_path)
    soup: BeautifulSoup = _parse_xhtml(book_path)

    scenes: list[SceneData] = extract_scenes(soup)
    disciplines_raw = extract_disciplines(soup)
    crt_rows_raw = extract_crt(soup)
    starting_equipment_raw = extract_starting_equipment(soup)

    logger.debug(
        "Extracted %d scenes, %d disciplines, %d CRT rows, %d equipment items",
        len(scenes),
        len(disciplines_raw),
        len(crt_rows_raw),
        len(starting_equipment_raw),
    )

    # ------------------------------------------------------------------
    # Stage 2: Transform
    # ------------------------------------------------------------------
    logger.info("Transform: %s", book_data.slug)

    scene_dicts, encounter_dicts, transform_warnings = _transform_scenes(scenes)
    warnings.extend(transform_warnings)

    choice_dicts, choice_warnings = _transform_choices(scenes)
    warnings.extend(choice_warnings)

    item_dicts, item_warnings = _transform_items(scene_dicts)
    warnings.extend(item_warnings)

    random_outcome_dicts = _collect_random_outcomes(scene_dicts)

    # Convert raw dataclasses to load-ready dicts
    discipline_dicts = [
        {
            "era": book_data.era,
            "name": d.name,
            "html_id": d.html_id,
            "description": d.description,
            "mechanical_effect": None,
            "source": "auto",
        }
        for d in disciplines_raw
    ]

    crt_dicts = [
        {
            "era": book_data.era,
            "random_number": r.random_number,
            "combat_ratio_min": r.combat_ratio_min,
            "combat_ratio_max": r.combat_ratio_max,
            "enemy_loss": r.enemy_loss,
            "hero_loss": r.hero_loss,
        }
        for r in crt_rows_raw
    ]

    equipment_dicts = [
        {
            "item_name": e.item_name,
            "item_type": e.item_type,
            "category": "backpack",
            "is_default": False,
            "source": "auto",
        }
        for e in starting_equipment_raw
    ]

    # ------------------------------------------------------------------
    # Stage 3: LLM enrich + merge with manual results
    # ------------------------------------------------------------------
    entity_game_objects: list[dict] = []
    entity_refs: list[dict] = []
    llm_call_count = 0

    if not entities_only:
        enrich_result = _enrich_with_llm(
            scenes=scenes,
            choice_dicts=choice_dicts,
            scene_dicts=scene_dicts,
            encounter_dicts=encounter_dicts,
            item_dicts=item_dicts,
            random_outcome_dicts=random_outcome_dicts,
            book_id=book_data.number,
            skip_llm=skip_llm,
            skip_entities=skip_entities,
            skip_choice_rewrite=False,
            no_cache=no_cache,
            client=llm_client,
        )
        choice_dicts = enrich_result.choice_dicts
        entity_game_objects = enrich_result.entity_game_objects
        entity_refs = enrich_result.entity_refs
        encounter_dicts = enrich_result.encounter_dicts
        item_dicts = enrich_result.item_dicts
        random_outcome_dicts = enrich_result.random_outcome_dicts
        llm_call_count = enrich_result.llm_call_count
        warnings.extend(enrich_result.warnings)
    else:
        # entities_only: run scene analysis but skip choice rewriting
        enrich_result = _enrich_with_llm(
            scenes=scenes,
            choice_dicts=choice_dicts,
            scene_dicts=scene_dicts,
            encounter_dicts=encounter_dicts,
            item_dicts=item_dicts,
            random_outcome_dicts=random_outcome_dicts,
            book_id=book_data.number,
            skip_llm=False,
            skip_entities=False,
            skip_choice_rewrite=True,
            no_cache=no_cache,
            client=llm_client,
        )
        entity_game_objects = enrich_result.entity_game_objects
        entity_refs = enrich_result.entity_refs
        encounter_dicts = enrich_result.encounter_dicts
        item_dicts = enrich_result.item_dicts
        random_outcome_dicts = enrich_result.random_outcome_dicts
        warnings.extend(enrich_result.warnings)

    # Combine entity game objects with any additional types
    all_game_objects: list[dict] = entity_game_objects
    all_refs: list[dict] = entity_refs

    # ------------------------------------------------------------------
    # Stage 4: Load
    # ------------------------------------------------------------------
    summary: dict[str, int] = {}

    if not dry_run:
        logger.info("Load: %s", book_data.slug)

        book_dict = {
            "slug": book_data.slug,
            "number": book_data.number,
            "title": book_data.title,
            "era": book_data.era,
            "series": "lone_wolf",
            "start_scene_number": 1,
            "max_total_picks": 1,
            "source": "auto",
        }

        # Clean internal sentinel keys from scene dicts before loading
        _INTERNAL_KEYS = {"_random_outcomes", "_mindblast_immune"}
        clean_scene_dicts = [
            {k: v for k, v in s.items() if k not in _INTERNAL_KEYS}
            for s in scene_dicts
        ]

        if db_session is not None:
            _do_load(
                db=db_session,
                book_dict=book_dict,
                scene_dicts=clean_scene_dicts,
                choice_dicts=choice_dicts,
                encounter_dicts=encounter_dicts,
                item_dicts=item_dicts,
                random_outcome_dicts=random_outcome_dicts,
                discipline_dicts=discipline_dicts,
                crt_dicts=crt_dicts,
                all_game_objects=all_game_objects,
                all_refs=all_refs,
                equipment_dicts=equipment_dicts,
                summary=summary,
                warnings=warnings,
            )
        else:
            db = SessionLocal()
            try:
                _do_load(
                    db=db,
                    book_dict=book_dict,
                    scene_dicts=clean_scene_dicts,
                    choice_dicts=choice_dicts,
                    encounter_dicts=encounter_dicts,
                    item_dicts=item_dicts,
                    random_outcome_dicts=random_outcome_dicts,
                    discipline_dicts=discipline_dicts,
                    crt_dicts=crt_dicts,
                    all_game_objects=all_game_objects,
                    all_refs=all_refs,
                    equipment_dicts=equipment_dicts,
                    summary=summary,
                    warnings=warnings,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
    else:
        logger.info("Dry run: skipping DB load for %s", book_data.slug)

    # ------------------------------------------------------------------
    # Stage 5: Copy illustrations
    # ------------------------------------------------------------------
    if not dry_run:
        try:
            copied = copy_illustrations(
                xhtml_dir=book_path.parent,
                book_slug=book_data.slug,
                dest_dir=illustrations_dest,
            )
            logger.debug("Copied %d illustration(s) for %s", len(copied), book_data.slug)
        except Exception as exc:
            warning_msg = f"Illustration copy failed for {book_data.slug}: {exc}"
            warnings.append(warning_msg)
            logger.warning(warning_msg)

    # Assemble final counts
    counts: dict[str, int] = {
        "scenes": len(scene_dicts),
        "choices": len(choice_dicts),
        "encounters": len(encounter_dicts),
        "items": len(item_dicts),
        "disciplines": len(discipline_dicts),
        "crt_rows": len(crt_dicts),
        "game_objects": len(all_game_objects),
        "refs": len(all_refs),
        "llm_calls": llm_call_count,
        "random_outcomes": len(random_outcome_dicts),
        "starting_equipment": len(equipment_dicts),
    }
    # Merge summary from load step (DB-confirmed counts)
    counts.update(summary)

    return PipelineResult(book_data=book_data, counts=counts, warnings=warnings)


def _do_load(
    db: object,
    book_dict: dict,
    scene_dicts: list[dict],
    choice_dicts: list[dict],
    encounter_dicts: list[dict],
    item_dicts: list[dict],
    random_outcome_dicts: list[dict],
    discipline_dicts: list[dict],
    crt_dicts: list[dict],
    all_game_objects: list[dict],
    all_refs: list[dict],
    equipment_dicts: list[dict],
    summary: dict,
    warnings: list[str],
) -> None:
    """Call load_book with the assembled data and merge the returned summary.

    Args:
        db: Active SQLAlchemy Session.
        book_dict: Single-book metadata dict.
        scene_dicts: Transformed scene rows.
        choice_dicts: Transformed choice rows.
        encounter_dicts: Transformed combat encounter rows.
        item_dicts: Detected item rows.
        random_outcome_dicts: Scene-level random outcome rows.
        discipline_dicts: Extracted discipline rows.
        crt_dicts: Extracted CRT rows.
        all_game_objects: Combined entity game object rows.
        all_refs: Entity relationship ref rows.
        equipment_dicts: Starting equipment rows.
        summary: Mutable dict to update with load counts.
        warnings: Mutable list to append load warnings to.
    """
    from app.parser.load import load_book

    load_summary = load_book(
        db=db,  # type: ignore[arg-type]
        book_data=book_dict,
        scenes=scene_dicts,
        choices=choice_dicts,
        encounters=encounter_dicts,
        items=item_dicts,
        random_outcomes=random_outcome_dicts,
        disciplines=discipline_dicts,
        crt_rows=crt_dicts,
        game_objects=all_game_objects,
        refs=all_refs,
        weapon_categories=[],
        starting_equipment=equipment_dicts,
        transition_rules=[],
    )
    summary.update(load_summary)
