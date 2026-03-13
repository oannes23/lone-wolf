# Game Engine

Pure functions with no HTTP or database dependencies. All engine functions take data objects (dataclasses or Pydantic models) as input and return results — the routers handle persistence.

## Combat Resolution

### Combat Ratio

```
combat_ratio = hero_effective_cs - enemy_cs
```

Where `hero_effective_cs` includes all modifiers:

```python
def effective_combat_skill(base_cs, disciplines, equipped_weapon, enemy, use_psi_surge=False):
    cs = base_cs
    if has_discipline("Mindblast") and not enemy.mindblast_immune:
        cs += 2  # Kai
    if has_discipline("Psi-surge") and use_psi_surge and not enemy.mindblast_immune:
        cs += 4  # Magnakai (replaces Mindblast if both present)
    if has_discipline("Weaponskill") and weapon_category_matches(equipped_weapon, skill_type):
        cs += 2  # Kai: +2 (category match via weapon_categories table)
    if has_discipline("Weaponmastery") and weapon_category_matches(equipped_weapon, mastery_types):
        cs += 3  # Magnakai: +3 (replaces Weaponskill, category match)
    if has_discipline("Kai-surge"):
        cs += 8  # Grand Master (replaces Psi-surge, with END cost)
    # Lore-circle bonuses
    cs += lore_circle_cs_bonus(disciplines)
    # Encounter-specific modifiers applied last
    for mod in enemy.modifiers:
        cs = apply_combat_modifier(cs, mod)
    return cs
```

### Psi-surge Opt-in

- **Decision**: Player sends `use_psi_surge: bool` with each combat round request
- **Rationale**: Per-round opt-in matches the book rules where the player decides each round
- **Implications**: If `use_psi_surge` is true and the character has Psi-surge, +4 CS but hero takes 2 extra END loss that round (applied after CRT resolution). If the character doesn't have Psi-surge, the flag is ignored.

### Combat Ratio Brackets

The CRT uses 13 brackets:

| Bracket | Range |
|---------|-------|
| 1 | ≤ −11 |
| 2 | −10 to −9 |
| 3 | −8 to −7 |
| 4 | −6 to −5 |
| 5 | −4 to −3 |
| 6 | −2 to −1 |
| 7 | 0 |
| 8 | 1 to 2 |
| 9 | 3 to 4 |
| 10 | 5 to 6 |
| 11 | 7 to 8 |
| 12 | 9 to 10 |
| 13 | ≥ 11 |

### CRT Lookup

```python
def resolve_combat_round(combat_ratio, crt_data):
    """
    Returns (enemy_loss, hero_loss) where None = instant kill.
    Random number generated server-side (0-9).
    """
    random_number = server_random(0, 9)
    bracket = ratio_to_bracket(combat_ratio)
    row = crt_data[(random_number, bracket)]
    return (row.enemy_loss, row.hero_loss, random_number)
```

### Random Number Generation

- **Decision**: All random numbers are server-generated. No client-provided values.
- **Rationale**: Prevents cheating. The books' "Random Number Table" is replaced by server-side `random.randint(0, 9)`.
- **Implications**: Combat round requests have no `random_number` parameter. The generated number is returned in the response for transparency.

### Combat Round Flow

```
1. Calculate hero effective CS (base + discipline bonuses + encounter modifiers + psi-surge if opted in)
2. Compute combat_ratio = effective_cs - enemy_cs
3. Server generates random_number (0–9)
4. Look up CRT → (enemy_loss, hero_loss)
5. If psi_surge_used: hero_loss += 2 (Psi-surge END cost)
6. Apply losses to both endurance pools
7. Save combat_round snapshot row (with remaining endurance for both sides)
8. Check for death (endurance ≤ 0 → killed)
9. Check evasion eligibility (round >= evasion_after_rounds)
10. Return round result
```

### Multi-Enemy Combat

