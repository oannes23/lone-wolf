"""YAML export/import utility for Lone Wolf book data.

Round-trips parsed book content between the database and a human-readable
YAML directory structure.

Usage:
    uv run python scripts/yaml_io.py export --book 01fftd --output-dir data/books
    uv run python scripts/yaml_io.py export --all --output-dir data/books
    uv run python scripts/yaml_io.py import --book 01fftd --input-dir data/books
    uv run python scripts/yaml_io.py import --all --input-dir data/books
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402
from sqlalchemy.orm import Session, joinedload  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.content import (  # noqa: E402
    Book,
    Choice,
    ChoiceRandomOutcome,
    CombatEncounter,
    CombatResults,
    Discipline,
    RandomOutcome,
    Scene,
    SceneItem,
    WeaponCategory,
)
from app.models.taxonomy import (  # noqa: E402
    BookStartingEquipment,
    BookTransitionRule,
    GameObject,
    GameObjectRef,
    GameObjectSceneAppearance,
)
from app.parser.load import load_book  # noqa: E402


# ---------------------------------------------------------------------------
# YAML formatting helpers
# ---------------------------------------------------------------------------

class _LiteralStr(str):
    """Marker for YAML literal block scalar output."""


def _literal_representer(dumper: yaml.Dumper, data: _LiteralStr) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


def _none_representer(dumper: yaml.Dumper, _data: None) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:null", "null")


def _make_dumper() -> type[yaml.Dumper]:
    """Return a Dumper subclass with custom representers."""
    dumper = type("BookDumper", (yaml.Dumper,), {})
    dumper.add_representer(_LiteralStr, _literal_representer)
    dumper.add_representer(type(None), _none_representer)
    return dumper


def _dump_yaml(data: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data, f,
            Dumper=_make_dumper(),
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )


def _load_yaml(path: Path) -> object:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _json_to_native(text: str | None) -> object:
    """Parse a JSON-encoded or Python-repr string into a native Python object."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fall back to Python repr parsing (DB may store ['foo'] instead of ["foo"])
    import ast
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def _native_to_json(obj: object) -> str:
    """Serialize a native Python object back to a JSON string."""
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _export_scene(scene: Scene, go_id_map: dict[int, tuple[str, str]],
                  scene_id_to_number: dict[int, int]) -> dict:
    """Build a clean YAML-ready dict for a single scene."""
    d: dict = {
        "number": scene.number,
        "html_id": scene.html_id,
        "narrative": _LiteralStr(scene.narrative),
        "is_death": scene.is_death,
        "is_victory": scene.is_victory,
        "must_eat": scene.must_eat,
        "loses_backpack": scene.loses_backpack,
    }
    if scene.illustration_path:
        d["illustration_path"] = scene.illustration_path

    # Choices
    choices = []
    for c in sorted(scene.choices, key=lambda x: x.ordinal):
        cd: dict = {
            "ordinal": c.ordinal,
            "target_scene_number": c.target_scene_number,
            "raw_text": c.raw_text,
            "display_text": c.display_text,
        }
        if c.condition_type:
            cd["condition_type"] = c.condition_type
            cd["condition_value"] = c.condition_value
        choices.append(cd)
    d["choices"] = choices

    # Combat encounters
    encounters = []
    for enc in sorted(scene.combat_encounters, key=lambda x: x.ordinal):
        ed: dict = {
            "ordinal": enc.ordinal,
            "enemy_name": enc.enemy_name,
            "enemy_cs": enc.enemy_cs,
            "enemy_end": enc.enemy_end,
            "mindblast_immune": enc.mindblast_immune,
        }
        if enc.evasion_after_rounds is not None:
            ed["evasion_after_rounds"] = enc.evasion_after_rounds
            ed["evasion_target"] = enc.evasion_target
            ed["evasion_damage"] = enc.evasion_damage
        if enc.condition_type:
            ed["condition_type"] = enc.condition_type
            ed["condition_value"] = enc.condition_value
        if enc.foe_game_object_id and enc.foe_game_object_id in go_id_map:
            kind, name = go_id_map[enc.foe_game_object_id]
            ed["foe_game_object_kind"] = kind
            ed["foe_game_object_name"] = name
        # Modifiers
        mods = []
        for m in enc.modifiers:
            md: dict = {"modifier_type": m.modifier_type}
            if m.modifier_value is not None:
                md["modifier_value"] = m.modifier_value
            if m.condition is not None:
                md["condition"] = m.condition
            mods.append(md)
        if mods:
            ed["modifiers"] = mods
        encounters.append(ed)
    d["combat_encounters"] = encounters

    # Items
    items = []
    for si in scene.scene_items:
        sid: dict = {
            "item_name": si.item_name,
            "item_type": si.item_type,
            "quantity": si.quantity,
            "action": si.action,
        }
        if si.is_mandatory:
            sid["is_mandatory"] = True
        if si.game_object_id and si.game_object_id in go_id_map:
            kind, name = go_id_map[si.game_object_id]
            sid["game_object_kind"] = kind
            sid["game_object_name"] = name
        items.append(sid)
    d["items"] = items

    # Scene-level random outcomes
    ros = []
    for ro in sorted(scene.random_outcomes, key=lambda x: (x.roll_group, x.range_min)):
        rod: dict = {
            "roll_group": ro.roll_group,
            "range_min": ro.range_min,
            "range_max": ro.range_max,
            "effect_type": ro.effect_type,
            "effect_value": ro.effect_value,
        }
        if ro.narrative_text:
            rod["narrative_text"] = ro.narrative_text
        ros.append(rod)
    d["random_outcomes"] = ros

    # Choice random outcomes
    cros = []
    for c in sorted(scene.choices, key=lambda x: x.ordinal):
        for cro in sorted(c.random_outcomes, key=lambda x: x.range_min):
            crod: dict = {
                "choice_ordinal": c.ordinal,
                "target_scene_number": cro.target_scene_number,
                "range_min": cro.range_min,
                "range_max": cro.range_max,
            }
            if cro.narrative_text:
                crod["narrative_text"] = cro.narrative_text
            cros.append(crod)
    d["choice_random_outcomes"] = cros

    return d


