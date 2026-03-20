"""Combat resolution engine for the Lone Wolf game.

Pure functions that compute combat skill, look up the Combat Results Table,
resolve a round of combat, handle evasion, and check conditional combat.
No side effects — callers are responsible for persisting results.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from app.engine.meters import apply_endurance_delta
from app.engine.types import (
    CharacterState,
    CombatContext,
    CombatEncounterData,
    CombatModifierData,
)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RoundResult:
    """Result of a single combat round."""

    hero_damage: int | None  # None = instant kill
    enemy_damage: int | None  # None = instant kill
    hero_end_remaining: int
    enemy_end_remaining: int
    hero_dead: bool
    enemy_dead: bool
    combat_ratio: int
    random_number: int
    psi_surge_used: bool
    events: list[dict]


@dataclass
class EvadeResult:
    """Result of attempting to evade a combat encounter."""

    success: bool  # True if evaded, False if died during evasion
    hero_end_remaining: int
    hero_dead: bool
    evasion_damage: int
    target_scene_id: int | None
    events: list[dict]


# ---------------------------------------------------------------------------
# Combat skill computation
# ---------------------------------------------------------------------------


def effective_combat_skill(state: CharacterState, encounter: CombatContext) -> int:
    """Compute the character's effective Combat Skill for one encounter.

    Applies all modifiers in this order:
    1. Base combat skill
    2. Unarmed penalty (-4 if no equipped weapon)
    3. Mindblast bonus (+2 if discipline present and enemy not immune)
    4. Mindshield defence (nullifies enemy_mindblast modifier)
    5. Weaponskill bonus (+2 if equipped weapon category matches chosen category)
    6. Equipped weapon combat_bonus (from weapon properties)
    7. Special item combat bonuses (summed across all carried special items)
    8. Encounter-level cs_bonus / cs_penalty modifiers

    Args:
        state: Current character state snapshot.
        encounter: Live combat context including modifiers.

    Returns:
        The final effective Combat Skill integer.
    """
    cs = state.combat_skill_base

    # --- Identify equipped weapon (if any) ---
    equipped_weapon_item = _get_equipped_weapon(state)

    # 1. Unarmed penalty
    if equipped_weapon_item is None:
        cs -= 4

    # 2. Mindblast bonus
    if "Mindblast" in state.disciplines and not encounter.mindblast_immune:
        cs += 2

    # 3. Enemy Mindblast — reduces CS unless Mindshield is held
    has_mindshield = "Mindshield" in state.disciplines
    for modifier in encounter.modifiers:
        if modifier.modifier_type == "enemy_mindblast" and not has_mindshield:
            cs -= 2

    # 4. Weaponskill bonus — requires the Weaponskill discipline
    if (
        "Weaponskill" in state.disciplines
        and equipped_weapon_item is not None
        and state.weapon_skill_category is not None
        and equipped_weapon_item.properties.get("category") == state.weapon_skill_category
    ):
        cs += 2

    # 5. Equipped weapon combat_bonus (may be replaced by combat_bonus_vs_special)
    if equipped_weapon_item is not None:
        weapon_bonus = _get_weapon_cs_bonus(equipped_weapon_item.properties, encounter.modifiers)
        cs += weapon_bonus

    # 6. Special item combat bonuses (all carried special items)
    for item in state.items:
        if item.item_type == "special" and "combat_bonus" in item.properties:
            cs += int(item.properties["combat_bonus"])

    # 7. Encounter modifiers: cs_bonus and cs_penalty
    for modifier in encounter.modifiers:
        if modifier.modifier_type == "cs_bonus":
            cs += int(modifier.modifier_value or 0)
        elif modifier.modifier_type == "cs_penalty":
            cs -= int(modifier.modifier_value or 0)

    return cs


def _get_weapon_cs_bonus(
    weapon_properties: dict, encounter_modifiers: list[CombatModifierData]
) -> int:
    """Return the CS bonus from the equipped weapon, accounting for special replacements.

    If the weapon has ``combat_bonus_vs_special`` and the encounter has a matching
    modifier (keyed by ``special_vs``), the vs-special bonus replaces the base bonus.
    """
    base_bonus = int(weapon_properties.get("combat_bonus", 0))
    combat_bonus_vs_special = weapon_properties.get("combat_bonus_vs_special")
    special_vs = weapon_properties.get("special_vs")

    if combat_bonus_vs_special is not None and special_vs is not None:
        for modifier in encounter_modifiers:
            if modifier.modifier_type == special_vs:
                return int(combat_bonus_vs_special)  # replacement, not stacking

    return base_bonus


# ---------------------------------------------------------------------------
# CRT helpers
# ---------------------------------------------------------------------------


def ratio_to_bracket(hero_cs: int, enemy_cs: int) -> int:
    """Compute the raw combat ratio for CRT bracket lookup.

    Args:
        hero_cs: Hero's effective combat skill.
        enemy_cs: Enemy's combat skill.

    Returns:
        The difference ``hero_cs - enemy_cs`` (not clamped; CRT rows define bounds).
    """
    return hero_cs - enemy_cs


def lookup_crt(
    crt_rows: list[dict],
    combat_ratio: int,
    random_number: int,
) -> tuple[int | None, int | None]:
    """Look up a Combat Results Table row by random number and combat ratio.

    Each row in ``crt_rows`` must have:
        - ``random_number`` (int)
        - ``combat_ratio_min`` (int)
        - ``combat_ratio_max`` (int)
        - ``enemy_loss`` (int | None)  — None means instant kill
        - ``hero_loss`` (int | None)   — None means instant kill

    Args:
        crt_rows: All rows of the Combat Results Table.
        combat_ratio: The pre-computed ``hero_cs - enemy_cs`` value.
        random_number: The random number rolled (0-9 for Lone Wolf).

    Returns:
        A two-tuple of ``(enemy_loss, hero_loss)``.  Either value may be None,
        indicating an instant kill for that combatant.

    Raises:
        ValueError: If no matching row is found for the given inputs.
    """
    for row in crt_rows:
        if (
            row["random_number"] == random_number
            and row["combat_ratio_min"] <= combat_ratio <= row["combat_ratio_max"]
        ):
            return row["enemy_loss"], row["hero_loss"]

    raise ValueError(
        f"No CRT row found for random_number={random_number}, combat_ratio={combat_ratio}"
    )


# ---------------------------------------------------------------------------
# Round resolution
# ---------------------------------------------------------------------------


def resolve_combat_round(
    state: CharacterState,
    encounter: CombatContext,
    crt_rows: list[dict],
    random_number: int,
    use_psi_surge: bool = False,
) -> RoundResult:
    """Resolve a single round of combat.

    Sequence:
    1. If ``use_psi_surge``, deduct 2 END from the hero and add +4 CS bonus.
    2. Compute effective CS (including psi-surge bonus).
    3. Compute the combat ratio and look up the CRT.
    4. Apply hero_loss to hero endurance; apply enemy_loss to enemy endurance.
    5. Handle instant-kill results (None loss value).

    Note: This function does not mutate ``state`` or ``encounter``.  The caller
    is responsible for persisting returned values.

    Args:
        state: Current character state snapshot.
        encounter: Live combat context.
        crt_rows: Full Combat Results Table.
        random_number: Roll result (0-9).
        use_psi_surge: Whether the player activates Psi-surge this round.

    Returns:
        A ``RoundResult`` describing the outcome of the round.
    """
    events: list[dict] = []
    hero_end = state.endurance_current

    # Ignore psi-surge if the character doesn't have the discipline
    psi_surge_active = use_psi_surge and "Psi-surge" in state.disciplines

    # 1. Compute effective CS (with optional psi-surge +4 bonus)
    if psi_surge_active:
        surge_modifier = CombatModifierData(
            modifier_type="cs_bonus",
            modifier_value="4",
            condition=None,
        )
        augmented_encounter = _with_extra_modifier(encounter, surge_modifier)
        hero_cs = effective_combat_skill(state, augmented_encounter)
    else:
        hero_cs = effective_combat_skill(state, encounter)

    combat_ratio = ratio_to_bracket(hero_cs, encounter.enemy_cs)

    # 2. CRT lookup
    enemy_loss, hero_loss = lookup_crt(crt_rows, combat_ratio, random_number)

    # 3. Apply special weapon effects to enemy_loss
    equipped_weapon_item = _get_equipped_weapon(state)
    if equipped_weapon_item is not None:
        enemy_loss = apply_special_weapon_effects(
            enemy_loss, equipped_weapon_item.properties, encounter.modifiers
        )

    # 4. Add psi-surge END cost to hero_loss (per spec: added AFTER CRT resolution)
    if psi_surge_active and hero_loss is not None:
        hero_loss += 2

    # 5. Apply hero damage
    hero_dead = False
    hero_damage = hero_loss

    if hero_loss is None:
        # Instant kill
        hero_end = 0
        hero_dead = True
        events.append({"type": "instant_kill", "target": "hero"})
    else:
        post_state = _with_endurance(state, hero_end)
        hero_end, hero_dead, end_events = apply_endurance_delta(post_state, -hero_loss)
        events.extend(end_events)

    # 6. Apply enemy damage
    enemy_end = encounter.enemy_end_remaining
    enemy_dead = False
    enemy_damage = enemy_loss

    if enemy_loss is None:
        enemy_end = 0
        enemy_dead = True
        events.append({"type": "instant_kill", "target": "enemy"})
    else:
        enemy_end = max(0, enemy_end - enemy_loss)
        if enemy_end == 0:
            enemy_dead = True

    return RoundResult(
        hero_damage=hero_damage,
        enemy_damage=enemy_damage,
        hero_end_remaining=hero_end,
        enemy_end_remaining=enemy_end,
        hero_dead=hero_dead,
        enemy_dead=enemy_dead,
        combat_ratio=combat_ratio,
        random_number=random_number,
        psi_surge_used=psi_surge_active,
        events=events,
    )


# ---------------------------------------------------------------------------
# Evasion
# ---------------------------------------------------------------------------


def evade_combat(state: CharacterState, encounter: CombatContext) -> EvadeResult:
    """Attempt to evade the current combat encounter.

    Evasion is only allowed once ``rounds_fought >= evasion_after_rounds``.
    The hero takes ``evasion_damage`` endurance loss regardless of success;
    if that damage kills the hero, death takes precedence over escape.

    Args:
        state: Current character state snapshot.
        encounter: Live combat context.

    Returns:
        An ``EvadeResult`` describing whether the hero escaped or died.
    """
    events: list[dict] = []

    # Check eligibility
    if (
        encounter.evasion_after_rounds is None
        or encounter.rounds_fought < encounter.evasion_after_rounds
    ):
        # Cannot evade yet — treat as failed with no damage (caller should not call this)
        return EvadeResult(
            success=False,
            hero_end_remaining=state.endurance_current,
            hero_dead=False,
            evasion_damage=0,
            target_scene_id=encounter.evasion_target,
            events=[{"type": "evasion_denied", "reason": "too_early"}],
        )

    # Apply evasion damage
    evasion_dmg = encounter.evasion_damage
    new_end, is_dead, end_events = apply_endurance_delta(state, -evasion_dmg)
    events.extend(end_events)

    if is_dead:
        # Death during evasion: escape fails
        events.append({"type": "evasion_failed", "reason": "hero_died"})
        return EvadeResult(
            success=False,
            hero_end_remaining=new_end,
            hero_dead=True,
            evasion_damage=evasion_dmg,
            target_scene_id=None,
            events=events,
        )

    events.append({"type": "evasion_success", "target_scene_id": encounter.evasion_target})
    return EvadeResult(
        success=True,
        hero_end_remaining=new_end,
        hero_dead=False,
        evasion_damage=evasion_dmg,
        target_scene_id=encounter.evasion_target,
        events=events,
    )


# ---------------------------------------------------------------------------
# Conditional combat check
# ---------------------------------------------------------------------------


def should_fight(state: CharacterState, encounter: CombatEncounterData) -> bool:
    """Determine whether the hero must fight this encounter.

    Some encounters can be bypassed if the hero has a specific discipline or
    item.  If the encounter specifies a ``condition_type`` / ``condition_value``
    pair and the hero satisfies it, the fight is skipped.

    Args:
        state: Current character state snapshot.
        encounter: The encounter definition from the scene.

    Returns:
        ``True`` if the hero must fight; ``False`` if the encounter is skipped.
    """
    if encounter.condition_type is None or encounter.condition_value is None:
        return True

    condition_type = encounter.condition_type.lower()
    condition_value = encounter.condition_value

    if condition_type == "discipline":
        if condition_value in state.disciplines:
            return False

    elif condition_type == "item":
        for item in state.items:
            if item.item_name == condition_value:
                return False

    return True


# ---------------------------------------------------------------------------
# Special weapon effect helpers
# ---------------------------------------------------------------------------


def apply_special_weapon_effects(
    enemy_damage: int | None,
    weapon_properties: dict,
    encounter_modifiers: list[CombatModifierData],
) -> int | None:
    """Apply special weapon effects to the raw enemy damage value.

    Two effects are handled:

    **Sommerswerd double damage** — If the weapon has a ``damage_multiplier``
    property AND the encounter has an "undead" modifier, multiply ``enemy_damage``
    by ``damage_multiplier``.  Instant kills (``None``) are left unchanged.

    **combat_bonus_vs_special replacement** — If the weapon has a
    ``combat_bonus_vs_special`` property AND a matching encounter modifier
    specifies the ``special_vs`` value, the vs-special bonus replaces (not stacks
    with) the weapon's base ``combat_bonus`` for purposes of this damage calc.
    (This function adjusts the returned damage value accordingly.)

    Args:
        enemy_damage: Raw enemy endurance loss from the CRT (None = instant kill).
        weapon_properties: The ``properties`` dict from the equipped weapon item.
        encounter_modifiers: All modifiers on the current encounter.

    Returns:
        Adjusted enemy damage, or ``None`` for an instant kill.
    """
    if enemy_damage is None:
        return None

    # Damage multiplier (e.g., Sommerswerd): multiply damage when special_vs matches
    # a modifier on the encounter. Uses generic special_vs matching, not hardcoded undead.
    damage_multiplier = weapon_properties.get("damage_multiplier")
    special_vs = weapon_properties.get("special_vs")
    if damage_multiplier is not None and special_vs is not None:
        if any(m.modifier_type == special_vs for m in encounter_modifiers):
            enemy_damage = enemy_damage * int(damage_multiplier)

    return enemy_damage


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_equipped_weapon(state: CharacterState):  # type: ignore[return]
    """Return the first equipped weapon ItemState, or None."""
    for item in state.items:
        if item.item_type == "weapon" and item.is_equipped:
            return item
    return None


def _with_endurance(state: CharacterState, new_endurance: int) -> CharacterState:
    """Return a shallow copy of ``state`` with ``endurance_current`` replaced."""
    return dataclasses.replace(state, endurance_current=new_endurance)


def _with_extra_modifier(encounter: CombatContext, modifier: CombatModifierData) -> CombatContext:
    """Return a shallow copy of ``encounter`` with one extra modifier appended."""
    return dataclasses.replace(encounter, modifiers=[*encounter.modifiers, modifier])
