# Game Engine

Pure functions with no HTTP or database dependencies. All engine functions take data objects (dataclasses or Pydantic models) as input and return results — the routers handle persistence.

## Engine Input Contracts (DTOs)

The API layer populates these dataclasses from the database. Engine functions accept only these types — never ORM models or raw DB rows.

```python
@dataclass
class CharacterState:
    """Snapshot of character state for engine functions."""
    id: int
    combat_skill_base: int
    endurance_base: int
    endurance_max: int
    endurance_current: int
    gold: int
    meals: int
    is_alive: bool
    version: int
    disciplines: list[str]          # discipline names
    items: list[ItemState]          # current inventory
    equipped_weapon: ItemState | None
    rule_overrides: dict | None

@dataclass
class ItemState:
    """An item in the character's inventory."""
    name: str
    item_type: str                  # weapon, backpack, special
    is_equipped: bool
    game_object_id: int | None
    properties: dict                # from game_object.properties JSON (combat_bonus, consumable, etc.)

@dataclass
class SceneContext:
    """All scene data needed for phase progression."""
    id: int
    number: int
    book_id: int
    is_death: bool
    is_victory: bool
    must_eat: bool
    loses_backpack: bool
    phase_sequence_override: list[dict] | None
    scene_items: list             # scene_items rows
    combat_encounters: list       # combat_encounters rows with modifiers
    random_outcomes: list         # random_outcomes rows
    choices: list                 # choices rows

@dataclass
class CombatContext:
    """Data needed for a single combat round."""
    encounter_id: int
    enemy_name: str
    enemy_cs: int
    enemy_end_remaining: int
    mindblast_immune: bool
    modifiers: list               # combat_modifiers rows
    evasion_after_rounds: int | None
    evasion_target: int | None
    evasion_damage: int
    rounds_fought: int
```

## Combat Resolution

### Combat Ratio

```
combat_ratio = hero_effective_cs - enemy_cs
```

Where `hero_effective_cs` includes all modifiers:

```python
def effective_combat_skill(base_cs, disciplines, equipped_weapon, carried_items, enemy, use_psi_surge=False):
    cs = base_cs
    # Unarmed penalty: -4 CS if no weapon equipped
    if equipped_weapon is None:
        cs -= 4
    # Enemy Mindblast: -2 CS if enemy has mindblast modifier and hero lacks Mindshield
    if has_combat_modifier(enemy, 'enemy_mindblast') and not has_discipline("Mindshield"):
        cs -= 2
    # Hero Mindblast: +2 CS (unless enemy immune)
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
    # Item-granted combat bonuses (e.g., Sommerswerd +8 CS)
    if equipped_weapon and equipped_weapon.properties.get("combat_bonus"):
        cs += equipped_weapon.properties["combat_bonus"]
    # Special item combat bonuses (e.g., Shield +2 CS, Silver Helm +2 CS)
    for item in carried_items:
        if item.item_type == "special" and item.properties.get("combat_bonus"):
            cs += item.properties["combat_bonus"]
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
10. Increment character.version (optimistic locking)
11. Return round result
```

### Multi-Enemy Combat

Some scenes have multiple enemies fought sequentially. The `ordinal` field on `combat_encounters` determines fight order. The next enemy engages only after the current one is defeated.

### Conditional Combat

Some combat encounters are conditional — they only trigger when the character **lacks** a certain discipline or item (e.g., "If you do not have Camouflage, you must fight...").

- **Decision**: `combat_encounters` has `condition_type` and `condition_value` columns. If the condition is met (character has the discipline/item), the combat is skipped entirely.
- **Rationale**: Keeps conditional combat as a property of the encounter rather than requiring scene restructuring.
- **Implications**: The combat phase in the phase sequence checks the condition before engaging. If skipped, a `combat_skipped` event is logged instead of `combat_start`/`combat_end`.

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

### Evasion Damage

- **Decision**: Evasion damage is configurable per encounter via `evasion_damage` on `combat_encounters`.
- **Rationale**: Some encounters deal damage when evading, others don't. Default is 0.

```python
def evade_combat(character, encounter):
    character.endurance_current -= encounter.evasion_damage
    character.active_combat_encounter_id = None
    if character.endurance_current <= 0:
        character.is_alive = False
    return encounter.evasion_target, encounter.evasion_damage
```

### Foes as Game Objects

Combat encounters reference foe game_objects via `foe_game_object_id`. Enemy stats (cs, end) are also stored inline on `combat_encounters` for direct gameplay use (denormalized from the game_object). The game_object link enables taxonomy queries like "in which scenes does this enemy appear?"

### Special Weapon Effects

Some weapons have special bonuses against specific foe types (e.g., Sommerswerd is especially effective against undead). Foe type is modeled via `combat_modifiers.modifier_type` (e.g., `'undead'`, `'helghast'`). The engine checks the equipped weapon's `special_vs` property against the encounter's modifier types.

```python
def apply_special_weapon_effects(equipped_weapon, encounter_modifiers, enemy_loss):
    """
    Check equipped weapon for special_vs match against encounter modifier types.
    Returns (adjusted_cs_bonus, adjusted_enemy_loss).

    special_vs: str matching a modifier_type on the encounter (e.g., 'undead')
    damage_multiplier: int — multiplies CRT enemy_loss on a match (e.g., 2 = double damage)
    combat_bonus_vs_special: int — CS bonus applied instead of base combat_bonus on a match
    """
    if equipped_weapon is None:
        return 0, enemy_loss

    props = equipped_weapon.properties
    special_vs = props.get("special_vs")
    if special_vs is None:
        return props.get("combat_bonus", 0), enemy_loss

    # Check if any encounter modifier matches the weapon's special_vs type
    modifier_types = [m.modifier_type for m in encounter_modifiers]
    if special_vs in modifier_types:
        # Special match: use combat_bonus_vs_special (replaces, does not stack with, base combat_bonus)
        cs_bonus = props.get("combat_bonus_vs_special", props.get("combat_bonus", 0))
        # Apply damage multiplier to CRT enemy_loss
        multiplier = props.get("damage_multiplier", 1)
        adjusted_enemy_loss = enemy_loss * multiplier if enemy_loss is not None else None
        return cs_bonus, adjusted_enemy_loss
    else:
        # No match: use base combat_bonus
        return props.get("combat_bonus", 0), enemy_loss
```