def export_book(db: Session, book: Book, output_dir: Path) -> None:
    """Export a single book's data to YAML files."""
    slug = book.slug
    book_dir = output_dir / slug
    scenes_dir = book_dir / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    # Build game object ID → (kind, name) map
    all_gos = db.query(GameObject).all()
    go_id_map: dict[int, tuple[str, str]] = {go.id: (go.kind, go.name) for go in all_gos}

    # Build scene_id → scene_number map
    scenes = (
        db.query(Scene)
        .filter_by(book_id=book.id)
        .options(
            joinedload(Scene.choices).joinedload(Choice.random_outcomes),
            joinedload(Scene.combat_encounters).joinedload(CombatEncounter.modifiers),
            joinedload(Scene.scene_items),
            joinedload(Scene.random_outcomes),
        )
        .order_by(Scene.number)
        .all()
    )
    scene_id_to_number = {s.id: s.number for s in scenes}

    # Book metadata
    book_id_to_slug = {b.id: b.slug for b in db.query(Book).all()}

    book_yaml: dict = {
        "slug": book.slug,
        "number": book.number,
        "title": book.title,
        "era": book.era,
        "series": book.series,
        "start_scene_number": book.start_scene_number,
        "max_total_picks": book.max_total_picks,
    }

    # Starting equipment
    equip = db.query(BookStartingEquipment).filter_by(book_id=book.id).all()
    equip_list = []
    for e in equip:
        ed: dict = {
            "item_name": e.item_name,
            "item_type": e.item_type,
            "category": e.category,
            "is_default": e.is_default,
        }
        if e.game_object_id and e.game_object_id in go_id_map:
            kind, name = go_id_map[e.game_object_id]
            ed["game_object_kind"] = kind
            ed["game_object_name"] = name
        equip_list.append(ed)
    if equip_list:
        book_yaml["starting_equipment"] = equip_list

    # Transition rules
    rules = db.query(BookTransitionRule).filter_by(from_book_id=book.id).all()
    rules_list = []
    for r in rules:
        rd: dict = {
            "to_book_slug": book_id_to_slug.get(r.to_book_id, f"unknown_{r.to_book_id}"),
            "max_weapons": r.max_weapons,
            "max_backpack_items": r.max_backpack_items,
            "special_items_carry": r.special_items_carry,
            "gold_carries": r.gold_carries,
            "new_disciplines_count": r.new_disciplines_count,
        }
        if r.base_cs_override is not None:
            rd["base_cs_override"] = r.base_cs_override
        if r.base_end_override is not None:
            rd["base_end_override"] = r.base_end_override
        if r.notes:
            rd["notes"] = r.notes
        rules_list.append(rd)
    if rules_list:
        book_yaml["transition_rules"] = rules_list

    _dump_yaml(book_yaml, book_dir / "book.yaml")

    # Build scene appearances per game object for this book's scenes
    go_appearances: dict[int, list[dict]] = {}
    scene_ids_in_book = {s.id for s in scenes}
    all_appearances = (
        db.query(GameObjectSceneAppearance)
        .filter(GameObjectSceneAppearance.scene_id.in_(scene_ids_in_book))
        .all()
    )
    for app in all_appearances:
        sn = scene_id_to_number.get(app.scene_id)
        if sn is not None:
            go_appearances.setdefault(app.game_object_id, []).append(
                {"scene": sn, "type": app.appearance_type}
            )
    for v in go_appearances.values():
        v.sort(key=lambda x: x["scene"])

    # Game objects: include all that appear in this book's scenes OR are
    # attributed to this book.  Entities like Banedon persist across books —
    # they're defined once (first_book) but appear in many books' scenes.
    go_ids_in_book = set(go_appearances.keys())
    gos = (
        db.query(GameObject)
        .filter(
            (GameObject.id.in_(go_ids_in_book))
            | (GameObject.first_book_id == book.id)
            | (GameObject.first_book_id.is_(None))
        )
        .order_by(GameObject.kind, GameObject.name)
        .all()
    )

    go_list = []
    for go in gos:
        god: dict = {
            "kind": go.kind,
            "name": go.name,
        }
        if go.description:
            god["description"] = go.description
        aliases = _json_to_native(go.aliases)
        if aliases and aliases != []:
            god["aliases"] = aliases
        props = _json_to_native(go.properties)
        if props and props != {}:
            god["properties"] = props
        # Track which book first introduced this entity
        if go.first_book_id and go.first_book_id != book.id:
            fb_slug = book_id_to_slug.get(go.first_book_id)
            if fb_slug:
                god["first_book"] = fb_slug
        appearances = go_appearances.get(go.id, [])
        if appearances:
            god["scene_appearances"] = appearances
        go_list.append(god)
    _dump_yaml(go_list, book_dir / "game_objects.yaml")

    # Game object refs
    go_ids_in_book = {go.id for go in gos}
    all_refs = (
        db.query(GameObjectRef)
        .filter(
            GameObjectRef.source_id.in_(go_ids_in_book)
            | GameObjectRef.target_id.in_(go_ids_in_book)
        )
        .all()
    )
    ref_list = []
    for r in all_refs:
        src = go_id_map.get(r.source_id)
        tgt = go_id_map.get(r.target_id)
        if not src or not tgt:
            continue
        rd = {
            "source_kind": src[0],
            "source_name": src[1],
            "target_kind": tgt[0],
            "target_name": tgt[1],
            "tags": _json_to_native(r.tags),
        }
        if r.metadata_:
            rd["metadata"] = _json_to_native(r.metadata_)
        ref_list.append(rd)
    _dump_yaml(ref_list, book_dir / "refs.yaml")

    # Scenes
    for scene in scenes:
        scene_dict = _export_scene(scene, go_id_map, scene_id_to_number)
        _dump_yaml(scene_dict, scenes_dir / f"{scene.number:03d}.yaml")

    print(f"  Exported {len(scenes)} scenes to {scenes_dir}/")