Some sections have multiple enemies fought sequentially. The `ordinal` field on `combat_encounters` determines fight order. The next enemy engages only after the current one is defeated.

### Conditional Combat

Some combat encounters are conditional — they only trigger when the character **lacks** a certain discipline or item (e.g., "If you do not have Camouflage, you must fight...").

- **Decision**: `combat_encounters` has `condition_type` and `condition_value` columns. If the condition is met (character has the discipline/item), the combat is skipped entirely.
- **Rationale**: Keeps conditional combat as a property of the encounter rather than requiring section restructuring.
- **Implications**: The combat phase in the phase sequence checks the condition before engaging. If skipped, no `combat_start`/`combat_end` events are logged. A `combat_skipped` event type is logged instead.

```python
def should_fight(encounter, character):
    if encounter.condition_type is None:
        return True  # always fight
    if encounter.condition_type == 'discipline':
        return not has_discipline(character, encounter.condition_value)
    if encounter.condition_type == 'item':
        return not has_item(character, encounter.condition_value)
    return True
```

## State Machine

### Section Phase System

Each section has an ordered sequence of **phases** that the character must progress through. The phase sequence determines what happens when a character enters a section and what must be resolved before choices become available.

#### Phase Types

| Phase | Description |
|-------|-------------|
| `items` | Item pickup/decline for one or more `section_items` with `action='gain'`. Player must accept or decline each item. |
| `item_loss` | Automatic item removal (`section_items` with `action='lose'`). Applied without player action. |
| `eat` | Meal check. Consumes a meal, uses Hunting discipline, or applies 3 END penalty. |
| `combat` | Combat encounter. Player fights one enemy to completion (win, loss, or evasion). |
| `random` | Random number roll. Player clicks to roll; server generates number and applies outcome. |
| `heal` | Healing discipline tick. +1 END if Healing discipline present and no combat occurred in this section (evasion counts as combat — no healing). Auto-applied. |
| `choices` | Terminal phase. Player can now select from available choices. Always the final phase. |

#### Phase Sequence Resolution

The phase sequence is determined per-section using a hybrid approach:

1. **Override**: If `sections.phase_sequence_override` is non-null, use that JSON array directly.
2. **Computed default**: Otherwise, build the sequence from the section's content:

```python
def compute_phase_sequence(section, section_items, combat_encounters):
    phases = []

    # Item losses are applied first (automatic)
    if any(si for si in section_items if si.action == 'lose'):
        phases.append({"type": "item_loss"})

    # Items available for pickup
    gain_items = [si for si in section_items if si.action == 'gain']
    if gain_items:
        phases.append({"type": "items", "item_ids": [si.id for si in gain_items]})

    # Eat check
    if section.must_eat:
        phases.append({"type": "eat"})

    # Combat encounters (in ordinal order) — conditional combats included;
    # condition is checked at runtime during phase progression, not here
    for encounter in sorted(combat_encounters, key=lambda e: e.ordinal):
        phases.append({"type": "combat", "encounter_id": encounter.id})

    # Random phase (if section has random_outcomes)
    if has_random_outcomes(section):
        phases.append({"type": "random"})

    # Healing (only if no combat phases — evasion counts as combat)
    if not combat_encounters:
        phases.append({"type": "heal"})

    # Choices are always the terminal phase
    phases.append({"type": "choices"})
    return phases
```

Sections with non-standard flow (e.g., items found after combat) use the `phase_sequence_override` column. The parser detects these from narrative position; admin can correct them.

#### Phase Progression

The character's position in the phase sequence is tracked by `section_phase` and `section_phase_index` on the `characters` table.

```
1. Character enters section T
2. Compute phase sequence for T
3. Set section_phase_index = 0, section_phase = first phase type
4. For each phase:
   a. If phase requires player action (items, combat, random, choices): wait for API call
   b. If phase is automatic (item_loss, eat, heal): apply immediately, log character_event, advance
5. When all phases complete except choices: section_phase = 'choices'
6. Player can now make a choice → transitions to new section, restart from step 1
```