- **Decision**: `combat_bonus_vs_special` replaces (does not stack with) the base `combat_bonus` when a special match is detected.
- **Rationale**: The Sommerswerd's power against undead is absolute — the special bonus is the relevant one, not a combination.
- **Implications**: `effective_combat_skill()` calls `apply_special_weapon_effects()` instead of directly reading `combat_bonus` from the weapon properties. The `damage_multiplier` is applied in `resolve_combat_round()` after the CRT lookup. A `damage_multiplier` of `None` means instant kill (same sentinel as CRT `enemy_loss = None`).

**Item properties for special weapons** (stored on game_object `properties` JSON):
- `{"combat_bonus": 8, "special_vs": "undead", "damage_multiplier": 2, "combat_bonus_vs_special": 10}` — Sommerswerd (example: +8 normally, +10 + double damage vs undead)

## State Machine

### Scene Phase System

Each scene has an ordered sequence of **phases** that the character must progress through. The phase sequence determines what happens when a character enters a scene and what must be resolved before choices become available.

#### Phase Types

| Phase | Description |
|-------|-------------|
| `items` | Item pickup/decline for one or more `scene_items` with `action='gain'`. Player must accept or decline each item. Inventory management (drop/equip/unequip) is available during this phase for swapping. |
| `item_loss` | Automatic item removal (`scene_items` with `action='lose'`). Applied without player action. If the character doesn't have the item, skip silently and log an `item_loss_skip` event. |
| `backpack_loss` | Automatic removal of all backpack items and meals. Triggered when `scene.loses_backpack` is true. |
| `eat` | Meal check. Consumes a meal (from `characters.meals` counter), uses Hunting discipline, or applies 3 END penalty. |
| `combat` | Combat encounter. Player fights one enemy to completion (win, loss, or evasion). |
| `random` | Random number roll. Player clicks to roll; server generates number and applies outcome. |
| `heal` | Healing discipline tick. +1 END if Healing discipline present and no combat occurred in this scene (evasion counts as combat — no healing). Capped at `endurance_max`. Auto-applied. |
| `choices` | Terminal phase. Player can now select from available choices. Always the final phase. |

#### Phase Sequence Resolution

The phase sequence is determined per-scene using a hybrid approach:

1. **Override**: If `scenes.phase_sequence_override` is non-null, use that JSON array directly.
2. **Computed default**: Otherwise, build the sequence from the scene's content:

```python
def compute_phase_sequence(scene, scene_items, combat_encounters):
    phases = []

    # Backpack loss applied first if flagged
    if scene.loses_backpack:
        phases.append({"type": "backpack_loss"})

    # Item losses are applied next (automatic, silent skip if missing)
    if any(si for si in scene_items if si.action == 'lose'):
        phases.append({"type": "item_loss"})

    # Items available for pickup
    gain_items = [si for si in scene_items if si.action == 'gain']
    if gain_items:
        phases.append({"type": "items", "item_ids": [si.id for si in gain_items]})

    # Eat check
    if scene.must_eat:
        phases.append({"type": "eat"})

    # Combat encounters (in ordinal order) — conditional combats included;
    # condition is checked at runtime during phase progression, not here
    for encounter in sorted(combat_encounters, key=lambda e: e.ordinal):
        phases.append({"type": "combat", "encounter_id": encounter.id})

    # Random phase (if scene has random_outcomes)
    if has_random_outcomes(scene):
        phases.append({"type": "random"})

    # Healing always included in sequence. At runtime, should_heal() checks
    # whether combat actually occurred (including conditional combats that were skipped).
    phases.append({"type": "heal"})

    # Choices are always the terminal phase
    phases.append({"type": "choices"})
    return phases
```

Scenes with non-standard flow (e.g., items found after combat) use the `phase_sequence_override` column. The parser detects these from narrative position; admin can correct them.

#### Phase Progression

The character's position in the phase sequence is tracked by `scene_phase` and `scene_phase_index` on the `characters` table.

```
1. Character enters scene T
2. If scene T has is_death=true: skip all phases, mark is_alive=false, log death event, return. Narrative is shown but no phases run.
3. Compute phase sequence for T
4. Set scene_phase_index = 0, scene_phase = first phase type
5. For each phase:
   a. If phase requires player action (items, combat, random, choices): wait for API call
   b. If phase is automatic (item_loss, backpack_loss, eat, heal): apply immediately, log character_event, advance
   c. For item_loss: if character doesn't have the item, skip silently and log item_loss_skip event
6. When all phases complete except choices: scene_phase = 'choices'
7. Player can now make a choice → transitions to new scene, restart from step 1
8. Increment character.version after each state mutation
```

#### scene_phase State Diagram

The `scene_phase` column on `characters` tracks the character's current interactive position in the phase sequence. Only interactive phases are stored — automatic phases complete atomically without ever being persisted in `scene_phase`.

**Valid interactive values** (client-visible):

| Value | Meaning |
|-------|---------|
| `items` | Character is in the item pickup/decline phase. One or more `scene_items` with `action='gain'` are pending. |
| `combat` | Character is in an active combat encounter. `active_combat_encounter_id` is set. |
| `random` | Character must roll. A `random_outcomes` phase is pending, or all scene exits are random-gated. |
| `choices` | Character has resolved all preceding phases and may now select a choice to advance. Terminal phase. |

**`null` means no active phase:**
- Character is dead (`is_alive = false`)
- Character is in a wizard (`active_wizard_id` is set)
- Character is at a death or victory scene
- Character is between scenes (transitioning)

**Automatic phases are never stored in `scene_phase`:**

The phases `eat`, `heal`, `item_loss`, and `backpack_loss` complete atomically during transition endpoint calls (`/choose`, `/roll`, `/restart`, `/replay`, `/combat/evade`). By the time the client reads the scene via `GET /scene`, these phases have already resolved and their results appear in `phase_results`.

**State transitions:**

```
null → items → combat → random → choices → null (on /choose or /roll exit)
         ↑ (any interactive phase can transition directly to null on death)
```

Multiple interactive phases may appear in sequence (e.g., `items` then `combat` then `choices`). Each transition endpoint advances `scene_phase` to the next interactive phase, running any automatic phases in between.

**Automatic phase results**: Since `eat` and `heal` (and `item_loss`, `backpack_loss`) are automatic, their results are reported in the `phase_results` array on the scene response. The client never sees `scene_phase = "eat"` — by the time it reads the scene, automatic phases have already resolved.

**Phase result severity**: Each entry in `phase_results` includes a `severity` field to guide UI presentation:

| Severity | Meaning | Examples |
|----------|---------|----------|
| `info` | Neutral or positive outcome | `meal_consumed`, `hunting_used`, `healed`, `item_loss_skip`, `backpack_loss` (no items) |
| `warn` | Notable negative outcome, not critical | `meal_penalty` (still alive), `item_loss` |
| `danger` | Critical outcome | `death` (from any cause), `meal_penalty` when endurance ≤ 3 |

Each phase completion logs a `character_event` with the phase type and details.

#### Blocking Rules

- **Items phase**: Gold and meal `scene_items` with `action='gain'` are auto-applied during phase progression (no accept/decline needed; reported in `phase_results`). For weapon/backpack/special items, the player must accept or decline each one before advancing. Mandatory items (`is_mandatory=true`) override slot limits — the player gets the item even if over capacity; the next items phase forces resolution back to within limits. API returns `409` if player attempts to choose or advance with unresolved items. Player CAN use the inventory endpoint (drop/equip/unequip) during this phase to make room for new items.
- **Combat phase**: Player must complete combat (win, loss, or evade) before advancing. `active_combat_encounter_id` is set on the character.
- **Random phase**: Player must click to roll before advancing.
- **Choices phase**: Player selects a choice, which triggers transition to the next scene.

### Scene Transition

```
1. Player at scene S in 'choices' phase
2. Filter choices by availability (see below)
3. Player selects choice Ci → target scene T
4. If choice has condition_type='gold': deduct int(condition_value) gold, log gold_change event
5. Log decision (character_id, S, T, Ci, run_number)
6. Move character to scene T
7. Compute phase sequence for T
8. Begin phase progression for T
9. Increment character.version
10. Return new scene state (with current phase info)
```

### Scene Response Assembly

`GET /gameplay/{id}/scene` is strictly **read-only**. It never mutates character state. It assembles the scene response from:

1. Current character state (`characters` row + related tables)
2. Persisted phase results from `character_events` for the current scene visit (the automatic phase results logged during the most recent transition)
3. Current scene content (narrative, choices, combat encounters, pending items)

**Transition endpoints run automatic phases synchronously:**

When a transition endpoint is called (`/choose`, `/roll`, `/restart`, `/replay`, `/combat/evade`), the server:

```
1. Executes the requested action (navigate, roll, restart, etc.)
2. Enters the new scene
3. Runs all automatic phases (backpack_loss, item_loss, eat, heal) synchronously
4. Logs each automatic phase result as a character_event
5. Stops at the first interactive phase (items, combat, random, choices)
6. Returns the assembled scene response (same shape as GET /scene)
```

The client never needs to poll or make a follow-up call to see automatic phase results. They are included in the transition response's `phase_results` array and are also accessible via `GET /scene` on any subsequent call.

- **Decision**: Automatic phases run at transition time, not lazily on GET.
- **Rationale**: Keeps GET /scene simple and idempotent. Prevents state inconsistencies where a phase partially runs across two requests. Makes the transition response self-contained.
- **Implications**: If an automatic phase causes death (e.g., starvation during the eat phase), the transition response already reflects the dead state. The client does not need to re-fetch.

### Choice Filtering

Each choice may have a condition. The engine evaluates availability:

| `condition_type` | Logic |
|------------------|-------|
| `discipline` | Character has the named discipline |
| `item` | Character has the named item |
| `gold` | Character has ≥ N gold crowns |
| `random` | Always available — presented as a "click to roll" button. Range in `condition_value` determines outcome mapping. |
| `none` / `null` | Always available |

**Compound conditions**: When `condition_value` is JSON (e.g., `{"any": ["Tracking", "Huntmastery"]}`), the engine evaluates the compound logic:

```python
def check_condition(character, condition_type, condition_value):
    if condition_type is None:
        return True

    # Parse compound conditions
    if isinstance(condition_value, str) and condition_value.startswith('{'):
        parsed = json.loads(condition_value)
        if 'any' in parsed:
            return any(
                check_single_condition(character, condition_type, v)
                for v in parsed['any']
            )

    return check_single_condition(character, condition_type, condition_value)

def check_single_condition(character, condition_type, value):
    if condition_type == 'discipline':
        return has_discipline(character, value)
    elif condition_type == 'item':
        return has_item(character, value)
    elif condition_type == 'gold':
        return character.gold >= int(value)
    elif condition_type == 'random':
        return True
    return True
```

All choices are returned to the client, including unavailable ones (with `available: false` and the condition displayed), so the player can see what they're missing.

**Unresolved choices**: Choices with `target_scene_id = null` and no `choice_random_outcomes` are shown with `available: false` and `condition_type = "path_unavailable"`. These represent unresolved cross-references from the parser that need admin correction.

### Death Scenes

Scenes with `is_death = true` end the adventure **immediately on entry**. The entire phase sequence is skipped — no items, eat, combat, or heal phases run. The character is marked `is_alive = false`. A `death` action is logged in both the decision log and the character events table. The narrative is shown to the player, but the only available action is restart.

```python
def enter_scene(character, scene):
    if scene.is_death:
        character.is_alive = False
        character.scene_phase = None
        character.scene_phase_index = None
        character.active_combat_encounter_id = None
        character.version += 1
        log_decision(character, action_type='death')
        log_character_event(character, scene, event_type='death')
        return  # no phases run
    # ... normal phase progression
```

### Death During Phase Progression

When `endurance_current` reaches 0 during any phase (combat damage, meal penalty, evasion damage, random effect), phase progression halts immediately. The character cannot continue to the next phase.

```python
def on_death_during_phase(character, causing_event_id):
    """Called whenever apply_endurance_delta() triggers death mid-phase."""
    character.is_alive = False
    character.scene_phase = None
    character.scene_phase_index = None
    character.active_combat_encounter_id = None
    character.version += 1
    log_character_event(
        character,
        event_type='death',
        parent_event_id=causing_event_id  # points to combat_end, meal_penalty, evasion, random_roll, etc.
    )
    # No further phases run. Only /restart is available.
```

- **Decision**: Death halts phase progression immediately and clears all active phase state.
- **Rationale**: A dead character has no meaningful game state. Clearing phase fields prevents stale state from persisting across a restart.
- **Implications**: The `death` event always has a `parent_event_id` pointing to the event that caused the fatal damage. After death, only `POST /gameplay/{id}/restart` is available. All other gameplay endpoints return 409 with `error_code: CHARACTER_DEAD`.

### Death and Restart

