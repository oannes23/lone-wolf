"""Deduplicate game objects using heuristic clustering + LLM merge decisions.

Usage:
    uv run python scripts/dedup_game_objects.py --book 01fftd --dry-run
    uv run python scripts/dedup_game_objects.py --book 01fftd
    uv run python scripts/dedup_game_objects.py --book 01fftd --yaml-dir data/books
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.content import (  # noqa: E402
    Book,
    CombatEncounter,
    Scene,
    SceneItem,
)
from app.models.taxonomy import (  # noqa: E402
    BookStartingEquipment,
    GameObject,
    GameObjectRef,
    GameObjectSceneAppearance,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MergePlan:
    canonical_kind: str
    canonical_name: str
    merged_description: str
    merged_aliases: list[str]
    absorbed_names: list[str]
    reason: str


@dataclass
class DeletePlan:
    kind: str
    name: str
    reason: str


@dataclass
class DeduplicationReport:
    merges: list[MergePlan] = field(default_factory=list)
    deletes: list[DeletePlan] = field(default_factory=list)
    unchanged: int = 0


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_for_dedup(name: str) -> str:
    """Normalize a name for dedup comparison."""
    n = name.lower().strip()
    for article in ("the ", "a ", "an "):
        if n.startswith(article):
            n = n[len(article):]
    if n.endswith("ves") and len(n) > 4:
        n = n[:-3] + "f"
    elif n.endswith("ies") and len(n) > 4:
        n = n[:-3] + "y"
    elif n.endswith("es") and not n.endswith("ss") and len(n) > 3:
        n = n[:-2]
    elif n.endswith("s") and not n.endswith("ss") and len(n) > 3:
        n = n[:-1]
    return n


def _parse_aliases(aliases_raw: str) -> list[str]:
    """Parse aliases from DB (JSON or Python repr format)."""
    if not aliases_raw or aliases_raw == "[]":
        return []
    try:
        result = json.loads(aliases_raw)
        if isinstance(result, list):
            return [str(a) for a in result]
    except (json.JSONDecodeError, TypeError):
        pass
    import ast
    try:
        result = ast.literal_eval(aliases_raw)
        if isinstance(result, list):
            return [str(a) for a in result]
    except (ValueError, SyntaxError):
        pass
    return []


# ---------------------------------------------------------------------------
# Heuristic clustering
# ---------------------------------------------------------------------------

def build_candidate_clusters(
    game_objects: list[dict],
) -> list[list[dict]]:
    """Group game objects into candidate duplicate clusters by kind."""
    # Group by kind
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for go in game_objects:
        by_kind[go["kind"]].append(go)

    clusters: list[list[dict]] = []

    for kind, gos in by_kind.items():
        # Build normalized key → list of GOs
        norm_groups: dict[str, list[dict]] = defaultdict(list)
        for go in gos:
            key = _normalize_for_dedup(go["name"])
            norm_groups[key].append(go)

        # Also check alias overlap
        for go in gos:
            aliases = go.get("aliases_parsed", [])
            for alias in aliases:
                alias_norm = _normalize_for_dedup(alias)
                # If alias matches another GO's normalized name, merge groups
                if alias_norm in norm_groups:
                    target_group = norm_groups[alias_norm]
                    go_norm = _normalize_for_dedup(go["name"])
                    if go_norm != alias_norm:
                        # Merge the two groups
                        source_group = norm_groups.get(go_norm, [])
                        if source_group and target_group:
                            combined = list({id(g): g for g in target_group + source_group}.values())
                            norm_groups[alias_norm] = combined
                            norm_groups[go_norm] = combined

        # Deduplicate clusters (same list object may appear under multiple keys)
        seen_ids: set[int] = set()
        for key, group in norm_groups.items():
            group_id = id(group)
            if group_id in seen_ids:
                continue
            seen_ids.add(group_id)
            if len(group) > 1:
                clusters.append(group)

    return clusters


# ---------------------------------------------------------------------------
# Scene co-occurrence enrichment
# ---------------------------------------------------------------------------

def _enrich_with_scene_data(
    db: Session,
    game_objects: list[dict],
) -> None:
    """Add scene_numbers list to each game object dict."""
    go_ids = [go["id"] for go in game_objects]
    appearances = (
        db.query(GameObjectSceneAppearance)
        .filter(GameObjectSceneAppearance.game_object_id.in_(go_ids))
        .all()
    )

    # Build go_id → set of scene_ids
    go_scenes: dict[int, set[int]] = defaultdict(set)
    for a in appearances:
        go_scenes[a.game_object_id].add(a.scene_id)

    # Map scene_id → scene_number
    scene_ids = set()
    for s in go_scenes.values():
        scene_ids.update(s)
    if scene_ids:
        scenes = db.query(Scene).filter(Scene.id.in_(scene_ids)).all()
        scene_id_to_num = {s.id: s.number for s in scenes}
    else:
        scene_id_to_num = {}

    for go in game_objects:
        scene_set = go_scenes.get(go["id"], set())
        go["scene_numbers"] = sorted(scene_id_to_num.get(sid, 0) for sid in scene_set)


def _find_cooccurrence_candidates(
    game_objects: list[dict],
) -> list[list[dict]]:
    """Find entities that share scenes, especially generic+proper name pairs."""
    # Characters that might be reveal patterns
    characters = [go for go in game_objects if go["kind"] == "character"]

    # Identify "generic" names (lowercase first char, or common titles)
    generic_patterns = {"man", "woman", "wizard", "hermit", "stranger", "guard",
                        "soldier", "merchant", "priest", "cleric", "captain",
                        "leader", "driver", "boy", "girl", "old man", "young"}

    generics = []
    propers = []
    for ch in characters:
        name_lower = ch["name"].lower()
        is_generic = (
            ch["name"][0].islower()
            or any(name_lower.startswith(g) or name_lower.endswith(g) for g in generic_patterns)
        )
        if is_generic:
            generics.append(ch)
        else:
            propers.append(ch)

    extra_clusters: list[list[dict]] = []
    for gen in generics:
        gen_scenes = set(gen.get("scene_numbers", []))
        if not gen_scenes:
            continue
        for prop in propers:
            prop_scenes = set(prop.get("scene_numbers", []))
            overlap = gen_scenes & prop_scenes
            if overlap:
                extra_clusters.append([gen, prop])

    return extra_clusters


# ---------------------------------------------------------------------------
# LLM merge plan
# ---------------------------------------------------------------------------

def generate_merge_plan(
    clusters: list[list[dict]],
    all_game_objects: list[dict],
    client: object | None = None,
) -> DeduplicationReport:
    """Send candidate clusters + full entity list to Haiku for merge decisions."""
    import anthropic

    if client is None:
        client = anthropic.Anthropic()

    # Build the prompt
    cluster_descriptions = []
    for i, cluster in enumerate(clusters):
        entries = []
        for go in cluster:
            scenes_str = ", ".join(str(s) for s in go.get("scene_numbers", [])[:10])
            if len(go.get("scene_numbers", [])) > 10:
                scenes_str += f" ... ({len(go['scene_numbers'])} total)"
            aliases = go.get("aliases_parsed", [])
            entries.append(
                f"  - name={go['name']!r}, kind={go['kind']}, "
                f"desc={go.get('description', '')!r}, "
                f"aliases={aliases}, scenes=[{scenes_str}]"
            )
        cluster_descriptions.append(f"Cluster {i+1}:\n" + "\n".join(entries))

    # Also find entities to potentially delete (generic/low-quality)
    all_names = []
    for go in all_game_objects:
        aliases = go.get("aliases_parsed", [])
        all_names.append(
            f"  {go['kind']}: {go['name']!r} (aliases={aliases}, "
            f"scenes={len(go.get('scene_numbers', []))})"
        )

    system_prompt = """\
