"""Transform phase of the parser pipeline.

Classifies and detects game mechanics from raw scene text and choice text.
All functions are pure text-processing heuristics — no ORM or database
dependencies. Detection is best-effort; the admin layer corrects errors
surfaced by player bug reports.
"""

from __future__ import annotations

import json
import re


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DISCIPLINE_NAMES = {
    # Kai disciplines (books 1-5)
    "camouflage",
    "hunting",
    "sixth sense",
    "tracking",
    "healing",
    "weaponskill",
    "mindshield",
    "mindblast",
    "animal kinship",
    "mind over matter",
    # Magnakai disciplines (books 6-12)
    "weaponmastery",
    "animal control",
    "curing",
    "invisibility",
    "huntmastery",
    "pathsmanship",
    "psi-surge",
    "psi-screen",
    "nexus",
    "divination",
    # Grand master disciplines
    "grand weaponmastery",
    "animal mastery",
    "deliverance",
    "assimilance",
    "grand huntmastery",
    "grand pathsmanship",
    "kai-surge",
    "kai-screen",
    "grand nexus",
    "telegnosis",
}


def _extract_discipline_name(text: str) -> str | None:
    """Extract a discipline name from lower-cased choice text.

    Tries the 'discipline of X' pattern first, then falls back to scanning
    for known discipline names.
    """
    # "kai discipline of X" or "discipline of X"
    m = re.search(r"discipline of\s+([a-z][a-z\s\-]+?)(?:\s*[,\.]|$|\s+to\s)", text)
    if m:
        return m.group(1).strip().title()

    # Fallback: scan for a known discipline name adjacent to "have" or "possess"
    for name in sorted(_DISCIPLINE_NAMES, key=len, reverse=True):
        if name in text:
            return name.title()

    return None


def _extract_item_name(text: str) -> str | None:
    """Extract the item name from a 'you possess X' or 'you have a X' phrase."""
    m = re.search(r"(?:you possess|if you possess)\s+(?:a\s+|an\s+)?(.+?)(?:\s*[,\.]|$|\s+and\s|\s+or\s|\s+you\s)", text)
    if m:
        return m.group(1).strip().title()

    m = re.search(r"if you have (?:a|an)\s+(.+?)(?:\s*[,\.]|$|\s+and\s|\s+or\s)", text)
    if m:
        return m.group(1).strip().title()

    return None


def _classify_item_type(item_name: str) -> str:
    """Heuristic: classify an item as weapon, backpack, special, gold, or meal."""
    lower = item_name.lower()
    weapons = {
        "sword", "axe", "mace", "dagger", "spear", "bow", "arrow", "quiver",
        "broadsword", "short sword", "warhammer", "lance", "quarterstaff",
        "saber", "sabre", "knife",
    }
    if any(w in lower for w in weapons):
        return "weapon"
    if "gold" in lower or "crown" in lower:
        return "gold"
    if "meal" in lower or "food" in lower or "ration" in lower:
        return "meal"
    return "backpack"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_condition(choice_text: str) -> tuple[str | None, str | None]:
    """Classify the gate condition embedded in a single choice's text.

    Parameters
    ----------
    choice_text:
        Raw text of a single choice paragraph (may include HTML-stripped text
        or plain text from the extraction phase).

    Returns
    -------
    (condition_type, condition_value) where both are ``None`` if no condition
    is detected.  Possible condition_type values:
    - ``"discipline"`` — requires a Kai/Magnakai/Grand Master discipline.
    - ``"item"``       — requires possession of a named item.
    - ``"gold"``       — requires a minimum number of Gold Crowns.
    - ``"random"``     — outcome depends on a random number roll.
    """
    text = choice_text.lower()

    # --- Discipline gate (including compound OR) ---
    # Check compound OR first: "If you have Tracking or Huntmastery"
    or_match = re.search(
        r"if you have\s+([a-z][a-z\s\-]+?)\s+or\s+([a-z][a-z\s\-]+?)(?:\s*[,\.]|$|\s+you\s|\s+and\s)",
        text,
    )
    if or_match:
        a = or_match.group(1).strip().title()
        b = or_match.group(2).strip().title()
        # Only emit discipline compound if both look like disciplines or the
        # phrase "discipline of" appears nearby.
        if (
            "discipline" in text
            or a.lower() in _DISCIPLINE_NAMES
            or b.lower() in _DISCIPLINE_NAMES
        ):
            return ("discipline", json.dumps({"any": [a, b]}))

    # Single discipline gate
    if "kai discipline of" in text or "discipline of" in text:
        name = _extract_discipline_name(text)
        if name:
            return ("discipline", name)

    # "if you have X or Y" where X/Y are known discipline names (no explicit "discipline of")
    if or_match:
        a = or_match.group(1).strip().title()
        b = or_match.group(2).strip().title()
        return ("discipline", json.dumps({"any": [a, b]}))

    # --- Item gate ---
    if "if you possess" in text or re.search(r"if you have (?:a|an)\s+", text):
        name = _extract_item_name(text)
        if name:
            return ("item", name)

    # --- Gold gate ---
    gold_m = re.search(r"if you have (\d+)\s+gold", text)
    if gold_m:
        return ("gold", gold_m.group(1))

    # --- Random number ---
    if "pick a number" in text or "random number" in text:
        return ("random", None)

    return (None, None)


