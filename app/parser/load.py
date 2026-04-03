"""Load phase of the parser pipeline.

Persists transformed book data into the database.  All writes use an
upsert-with-source pattern: manual rows are never overwritten, auto rows
are updated, and missing rows are inserted.

This module imports from app.models and writes to the database.
It is not imported by the API at runtime — only used by parser scripts.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.content import (
    Book,
    Choice,
    ChoiceRandomOutcome,
    CombatEncounter,
    CombatModifier,
    CombatResults,
    Discipline,
    RandomOutcome,
    Scene,
    SceneItem,
    WeaponCategory,
)
from app.models.taxonomy import (
    BookStartingEquipment,
    BookTransitionRule,
    GameObject,
    GameObjectRef,
    GameObjectSceneAppearance,
)

logger = logging.getLogger(__name__)


def upsert_with_source(
    db: Session,
    model: type,
    data: dict,
    unique_keys: list[str],
) -> object:
    """Query for an existing row; respect source to decide whether to update.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    model:
        ORM model class to query and insert into.
    data:
        Dict of field values.  Must include all ``unique_keys`` and a
        ``source`` key with value ``'auto'`` or ``'manual'``.
    unique_keys:
        Column names whose values together form the lookup key.

    Returns
    -------
    The existing or newly created model instance.

    Notes
    -----
    - If no row exists: INSERT with ``source='auto'`` (or the source in *data*).
    - If existing row has ``source='manual'``: skip — return unchanged instance.
    - If existing row has ``source='auto'``: UPDATE all fields from *data*.
    """
    filters = {k: data[k] for k in unique_keys}
    existing = db.query(model).filter_by(**filters).one_or_none()

    if existing is None:
        # Strip keys that don't exist as columns on the model
        valid_cols = {c.key for c in model.__table__.columns}
        filtered = {k: v for k, v in data.items() if k in valid_cols}
        instance = model(**filtered)
        db.add(instance)
        return instance

    if getattr(existing, "source", None) == "manual":
        # Preserve manual edits — skip update
        return existing

    # Auto row — update all fields from data
    valid_cols = {c.key for c in model.__table__.columns}
    for field, value in data.items():
        if field in valid_cols:
            setattr(existing, field, value)
    return existing


def load_book(
    db: Session,
    book_data: dict,
    scenes: list[dict],
    choices: list[dict],
    encounters: list[dict],
    items: list[dict],
    random_outcomes: list[dict],
    disciplines: list[dict],
    crt_rows: list[dict],
    game_objects: list[dict],
    refs: list[dict],
    weapon_categories: list[dict],
    starting_equipment: list[dict],
    transition_rules: list[dict],
    scene_appearances: list[dict] | None = None,
) -> dict:
    """Load all parsed book data into the database in FK dependency order.

    Parameters
    ----------
    db:
        Active SQLAlchemy session.
    book_data:
        Single-book metadata dict (slug, number, title, era, series,
        start_scene_number, max_total_picks).
    scenes:
        List of scene dicts (number, html_id, narrative, is_death,
        is_victory, must_eat, loses_backpack, source, and optionally
        game_object_kind+game_object_name for the linked game object).
    choices:
        List of choice dicts (scene_number, target_scene_number,
        raw_text, display_text, condition_type, condition_value, ordinal,
        source).
    encounters:
        List of combat-encounter dicts (scene_number, enemy_name, enemy_cs,
        enemy_end, ordinal, mindblast_immune, evasion_after_rounds,
        evasion_target, evasion_damage, condition_type, condition_value,
        source; optionally foe_game_object_kind+foe_game_object_name).
    items:
        List of scene-item dicts (scene_number, item_name, item_type,
        quantity, action, is_mandatory, phase_ordinal, source; optionally
        game_object_kind+game_object_name).
    random_outcomes:
        List of random-outcome dicts (scene_number, roll_group, range_min,
        range_max, effect_type, effect_value, narrative_text, ordinal,
        source).
    disciplines:
        List of discipline dicts (era, name, html_id, description,
        mechanical_effect).
    crt_rows:
        List of CombatResults dicts (era, random_number, combat_ratio_min,
        combat_ratio_max, enemy_loss, hero_loss).
    game_objects:
        List of game-object dicts (kind, name, description, aliases,
        properties, source; optionally first_book_slug).
    refs:
        List of game-object-ref dicts (source_kind, source_name,
        target_kind, target_name, tags, metadata_, source).
    weapon_categories:
        List of weapon-category dicts (weapon_name, category).
    starting_equipment:
        List of book-starting-equipment dicts (item_name, item_type,
        category, is_default, source; optionally game_object_kind +
        game_object_name).
    transition_rules:
        List of book-transition-rule dicts (to_book_slug, max_weapons,
        max_backpack_items, special_items_carry, gold_carries,
        new_disciplines_count, base_cs_override, base_end_override, notes).

    Returns
    -------
    Summary dict with keys: books, disciplines, scenes, scene_game_objects,
    item_game_objects, foe_game_objects, other_game_objects, choices,
    choice_random_outcomes, encounters, combat_modifiers, scene_items,
    random_outcomes, crt_rows, refs, weapon_categories, starting_equipment,
    transition_rules.
    """
    summary: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 1. Book
    # ------------------------------------------------------------------
    book_obj = upsert_with_source(db, Book, book_data, ["slug"])
    db.flush()
    book_id: int = book_obj.id  # type: ignore[attr-defined]
    summary["books"] = 1

    # ------------------------------------------------------------------
    # 2. Disciplines (era-scoped)
    # ------------------------------------------------------------------
    loaded_disciplines = 0
    for d in disciplines:
        upsert_with_source(db, Discipline, d, ["era", "name"])
        loaded_disciplines += 1
    db.flush()
    summary["disciplines"] = loaded_disciplines

    # ------------------------------------------------------------------
    # Helper: resolve game object by kind+name
    # ------------------------------------------------------------------
    def _resolve_game_object(kind_key: str, name_key: str, row: dict) -> int | None:
        """Return the game_object.id for the given kind+name keys in *row*."""
        kind = row.get(kind_key)
        name = row.get(name_key)
        if not kind or not name:
            return None
        go = db.query(GameObject).filter_by(kind=kind, name=name).one_or_none()
        return go.id if go is not None else None  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 3. Game objects — scenes
    # ------------------------------------------------------------------
    scene_game_objects = 0
    for go in game_objects:
        if go.get("kind") != "scene":
            continue
        row = {
            "kind": go["kind"],
            "name": go["name"],
            "description": go.get("description"),
            "aliases": go.get("aliases", "[]"),
            "properties": go.get("properties", "{}"),
            "source": go.get("source", "auto"),
        }
        if go.get("first_book_slug"):
            fb = db.query(Book).filter_by(slug=go["first_book_slug"]).one_or_none()
            row["first_book_id"] = fb.id if fb is not None else None  # type: ignore[assignment]
        upsert_with_source(db, GameObject, row, ["kind", "name"])
        scene_game_objects += 1
    db.flush()
    summary["scene_game_objects"] = scene_game_objects

    # ------------------------------------------------------------------
    # 4. Scenes (upsert by book_id + number)
    # ------------------------------------------------------------------
    # Build a scene-number → scene_id map after inserting
    scene_number_to_id: dict[int, int] = {}

    # Populate scene_number_to_id from any already-existing scenes for this book
    existing_scenes = db.query(Scene).filter_by(book_id=book_id).all()
    for s in existing_scenes:
        scene_number_to_id[s.number] = s.id  # type: ignore[index]

    loaded_scenes = 0
    for s in scenes:
        row: dict = {
            "book_id": book_id,
            "number": s["number"],
            "html_id": s["html_id"],
            "narrative": s["narrative"],
            "is_death": s.get("is_death", False),
            "is_victory": s.get("is_victory", False),
            "must_eat": s.get("must_eat", False),
            "loses_backpack": s.get("loses_backpack", False),
            "illustration_path": s.get("illustration_path"),
            "phase_sequence_override": s.get("phase_sequence_override"),
            "source": s.get("source", "auto"),
        }
        # Resolve optional game object link
        go_id = _resolve_game_object("game_object_kind", "game_object_name", s)
        row["game_object_id"] = go_id

        scene_obj = upsert_with_source(db, Scene, row, ["book_id", "number"])
        loaded_scenes += 1
        db.flush()
        scene_number_to_id[s["number"]] = scene_obj.id  # type: ignore[attr-defined]

    summary["scenes"] = loaded_scenes

    # ------------------------------------------------------------------
    # 5. Game objects — items
    # ------------------------------------------------------------------
    item_game_objects = 0
    for go in game_objects:
        if go.get("kind") != "item":
            continue
        row = {
            "kind": go["kind"],
            "name": go["name"],
            "description": go.get("description"),
            "aliases": go.get("aliases", "[]"),
            "properties": go.get("properties", "{}"),
            "source": go.get("source", "auto"),
        }
        if go.get("first_book_slug"):
            fb = db.query(Book).filter_by(slug=go["first_book_slug"]).one_or_none()
            row["first_book_id"] = fb.id if fb is not None else None  # type: ignore[assignment]
        upsert_with_source(db, GameObject, row, ["kind", "name"])
        item_game_objects += 1
    db.flush()
    summary["item_game_objects"] = item_game_objects

    # ------------------------------------------------------------------
    # 6. Game objects — foes
    # ------------------------------------------------------------------
    foe_game_objects = 0
    for go in game_objects:
        if go.get("kind") != "foe":
            continue
        row = {
            "kind": go["kind"],
            "name": go["name"],
            "description": go.get("description"),
            "aliases": go.get("aliases", "[]"),
            "properties": go.get("properties", "{}"),
            "source": go.get("source", "auto"),
        }
        if go.get("first_book_slug"):
            fb = db.query(Book).filter_by(slug=go["first_book_slug"]).one_or_none()
            row["first_book_id"] = fb.id if fb is not None else None  # type: ignore[assignment]
        upsert_with_source(db, GameObject, row, ["kind", "name"])
        foe_game_objects += 1
    db.flush()
    summary["foe_game_objects"] = foe_game_objects

    # ------------------------------------------------------------------
    # 7. Choices — first pass: insert all with target_scene_id=None
    # ------------------------------------------------------------------
    # Choices are keyed by (scene_id, ordinal) — no unique constraint in the
    # schema, so we look up by scene_id + ordinal to avoid duplicates.
    choice_scene_ordinal_to_id: dict[tuple[int, int], int] = {}

    loaded_choices = 0
    for c in choices:
        scene_number = c["scene_number"]
        scene_id = scene_number_to_id.get(scene_number)
        if scene_id is None:
            logger.warning("Choice references unknown scene number %s — skipping", scene_number)
            continue

        row = {
            "scene_id": scene_id,
            "target_scene_id": None,  # resolved in second pass
            "target_scene_number": c["target_scene_number"],
            "raw_text": c["raw_text"],
            "display_text": c.get("display_text", c["raw_text"]),
            "condition_type": c.get("condition_type"),
            "condition_value": c.get("condition_value"),
            "ordinal": c["ordinal"],
            "source": c.get("source", "auto"),
        }

        # Look up existing choice by scene_id + ordinal
        existing = (
            db.query(Choice)
            .filter_by(scene_id=scene_id, ordinal=c["ordinal"])
            .one_or_none()
        )
        if existing is None:
            choice_obj = Choice(**row)
            db.add(choice_obj)
            db.flush()
        else:
            if getattr(existing, "source", None) != "manual":
                for field, value in row.items():
                    setattr(existing, field, value)
            choice_obj = existing

        key = (scene_id, c["ordinal"])
        choice_scene_ordinal_to_id[key] = choice_obj.id  # type: ignore[attr-defined]
        loaded_choices += 1

    db.flush()
    summary["choices"] = loaded_choices

    # ------------------------------------------------------------------
    # 8. Choices — second pass: resolve target_scene_id
    # ------------------------------------------------------------------
    for c in choices:
        scene_number = c["scene_number"]
        scene_id = scene_number_to_id.get(scene_number)
        if scene_id is None:
            continue

        key = (scene_id, c["ordinal"])
        choice_id = choice_scene_ordinal_to_id.get(key)
        if choice_id is None:
            continue

        target_number = c["target_scene_number"]
        target_scene_id = scene_number_to_id.get(target_number)

        choice_obj = db.query(Choice).filter_by(id=choice_id).one()
        if getattr(choice_obj, "source", None) != "manual":
            choice_obj.target_scene_id = target_scene_id  # type: ignore[attr-defined]

    db.flush()

    # ------------------------------------------------------------------
    # 9. Choice random outcomes
    # ------------------------------------------------------------------
    loaded_cro = 0
    for cro in random_outcomes:
        # random_outcomes list contains both choice-based and scene-based outcomes;
        # choice random outcomes have a choice_scene_number + choice_ordinal key.
        if "choice_scene_number" not in cro:
            continue

        choice_scene_number = cro["choice_scene_number"]
        choice_ordinal = cro["choice_ordinal"]
        choice_scene_id = scene_number_to_id.get(choice_scene_number)
        if choice_scene_id is None:
            logger.warning(
                "ChoiceRandomOutcome references unknown scene %s — skipping",
                choice_scene_number,
            )
            continue

        key = (choice_scene_id, choice_ordinal)
        choice_id = choice_scene_ordinal_to_id.get(key)
        if choice_id is None:
            logger.warning(
                "ChoiceRandomOutcome references unknown choice (scene=%s, ordinal=%s) — skipping",
                choice_scene_number,
                choice_ordinal,
            )
            continue

        target_number = cro["target_scene_number"]
        target_scene_id = scene_number_to_id.get(target_number)

        row = {
            "choice_id": choice_id,
            "range_min": cro["range_min"],
            "range_max": cro["range_max"],
            "target_scene_id": target_scene_id,
            "target_scene_number": target_number,
            "narrative_text": cro.get("narrative_text"),
            "source": cro.get("source", "auto"),
        }
        upsert_with_source(
            db, ChoiceRandomOutcome, row, ["choice_id", "range_min", "range_max"]
        )
        loaded_cro += 1

    db.flush()
    summary["choice_random_outcomes"] = loaded_cro

    # ------------------------------------------------------------------
    # 10. Combat encounters
    # ------------------------------------------------------------------
    # Keyed by (scene_id, ordinal)
    encounter_scene_ordinal_to_id: dict[tuple[int, int], int] = {}

    loaded_encounters = 0
    for enc in encounters:
        scene_number = enc["scene_number"]
        scene_id = scene_number_to_id.get(scene_number)
        if scene_id is None:
            logger.warning(
                "CombatEncounter references unknown scene %s — skipping", scene_number
            )
            continue

        foe_id = _resolve_game_object("foe_game_object_kind", "foe_game_object_name", enc)

        row = {
            "scene_id": scene_id,
            "foe_game_object_id": foe_id,
            "enemy_name": enc["enemy_name"],
            "enemy_cs": enc["enemy_cs"],
            "enemy_end": enc["enemy_end"],
            "ordinal": enc["ordinal"],
            "mindblast_immune": enc.get("mindblast_immune", False),
            "evasion_after_rounds": enc.get("evasion_after_rounds"),
            "evasion_target": enc.get("evasion_target"),
            "evasion_damage": enc.get("evasion_damage", 0),
            "condition_type": enc.get("condition_type"),
            "condition_value": enc.get("condition_value"),
            "source": enc.get("source", "auto"),
        }

        existing = (
            db.query(CombatEncounter)
            .filter_by(scene_id=scene_id, ordinal=enc["ordinal"])
            .one_or_none()
        )
        if existing is None:
            enc_obj = CombatEncounter(**row)
            db.add(enc_obj)
            db.flush()
        else:
            if getattr(existing, "source", None) != "manual":
                for field, value in row.items():
                    setattr(existing, field, value)
            enc_obj = existing

        key = (scene_id, enc["ordinal"])
        encounter_scene_ordinal_to_id[key] = enc_obj.id  # type: ignore[attr-defined]
        loaded_encounters += 1

    db.flush()
    summary["encounters"] = loaded_encounters

    # ------------------------------------------------------------------
    # 11. Combat modifiers
    # ------------------------------------------------------------------
    loaded_modifiers = 0
    for mod in encounters:
        # Combat modifiers are embedded as a 'modifiers' list inside encounter dicts
        modifiers_list = mod.get("modifiers", [])
        if not modifiers_list:
            continue

        scene_number = mod["scene_number"]
        scene_id = scene_number_to_id.get(scene_number)
        if scene_id is None:
            continue

        key = (scene_id, mod["ordinal"])
        enc_id = encounter_scene_ordinal_to_id.get(key)
        if enc_id is None:
            continue

        for m in modifiers_list:
            row = {
                "combat_encounter_id": enc_id,
                "modifier_type": m["modifier_type"],
                "modifier_value": m.get("modifier_value"),
                "condition": m.get("condition"),
                "source": m.get("source", "auto"),
            }
            # Upsert by encounter_id + modifier_type (best available key)
            upsert_with_source(
                db, CombatModifier, row, ["combat_encounter_id", "modifier_type"]
            )
            loaded_modifiers += 1

    db.flush()
    summary["combat_modifiers"] = loaded_modifiers

    # ------------------------------------------------------------------
    # 12. Scene items
    # ------------------------------------------------------------------
    loaded_items = 0
    for item in items:
        scene_number = item["scene_number"]
        scene_id = scene_number_to_id.get(scene_number)
        if scene_id is None:
            logger.warning(
                "SceneItem references unknown scene %s — skipping", scene_number
            )
            continue

        go_id = _resolve_game_object("game_object_kind", "game_object_name", item)

        row = {
            "scene_id": scene_id,
            "game_object_id": go_id,
            "item_name": item["item_name"],
            "item_type": item["item_type"],
            "quantity": item.get("quantity", 1),
            "action": item["action"],
            "is_mandatory": item.get("is_mandatory", False),
            "phase_ordinal": item.get("phase_ordinal", 0),
            "source": item.get("source", "auto"),
        }

        # No unique constraint on scene_items — key by (scene_id, item_name, action)
        existing = (
            db.query(SceneItem)
            .filter_by(scene_id=scene_id, item_name=item["item_name"], action=item["action"])
            .one_or_none()
        )
        if existing is None:
            si_obj = SceneItem(**row)
            db.add(si_obj)
        else:
            if getattr(existing, "source", None) != "manual":
                for field, value in row.items():
                    setattr(existing, field, value)

        loaded_items += 1

    db.flush()
    summary["scene_items"] = loaded_items

    # ------------------------------------------------------------------
    # 13. Random outcomes (scene-level, not choice-level)
    # ------------------------------------------------------------------
    loaded_ro = 0
    for ro in random_outcomes:
        if "choice_scene_number" in ro:
            # Choice random outcome — already handled in step 9
            continue

        scene_number = ro["scene_number"]
        scene_id = scene_number_to_id.get(scene_number)
        if scene_id is None:
            logger.warning(
                "RandomOutcome references unknown scene %s — skipping", scene_number
            )
            continue

        row = {
            "scene_id": scene_id,
            "roll_group": ro.get("roll_group", 0),
            "range_min": ro["range_min"],
            "range_max": ro["range_max"],
            "effect_type": ro["effect_type"],
            "effect_value": str(ro["effect_value"]),
            "narrative_text": ro.get("narrative_text"),
            "ordinal": ro.get("ordinal", 0),
            "source": ro.get("source", "auto"),
        }
        upsert_with_source(
            db,
            RandomOutcome,
            row,
            ["scene_id", "roll_group", "range_min", "range_max"],
        )
        loaded_ro += 1

    db.flush()
    summary["random_outcomes"] = loaded_ro

    # ------------------------------------------------------------------
    # 14. Combat results (era-scoped)
    # ------------------------------------------------------------------
    loaded_crt = 0
    for crt in crt_rows:
        upsert_with_source(
            db,
            CombatResults,
            crt,
            ["era", "random_number", "combat_ratio_min", "combat_ratio_max"],
        )
        loaded_crt += 1

    db.flush()
    summary["crt_rows"] = loaded_crt

    # ------------------------------------------------------------------
    # 15. Game objects — other entities (character, location, creature, organization)
    # ------------------------------------------------------------------
    other_kinds = {"character", "location", "creature", "organization"}
    other_game_objects = 0
    for go in game_objects:
        if go.get("kind") not in other_kinds:
            continue
        row = {
            "kind": go["kind"],
            "name": go["name"],
            "description": go.get("description"),
            "aliases": go.get("aliases", "[]"),
            "properties": go.get("properties", "{}"),
            "source": go.get("source", "auto"),
        }
        if go.get("first_book_slug"):
            fb = db.query(Book).filter_by(slug=go["first_book_slug"]).one_or_none()
            row["first_book_id"] = fb.id if fb is not None else None  # type: ignore[assignment]
        upsert_with_source(db, GameObject, row, ["kind", "name"])
        other_game_objects += 1

    db.flush()
    summary["other_game_objects"] = other_game_objects

    # ------------------------------------------------------------------
    # 16. Game object refs
    # ------------------------------------------------------------------
    loaded_refs = 0
    for ref in refs:
        source_obj = (
            db.query(GameObject)
            .filter_by(kind=ref["source_kind"], name=ref["source_name"])
            .one_or_none()
        )
        target_obj = (
            db.query(GameObject)
            .filter_by(kind=ref["target_kind"], name=ref["target_name"])
            .one_or_none()
        )
        if source_obj is None or target_obj is None:
            logger.warning(
                "GameObjectRef: cannot resolve %s/%s → %s/%s — skipping",
                ref["source_kind"],
                ref["source_name"],
                ref["target_kind"],
                ref["target_name"],
            )
            continue

        row = {
            "source_id": source_obj.id,  # type: ignore[attr-defined]
            "target_id": target_obj.id,  # type: ignore[attr-defined]
            "tags": ref["tags"],
            "metadata_": ref.get("metadata_"),
            "source": ref.get("source", "auto"),
        }
        # Upsert by source_id + target_id + tags
        existing = (
            db.query(GameObjectRef)
            .filter_by(
                source_id=source_obj.id,  # type: ignore[attr-defined]
                target_id=target_obj.id,  # type: ignore[attr-defined]
                tags=ref["tags"],
            )
            .one_or_none()
        )
        if existing is None:
            ref_obj = GameObjectRef(**row)
            db.add(ref_obj)
        else:
            if getattr(existing, "source", None) != "manual":
                for field, value in row.items():
                    setattr(existing, field, value)

        loaded_refs += 1

    db.flush()
    summary["refs"] = loaded_refs

    # ------------------------------------------------------------------
    # 17. Weapon categories
    # ------------------------------------------------------------------
    loaded_wc = 0
    for wc in weapon_categories:
        upsert_with_source(db, WeaponCategory, wc, ["weapon_name"])
        loaded_wc += 1

    db.flush()
    summary["weapon_categories"] = loaded_wc

    # ------------------------------------------------------------------
    # 18. Book starting equipment
    # ------------------------------------------------------------------
    loaded_se = 0
    for se in starting_equipment:
        go_id = _resolve_game_object("game_object_kind", "game_object_name", se)
        row = {
            "book_id": book_id,
            "game_object_id": go_id,
            "item_name": se["item_name"],
            "item_type": se["item_type"],
            "category": se["category"],
            "is_default": se.get("is_default", False),
            "source": se.get("source", "auto"),
        }
        # Upsert by book_id + item_name + category
        existing = (
            db.query(BookStartingEquipment)
            .filter_by(book_id=book_id, item_name=se["item_name"], category=se["category"])
            .one_or_none()
        )
        if existing is None:
            se_obj = BookStartingEquipment(**row)
            db.add(se_obj)
        else:
            if getattr(existing, "source", None) != "manual":
                for field, value in row.items():
                    setattr(existing, field, value)

        loaded_se += 1

    db.flush()
    summary["starting_equipment"] = loaded_se

    # ------------------------------------------------------------------
    # Transition rules (optional — load if provided)
    # ------------------------------------------------------------------
    loaded_tr = 0
    for tr in transition_rules:
        to_book = db.query(Book).filter_by(slug=tr["to_book_slug"]).one_or_none()
        if to_book is None:
            logger.warning(
                "BookTransitionRule: to_book_slug=%s not found — skipping", tr["to_book_slug"]
            )
            continue

        row = {
            "from_book_id": book_id,
            "to_book_id": to_book.id,  # type: ignore[attr-defined]
            "max_weapons": tr["max_weapons"],
            "max_backpack_items": tr["max_backpack_items"],
            "special_items_carry": tr["special_items_carry"],
            "gold_carries": tr["gold_carries"],
            "new_disciplines_count": tr["new_disciplines_count"],
            "base_cs_override": tr.get("base_cs_override"),
            "base_end_override": tr.get("base_end_override"),
            "notes": tr.get("notes"),
        }
        upsert_with_source(db, BookTransitionRule, row, ["from_book_id", "to_book_id"])
        loaded_tr += 1

    db.flush()
    summary["transition_rules"] = loaded_tr

    # ------------------------------------------------------------------
    # 19. Scene appearances (optional)
    # ------------------------------------------------------------------
    loaded_appearances = 0
    if scene_appearances:
        for app in scene_appearances:
            scene_number = app.get("scene_number")
            scene_id = scene_number_to_id.get(scene_number) if scene_number else None
            if scene_id is None:
                continue

            go_id = _resolve_game_object(
                "game_object_kind", "game_object_name", app
            )
            if go_id is None:
                continue

            existing = (
                db.query(GameObjectSceneAppearance)
                .filter_by(
                    game_object_id=go_id,
                    scene_id=scene_id,
                    appearance_type=app["appearance_type"],
                )
                .one_or_none()
            )
            if existing is None:
                db.add(GameObjectSceneAppearance(
                    game_object_id=go_id,
                    scene_id=scene_id,
                    appearance_type=app["appearance_type"],
                    source=app.get("source", "auto"),
                ))
                loaded_appearances += 1

        db.flush()
    summary["scene_appearances"] = loaded_appearances

    logger.info(
        "load_book complete for %s: %s",
        book_data.get("slug", "?"),
        summary,
    )
    return summary