You are deduplicating a knowledge graph of entities extracted from a Lone Wolf gamebook.

Return ONLY valid JSON matching this schema:
{
  "merges": [
    {
      "canonical_name": "the best name for this entity",
      "canonical_kind": "character|creature|location|organization",
      "merged_description": "combined description",
      "merged_aliases": ["alias1", "alias2"],
      "absorbed_names": ["Name2", "Name3"],
      "reason": "why these are the same"
    }
  ],
  "deletes": [
    {
      "kind": "character",
      "name": "Man",
      "reason": "generic reference, not a named entity"
    }
  ]
}

Rules:
- For merges: pick the most specific proper name as canonical. Keep absorbed names as aliases.
- Singular vs plural: always use singular as canonical ("Giak" not "Giaks").
- Articles: drop leading "The"/"A" ("King" not "The King").
- Narrative reveal pattern: when a character appears first as a generic title ("young wizard") and later by name ("Banedon"), merge under the proper name. Scene co-occurrence is a strong signal.
- Legitimately distinct entities should NOT be merged (e.g., "Giak" and "Giak Officer" are different).
- Delete generic references that aren't proper-noun entities (e.g., "Man", "Horse", "Creature", "Guards", "driver", "merchant", "Tree", "Forest").
- Keep named locations like "Dorier Forest" but delete generic "Forest".
- Be aggressive about deleting low-quality generic entities.
- Do not invent merges not supported by the data."""

    user_prompt = f"""\