def detect_must_eat(narrative: str) -> bool:
    """Return True if the scene narrative requires the player to eat a Meal.

    Parameters
    ----------
    narrative:
        The plain-text narrative of the scene (all non-choice, non-combat
        paragraphs concatenated).
    """
    text = narrative.lower()
    patterns = [
        "you must eat a meal",
        "must eat a meal",
        "eat a meal here",
        "you need to eat",
        "mark off a meal",
        "you must now eat",
        "must now eat",
        "eat one meal",
        "consume a meal",
    ]
    return any(p in text for p in patterns)


def detect_backpack_loss(narrative: str) -> bool:
    """Return True if the scene narrative indicates loss of the player's Backpack.

    Parameters
    ----------
    narrative:
        The plain-text narrative of the scene.
    """
    text = narrative.lower()
    patterns = [
        "you lose your backpack",
        "your backpack is lost",
        "backpack and all its contents",
        "lose your backpack",
        "your backpack has been taken",
        "backpack is taken",
        "backpack is stolen",
        "lose the backpack",
        "backpack has been lost",
    ]
    return any(p in text for p in patterns)


def detect_items(
    narrative: str,
    choices: list[str] | None = None,
) -> list[dict]:
    """Detect items gained or lost in a scene's narrative text.

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.
    choices:
        Optional list of raw choice strings (currently unused; reserved for
        future enhancement).

    Returns
    -------
    A list of dicts, each with keys:
    - ``item_name``  — canonical item name (title-cased)
    - ``item_type``  — ``"weapon"``, ``"backpack"``, ``"special"``, ``"gold"``,
                       or ``"meal"``
    - ``action``     — ``"gain"`` or ``"lose"``
    - ``quantity``   — integer quantity (default 1)
    """
    items: list[dict] = []
    text = narrative.lower()

    # --- Gold gains ---
    gain_verbs = r"(?:find|gain|take|receive|pick up|collect|awarded|given)"
    gold_gain = re.findall(
        rf"(?:{gain_verbs}[^.]*?)(\d+)\s+gold\s+crown|(\d+)\s+gold\s+crown[s]?[^.]*?(?:{gain_verbs})",
        text,
    )
    # Use a simpler single pass instead
    gold_gain_m = re.search(
        rf"({gain_verbs})[^.]*?(\d+)\s+gold\s+crown",
        text,
    )
    if gold_gain_m:
        items.append(
            {
                "item_name": "Gold Crowns",
                "item_type": "gold",
                "action": "gain",
                "quantity": int(gold_gain_m.group(2)),
            }
        )
    else:
        # also catch "X gold crowns" without explicit verb nearby
        gold_only_m = re.search(r"(\d+)\s+gold\s+crowns?\s+(?:are\s+)?(?:yours|inside|here|available)", text)
        if gold_only_m:
            items.append(
                {
                    "item_name": "Gold Crowns",
                    "item_type": "gold",
                    "action": "gain",
                    "quantity": int(gold_only_m.group(1)),
                }
            )

    # --- Gold losses ---
    gold_lose_m = re.search(
        r"(?:lose|pay|spend|cost)[^.]*?(\d+)\s+gold\s+crown",
        text,
    )
    if gold_lose_m:
        items.append(
            {
                "item_name": "Gold Crowns",
                "item_type": "gold",
                "action": "lose",
                "quantity": int(gold_lose_m.group(1)),
            }
        )

    # --- Meal gains ---
    meal_gain = re.search(
        rf"(?:{gain_verbs})[^.]*?meal|meal[^.]*?(?:{gain_verbs})",
        text,
    )
    if meal_gain:
        items.append(
            {
                "item_name": "Meal",
                "item_type": "meal",
                "action": "gain",
                "quantity": 1,
            }
        )

    # --- Generic "you may take the X" gains ---
    take_matches = re.finditer(r"you may take (?:the\s+)?(.+?)[\.,]", text)
    for m in take_matches:
        name = m.group(1).strip().title()
        if "gold" in name.lower() or "meal" in name.lower():
            continue  # already handled above
        items.append(
            {
                "item_name": name,
                "item_type": _classify_item_type(name),
                "action": "gain",
                "quantity": 1,
            }
        )

    # --- Generic item losses: "you lose your X" / "you lose X" ---
    lose_matches = re.finditer(r"you lose (?:your\s+)?(.+?)[\.,]", text)
    for m in lose_matches:
        name = m.group(1).strip()
        if "backpack" in name or "gold" in name or "crown" in name:
            continue  # handled elsewhere
        name_title = name.title()
        items.append(
            {
                "item_name": name_title,
                "item_type": _classify_item_type(name_title),
                "action": "lose",
                "quantity": 1,
            }
        )

    return items