def export_era_shared(db: Session, era: str, output_dir: Path) -> None:
    """Export era-scoped disciplines and CRT."""
    shared_dir = output_dir / "_shared" / era

    # Disciplines
    discs = db.query(Discipline).filter_by(era=era).order_by(Discipline.name).all()
    disc_yaml: dict = {
        "era": era,
        "disciplines": [
            {
                "name": d.name,
                "html_id": d.html_id,
                "description": _LiteralStr(d.description),
                "mechanical_effect": d.mechanical_effect,
            }
            for d in discs
        ],
    }
    _dump_yaml(disc_yaml, shared_dir / "disciplines.yaml")
    print(f"  Exported {len(discs)} disciplines for era '{era}'")

    # Combat results
    crt = (
        db.query(CombatResults)
        .filter_by(era=era)
        .order_by(CombatResults.random_number, CombatResults.combat_ratio_min)
        .all()
    )
    crt_yaml: dict = {
        "era": era,
        "rows": [
            {
                "random_number": r.random_number,
                "combat_ratio_min": r.combat_ratio_min,
                "combat_ratio_max": r.combat_ratio_max,
                "enemy_loss": r.enemy_loss,
                "hero_loss": r.hero_loss,
            }
            for r in crt
        ],
    }
    _dump_yaml(crt_yaml, shared_dir / "combat_results.yaml")
    print(f"  Exported {len(crt)} CRT rows for era '{era}'")