Each phase completion logs a `character_event` with the phase type and details.

#### Blocking Rules

- **Items phase**: Player must accept or decline EVERY pending item before advancing. API returns `409` if player attempts to choose or advance with unresolved items.
- **Combat phase**: Player must complete combat (win, loss, or evade) before advancing. `active_combat_encounter_id` is set on the character.
- **Random phase**: Player must click to roll before advancing.
- **Choices phase**: Player selects a choice, which triggers transition to the next section.

### Section Transition

```
1. Player at section S in 'choices' phase
2. Filter choices by availability (see below)
3. Player selects choice Ci → target section T
4. Log decision (character_id, S, T, Ci, run_number)
5. Move character to section T
6. Compute phase sequence for T
7. Begin phase progression for T
8. Return new section state (with current phase info)
```

### Choice Filtering

Each choice may have a condition. The engine evaluates availability:

| `condition_type` | Logic |
|------------------|-------|
| `discipline` | Character has the named discipline |
| `item` | Character has the named item |
| `gold` | Character has ≥ N gold crowns |
| `random` | Always available — presented as a "click to roll" button. Range in `condition_value` (e.g., `0-4`) determines outcome mapping. |
| `none` / `null` | Always available |

All choices are returned to the client, including unavailable ones (with `available: false` and the condition displayed), so the player can see what they're missing.

### Death Sections

Sections with `is_death = true` end the adventure. The character is marked `is_alive = false`. A `death` action is logged in both the decision log and the character events table.

### Death and Restart