def detect_death_scene(
    narrative: str,
    choices: list[str] | None = None,
) -> bool:
    """Return True if this scene is a death scene.

    A death scene has no outgoing choices *and* contains death language in
    its narrative.

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.
    choices:
        List of raw choice strings.  If non-empty, the scene has outgoing
        paths and therefore cannot be a death scene.
    """
    if choices:
        return False

    text = narrative.lower()
    death_patterns = [
        "your adventure ends here",
        "your adventure is over",
        "your life ends",
        "you are dead",
        "you have been killed",
        "you have died",
        "your life force ebbs",
        "you have failed",
        "you have met your end",
        "death comes",
        "your quest ends here",
        "you are slain",
        "you perish",
        "you die",
        "your life is over",
    ]
    return any(p in text for p in death_patterns)


def detect_victory_scene(
    narrative: str,
    choices: list[str] | None = None,
) -> bool:
    """Return True if this scene is a book-completion victory scene.

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.
    choices:
        List of raw choice strings.  Optional; not strictly required for
        victory detection but available for future logic.
    """
    text = narrative.lower()
    victory_patterns = [
        "your quest is complete",
        "you have completed",
        "your mission is complete",
        "congratulations",
        "you have succeeded",
        "the adventure is complete",
        "you have won",
        "your adventure is complete",
        "mission accomplished",
        "your quest has been fulfilled",
        "you have achieved",
        "your journey is complete",
    ]
    return any(p in text for p in victory_patterns)


def parse_combat(combat_block: str) -> dict | None:
    """Parse a combat block string into structured enemy data.

    Handles the standard Project Aon format::

        ENEMY NAME: COMBAT SKILL 16   ENDURANCE 24

    The ``<small>`` tags are stripped before this function is called (or the
    caller passes plain text obtained via ``get_text()``).

    Parameters
    ----------
    combat_block:
        Raw text of a combat paragraph with HTML tags already removed.

    Returns
    -------
    A dict with keys ``enemy_name``, ``enemy_cs``, ``enemy_end``, or
    ``None`` if the block does not match the expected pattern.
    """
    if not combat_block:
        return None

    # Normalize whitespace
    text = re.sub(r"\s+", " ", combat_block.strip())

    # Primary pattern: "Name: COMBAT SKILL N ENDURANCE M"
    m = re.match(
        r"(.+?):\s*COMBAT\s+SKILL\s+(\d+)\s+ENDURANCE\s+(\d+)",
        text,
        re.IGNORECASE,
    )
    if m:
        return {
            "enemy_name": m.group(1).strip(),
            "enemy_cs": int(m.group(2)),
            "enemy_end": int(m.group(3)),
        }

    # Alternate compact form: "Name: CS N / E M"
    m2 = re.match(
        r"(.+?):\s*CS\s+(\d+)\s*/?\s*E\s+(\d+)",
        text,
        re.IGNORECASE,
    )
    if m2:
        return {
            "enemy_name": m2.group(1).strip(),
            "enemy_cs": int(m2.group(2)),
            "enemy_end": int(m2.group(3)),
        }

    return None