- **Decision**: On death, the character can restart from the beginning of the current book.
- **Rationale**: Matches the book experience (you'd flip back to scene 1) while preserving all history for analytics.
- **Implications**:
  - A `character_book_starts` snapshot is saved at the beginning of each book (after discipline selection and inventory adjustment)
  - On restart: restore character from snapshot, increment `death_count` and `current_run`, log a `restart` action
  - All decision log entries are preserved with their `run_number`
  - Enables analytics: furthest character without death, most deadly decisions per book, death leaderboards

```python
def restart_character(character, snapshot):
    character.combat_skill_base = snapshot.combat_skill_base
    character.endurance_base = snapshot.endurance_base
    character.endurance_max = snapshot.endurance_max
    character.endurance_current = snapshot.endurance_current
    character.gold = snapshot.gold
    character.meals = snapshot.meals
    character.is_alive = True
    character.death_count += 1
    character.current_run += 1
    character.current_scene_id = first_scene_of_book(character.book_id)
    character.active_combat_encounter_id = None
    character.scene_phase = None
    character.scene_phase_index = None
    character.active_wizard_id = None
    character.version += 1
    restore_items(character, snapshot.items_json)
    restore_disciplines(character, snapshot.disciplines_json)
```

### Endurance Max

Endurance is tracked with three values:
- `endurance_base`: The rolled base value (e.g., 20 + random). Set at character creation, may change on era transitions.
- `endurance_max`: The effective maximum (base + permanent bonuses + item bonuses). Lore-circle bonuses and special item `endurance_bonus` properties increase this value. Healing caps here.
- `endurance_current`: The current health. Can never exceed `endurance_max`.

```python
def compute_endurance_max(endurance_base, disciplines, carried_items):
    max_end = endurance_base
    max_end += lore_circle_end_bonus(disciplines)
    # Special item endurance bonuses (Chainmail Waistcoat +4, Helmet +2, etc.)
    for item in carried_items:
        max_end += item.properties.get("endurance_bonus", 0)
    # Other permanent bonuses could add here
    return max_end
```

Endurance max is recalculated when disciplines change (new discipline learned, book transition). The value is stored on the character for fast reads and snapshotted in `character_book_starts`.

### endurance_max Recalculation Invariant

`endurance_max` must be recalculated (and `endurance_current` clamped) whenever the set of inputs to `compute_endurance_max()` changes.

**Trigger points:**

| Trigger | Reason |
|---------|--------|
| Item pickup (weapon, special, backpack) | Item may have `endurance_bonus` property |
| Item drop | Removing an item with `endurance_bonus` lowers the max |
| Item loss (scene event) | Same as drop |
| Backpack loss | Bulk removal of items that may have `endurance_bonus` |
| Discipline gained | Lore-circle completion may add END bonus |
| Wizard completion (character creation or book advance) | Multiple changes applied at once — recalculate after all changes are applied |
| Restart / replay | Restoring from snapshot — recalculate after snapshot is applied to confirm stored max is consistent |

**Clamping rule:**

```python
def recalculate_endurance_max(character):
    new_max = compute_endurance_max(
        character.endurance_base,
        character.disciplines,
        character.items
    )
    character.endurance_max = new_max
    if character.endurance_current > new_max:
        character.endurance_current = new_max  # clamp — never exceed max
    character.version += 1
```

- **Decision**: Always clamp `endurance_current` to the new max if it would exceed it.
- **Rationale**: If an item with an endurance bonus is removed, the max decreases. Without clamping, the character would have current endurance above their new maximum — an illegal state.
- **Implications**: Dropping a bonus item mid-scene can reduce `endurance_current`. This is intentional and book-accurate.

### Healing and Evasion

- **Decision**: Evasion counts as combat occurring. No healing applies in scenes where the character evaded combat.
- **Rationale**: Matches the books' intent that healing is for peaceful scenes. Even partial combat (fighting then fleeing) is still combat.

```python
def apply_healing(character, scene_phases_completed):
    if not should_heal(character, scene_phases_completed):
        return 0
    bonus = get_healing_bonus(character)
    actual = min(bonus, character.endurance_max - character.endurance_current)
    character.endurance_current += actual
    character.version += 1
    return actual

def should_heal(character, scene_phases_completed):
    combat_occurred = any(
        p["type"] == "combat" and p.get("result") in ("win", "evasion")
        for p in scene_phases_completed
    )
    return not combat_occurred
```

### Victory Scenes

Scenes with `is_victory = true` complete the current book. The character can then advance to the next book via the book advance wizard, or **replay the current book**.

### Book Replay

- **Decision**: Players can replay the current book instead of advancing after reaching a victory scene.
- **Rationale**: Allows completionists to explore different paths without creating a new character.
- **Implications**:
  - Replay resets to the `character_book_starts` snapshot (same as death restart)
  - Increments `current_run` (but NOT `death_count`)
  - Logs a `replay` action in `decision_log` and a `replay` event in `character_events`
  - Available only when `is_victory = true` on current scene and character hasn't entered the advance wizard

```python
def replay_book(character, snapshot):
    """Replay current book from beginning. Same as death restart but without incrementing death_count."""
    character.combat_skill_base = snapshot.combat_skill_base
    character.endurance_base = snapshot.endurance_base
    character.endurance_max = snapshot.endurance_max
    character.endurance_current = snapshot.endurance_current
    character.gold = snapshot.gold
    character.meals = snapshot.meals
    character.is_alive = True
    character.current_run += 1
    # death_count NOT incremented
    character.current_scene_id = first_scene_of_book(character.book_id)
    character.active_combat_encounter_id = None
    character.scene_phase = None
    character.scene_phase_index = None
    character.active_wizard_id = None
    character.version += 1
    restore_items(character, snapshot.items_json)
    restore_disciplines(character, snapshot.disciplines_json)
```

## Generic Wizard System

Both character creation and book advance use the same data-driven wizard infrastructure. Wizard templates define step sequences; wizard progress tracks the character's position.

### Wizard Flow

```
1. Wizard is initiated:
   - Character creation: POST /characters auto-starts wizard after creating character
   - Book advance: POST /gameplay/{id}/advance explicitly starts wizard (no lazy-init)
2. character_wizard_progress row created, current_step_index = 0
3. character.active_wizard_id set to the progress row
4. For each step:
   a. GET /characters/{id}/wizard returns current step type, config, and available options
   b. POST /characters/{id}/wizard submits the step's choice
   c. Choice is validated and stored in progress.state JSON
   d. current_step_index incremented
5. On final step (confirm): wizard completes
   a. State is applied to character (disciplines, items, stats)
   b. progress.completed_at set
   c. character.active_wizard_id cleared
   d. character_book_starts snapshot saved (for book advance)
```

### Wizard Template Seed Data

**`character_creation` template** (2 steps):

| Step | step_type | config | API call |
|------|-----------|--------|----------|
| 0 | `pick_equipment` | `{"categories": ["weapons", "backpack"]}` | `POST /characters/{id}/wizard` |
| 1 | `confirm` | `null` | `POST /characters/{id}/wizard` |

Pre-wizard steps (dedicated endpoints, not wizard-managed):
- Stat rolling: `POST /characters/roll` (repeatable, stateless)
- Character creation + discipline/weapon skill selection: `POST /characters` (creates character, auto-starts wizard)

**`book_advance` template** (4 steps):

| Step | step_type | config | API call |
|------|-----------|--------|----------|
| 0 | `pick_disciplines` | `{"count": 1}` (from book_transition_rules.new_disciplines_count) | `POST /characters/{id}/wizard` |
| 1 | `pick_equipment` | `{"book_id": "<from books table>"}` | `POST /characters/{id}/wizard` |
| 2 | `inventory_adjust` | `null` (limits from book_transition_rules) | `POST /characters/{id}/wizard` |
| 3 | `confirm` | `null` | `POST /characters/{id}/wizard` |

The `pick_equipment` step (ordinal 1) provides equipment available at the start of the new book, separate from the carried inventory managed in `inventory_adjust`. The advance wizard is started explicitly via `POST /gameplay/{id}/advance`. Until initiated, replay remains available at victory scenes.

### Wizard State

The `active_wizard_id` column on `characters` replaces the old `wizard_step` column. It points to the `character_wizard_progress` row, which tracks:
- Which template is being used
- Current step index
- Accumulated state (JSON blob of all choices so far)

### Starting Scene

The starting scene for a book is data-driven via `books.start_scene_number` (default 1). When a character starts or restarts a book, they are placed at this scene.

```python
def first_scene_of_book(book_id):
    book = get_book(book_id)
    return get_scene_by_number(book_id, book.start_scene_number)
```

## Book Advance Wizard

Multi-step process for transitioning between books. Uses the generic wizard system with template name `book_advance`.

### Wizard Steps

```
Step 1: Discipline Selection (pick_disciplines)
  - Server presents available disciplines for the new era (excluding already-learned ones)
  - Player picks N new disciplines (count from book_transition_rules)

Step 2: Equipment Selection (pick_equipment)
  - Server presents starting equipment available at the beginning of the new book
  - Player picks from available weapons and backpack items (per book's max_total_picks)
  - This is new equipment granted at the book start, separate from carried inventory

Step 3: Inventory Adjustment (inventory_adjust)
  - Server presents current inventory and carry-over limits (from book_transition_rules)
  - Player selects which carried weapons and backpack items to keep
  - Special items carry over automatically (if rules allow)
  - Gold carries over (if rules allow, still capped at 50)

Step 4: Confirmation (confirm)
  - Server shows summary of new character state
  - Player confirms
  - Character moves to start scene of the new book
  - New character_book_starts snapshot is saved
  - endurance_max recalculated with new disciplines
```

### Carry-over Rules

Defined per book transition in the `book_transition_rules` table:

| Era Transition | Typical Rules |
|----------------|---------------|
| Kai → Kai (1→2, 2→3, etc.) | Keep all items, gold, disciplines. Pick 1 new Kai discipline. |
| Kai → Magnakai (5→6) | Keep special items, choose weapons/backpack. Start with all 10 Kai + pick 3 Magnakai. Base stats may change. |
| Magnakai → Magnakai (6→7, etc.) | Keep all items, gold, disciplines. Pick 1 new Magnakai discipline. |
| Magnakai → Grand Master (12→13) | Base CS = 15 + random, END = 25 + random. Pick 4 Grand Master disciplines. Keep select items. |
| Grand Master → New Order (20→21) | New character (Kai Lord in training). Some carry-over mechanics. |

## Inventory Constraints

### Weapons

- **Maximum**: 2 weapons
- Only the **equipped** weapon provides combat bonuses
- Weaponskill/Weaponmastery bonuses only apply if the matching weapon is equipped

### Backpack Items

- **Maximum**: 8 items
- Meals are NOT backpack items — they are tracked separately as a counter on the character
- If backpack is lost (`loses_backpack` scene flag), all backpack-type items are removed

### Special Items

- No hard limit on count (varies by book)
- Cannot be dropped voluntarily (some are removed by story events)
- Examples: Map, Seal of Dorier, Vordak Gem

### Gold Crowns

- **Maximum**: 50 gold crowns (belt pouch)
- On pickup, partial acceptance up to cap is auto-applied (no player decision needed)

### Pickup Logic

```python
def pickup_gold(character, amount):
    """Accept gold up to the 50-crown cap. Returns actual amount taken."""
    actual = min(amount, 50 - character.gold)
    character.gold += actual
    character.version += 1
    return actual

def can_pickup(character, item_name, item_type):
    if item_type == "weapon":
        return count_weapons(character) < 2
    elif item_type == "backpack":
        return count_backpack(character) < 8
    elif item_type == "gold":
        return True  # partial acceptance handled by pickup_gold
    elif item_type == "special":
        return True  # story grants these
    elif item_type == "meal":
        return True  # meals are a counter, always accepted
```

### Backpack Loss

```python
def apply_backpack_loss(character):
    """Remove all backpack items and meals. Called when scene has loses_backpack=true."""
    remove_all_items_of_type(character, 'backpack')
    character.meals = 0
    character.version += 1
```

### Item Loss Skip

```python
def apply_item_loss(character, item_name, item_type):
    """Remove an item. If character doesn't have it, skip silently and return False."""
    if has_item(character, item_name):
        remove_item(character, item_name)
        character.version += 1
        return True  # item was removed
    else:
        return False  # skipped — log item_loss_skip event
```

### Consumable Item Usage

Consumable items (Healing Potions, Laumspur, etc.) can be used at any phase via `POST /gameplay/{id}/use-item`. Item effects are data-driven via game_object `properties` JSON.

```python
def use_consumable(character, item):
    """Use a consumable item. Item must have consumable=true in properties."""
    props = item.properties
    if not props.get("consumable"):
        raise InvalidAction("Item is not consumable")

    effect = props.get("effect")
    if effect == "endurance_restore":
        amount = props.get("amount", 0)
        apply_endurance_delta(character, amount)
    # Future effects can be added here (cure_poison, etc.)

    remove_item(character, item.name)
    character.version += 1
    return effect, amount
```

**Item properties for consumable items** (stored on game_object `properties` JSON):
- `{"consumable": true, "effect": "endurance_restore", "amount": 4}` — Healing Potion
- `{"consumable": true, "effect": "endurance_restore", "amount": 4}` — Laumspur

**Item properties for special weapons** (stored on game_object `properties` JSON):
- `{"combat_bonus": 8, "special_vs": "undead", "damage_multiplier": 2}` — Sommerswerd

## Optimistic Locking

The `version` column on characters prevents concurrent modification (e.g., two browser tabs).

```python
def check_version(character, expected_version):
    """Raises ConflictError if version doesn't match."""
    if character.version != expected_version:
        raise ConflictError(
            f"Character state has changed. Please refresh and retry.",
            current_version=character.version
        )
```

Every state-mutating engine function increments `character.version` after applying changes. The API layer checks the version before applying, returning 409 on mismatch.

## Transaction Boundaries

Each state-mutating gameplay endpoint executes within a single database transaction. The sequence within the transaction is:

```
1. Load character (SELECT ... FOR UPDATE or equivalent)
2. Check version (raise 409 VERSION_MISMATCH if mismatch)
3. Run engine logic (phase resolution, combat, item changes, etc.)
4. Write character state mutations
5. Write character_events rows (including parent_event_id links)
6. Increment character.version
7. Commit
```

- **Decision**: Version check, state mutation, event logging, and version increment are all atomic within one transaction.
- **Rationale**: A partial write (state changed but event not logged, or version not incremented) would leave the system in an inconsistent state that is difficult to detect and repair.
- **Implications**: If any step fails, the entire transaction rolls back. The character remains at its pre-request state. The client may retry with the same version number. There are no partial-success states.

Read endpoints (`GET /scene`, `GET /characters/{id}`, etc.) do not use transactions — they are read-only and always see committed state.

## Discipline Effects

### Kai Era (Books 1–5)

10 disciplines, character picks 5 at creation. One additional discipline gained per book completed.

| Discipline | Mechanical Effect |
|------------|-------------------|
| Camouflage | Unlocks discipline-gated choices |
| Hunting | No meal required when instructed to eat (uses `characters.meals` counter bypass) |
| Sixth Sense | Unlocks discipline-gated choices |
| Tracking | Unlocks discipline-gated choices |
| Healing | +1 END per scene if no combat occurred (up to `endurance_max`). Applied during heal phase. |
| Weaponskill | +2 CS when equipped weapon's category matches chosen type (via `weapon_categories` table) |
| Mindshield | Immune to -2 CS penalty from enemy Mindblast. Modeled via `enemy_mindblast` combat_modifier. |
| Mindblast | +2 CS in combat (unless enemy is immune) |
| Animal Kinship | Unlocks discipline-gated choices |
| Mind Over Matter | Unlocks discipline-gated choices |

### Magnakai Era (Books 6–12)

10 new disciplines. Character starts book 6 with 3 Magnakai + all 10 Kai. One additional Magnakai discipline per book.

| Discipline | Mechanical Effect |
|------------|-------------------|
| Weaponmastery | +3 CS with mastered weapon (pick 3 weapon types) |
| Animal Control | Unlocks choices + situational combat bonuses |
| Curing | +1 END per scene without combat (up to `endurance_max`); can cure disease/poison |
| Invisibility | Unlocks choices (enhanced Camouflage) |
| Huntmastery | No meal needed + enhanced tracking; +2 CS in wild |
| Pathsmanship | Unlocks choices (enhanced Tracking) |
| Psi-surge | +4 CS but costs 2 END per round (opt-in per round via API flag) |
| Psi-screen | Immune to Mindblast + Psi-surge; blocks psychic attacks |
| Nexus | Unlocks choices (combines Sixth Sense + enhanced awareness) |
| Divination | Unlocks choices; reveals hidden information |

**Lore-circles**: Completing all disciplines in a circle grants stat bonuses. END bonuses increase `endurance_max`.

| Circle | Disciplines | Bonus |
|--------|-------------|-------|
| Circle of Fire | Weaponmastery, Huntmastery | +1 CS, +2 END (to max) |
| Circle of Light | Animal Control, Curing | +3 END (to max) |
| Circle of Solaris | Invisibility, Pathsmanship, Divination | +1 CS, +3 END (to max) |
| Circle of the Spirit | Psi-surge, Psi-screen, Nexus | +3 CS, +3 END (to max) |

### Grand Master Era (Books 13–20)

Further evolved disciplines with stronger effects. Base stats: CS = 15 + random, END = 25 + random. Character starts with 4 Grand Master disciplines. One additional per book.

| Discipline | Mechanical Effect |
|------------|-------------------|
| Grand Weaponmastery | +5 CS with mastered weapon type. Pick from expanded weapon list. |
| Animal Mastery | Enhanced Animal Control. Unlocks choices + stronger combat bonuses in wild encounters. |
| Deliverance | Enhanced Curing. +2 END per scene without combat (up to `endurance_max`). Can neutralize any poison/disease. |
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

Characters have a `rule_overrides` JSON column for per-character rule variants.

### Discipline Stacking Mode

- **Decision**: Configurable per character. Default: `"stack"`.
- **Rationale**: The books are ambiguous about whether tiered discipline effects stack.
- **Options**:
  - `"stack"` — All tiers add their bonuses. Healing (+1) + Curing (+1) + Deliverance (+2) = +4 END per scene without combat.
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

def get_rule(character, key, default=None):
    overrides = json.loads(character.rule_overrides or '{}')
    return overrides.get(key, default)
```

## Weapon Category Matching

Weaponskill/Weaponmastery bonuses use **category-based matching**. The `weapon_categories` table maps weapon names to categories.

```python
def weapon_category_matches(equipped_weapon_name, skill_weapon_type):
    """Check if equipped weapon's category matches the character's skill type."""
    category = lookup_weapon_category(equipped_weapon_name)
    return category == skill_weapon_type
```

Kai-era weapon categories (from books 1-5). See seed-data.md for the full table.
- **Sword**: Sword, Broadsword, Short Sword, Sommerswerd
- **Axe**: Axe
- **Mace**: Mace, Jewelled Mace
- **Spear**: Spear, Magic Spear
- **Dagger**: Dagger
- **Quarterstaff**: Quarterstaff
- **Warhammer**: Warhammer

## Meal Mechanics

Meals are tracked as an integer counter on `characters.meals` — they are NOT inventory items and do NOT count against the backpack limit.

**Eating is fully automatic** during phase progression. There is no dedicated eat endpoint. When the `eat` phase is reached, the server auto-applies meal logic and the result is included in `phase_results` on the scene response.

When a scene has `must_eat = true`:

```python
def eat_meal(character):
    if has_discipline("Hunting") or has_discipline("Huntmastery") or has_discipline("Grand Huntmastery"):
        return 0  # no meal consumed, no END loss
    elif character.meals > 0:
        character.meals -= 1
        character.version += 1
        return 0  # no END loss
    else:
        apply_endurance_delta(character, -3)  # uses centralized meter function
        return -3  # lost 3 END (death checked by apply_endurance_delta)
```

- **Decision**: Starvation can kill. Death check after meal penalty.
- **Rationale**: 3 END loss can reduce endurance to 0. Without a check, character continues at negative END. Aligns with ops.md Meter underflow pattern.

## Meter Semantics

Endurance, gold, and meals are **meters** — bounded numeric fields with defined boundary behavior. All meter mutations route through centralized functions that enforce bounds and fire triggers on boundary conditions.

### Meter Definitions

| Field | Min | Max | Underflow Behavior | Overflow Behavior |
|-------|-----|-----|-------------------|-------------------|
| `endurance_current` | 0 | `endurance_max` | Death trigger fires | Capped at max (healing) |
| `gold` | 0 | 50 | Cannot go below 0 | Partial acceptance up to cap |
| `meals` | 0 | 8 | 3 END penalty (starvation) | Partial acceptance up to cap |

### Centralized Endurance Function

All endurance mutations route through `apply_endurance_delta()`. This is the single place for the death check — combat damage, meal penalty, evasion damage, random effects, and any other source of endurance loss all call this function.

```python
def apply_endurance_delta(character, delta):
    """Apply an endurance change with bounds enforcement and death trigger.

    All endurance mutations (combat, starvation, healing, random effects)
    route through this function. Single point for death check.
    """
    character.endurance_current += delta
    if character.endurance_current > character.endurance_max:
        character.endurance_current = character.endurance_max  # cap on heal
    if character.endurance_current <= 0:
        character.endurance_current = 0
        character.is_alive = False  # death trigger
    character.version += 1
```

- **Decision**: All endurance mutations go through one function.
- **Rationale**: Without centralization, death checks are scattered across 4+ locations (combat, eat_meal, evasion, random effects). Missing any one creates a bug where characters survive at negative endurance. The `apply_endurance_delta` pattern follows ops.md Meter boundary enforcement (section 1.3).

### Scene Redirect Depth Limit

```python
MAX_REDIRECT_DEPTH = 5
```

When a scene redirect triggers another redirect (e.g., random outcome → redirect → death scene), the engine tracks redirect depth and raises an error if `MAX_REDIRECT_DEPTH` is exceeded.

- **Decision**: Hard limit of 5 chained redirects.
- **Rationale**: Prevents infinite loops from misconfigured scene data. Follows ops.md cascade safety pattern (section 4.3). In practice, Lone Wolf books rarely chain more than 1-2 redirects.

## Event Operations Mapping

Each `character_events.event_type` decomposes into one or more ops.md operations recorded in the `operations` JSON column. Signal events (no state mutation) have null operations.

| event_type | Operations | Notes |
|------------|-----------|-------|
| `item_pickup` | `[{"op": "ref.add", "field": "items", "value": "<item_name>"}]` | Adds item to inventory |
| `item_decline` | _(null — signal event)_ | No state mutation |
| `item_loss` | `[{"op": "ref.remove", "field": "items", "value": "<item_name>"}]` | Removes item |
| `item_loss_skip` | _(null — signal event)_ | Character didn't have the item |
| `meal_consumed` | `[{"op": "meter.delta", "field": "meals", "delta": -1}]` | |
| `meal_penalty` | `[{"op": "meter.delta", "field": "endurance_current", "delta": -3}]` | May trigger death (child event) |
| `gold_change` | `[{"op": "meter.delta", "field": "gold", "delta": <amount>}]` | Positive or negative |
| `endurance_change` | `[{"op": "meter.delta", "field": "endurance_current", "delta": <amount>}]` | From random effects |
| `healing` | `[{"op": "meter.delta", "field": "endurance_current", "delta": <amount>}]` | Capped at endurance_max |
| `combat_start` | `[{"op": "ref.set", "field": "active_combat_encounter_id", "value": <id>}]` | |
| `combat_end` | `[{"op": "ref.set", "field": "active_combat_encounter_id", "value": null}, {"op": "meter.delta", "field": "endurance_current", "delta": <total_loss>}]` | Includes cumulative combat damage |
| `combat_skipped` | _(null — signal event)_ | Condition met, combat bypassed |
| `evasion` | `[{"op": "ref.set", "field": "active_combat_encounter_id", "value": null}, {"op": "meter.delta", "field": "endurance_current", "delta": <evasion_damage>}]` | |
| `death` | `[{"op": "object.update", "field": "is_alive", "value": false}]` | Always has `parent_event_id` pointing to cause |
| `restart` | `[{"op": "object.update", "field": "is_alive", "value": true}, {"op": "meter.set", "field": "endurance_current", "value": <snapshot_value>}]` | Restores from snapshot |
| `replay` | Same as restart | Without death_count increment |
| `discipline_gained` | `[{"op": "ref.add", "field": "disciplines", "value": <discipline_id>}]` | |
| `book_advance` | `[{"op": "ref.set", "field": "book_id", "value": <new_book_id>}]` | |
| `random_roll` | Varies by effect | gold_change, endurance_change, item_gain, item_loss, scene_redirect |
| `item_consumed` | `[{"op": "ref.remove", "field": "items", "value": "<item_name>"}, {"op": "meter.delta", "field": "endurance_current", "delta": <amount>}]` | Consumable item used |
| `backpack_loss` | `[{"op": "ref.remove", "field": "backpack_items", "value": "<all>"}, {"op": "meter.set", "field": "meals", "value": 0}]` | Bulk removal |

## Random Number Mechanics

There are **three distinct random mechanics** in the game. All three auto-apply effects immediately via the `/roll` endpoint. `requires_confirm` in the response is a **UI-only hint** — the client shows the result and the player clicks a confirm button to proceed, but no server call is needed for the confirm.

### 1. Phase-Based Random (Background In-Scene Effects)

Used when a scene instructs the player to "pick a number from the Random Number Table" and applies an effect based on the result. The narrative might say "roll, if you get 0 lose all your gold" — the effect is auto-applied and the result is shown in the narrative.

- **Data**: `random_outcomes` table stores outcome bands per scene
- **Phase**: `random` phase is added to the phase sequence
- **Flow**: Player is in the `random` phase → clicks "Roll" → server generates number → engine matches to outcome band → applies effect → logs `random_roll` character event → returns result with narrative text
- **Scene redirect**: When `effect_type='scene_redirect'`, remaining automatic phases (heal) complete first. The redirect then fires in place of the choices phase.

```python
def resolve_random_phase(scene_id, random_outcomes, current_roll_group):
    """Resolve one roll group. Called once per /roll request.
    Returns result with rolls_remaining count.
    If effect is scene_redirect, remaining groups are skipped (redirect wins).
    """
    group_outcomes = [o for o in random_outcomes if o.roll_group == current_roll_group]
    number = random.randint(0, 9)
    for outcome in group_outcomes:
        if outcome.range_min <= number <= outcome.range_max:
            max_group = max(o.roll_group for o in random_outcomes)
            rolls_remaining = max_group - current_roll_group
            if outcome.effect_type == 'scene_redirect':
                rolls_remaining = 0  # redirect wins, skip remaining groups
            return apply_random_effect(outcome, number), rolls_remaining
    raise ValueError(f"No outcome band covers number {number} in group {current_roll_group}")
```

### 2. Scene-Level Random Exits (No Player Choice)

Used when ALL choices in a scene have `condition_type='random'` with number ranges. The player doesn't decide — they just roll, and the result determines which scene they go to.

- **Data**: Multiple `choices` rows with `condition_type='random'` and `condition_value` like `"0-4"`, `"5-9"`
- **Phase**: `random` phase is added to the phase sequence (detected when all choices are random-gated)
- **Flow**: Scene shows "Roll" button → server generates number → engine finds the choice whose range contains the number → auto-transitions to target scene → returns new scene state

```python
def resolve_random_exit(choices, random_number):
    for choice in choices:
        if choice.condition_type == 'random':
            range_min, range_max = parse_range(choice.condition_value)
            if range_min <= random_number <= range_max:
                return choice
    raise ValueError(f"No random choice covers number {random_number}")
```

**Mixed scenes**: A scene can have both condition-gated choices (discipline/item) and random-exit choices. The UI shows available choices alongside a roll button for the random ones.

### 3. Choice-Triggered Random (Choose Then Roll)

Used when a specific choice leads to a roll with multiple possible outcomes. The player first selects a choice (e.g., "try to run away"), then rolls to determine the actual result.

- **Data**: The parent choice has `target_scene_id = null`. Outcome bands are stored in the `choice_random_outcomes` table (choice_id FK, range_min, range_max, target_scene_id, narrative_text).
- **Phase**: Occurs during the `choices` phase. No separate `random` phase needed.
- **Flow**: Player selects the choice via `/choose` → server detects `choice_random_outcomes` exist → returns `requires_roll: true` with outcome bands → player calls `/roll` → server generates number → matches to outcome band → auto-transitions to target scene

```python
def resolve_choice_triggered_random(choice_random_outcomes):
    number = random.randint(0, 9)
    for outcome in choice_random_outcomes:
        if outcome.range_min <= number <= outcome.range_max:
            return outcome
    raise ValueError(f"No outcome band covers number {number}")
```

### Mixed Random + Regular Choice Handling

Some scenes have a mix of random-gated choices and regular choices. These are handled entirely within the `choices` phase — no separate `random` phase is added to the sequence.

- **Decision**: The `choices` phase handles both regular and random-gated choices together. The `random` phase is only used for `random_outcomes` table entries (phase-based effects) and for scenes where **all** exits are random-gated.
- **Rationale**: Mixed scenes are fundamentally a presentation concern — the player sees all their options (regular choices and rollable choices) at once and picks one. There is no need for a dedicated phase.

**Phase sequence logic:**

```python
def compute_phase_sequence(scene, scene_items, combat_encounters, choices):
    phases = []
    # ... (backpack_loss, item_loss, items, eat, combat phases as before) ...

    # Random phase: ONLY if scene has random_outcomes entries (phase-based effects)
    # OR if ALL choices are random-gated (scene-level random exit)
    all_choices_random = choices and all(c.condition_type == 'random' for c in choices)
    has_random_outcomes = bool(scene.random_outcomes)
    if has_random_outcomes or all_choices_random:
        phases.append({"type": "random"})

    # Otherwise (mixed scene): choices phase handles random-gated + regular choices together.
    # No separate random phase. Player selects a random-gated choice → /choose returns
    # requires_roll: true → /roll resolves via choice_random_outcomes.

    phases.append({"type": "heal"})
    phases.append({"type": "choices"})
    return phases
```

**Client flow for mixed scenes:**

```
GET /scene → phase: "choices", choices includes:
  - Regular choice (available: true, has_random_outcomes: false)
  - Random-gated choice (available: true, has_random_outcomes: true)
  - Unavailable choice (available: false, condition: ...)

Player selects the random-gated choice:
POST /choose → { requires_roll: true, choice_id: 42, outcome_bands: [...] }

Player rolls:
POST /roll → resolves choice_random_outcomes, auto-transitions to target scene
```

## Character Creation

Uses the generic wizard system with template name `character_creation`.

### Wizard Steps

```
Step 1: Stat Roll (repeatable)
  - POST /characters/roll → returns roll_token (JWT with stats)
  - Can reroll as many times as desired
  - No character persisted yet

Step 2: Finalize
  - POST /characters with roll_token, name, book_id, discipline_ids, weapon_skill_type
  - Character created with active_wizard_id set
  - character_book_starts snapshot saved

Step 3: Equipment Selection
  - POST /characters/{id}/equip with equipment choices
  - Equipment list from book_starting_equipment table
  - Wizard completes, active_wizard_id cleared
  - Character is now playable
```

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

- Rolled stats are encoded in a JWT `roll_token` with 1-hour expiry
- The roll endpoint is stateless — no DB writes until finalization
- Character creation respects the `users.max_characters` limit (default: 3)
- `endurance_max` is computed from `endurance_base` + lore-circle bonuses at creation

## Book Transitions

When completing a book (reaching a victory scene), the character advances via the book advance wizard:

- **Stats**: CS and END base values carry over (unless era transition overrides them)
- **Items**: Carry-over limits defined per transition in `book_transition_rules`
- **Disciplines**: All learned disciplines carry over; player picks new disciplines per rules
- **Gold**: Carries over if allowed (still capped at 50)
- **Endurance max**: Recalculated with new discipline set
- **Snapshot**: A new `character_book_starts` snapshot is saved after the wizard completes
- **Start scene**: Character placed at `books.start_scene_number` of the new book
