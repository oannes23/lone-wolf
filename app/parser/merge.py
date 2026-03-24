"""Reconciliation logic for merging manual heuristic extraction with LLM results.

Each merge function accepts manual and LLM extraction outputs for a single
data type and returns ``(merged_result, warnings)`` where warnings list
any disagreements found between the two sources.

When LLM data is ``None`` (i.e. ``--skip-llm`` was set), all merge functions
pass through manual results unchanged with no warnings.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def merge_combat_encounters(
    manual: list[dict],
    llm: list[dict] | None,
    scene_number: int,
) -> tuple[list[dict], list[str]]:
    """Merge combat encounter lists.

    When LLM returns at least one encounter it wins outright, but encounters
    found only in the manual extraction are also included (with a warning).
    When LLM returns an empty list, manual results are passed through silently.
    When LLM is ``None`` (``--skip-llm``), manual results are passed through.

    Note on field names: manual encounters use ``enemy_cs``/``enemy_end``
    while LLM encounters use ``combat_skill``/``endurance``.  The merged
    output normalises to ``enemy_cs``/``enemy_end``.

    Args:
        manual: Combat encounter dicts from the transform phase.
        llm: Combat encounter dicts from :func:`~app.parser.llm.analyze_scene`,
            or ``None`` when LLM was skipped.
        scene_number: Scene number for warning messages.

    Returns:
        ``(merged, warnings)`` where *merged* uses ``enemy_cs``/``enemy_end``
        field names and *warnings* lists any disagreements found.
    """
    if llm is None:
        return manual, []

    warnings: list[str] = []

    if not llm:
        return manual, []

    # LLM returned encounters — it wins, but warn on disagreements
    if manual:
        manual_names = {e["enemy_name"].lower() for e in manual}
        llm_names = {e["enemy_name"].lower() for e in llm}
        only_manual = manual_names - llm_names
        only_llm = llm_names - manual_names
        if only_manual:
            warnings.append(
                f"MERGE_CONFLICT scene={scene_number} field=combat_encounters: "
                f"manual_only={sorted(only_manual)} — included from manual"
            )
        if only_llm:
            warnings.append(
                f"MERGE_CONFLICT scene={scene_number} field=combat_encounters: "
                f"llm_only={sorted(only_llm)} — included from LLM"
            )
        for me in manual:
            for le in llm:
                if me["enemy_name"].lower() == le["enemy_name"].lower():
                    if me.get("enemy_cs") != le.get("combat_skill") or me.get("enemy_end") != le.get("endurance"):
                        warnings.append(
                            f"MERGE_CONFLICT scene={scene_number} field=combat_stats "
                            f"enemy={me['enemy_name']}: "
                            f"manual=CS{me.get('enemy_cs')}/END{me.get('enemy_end')} "
                            f"llm=CS{le.get('combat_skill')}/END{le.get('endurance')} "
                            f"winner=llm"
                        )

    # Convert LLM format to manual format + include manual-only encounters
    merged: list[dict] = []
    llm_names_lower = {e["enemy_name"].lower() for e in llm}

    for le in llm:
        merged.append({
            "enemy_name": le["enemy_name"],
            "enemy_cs": le["combat_skill"],
            "enemy_end": le["endurance"],
            "ordinal": le.get("ordinal", len(merged) + 1),
        })

    # Add manual-only encounters that LLM missed
    for me in manual:
        if me["enemy_name"].lower() not in llm_names_lower:
            merged.append(me)

    return merged, warnings


def merge_items(
    manual: list[dict],
    llm: list[dict] | None,
    scene_number: int,
) -> tuple[list[dict], list[str]]:
    """Merge item lists.  Union of both, deduplicated by (item_name, action)."""
    if llm is None:
        return manual, []

    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []

    # LLM items first (preferred source)
    for item in llm:
        key = (item["item_name"].lower(), item["action"])
        if key not in seen:
            seen.add(key)
            merged.append(item)

    # Manual items that weren't in LLM output
    for item in manual:
        key = (item.get("item_name", "").lower(), item.get("action", ""))
        if key not in seen:
            seen.add(key)
            merged.append(item)
            warnings.append(
                f"MERGE_CONFLICT scene={scene_number} field=items: "
                f"manual_only={item.get('item_name')} action={item.get('action')} — included from manual"
            )

    # Check for quantity disagreements
    manual_by_key = {
        (i.get("item_name", "").lower(), i.get("action", "")): i for i in manual
    }
    for item in llm:
        key = (item["item_name"].lower(), item["action"])
        mi = manual_by_key.get(key)
        if mi and mi.get("quantity", 1) != item.get("quantity", 1):
            warnings.append(
                f"MERGE_CONFLICT scene={scene_number} field=item_quantity "
                f"item={item['item_name']}: manual={mi.get('quantity', 1)} "
                f"llm={item.get('quantity', 1)} winner=llm"
            )

    return merged, warnings


def merge_random_outcomes(
    manual: list[dict],
    llm: list[dict] | None,
    scene_number: int,
) -> tuple[list[dict], list[str]]:
    """Merge random outcome bands.

    When LLM returns at least one outcome band it wins outright (the entire
    LLM list replaces manual).  A warning is emitted if the count differs.
    When LLM returns an empty list, manual results are passed through silently.
    When LLM is ``None`` (``--skip-llm``), manual results are passed through.

    Args:
        manual: Random outcome dicts from the transform phase.
        llm: Random outcome dicts from :func:`~app.parser.llm.analyze_scene`,
            or ``None`` when LLM was skipped.
        scene_number: Scene number for warning messages.

    Returns:
        ``(merged, warnings)`` where *merged* is the winning outcome list and
        *warnings* notes count mismatches between sources.
    """
    if llm is None:
        return manual, []

    warnings: list[str] = []

    if not llm:
        return manual, []

    if manual and len(manual) != len(llm):
        warnings.append(
            f"MERGE_CONFLICT scene={scene_number} field=random_outcomes: "
            f"manual_count={len(manual)} llm_count={len(llm)} winner=llm"
        )

    return llm, warnings


def merge_evasion(
    manual: tuple | None,
    llm: dict | None,
    scene_number: int,
) -> tuple[tuple | None, list[str]]:
    """Merge evasion data.  LLM wins if it returns evasion info.

    Manual evasion is a (rounds, target_scene, damage) tuple.
    LLM evasion is a dict with {rounds, target_scene, damage}.
    Result is always a tuple or None.
    """
    if llm is None:
        # --skip-llm: pass through manual
        return manual, []

    warnings: list[str] = []

    if not llm:
        return manual, []

    llm_tuple = (llm["rounds"], llm["target_scene"], llm.get("damage", 0))

    if manual and manual != llm_tuple:
        warnings.append(
            f"MERGE_CONFLICT scene={scene_number} field=evasion: "
            f"manual={manual} llm={llm_tuple} winner=llm"
        )

    return llm_tuple, warnings


def merge_combat_modifiers(
    manual: list[dict],
    llm: list[dict] | None,
    scene_number: int,
) -> tuple[list[dict], list[str]]:
    """Merge combat modifiers.  Union of both, deduplicated by modifier_type."""
    if llm is None:
        return manual, []

    warnings: list[str] = []
    seen_types: set[str] = set()
    merged: list[dict] = []

    # LLM modifiers first (preferred)
    for mod in llm:
        mtype = mod["modifier_type"]
        if mtype not in seen_types:
            seen_types.add(mtype)
            merged.append(mod)

    # Manual modifiers not in LLM
    for mod in manual:
        mtype = mod.get("modifier_type", "")
        if mtype not in seen_types:
            seen_types.add(mtype)
            merged.append(mod)
            warnings.append(
                f"MERGE_CONFLICT scene={scene_number} field=combat_modifiers: "
                f"manual_only={mtype} — included from manual"
            )

    return merged, warnings


def merge_conditions(
    manual_choices: list[dict],
    llm_conditions: list[dict] | None,
    scene_number: int,
) -> tuple[list[dict], list[str]]:
    """Merge choice conditions.  LLM wins per-choice; manual as fallback.

    Args:
        manual_choices: Choice dicts with ``ordinal``, ``condition_type``,
            ``condition_value`` keys (from the transform phase).
        llm_conditions: List of condition dicts with ``choice_ordinal``,
            ``condition_type``, ``condition_value`` from scene analysis.
        scene_number: Scene number for warnings.

    Returns:
        Updated choice dicts list and warnings.  The choice dicts are
        modified in-place with LLM conditions where available.
    """
    if llm_conditions is None:
        return manual_choices, []

    warnings: list[str] = []
    llm_by_ordinal = {c["choice_ordinal"]: c for c in llm_conditions}

    for choice in manual_choices:
        ordinal = choice.get("ordinal")
        llm_cond = llm_by_ordinal.get(ordinal)

        if llm_cond:
            manual_type = choice.get("condition_type")
            llm_type = llm_cond["condition_type"]

            if manual_type and manual_type != llm_type:
                warnings.append(
                    f"MERGE_CONFLICT scene={scene_number} field=condition "
                    f"choice_ordinal={ordinal}: "
                    f"manual={manual_type}:{choice.get('condition_value')} "
                    f"llm={llm_type}:{llm_cond.get('condition_value')} "
                    f"winner=llm"
                )

            choice["condition_type"] = llm_cond["condition_type"]
            choice["condition_value"] = llm_cond.get("condition_value")
        # else: keep manual condition (LLM didn't detect one for this choice)

    return manual_choices, warnings


def merge_scene_flags(
    manual_flags: dict,
    llm_flags: dict | None,
    scene_number: int,
) -> tuple[dict, list[str]]:
    """Merge scene flags using a manual-positive-wins strategy.

    Manual substring matching is reliable when it fires (True is trusted).
    LLM is used to catch edge cases that the manual patterns miss — if manual
    is ``False`` and LLM is ``True``, LLM wins and a warning is emitted.

    Flags handled: ``must_eat``, ``loses_backpack``, ``is_death``,
    ``is_victory``, ``mindblast_immune``.

    Args:
        manual_flags: Dict of flag name → bool from the transform phase.
        llm_flags: Dict of flag name → bool from
            :func:`~app.parser.llm.analyze_scene`, or ``None`` when LLM was
            skipped.
        scene_number: Scene number for warning messages.

    Returns:
        ``(merged, warnings)`` where *merged* is a dict of all five flags and
        *warnings* lists any cases where LLM overrode a manual False.
    """
    if llm_flags is None:
        return manual_flags, []

    warnings: list[str] = []
    merged: dict = {}

    for flag in ("must_eat", "loses_backpack", "is_death", "is_victory", "mindblast_immune"):
        manual_val = manual_flags.get(flag, False)
        llm_val = llm_flags.get(flag, False)

        if manual_val:
            # Manual detected it — keep it
            merged[flag] = True
        elif llm_val:
            # Manual missed it but LLM caught it
            merged[flag] = True
            warnings.append(
                f"MERGE_CONFLICT scene={scene_number} field={flag}: "
                f"manual=False llm=True winner=llm"
            )
        else:
            merged[flag] = False

    return merged, warnings