Here are candidate duplicate clusters to review:

{chr(10).join(cluster_descriptions)}

And here is the full entity list (review for entities that should be deleted as generic):

{chr(10).join(all_names)}

Return the merge plan as JSON."""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16384,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    # Parse response
    text = response.content[0].text
    # Strip markdown code fences if present
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    # Fix common JSON issues: trailing commas
    import re as _re
    text = _re.sub(r",\s*([}\]])", r"\1", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Write raw response for debugging
        Path("dedup_raw_response.txt").write_text(text, encoding="utf-8")
        print(f"ERROR: Could not parse LLM response as JSON: {e}", file=sys.stderr)
        print("Raw response saved to dedup_raw_response.txt", file=sys.stderr)
        raise

    report = DeduplicationReport()
    for m in data.get("merges", []):
        report.merges.append(MergePlan(
            canonical_kind=m["canonical_kind"],
            canonical_name=m["canonical_name"],
            merged_description=m.get("merged_description", ""),
            merged_aliases=m.get("merged_aliases", []),
            absorbed_names=m.get("absorbed_names", []),
            reason=m.get("reason", ""),
        ))
    for d in data.get("deletes", []):
        report.deletes.append(DeletePlan(
            kind=d["kind"],
            name=d["name"],
            reason=d.get("reason", ""),
        ))

    return report


# ---------------------------------------------------------------------------
# Apply merges to DB
# ---------------------------------------------------------------------------

def apply_report(db: Session, report: DeduplicationReport) -> dict[str, int]:
    """Apply merges and deletes to the database."""
    counts = {"merged": 0, "deleted": 0, "refs_updated": 0, "appearances_updated": 0}

    # Process merges
    for merge in report.merges:
        canonical = (
            db.query(GameObject)
            .filter_by(kind=merge.canonical_kind, name=merge.canonical_name)
            .one_or_none()
        )
        if canonical is None:
            # Canonical might be an absorbed name being renamed — find it
            for name in [merge.canonical_name] + merge.absorbed_names:
                canonical = (
                    db.query(GameObject)
                    .filter_by(kind=merge.canonical_kind, name=name)
                    .one_or_none()
                )
                if canonical:
                    break
            if canonical is None:
                print(f"  WARNING: Cannot find canonical {merge.canonical_kind}/{merge.canonical_name}")
                continue

        # Update canonical's fields
        canonical.name = merge.canonical_name
        if merge.merged_description:
            canonical.description = merge.merged_description
        canonical.aliases = json.dumps(merge.merged_aliases, ensure_ascii=False)

        # Find and absorb the other entities
        for absorbed_name in merge.absorbed_names:
            if absorbed_name == canonical.name:
                continue
            absorbed = (
                db.query(GameObject)
                .filter_by(kind=merge.canonical_kind, name=absorbed_name)
                .one_or_none()
            )
            if absorbed is None:
                continue

            absorbed_id = absorbed.id
            canonical_id = canonical.id

            # Update all FK references
            for ref in db.query(GameObjectRef).filter_by(source_id=absorbed_id).all():
                ref.source_id = canonical_id
                counts["refs_updated"] += 1
            for ref in db.query(GameObjectRef).filter_by(target_id=absorbed_id).all():
                ref.target_id = canonical_id
                counts["refs_updated"] += 1

            for enc in db.query(CombatEncounter).filter_by(foe_game_object_id=absorbed_id).all():
                enc.foe_game_object_id = canonical_id
            for si in db.query(SceneItem).filter_by(game_object_id=absorbed_id).all():
                si.game_object_id = canonical_id
            for s in db.query(Scene).filter_by(game_object_id=absorbed_id).all():
                s.game_object_id = canonical_id
            for bse in db.query(BookStartingEquipment).filter_by(game_object_id=absorbed_id).all():
                bse.game_object_id = canonical_id

            # Move scene appearances (skip duplicates)
            for app in db.query(GameObjectSceneAppearance).filter_by(game_object_id=absorbed_id).all():
                existing = (
                    db.query(GameObjectSceneAppearance)
                    .filter_by(
                        game_object_id=canonical_id,
                        scene_id=app.scene_id,
                        appearance_type=app.appearance_type,
                    )
                    .one_or_none()
                )
                if existing is None:
                    app.game_object_id = canonical_id
                    counts["appearances_updated"] += 1
                else:
                    db.delete(app)

            db.flush()

            # Delete duplicate refs (same source+target+tags after merge)
            _dedup_refs(db, canonical_id)

            # Delete the absorbed game object
            db.delete(absorbed)
            counts["merged"] += 1

        db.flush()

    # Process deletes
    for delete in report.deletes:
        go = (
            db.query(GameObject)
            .filter_by(kind=delete.kind, name=delete.name)
            .one_or_none()
        )
        if go is None:
            continue

        # Delete appearances, refs, then the object
        db.query(GameObjectSceneAppearance).filter_by(game_object_id=go.id).delete()
        db.query(GameObjectRef).filter(
            (GameObjectRef.source_id == go.id) | (GameObjectRef.target_id == go.id)
        ).delete(synchronize_session="fetch")
        # Null out FK references rather than cascade
        for enc in db.query(CombatEncounter).filter_by(foe_game_object_id=go.id).all():
            enc.foe_game_object_id = None
        for si in db.query(SceneItem).filter_by(game_object_id=go.id).all():
            si.game_object_id = None
        for s in db.query(Scene).filter_by(game_object_id=go.id).all():
            s.game_object_id = None
        for bse in db.query(BookStartingEquipment).filter_by(game_object_id=go.id).all():
            bse.game_object_id = None

        db.delete(go)
        counts["deleted"] += 1

    db.flush()
    return counts


def _dedup_refs(db: Session, go_id: int) -> None:
    """Remove duplicate refs after a merge (same source+target+tags)."""
    refs = (
        db.query(GameObjectRef)
        .filter(
            (GameObjectRef.source_id == go_id) | (GameObjectRef.target_id == go_id)
        )
        .all()
    )
    seen: set[tuple[int, int, str]] = set()
    for ref in refs:
        key = (ref.source_id, ref.target_id, ref.tags)
        if key in seen:
            db.delete(ref)
        else:
            seen.add(key)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dedup_game_objects",
        description="Deduplicate game objects using heuristic clustering + LLM.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--book", metavar="SLUG")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't apply")
    parser.add_argument("--yaml-dir", metavar="DIR", help="Also re-export YAML after dedup")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        # Load all game objects
        all_gos_query = db.query(GameObject).order_by(GameObject.kind, GameObject.name).all()
        game_objects = []
        for go in all_gos_query:
            game_objects.append({
                "id": go.id,
                "kind": go.kind,
                "name": go.name,
                "description": go.description,
                "aliases_parsed": _parse_aliases(go.aliases),
                "source": go.source,
            })

        print(f"Loaded {len(game_objects)} game objects")

        # Enrich with scene data
        print("Enriching with scene appearance data ...")
        _enrich_with_scene_data(db, game_objects)

        # Step 1: Heuristic clustering
        clusters = build_candidate_clusters(game_objects)
        print(f"Found {len(clusters)} candidate clusters from heuristics")

        # Step 1.5: Co-occurrence candidates
        cooccurrence = _find_cooccurrence_candidates(game_objects)
        print(f"Found {len(cooccurrence)} co-occurrence candidates")

        # Merge cluster lists, deduplicating
        all_clusters = clusters + cooccurrence
        # Deduplicate: if any two clusters share a member, merge them
        all_clusters = _merge_overlapping_clusters(all_clusters)
        print(f"Total clusters after merge: {len(all_clusters)}")

        if not all_clusters and not game_objects:
            print("Nothing to deduplicate.")
            return 0

        # Step 2: LLM merge plan
        print("Generating LLM merge plan ...")
        report = generate_merge_plan(all_clusters, game_objects)

        print(f"\nMerge plan: {len(report.merges)} merges, {len(report.deletes)} deletes")
        for m in report.merges:
            print(f"  MERGE: {m.absorbed_names} → {m.canonical_name} ({m.reason})")
        for d in report.deletes:
            print(f"  DELETE: {d.kind}/{d.name} ({d.reason})")

        # Write report
        report_path = Path(f"dedup_report.json")
        report_data = {
            "merges": [asdict(m) for m in report.merges],
            "deletes": [asdict(d) for d in report.deletes],
        }
        report_path.write_text(
            json.dumps(report_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nReport written to {report_path}")

        if args.dry_run:
            print("\nDry run — no changes applied.")
            return 0

        # Step 3: Apply
        print("\nApplying merges ...")
        counts = apply_report(db, report)
        db.commit()
        print(f"Done: {counts}")

        remaining = db.query(GameObject).count()
        print(f"Game objects remaining: {remaining}")

        # Step 4: Re-export YAML if requested
        if args.yaml_dir:
            print(f"\nRe-exporting YAML to {args.yaml_dir} ...")
            from scripts.yaml_io import export_book, SessionLocal as _  # noqa: F401

            if args.all:
                books = db.query(Book).order_by(Book.number).all()
            else:
                books = db.query(Book).filter_by(slug=args.book).all()

            for book in books:
                if db.query(Scene).filter_by(book_id=book.id).count() > 0:
                    from scripts.yaml_io import export_book
                    export_book(db, book, Path(args.yaml_dir))

        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _merge_overlapping_clusters(clusters: list[list[dict]]) -> list[list[dict]]:
    """Merge clusters that share any member."""
    if not clusters:
        return []

    # Use union-find by name
    name_to_cluster_idx: dict[str, int] = {}
    parent: list[int] = list(range(len(clusters)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for idx, cluster in enumerate(clusters):
        for go in cluster:
            key = f"{go['kind']}:{go['name']}"
            if key in name_to_cluster_idx:
                union(idx, name_to_cluster_idx[key])
            else:
                name_to_cluster_idx[key] = idx

    # Collect merged clusters
    merged: dict[int, list[dict]] = defaultdict(list)
    for idx, cluster in enumerate(clusters):
        root = find(idx)
        seen_names: set[str] = {f"{g['kind']}:{g['name']}" for g in merged[root]}
        for go in cluster:
            key = f"{go['kind']}:{go['name']}"
            if key not in seen_names:
                merged[root].append(go)
                seen_names.add(key)

    return [c for c in merged.values() if len(c) > 1]


if __name__ == "__main__":
    sys.exit(main())