- **Decision**: On death, the character can restart from the beginning of the current book.
- **Rationale**: Matches the book experience (you'd flip back to section 1) while preserving all history for analytics.
- **Implications**:
  - A `character_book_starts` snapshot is saved at the beginning of each book (after discipline selection and inventory adjustment)
  - On restart: restore character from snapshot, increment `death_count` and `current_run`, log a `restart` action
  - All decision log entries are preserved with their `run_number`
  - Enables analytics: furthest character without death, most deadly decisions per book, death leaderboards

```python
def restart_character(character, snapshot):
    character.combat_skill_base = snapshot.combat_skill_base
    character.endurance_base = snapshot.endurance_base
    character.endurance_current = snapshot.endurance_current
    character.gold = snapshot.gold
    character.meals = snapshot.meals
    character.is_alive = True
    character.death_count += 1
    character.current_run += 1
    character.current_section_id = first_section_of_book(character.book_id)
    character.active_combat_encounter_id = None
    character.section_phase = None
    character.section_phase_index = None
    character.wizard_step = None
    restore_items(character, snapshot.items_json)
    restore_disciplines(character, snapshot.disciplines_json)
```

### Healing and Evasion

- **Decision**: Evasion counts as combat occurring. No healing applies in sections where the character evaded combat.
- **Rationale**: Matches the books' intent that healing is for peaceful sections. Even partial combat (fighting then fleeing) is still combat.

```python
def should_heal(character, section_phases_completed):
    combat_occurred = any(
        p["type"] == "combat" and p.get("result") in ("win", "evasion")
        for p in section_phases_completed
    )
    return not combat_occurred
```

### Victory Sections

Sections with `is_victory = true` complete the current book. The character can then advance to the next book via the book advance wizard, or **replay the current book**.

### Book Replay

- **Decision**: Players can replay the current book instead of advancing after reaching a victory section.
- **Rationale**: Allows completionists to explore different paths without creating a new character.
- **Implications**:
  - Replay resets to the `character_book_starts` snapshot (same as death restart)
  - Increments `current_run` (but NOT `death_count`)
  - Logs a `replay` action in `decision_log` and a `replay` event in `character_events`
  - Available only when `is_victory = true` on current section and character hasn't entered the advance wizard

```python
def replay_book(character, snapshot):
    """Replay current book from beginning. Same as death restart but without incrementing death_count."""
    character.combat_skill_base = snapshot.combat_skill_base
    character.endurance_base = snapshot.endurance_base
    character.endurance_current = snapshot.endurance_current
    character.gold = snapshot.gold
    character.meals = snapshot.meals
    character.is_alive = True
    character.current_run += 1
    # death_count NOT incremented
    character.current_section_id = first_section_of_book(character.book_id)
    character.active_combat_encounter_id = None
    character.section_phase = None
    character.section_phase_index = None
    character.wizard_step = None
    restore_items(character, snapshot.items_json)
    restore_disciplines(character, snapshot.disciplines_json)
```

## Book Advance Wizard

Multi-step process for transitioning between books.

### Wizard Steps

```
Step 1: Discipline Selection
  - Server presents available disciplines for the new era (excluding already-learned ones)
  - Player picks N new disciplines (count from book_transition_rules)

Step 2: Inventory Adjustment
  - Server presents current inventory and carry-over limits (from book_transition_rules)
  - Player selects which weapons and backpack items to keep
  - Special items carry over automatically (if rules allow)
  - Gold carries over (if rules allow, still capped at 50)

Step 3: Confirmation
  - Server shows summary of new character state
  - Player confirms
  - Character moves to section 1 of the new book
  - New character_book_starts snapshot is saved
```

### Wizard State

The wizard step is tracked explicitly via the `wizard_step` column on `characters`:

- `null` — not in wizard
- `discipline` — step 1: picking new disciplines
- `inventory` — step 2: adjusting inventory for carry-over limits
- `confirm` — step 3: reviewing summary before advancing

The wizard is entered when the character reaches a victory section and the player calls `GET /gameplay/{character_id}/advance-book`. The `wizard_step` is set to `discipline` (or `inventory` if no new disciplines are needed). It advances with each `POST` and is cleared to `null` when the wizard completes.

### Carry-over Rules

Defined per book transition in the `book_transition_rules` table:

| Era Transition | Typical Rules |
|----------------|---------------|
| Kai → Kai (1→2, 2→3, etc.) | Keep all items, gold, disciplines. Pick 1 new Kai discipline. |
| Kai → Magnakai (5→6) | Keep special items, choose weapons/backpack. Start with all 10 Kai + pick 3 Magnakai. Base stats may change. |
| Magnakai → Magnakai (6→7, etc.) | Keep all items, gold, disciplines. Pick 1 new Magnakai discipline. |
| Magnakai → Grand Master (12→13) | Base CS = 15 + random, END = 25 + random. Pick 4 Grand Master disciplines. Keep select items. |
| Grand Master → New Order (20→21) | New character (Kai Lord in training). Some carry-over mechanics. |

Exact rules per book pair are defined in `book_transition_rules` table, populated via parser or admin.

## Inventory Constraints

### Weapons

- **Maximum**: 2 weapons
- Only the **equipped** weapon provides combat bonuses
- Weaponskill/Weaponmastery bonuses only apply if the matching weapon is equipped

### Backpack Items

- **Maximum**: 8 items (including meals)
- Meals are backpack items
- If backpack is lost, all backpack items and meals are lost

### Special Items

- No hard limit on count (varies by book)
- Cannot be dropped voluntarily (some are removed by story events)
- Examples: Map, Seal of Dorier, Vordak Gem

### Gold Crowns

- **Maximum**: 50 gold crowns (belt pouch)
- Excess gold must be left behind

### Pickup Logic

```python
def can_pickup(character, item_name, item_type):
    if item_type == "weapon":
        return count_weapons(character) < 2
    elif item_type == "backpack":
        return count_backpack(character) < 8
    elif item_type == "gold":
        return character.gold < 50
    elif item_type == "special":
        return True  # story grants these
    elif item_type == "meal":
        return count_backpack(character) < 8
```

## Discipline Effects

### Kai Era (Books 1–5)

10 disciplines, character picks 5 at creation. One additional discipline gained per book completed.

| Discipline | Mechanical Effect |
|------------|-------------------|
| Camouflage | Unlocks discipline-gated choices |
| Hunting | No meal required when instructed to eat |
| Sixth Sense | Unlocks discipline-gated choices |
| Tracking | Unlocks discipline-gated choices |
| Healing | +1 END on section entry if no combat in section (up to base END). Applied after all other phases resolve. |
| Weaponskill | +2 CS when equipped weapon's category matches chosen type (via `weapon_categories` table) |
| Mindshield | Immune to enemy Mindblast attacks (no END loss) |
| Mindblast | +2 CS in combat (unless enemy is immune) |
| Animal Kinship | Unlocks discipline-gated choices |
| Mind Over Matter | Unlocks discipline-gated choices |

### Magnakai Era (Books 6–12)

10 new disciplines. Character starts book 6 with 3 Magnakai + all 10 Kai. One additional Magnakai discipline per book.

| Discipline | Mechanical Effect |
|------------|-------------------|
| Weaponmastery | +3 CS with mastered weapon (pick 3 weapon types) |
| Animal Control | Unlocks choices + situational combat bonuses |
| Curing | +1 END per section without combat; can cure disease/poison |
| Invisibility | Unlocks choices (enhanced Camouflage) |
| Huntmastery | No meal needed + enhanced tracking; +2 CS in wild |
| Pathsmanship | Unlocks choices (enhanced Tracking) |
| Psi-surge | +4 CS but costs 2 END per round (opt-in per round via API flag) |
| Psi-screen | Immune to Mindblast + Psi-surge; blocks psychic attacks |
| Nexus | Unlocks choices (combines Sixth Sense + enhanced awareness) |
| Divination | Unlocks choices; reveals hidden information |

**Lore-circles**: Completing all disciplines in a circle grants stat bonuses.

| Circle | Disciplines | Bonus |
|--------|-------------|-------|
| Circle of Fire | Weaponmastery, Huntmastery | +1 CS, +2 END |
| Circle of Light | Animal Control, Curing | +3 END |
| Circle of Solaris | Invisibility, Pathsmanship, Divination | +1 CS, +3 END |
| Circle of the Spirit | Psi-surge, Psi-screen, Nexus | +3 CS, +3 END |

### Grand Master Era (Books 13–20)

Further evolved disciplines with stronger effects. Base stats: CS = 15 + random, END = 25 + random. Character starts with 4 Grand Master disciplines. One additional per book.

| Discipline | Mechanical Effect |
|------------|-------------------|
| Grand Weaponmastery | +5 CS with mastered weapon type. Pick from expanded weapon list. |
| Animal Mastery | Enhanced Animal Control. Unlocks choices + stronger combat bonuses in wild encounters. |
| Deliverance | Enhanced Curing. +2 END per section without combat. Can neutralize any poison/disease. |
| Assimilance | Enhanced Invisibility. Unlocks choices + can mimic appearance/voice. |
| Grand Huntmastery | No meal needed. +3 CS in wilderness combat. Enhanced tracking/navigation. |
| Grand Pathsmanship | Enhanced Pathsmanship. Unlocks choices + danger sense in travel. |
| Kai-surge | +8 CS but costs 4 END per round (opt-in, replaces Psi-surge). |
| Kai-screen | Enhanced Psi-screen. Immune to all psychic attacks + can reflect psychic damage. |
| Grand Nexus | Enhanced Nexus. Unlocks choices + telepathic communication. |
| Telegnosis | Enhanced Divination. Unlocks choices + remote viewing + prophecy. |
| Magi-magic | Spell-like abilities. Unlocks special choices + situational combat effects. |
| Kai-alchemy | Create/enhance items. Unlocks special choices + potion crafting. |

**Grand Master Lore-circles**: TODO — research exact circle groupings and bonuses from source books.

### New Order Era (Books 21–28)

Lone Wolf training new Kai Lords. New character with some carry-over mechanics.

| Discipline | Mechanical Effect |
|------------|-------------------|
| Grand Weaponmastery | Same as Grand Master era |
| Animal Mastery | Same as Grand Master era |
| Deliverance | Same as Grand Master era |
| Assimilance | Same as Grand Master era |
| Grand Huntmastery | Same as Grand Master era |
| Grand Pathsmanship | Same as Grand Master era |
| Kai-surge | Same as Grand Master era |
| Kai-screen | Same as Grand Master era |
| Grand Nexus | Same as Grand Master era |
| Telegnosis | Same as Grand Master era |
| Magi-magic | Same as Grand Master era |
| Kai-alchemy | Same as Grand Master era |
| Astrology | Unlocks choices + time/navigation bonuses. New Order exclusive. |
| Herbmastery | Enhanced healing. Identify and use herbs for various effects. New Order exclusive. |
| Elementalism | Control elements. Unlocks special combat and exploration choices. New Order exclusive. |
| Bardsmanship | Social/persuasion ability. Unlocks choices + can calm or inspire. New Order exclusive. |

**New Order notes**: The New Order character starts fresh with base stats similar to Grand Master (CS = 15 + random, END = 25 + random) and picks from the expanded discipline list. Some Grand Master-era disciplines have enhanced effects. TODO — research exact starting conditions and discipline counts per book.

## Per-Character Rule Configuration

Characters have a `rule_overrides` JSON column for per-character rule variants. This allows different characters to use different rule interpretations.

### Discipline Stacking Mode

- **Decision**: Configurable per character. Default: `"stack"`.
- **Rationale**: The books are ambiguous about whether tiered discipline effects stack. Making it configurable lets players choose their preferred interpretation.
- **Options**:
  - `"stack"` — All tiers add their bonuses. Healing (+1) + Curing (+1) + Deliverance (+2) = +4 END per section without combat.
  - `"highest"` — Only the most advanced tier applies. Deliverance alone gives +2 END.

```python
def get_healing_bonus(character):
    mode = get_rule(character, "discipline_stacking", default="stack")
    tiers = []
    if has_discipline(character, "Healing"):
        tiers.append(1)
    if has_discipline(character, "Curing"):
        tiers.append(1)
    if has_discipline(character, "Deliverance"):
        tiers.append(2)
    if mode == "stack":
        return sum(tiers)
    else:  # "highest"
        return max(tiers) if tiers else 0
```

The same pattern applies to CS bonuses from Mindblast → Psi-surge → Kai-surge and Weaponskill → Weaponmastery → Grand Weaponmastery.

```python
def get_rule(character, key, default=None):
    overrides = json.loads(character.rule_overrides or '{}')
    return overrides.get(key, default)
```

## Weapon Category Matching

Weaponskill/Weaponmastery bonuses use **category-based matching** rather than exact name matching. The `weapon_categories` table maps weapon names to categories.

```python
def weapon_category_matches(equipped_weapon_name, skill_weapon_type):
    """Check if equipped weapon's category matches the character's skill type."""
    category = lookup_weapon_category(equipped_weapon_name)
    return category == skill_weapon_type
```

Example categories:
- **Sword**: Sword, Broadsword, Short Sword, Sommerswerd
- **Axe**: Axe, Battle Axe, Hand Axe
- **Mace**: Mace, War Hammer, Morning Star
- **Spear**: Spear, Javelin, Lance
- **Dagger**: Dagger, Throwing Knife
- **Bow**: Bow, Longbow, Short Bow, Crossbow
- **Quarterstaff**: Quarterstaff, Staff
- **Warhammer**: Warhammer

The parser seeds this table from known weapon names in the XHTML. Admin can add/correct entries as new weapons are encountered.

## Meal Mechanics

When a section has `must_eat = true`:

```python
def eat_meal(character):
    if has_discipline("Hunting") or has_discipline("Huntmastery") or has_discipline("Grand Huntmastery"):
        return 0  # no meal consumed, no END loss
    elif character.meals > 0:
        character.meals -= 1
        return 0  # no END loss
    else:
        character.endurance_current -= 3
        return -3  # lost 3 END
```

## Random Number Mechanics

There are **two distinct random mechanics** in the game:

### Phase-Based Random (In-Section Effects)

Used when a section instructs the player to "pick a number from the Random Number Table" and applies an effect based on the result (gold change, END change, item gain/loss, or redirect to another section).

- **Data**: `random_outcomes` table stores outcome bands per section (range_min, range_max, effect_type, effect_value, narrative_text)
- **Flow**: Player is in the `random` phase → clicks "Roll" → server generates number → engine matches to outcome band → applies effect → logs `random_roll` character event → shows result with narrative text → player clicks "Continue"
- **UI**: "Show then confirm" pattern. After rolling, display the result and outcome description. Player clicks "Continue" to proceed (or to be redirected if effect_type is `section_redirect`).

```python
def resolve_random_phase(section_id, random_outcomes):
    number = random.randint(0, 9)
    for outcome in random_outcomes:
        if outcome.range_min <= number <= outcome.range_max:
            return apply_random_effect(outcome, number)
    raise ValueError(f"No outcome band covers number {number}")
```

### Choice-Based Random (Section Branching)

Used when multiple choices each have `condition_type='random'` with a number range in `condition_value` (e.g., `"0-4"`). The player rolls once, and the engine routes to the matching choice's target section.

- **Data**: Multiple `choices` rows with `condition_type='random'` and `condition_value` like `"0-4"`, `"5-9"`
- **Flow**: Section shows "Roll the dice" button → server generates number → engine finds the choice whose range contains the number → shows result and selected path → player clicks "Continue" → navigates to target section
- **UI**: Same "show then confirm" pattern. Display the roll result and which path was selected. Player clicks "Continue" to navigate.

```python
def resolve_random_choice(choices, random_number):
    for choice in choices:
        if choice.condition_type == 'random':
            range_min, range_max = parse_range(choice.condition_value)
            if range_min <= random_number <= range_max:
                return choice
    raise ValueError(f"No random choice covers number {random_number}")
```

### Server-Side Generation

- **Decision**: All random numbers are server-generated using `random.randint(0, 9)`.
- **Rationale**: Prevents cheating. The books' "Random Number Table" is replaced by server-side generation.
- The generated number is always returned in responses for transparency.

## Character Creation

Two-phase process: roll stats (repeatable), then finalize.

### Stat Rolling

```python
def roll_stats(era: str) -> dict:
    base_cs, base_end = ERA_BASE_STATS[era]  # kai: (10, 20), grand_master: (15, 25), etc.
    cs_random = random.randint(0, 9)
    end_random = random.randint(0, 9)
    return {
        "combat_skill_base": base_cs + cs_random,
        "endurance_base": base_end + end_random,
    }
```

- **Decision**: Players can reroll stats as many times as they want before finalizing, but cannot choose their numbers.
- **Rationale**: Avoids the tedious delete-and-recreate loop for bad rolls while preserving the randomness the books intended.
- Rolled stats are encoded in a JWT `roll_token` signed with the app secret, with a 1-hour expiry. The finalize step validates this token to ensure stats were server-generated.
- The roll endpoint is stateless — no DB writes until finalization.
- Character creation respects the `users.max_characters` limit (default: 3). Returns `400` if the limit is reached.

## Book Transitions

When completing a book (reaching a victory section), the character advances via the multi-step wizard:

- **Stats**: CS and END base values carry over (unless era transition overrides them)
- **Items**: Carry-over limits defined per transition in `book_transition_rules`
- **Disciplines**: All learned disciplines carry over; player picks new disciplines per rules
- **Gold**: Carries over if allowed (still capped at 50)
- **Snapshot**: A new `character_book_starts` snapshot is saved after the wizard completes