def detect_evasion(narrative: str) -> tuple[int, int, int] | None:
    """Detect evasion rules embedded in narrative text.

    Looks for patterns such as:
    - "you may evade after X rounds of combat"
    - "after X rounds … turn to Y"
    - "evade … turn to Y … lose N ENDURANCE"

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.

    Returns
    -------
    A tuple ``(rounds, target_scene_number, damage)`` where *damage* defaults
    to 0 if no evasion damage is mentioned.  Returns ``None`` if no evasion
    rule is found.
    """
    text = narrative.lower()

    # Look for evasion + round threshold.
    # Try forward order first (evade ... after N rounds), then reverse order.
    evade_m = re.search(
        r"(?:evade|escape|flee|run).*?after\s+(\w+)\s+round",
        text,
        re.DOTALL,
    )
    if evade_m is None:
        evade_m = re.search(
            r"after\s+(\w+)\s+rounds?[\s,].*?(?:evade|escape|flee|run|turn)",
            text,
            re.DOTALL,
        )

    if evade_m is None:
        # No evasion detected
        return None

    # Convert word numbers to int
    word_to_int = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    rounds_raw = evade_m.group(1)
    if rounds_raw.isdigit():
        rounds = int(rounds_raw)
    else:
        rounds = word_to_int.get(rounds_raw, 1)

    # Find target scene number via "turn to N" or "turning to N"
    turn_m = re.search(r"turn(?:ing)?\s+to\s+(\d+)", text)
    if not turn_m:
        return None
    target = int(turn_m.group(1))

    # Find optional evasion damage
    damage = 0
    dmg_m = re.search(r"lose\s+(\d+)\s+(?:endurance|e\.p\.?)", text)
    if dmg_m:
        damage = int(dmg_m.group(1))

    return (rounds, target, damage)


def detect_mindblast_immunity(narrative: str) -> bool:
    """Return True if the scene indicates an enemy is immune to Mindblast.

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.
    """
    text = narrative.lower()
    patterns = [
        "immune to mindblast",
        "mindblast has no effect",
        "unaffected by mindblast",
        "mindblast does not affect",
        "mindblast cannot affect",
        "mindblast will not work",
        "immune to your mindblast",
        "immune to the mindblast",
    ]
    return any(p in text for p in patterns)


def detect_combat_modifiers(narrative: str) -> list[dict]:
    """Detect combat modifiers mentioned near combat encounters.

    Each modifier is returned as a dict with at minimum a ``modifier_type``
    key and an optional ``value`` key.

    Detected modifier types:
    - ``cs_bonus``       — positive combat skill adjustment for the player.
    - ``cs_penalty``     — negative combat skill adjustment for the player.
    - ``double_damage``  — player deals double damage.
    - ``undead``         — enemy is undead (relevant to Sommerswerd bonus).
    - ``enemy_mindblast``— enemy can use Mindblast against the player.

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.
    """
    text = narrative.lower()
    modifiers: list[dict] = []

    # CS bonus: "+N to your combat skill" / "add N to your combat"
    cs_bonus_m = re.search(
        r"(?:add|plus|\+)\s*(\d+)\s+(?:to your\s+)?combat\s+skill",
        text,
    )
    if cs_bonus_m:
        modifiers.append({"modifier_type": "cs_bonus", "value": int(cs_bonus_m.group(1))})

    # CS penalty: "deduct N from your combat skill" / "-N to your combat skill"
    cs_penalty_m = re.search(
        r"(?:deduct|subtract|minus|-)\s*(\d+)\s+(?:from your\s+)?combat\s+skill",
        text,
    )
    if cs_penalty_m:
        modifiers.append({"modifier_type": "cs_penalty", "value": int(cs_penalty_m.group(1))})

    # Double damage
    if "double" in text and re.search(r"double.*?(?:damage|endurance)", text):
        modifiers.append({"modifier_type": "double_damage", "value": None})

    # Undead
    if re.search(r"\bundead\b", text):
        modifiers.append({"modifier_type": "undead", "value": None})

    # Enemy Mindblast
    if re.search(r"(?:uses?|using|possesses?)\s+mindblast", text) or "mindblast attack" in text:
        modifiers.append({"modifier_type": "enemy_mindblast", "value": None})

    return modifiers