def export_weapon_categories(db: Session, output_dir: Path) -> None:
    """Export global weapon categories."""
    wcs = db.query(WeaponCategory).order_by(WeaponCategory.category, WeaponCategory.weapon_name).all()
    wc_list = [{"weapon_name": w.weapon_name, "category": w.category} for w in wcs]
    _dump_yaml(wc_list, output_dir / "weapon_categories.yaml")
    print(f"  Exported {len(wc_list)} weapon categories")


def run_export(args: argparse.Namespace) -> int:
    """Run the export subcommand."""
    output_dir = Path(args.output_dir)
    db = SessionLocal()
    try:
        if args.all:
            books = db.query(Book).order_by(Book.number).all()
        else:
            books = db.query(Book).filter_by(slug=args.book).all()
            if not books:
                print(f"ERROR: Book '{args.book}' not found", file=sys.stderr)
                return 1

        # Only export books that have scenes
        books_with_scenes = [b for b in books if db.query(Scene).filter_by(book_id=b.id).count() > 0]
        if not books_with_scenes:
            print("No books with scene data found to export.", file=sys.stderr)
            return 1

        # Export shared data for each era encountered
        eras_done: set[str] = set()
        for book in books_with_scenes:
            if book.era not in eras_done:
                export_era_shared(db, book.era, output_dir)
                eras_done.add(book.era)

        export_weapon_categories(db, output_dir)

        for book in books_with_scenes:
            print(f"Exporting Book {book.number}: {book.title} ...")
            export_book(db, book, output_dir)

        print(f"\nExported {len(books_with_scenes)} book(s) to {output_dir}/")
        return 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _flatten_scenes(scene_dicts: list[dict]) -> tuple[
    list[dict], list[dict], list[dict], list[dict], list[dict]
]:
    """Flatten nested scene YAMLs into the flat lists load_book expects.

    Returns (scenes, choices, encounters, items, random_outcomes).
    The random_outcomes list includes both scene-level and choice-level outcomes.
    """
    scenes: list[dict] = []
    choices: list[dict] = []
    encounters: list[dict] = []
    items: list[dict] = []
    random_outcomes: list[dict] = []

    for sd in scene_dicts:
        num = sd["number"]

        # Scene-level fields
        scene_row: dict = {
            "number": num,
            "html_id": sd["html_id"],
            "narrative": sd["narrative"],
            "is_death": sd.get("is_death", False),
            "is_victory": sd.get("is_victory", False),
            "must_eat": sd.get("must_eat", False),
            "loses_backpack": sd.get("loses_backpack", False),
            "illustration_path": sd.get("illustration_path"),
            "source": sd.get("source", "auto"),
        }
        if "game_object_kind" in sd:
            scene_row["game_object_kind"] = sd["game_object_kind"]
            scene_row["game_object_name"] = sd["game_object_name"]
        scenes.append(scene_row)

        # Choices
        for cd in sd.get("choices", []):
            choice_row: dict = {
                "scene_number": num,
                "target_scene_number": cd["target_scene_number"],
                "raw_text": cd.get("raw_text", cd.get("display_text", "")),
                "display_text": cd.get("display_text", cd.get("raw_text", "")),
                "condition_type": cd.get("condition_type"),
                "condition_value": cd.get("condition_value"),
                "ordinal": cd["ordinal"],
                "source": cd.get("source", "auto"),
            }
            choices.append(choice_row)

        # Combat encounters
        for ed in sd.get("combat_encounters", []):
            enc_row: dict = {
                "scene_number": num,
                "enemy_name": ed["enemy_name"],
                "enemy_cs": ed["enemy_cs"],
                "enemy_end": ed["enemy_end"],
                "ordinal": ed["ordinal"],
                "mindblast_immune": ed.get("mindblast_immune", False),
                "evasion_after_rounds": ed.get("evasion_after_rounds"),
                "evasion_target": ed.get("evasion_target"),
                "evasion_damage": ed.get("evasion_damage", 0),
                "condition_type": ed.get("condition_type"),
                "condition_value": ed.get("condition_value"),
                "source": ed.get("source", "auto"),
            }
            if "foe_game_object_kind" in ed:
                enc_row["foe_game_object_kind"] = ed["foe_game_object_kind"]
                enc_row["foe_game_object_name"] = ed["foe_game_object_name"]
            # Modifiers (nested, passed through as-is)
            mods = []
            for md in ed.get("modifiers", []):
                mods.append({
                    "modifier_type": md["modifier_type"],
                    "modifier_value": md.get("modifier_value"),
                    "condition": md.get("condition"),
                    "source": md.get("source", "auto"),
                })
            enc_row["modifiers"] = mods
            encounters.append(enc_row)

        # Scene items
        for sid in sd.get("items", []):
            item_row: dict = {
                "scene_number": num,
                "item_name": sid["item_name"],
                "item_type": sid["item_type"],
                "quantity": sid.get("quantity", 1),
                "action": sid["action"],
                "is_mandatory": sid.get("is_mandatory", False),
                "phase_ordinal": sid.get("phase_ordinal", 0),
                "source": sid.get("source", "auto"),
            }
            if "game_object_kind" in sid:
                item_row["game_object_kind"] = sid["game_object_kind"]
                item_row["game_object_name"] = sid["game_object_name"]
            items.append(item_row)

        # Scene-level random outcomes
        for rod in sd.get("random_outcomes", []):
            ro_row: dict = {
                "scene_number": num,
                "roll_group": rod.get("roll_group", 0),
                "range_min": rod["range_min"],
                "range_max": rod["range_max"],
                "effect_type": rod["effect_type"],
                "effect_value": rod["effect_value"],
                "narrative_text": rod.get("narrative_text"),
                "ordinal": rod.get("ordinal", 0),
                "source": rod.get("source", "auto"),
            }
            random_outcomes.append(ro_row)

        # Choice random outcomes → special format
        for crod in sd.get("choice_random_outcomes", []):
            cro_row: dict = {
                "choice_scene_number": num,
                "choice_ordinal": crod["choice_ordinal"],
                "target_scene_number": crod["target_scene_number"],
                "range_min": crod["range_min"],
                "range_max": crod["range_max"],
                "narrative_text": crod.get("narrative_text"),
                "source": crod.get("source", "auto"),
            }
            random_outcomes.append(cro_row)

    return scenes, choices, encounters, items, random_outcomes


def run_import(args: argparse.Namespace) -> int:
    """Run the import subcommand."""
    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"ERROR: --input-dir does not exist: {input_dir}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        if args.all:
            # Find all book directories (exclude _shared)
            book_slugs = sorted(
                d.name for d in input_dir.iterdir()
                if d.is_dir() and d.name != "_shared" and (d / "book.yaml").exists()
            )
        else:
            book_slugs = [args.book]

        if not book_slugs:
            print("No books found to import.", file=sys.stderr)
            return 1

        for slug in book_slugs:
            book_dir = input_dir / slug
            if not (book_dir / "book.yaml").exists():
                print(f"ERROR: {book_dir}/book.yaml not found", file=sys.stderr)
                return 1

            print(f"Importing {slug} ...")
            _import_single_book(db, slug, book_dir, input_dir)
            db.commit()
            print(f"  Committed {slug}")

        print(f"\nImported {len(book_slugs)} book(s)")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _import_single_book(db: Session, slug: str, book_dir: Path, root_dir: Path) -> None:
    """Import a single book from YAML into the database."""
    # Book metadata
    book_yaml = _load_yaml(book_dir / "book.yaml")
    era = book_yaml["era"]

    book_data: dict = {
        "slug": book_yaml["slug"],
        "number": book_yaml["number"],
        "title": book_yaml["title"],
        "era": era,
        "series": book_yaml.get("series", "lone_wolf"),
        "start_scene_number": book_yaml.get("start_scene_number", 1),
        "max_total_picks": book_yaml["max_total_picks"],
        "source": "auto",
    }

    # Starting equipment
    starting_equipment = []
    for se in book_yaml.get("starting_equipment", []):
        row: dict = {
            "item_name": se["item_name"],
            "item_type": se["item_type"],
            "category": se["category"],
            "is_default": se.get("is_default", False),
            "source": se.get("source", "auto"),
        }
        if "game_object_kind" in se:
            row["game_object_kind"] = se["game_object_kind"]
            row["game_object_name"] = se["game_object_name"]
        starting_equipment.append(row)

    # Transition rules
    transition_rules = []
    for tr in book_yaml.get("transition_rules", []):
        transition_rules.append({
            "to_book_slug": tr["to_book_slug"],
            "max_weapons": tr["max_weapons"],
            "max_backpack_items": tr["max_backpack_items"],
            "special_items_carry": tr["special_items_carry"],
            "gold_carries": tr["gold_carries"],
            "new_disciplines_count": tr["new_disciplines_count"],
            "base_cs_override": tr.get("base_cs_override"),
            "base_end_override": tr.get("base_end_override"),
            "notes": tr.get("notes"),
        })

    # Disciplines (era-scoped)
    discipline_dicts: list[dict] = []
    disc_path = root_dir / "_shared" / era / "disciplines.yaml"
    if disc_path.exists():
        disc_yaml = _load_yaml(disc_path)
        for d in disc_yaml.get("disciplines", []):
            discipline_dicts.append({
                "era": era,
                "name": d["name"],
                "html_id": d["html_id"],
                "description": d["description"],
                "mechanical_effect": d.get("mechanical_effect"),
                "source": "auto",
            })

    # CRT (era-scoped)
    crt_dicts: list[dict] = []
    crt_path = root_dir / "_shared" / era / "combat_results.yaml"
    if crt_path.exists():
        crt_yaml = _load_yaml(crt_path)
        for r in crt_yaml.get("rows", []):
            crt_dicts.append({
                "era": era,
                "random_number": r["random_number"],
                "combat_ratio_min": r["combat_ratio_min"],
                "combat_ratio_max": r["combat_ratio_max"],
                "enemy_loss": r.get("enemy_loss"),
                "hero_loss": r.get("hero_loss"),
            })

    # Weapon categories (global)
    weapon_dicts: list[dict] = []
    wc_path = root_dir / "weapon_categories.yaml"
    if wc_path.exists():
        wc_yaml = _load_yaml(wc_path)
        for w in (wc_yaml or []):
            weapon_dicts.append({
                "weapon_name": w["weapon_name"],
                "category": w["category"],
            })

    # Game objects + scene appearances
    game_object_dicts: list[dict] = []
    appearance_dicts: list[dict] = []
    go_path = book_dir / "game_objects.yaml"
    if go_path.exists():
        go_yaml = _load_yaml(go_path) or []
        for go in go_yaml:
            # Use first_book field if present (entity from an earlier book),
            # otherwise default to the current book being imported.
            first_book = go.get("first_book", slug)
            game_object_dicts.append({
                "kind": go["kind"],
                "name": go["name"],
                "description": go.get("description"),
                "aliases": _native_to_json(go.get("aliases", [])),
                "properties": _native_to_json(go.get("properties", {})),
                "first_book_slug": first_book,
                "source": go.get("source", "auto"),
            })
            for app in go.get("scene_appearances", []):
                appearance_dicts.append({
                    "game_object_kind": go["kind"],
                    "game_object_name": go["name"],
                    "scene_number": app["scene"],
                    "appearance_type": app["type"],
                    "source": "auto",
                })

    # Refs
    ref_dicts: list[dict] = []
    ref_path = book_dir / "refs.yaml"
    if ref_path.exists():
        ref_yaml = _load_yaml(ref_path) or []
        for r in ref_yaml:
            ref_dicts.append({
                "source_kind": r["source_kind"],
                "source_name": r["source_name"],
                "target_kind": r["target_kind"],
                "target_name": r["target_name"],
                "tags": _native_to_json(r["tags"]),
                "metadata_": _native_to_json(r.get("metadata")) if r.get("metadata") else None,
                "source": r.get("source", "auto"),
            })

    # Scenes
    scenes_dir = book_dir / "scenes"
    scene_dicts: list[dict] = []
    if scenes_dir.is_dir():
        for scene_path in sorted(scenes_dir.glob("*.yaml")):
            sd = _load_yaml(scene_path)
            if sd:
                scene_dicts.append(sd)

    scenes, choices, encounters, items, random_outcomes = _flatten_scenes(scene_dicts)

    summary = load_book(
        db,
        book_data=book_data,
        scenes=scenes,
        choices=choices,
        encounters=encounters,
        items=items,
        random_outcomes=random_outcomes,
        disciplines=discipline_dicts,
        crt_rows=crt_dicts,
        game_objects=game_object_dicts,
        refs=ref_dicts,
        weapon_categories=weapon_dicts,
        starting_equipment=starting_equipment,
        transition_rules=transition_rules,
        scene_appearances=appearance_dicts if appearance_dicts else None,
    )
    print(f"  Load summary: {summary}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yaml_io",
        description="Export/import Lone Wolf book data as YAML files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Export
    exp = sub.add_parser("export", help="Export book data from DB to YAML")
    exp_group = exp.add_mutually_exclusive_group(required=True)
    exp_group.add_argument("--book", metavar="SLUG", help="Book slug to export (e.g. 01fftd)")
    exp_group.add_argument("--all", action="store_true", help="Export all books with scene data")
    exp.add_argument("--output-dir", default="data/books", help="Output directory (default: data/books)")

    # Import
    imp = sub.add_parser("import", help="Import book data from YAML to DB")
    imp_group = imp.add_mutually_exclusive_group(required=True)
    imp_group.add_argument("--book", metavar="SLUG", help="Book slug to import")
    imp_group.add_argument("--all", action="store_true", help="Import all books in input dir")
    imp.add_argument("--input-dir", default="data/books", help="Input directory (default: data/books)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "export":
        return run_export(args)
    elif args.command == "import":
        return run_import(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