def detect_conditional_combat(narrative: str) -> tuple[str, str] | None:
    """Detect a conditional combat: combat only required if player lacks X.

    Looks for patterns such as:
    - "If you do not have the Kai Discipline of Tracking, you must fight"
    - "If you do not possess a Sword, you must fight"

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.

    Returns
    -------
    A tuple ``(condition_type, condition_value)`` describing what the player
    needs in order to *avoid* combat, or ``None`` if no conditional combat is
    found.
    """
    text = narrative.lower()

    # "if you do not have the kai discipline of X"
    m = re.search(
        r"if you do not have.*?discipline of\s+([a-z][a-z\s\-]+?)(?:\s*[,\.]|\s+you\s)",
        text,
    )
    if m:
        return ("discipline", m.group(1).strip().title())

    # "if you do not possess X"
    m2 = re.search(
        r"if you do not possess\s+(?:a\s+|an\s+)?(.+?)(?:\s*[,\.]|\s+you\s|$)",
        text,
    )
    if m2:
        return ("item", m2.group(1).strip().title())

    # "if you have no X" near combat
    m3 = re.search(
        r"if you have no\s+(.+?)(?:\s*[,\.]|\s+you\s|$)",
        text,
    )
    if m3:
        name = m3.group(1).strip()
        # Simple heuristic: if it looks like a discipline name, use discipline type
        ctype = "discipline" if name in _DISCIPLINE_NAMES else "item"
        return (ctype, name.title())

    return None


def detect_random_outcomes(narrative: str) -> list[dict]:
    """Detect phase-based random number outcomes in scene narrative.

    Looks for "pick a number from the Random Number Table" followed by
    outcome bands such as "0–2: lose 3 ENDURANCE", "3–9: gain 10 Gold Crowns",
    or redirect directives "turn to N".

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.

    Returns
    -------
    A list of outcome dicts.  Each dict has:
    - ``range_min``       — inclusive lower bound of the random number range.
    - ``range_max``       — inclusive upper bound.
    - ``effect_type``     — one of ``"gold_change"``, ``"endurance_change"``,
                           ``"item_gain"``, ``"item_loss"``, ``"meal_change"``,
                           ``"scene_redirect"``.
    - ``effect_value``    — string or numeric value for the effect.
    - ``narrative_text``  — raw text describing this outcome band.
    """
    text = narrative.lower()
    outcomes: list[dict] = []

    if "random number table" not in text and "pick a number" not in text:
        return outcomes

    # Find outcome bands: "N–M: ..." or "N-M ..." or "if the number is N-M"
    band_pattern = re.compile(
        r"(\d)\s*[–\-]\s*(\d)\s*[:\.]?\s*(.+?)(?=\d\s*[–\-]\s*\d|$)",
        re.DOTALL,
    )

    for m in band_pattern.finditer(text):
        range_min = int(m.group(1))
        range_max = int(m.group(2))
        outcome_text = m.group(3).strip()

        # Determine effect type
        effect_type: str
        effect_value: str | int | None

        if "turn to" in outcome_text:
            turn_m = re.search(r"turn to\s+(\d+)", outcome_text)
            effect_type = "scene_redirect"
            effect_value = int(turn_m.group(1)) if turn_m else None
        elif "endurance" in outcome_text or "e.p." in outcome_text:
            ep_m = re.search(r"(\d+)\s+(?:endurance|e\.p\.?)", outcome_text)
            effect_type = "endurance_change"
            effect_value = int(ep_m.group(1)) if ep_m else None
            if "lose" in outcome_text or "deduct" in outcome_text:
                effect_value = -(effect_value) if effect_value is not None else None
        elif "gold" in outcome_text or "crown" in outcome_text:
            gold_m = re.search(r"(\d+)\s+gold", outcome_text)
            effect_type = "gold_change"
            effect_value = int(gold_m.group(1)) if gold_m else None
            if "lose" in outcome_text or "pay" in outcome_text:
                effect_value = -(effect_value) if effect_value is not None else None
        elif "meal" in outcome_text:
            effect_type = "meal_change"
            effect_value = -1 if "lose" in outcome_text else 1
        else:
            # Fallback: treat as item gain/loss
            effect_type = "item_loss" if "lose" in outcome_text else "item_gain"
            effect_value = outcome_text

        outcomes.append(
            {
                "range_min": range_min,
                "range_max": range_max,
                "effect_type": effect_type,
                "effect_value": effect_value,
                "narrative_text": m.group(3).strip(),
            }
        )

    return outcomes


def detect_choice_triggered_random(choices: list[str]) -> bool:
    """Return True if any choice text contains a random-triggered pattern.

    A choice is random-triggered if its text references the Random Number
    Table or describes a number range that determines the outcome.

    Parameters
    ----------
    choices:
        List of raw choice text strings for the scene.
    """
    if not choices:
        return False

    random_patterns = [
        r"pick a number",
        r"random number",
        r"roll.*?die",
        r"throw.*?die",
        r"\d\s*[–\-]\s*\d",  # a number range like "0-2" or "3–9"
    ]
    compiled = [re.compile(p, re.IGNORECASE) for p in random_patterns]

    for choice in choices:
        if any(pat.search(choice) for pat in compiled):
            return True
    return False


def detect_scene_level_random_exits(choices: list[str]) -> bool:
    """Return True if ALL choices in the scene are gated by a random condition.

    A scene has random exits if every choice contains a random number range
    or references the Random Number Table, meaning the destination is always
    determined by chance rather than player decision.

    Parameters
    ----------
    choices:
        List of raw choice text strings for the scene.  Must be non-empty.
    """
    if not choices:
        return False

    range_pattern = re.compile(r"\d\s*[–\-]\s*\d", re.IGNORECASE)
    random_pattern = re.compile(r"random number|pick a number", re.IGNORECASE)

    return all(
        range_pattern.search(c) or random_pattern.search(c) for c in choices
    )


def detect_phase_ordering(narrative: str) -> list[str] | None:
    """Best-effort detection of non-standard phase ordering in a scene.

    The default phase sequence is: eat → items → combat → random.
    This function examines the relative text position of game-mechanic
    keywords to detect deviations.

    Parameters
    ----------
    narrative:
        Plain-text narrative of the scene.

    Returns
    -------
    A list of phase name strings (e.g. ``["combat", "eat", "items"]``) if a
    non-standard order is detected, or ``None`` if the default order should
    be used.
    """
    text = narrative.lower()

    # Find approximate text positions of each phase anchor
    phase_anchors: dict[str, int] = {}

    eat_m = re.search(r"eat a meal|must eat|mark off a meal|consume a meal", text)
    if eat_m:
        phase_anchors["eat"] = eat_m.start()

    combat_m = re.search(r"combat skill|you must fight|do battle|engage.*?combat", text)
    if combat_m:
        phase_anchors["combat"] = combat_m.start()

    random_m = re.search(r"random number table|pick a number", text)
    if random_m:
        phase_anchors["random"] = random_m.start()

    item_m = re.search(r"you may take|you find|you pick up|you gain|you receive", text)
    if item_m:
        phase_anchors["items"] = item_m.start()

    if len(phase_anchors) < 2:
        # Not enough phases detected to infer ordering
        return None

    # Sort detected phases by their position in the text
    detected_order = [phase for phase, _ in sorted(phase_anchors.items(), key=lambda kv: kv[1])]

    # Default ordering for the detected subset
    default_sequence = ["eat", "items", "combat", "random"]
    default_order = [p for p in default_sequence if p in phase_anchors]

    if detected_order == default_order:
        return None  # Standard order — no override needed

    return detected_order
