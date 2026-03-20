# Epic 3: Game Engine (Pure Functions)

**Phase**: 2 (parallel with Epics 2 and 5)
**Dependencies**: Epic 1 (for DTO design reference only — no DB imports)
**Status**: Not Started

Pure game logic with zero dependencies on database, HTTP, or ORM layers. All functions accept dataclass DTOs, return results. Highly testable with millisecond execution. This is the heart of the game.

**Critical rule**: `app/engine/` must NEVER import from `app/models/`, `app/database`, `app/services/`, `app/routers/`, `fastapi`, or `sqlalchemy`.

---

## Story 3.1: Engine DTOs & Meter Semantics

**Status**: Not Started

### Description

Core dataclasses that define the engine's input/output contract, plus centralized meter boundary logic.

### Tasks

- [ ] Create `app/engine/types.py` with dataclasses:
  ```python
  @dataclass
  class ItemState:
      character_item_id: int
      item_name: str
      item_type: str  # weapon, backpack, special
      is_equipped: bool
      game_object_id: int | None
      properties: dict  # from game_object.properties

  @dataclass
  class CharacterState:
      character_id: int
      combat_skill_base: int
      endurance_base: int
      endurance_max: int
      endurance_current: int
      gold: int
      meals: int
      is_alive: bool
      disciplines: list[str]  # discipline names
      weapon_skill_category: str | None  # Weaponskill weapon category
      items: list[ItemState]
      version: int
      current_run: int
      death_count: int
      rule_overrides: dict | None

  @dataclass
  class SceneContext:
      scene_id: int
      book_id: int
      scene_number: int
      is_death: bool
      is_victory: bool
      must_eat: bool
      loses_backpack: bool
      phase_sequence_override: list[str] | None
      choices: list[ChoiceData]
      combat_encounters: list[CombatEncounterData]
      scene_items: list[SceneItemData]
      random_outcomes: list[RandomOutcomeData]

  @dataclass
  class CombatContext:
      encounter_id: int
      enemy_name: str
      enemy_cs: int
      enemy_end: int
      enemy_end_remaining: int
      mindblast_immune: bool
      evasion_after_rounds: int | None
      evasion_target: int | None
      evasion_damage: int
      modifiers: list[CombatModifierData]
      rounds_fought: int
  ```
  (Plus supporting dataclasses: ChoiceData, CombatEncounterData, SceneItemData, RandomOutcomeData, CombatModifierData)
- [ ] Create `app/engine/meters.py`:
  - `apply_endurance_delta(state, delta) → (new_end, is_dead, events)` — single death check point, clamp to [0, endurance_max]
  - `apply_gold_delta(state, delta) → (new_gold, actual_delta)` — cap at 50, floor at 0, partial acceptance
  - `apply_meal_delta(state, delta) → (new_meals, actual_delta)` — cap at 8, floor at 0, partial acceptance
  - `compute_endurance_max(base, disciplines, items) → max` — lore-circle bonuses + item endurance bonuses (Chainmail +4, Helmet +2, etc.)
- [ ] Define `MAX_REDIRECT_DEPTH = 5` constant

### Acceptance Criteria

- Unit tests for all meter boundaries:
  - Death at endurance 0 (delta takes END below 0 → clamp to 0, is_dead=True)
  - Gold overflow at 50 (actual_delta < requested_delta)
  - Gold underflow at 0
  - Meal cap at 8
  - Healing cap at endurance_max (cannot heal above max)
  - endurance_max recalculation with item bonuses

---

## Story 3.2: Combat Resolution

**Status**: Not Started

### Description

Full combat system: effective CS calculation, CRT lookup, round resolution, evasion, special weapons.

### Tasks

- [ ] Create `app/engine/combat.py`:
  - `effective_combat_skill(state, encounter, crt_era)` — computes CS with all modifiers:
    - Base CS
    - Unarmed penalty: -4 if no weapon equipped
    - Mindblast: +2 if character has Mindblast and enemy is not immune
    - Mindshield: prevents -2 penalty from enemy_mindblast modifier
    - Weaponskill: +2 if equipped weapon category matches weapon_skill_category
    - Item combat bonuses: from equipped weapon properties (`combat_bonus`)
    - Special item bonuses: from special items with `combat_bonus` property (Shield +2, Silver Helm +2)
    - Encounter modifiers: cs_bonus, cs_penalty from combat_modifiers
    - Enemy Mindblast: -2 if modifier present and character lacks Mindshield
  - `ratio_to_bracket(hero_cs, enemy_cs)` → combat_ratio integer
  - `lookup_crt(crt_rows, combat_ratio, random_number)` → (enemy_loss, hero_loss) — using bracket range lookup with sentinel values
  - `resolve_combat_round(state, encounter, crt_rows, random_number, use_psi_surge)` → RoundResult
    - Psi-surge: +4 CS, +2 END cost to hero (applied before round, not after)
  - `evade_combat(state, encounter, rounds_fought)` → EvadeResult
    - Apply evasion_damage, check death priority (death trumps evasion)
  - `should_fight(state, encounter)` → bool
    - Conditional combat: skip if character has condition_value discipline/item
  - `apply_special_weapon_effects(round_result, weapon_properties, encounter_modifiers)` → modified RoundResult
    - Sommerswerd: double `enemy_loss` vs undead
    - `combat_bonus_vs_special`: replaces (not stacks with) base `combat_bonus`

### Acceptance Criteria

- Unit tests for all modifier combinations (at least 10 test cases for effective_combat_skill)
- Unit tests for all 13 bracket boundaries (ratio_to_bracket)
- Unit tests for instant kill (NULL loss values)
- Unit test for evasion into death (evasion_damage kills hero)
- Unit test for conditional combat skip
- Unit test for Sommerswerd double damage vs undead
- Unit test for combat_bonus_vs_special replacing base bonus

---

## Story 3.3: Choice Filtering & Conditions

**Status**: Not Started

### Description

Evaluate choice availability based on character state and conditions.

### Tasks

- [ ] Create `app/engine/conditions.py`:
  - `check_condition(state, condition_type, condition_value) → bool`:
    - `None` / `"none"` → always True
    - `"discipline"` → check if discipline name in state.disciplines
    - `"item"` → check if item_name in state.items
    - `"gold"` → check if state.gold >= int(condition_value)
    - `"random"` → always True (random-gated choices are always "available" for selection)
    - Compound OR: `{"any": ["Tracking", "Huntmastery"]}` → True if any match
  - `filter_choices(choices, state) → list[ChoiceWithAvailability]`:
    - Each choice gets `available: bool` and `reason: str | None`
    - Choices with `target_scene_id = None` AND no `choice_random_outcomes` → `available: False, reason: "path_unavailable"`
    - Choices with failed condition → `available: False, reason: condition description`
  - `compute_gold_deduction(choice) → int | None`:
    - If condition_type == "gold", return int(condition_value) (amount to deduct on selection)

### Acceptance Criteria

- Unit tests for all condition types (discipline, item, gold, random, none/null)
- Unit test for compound OR logic (any of multiple disciplines)
- Unit test for unresolved choices (null target, no random outcomes → path_unavailable)
- Unit test for gold gating (gold >= N required)
- Unit test for gold deduction calculation

---

## Story 3.4: Phase Sequence & Progression

**Status**: Not Started

### Description

Compute and execute the ordered sequence of phases for each scene. This is the core state machine.

### Tasks

- [ ] Create `app/engine/phases.py`:
  - `compute_phase_sequence(scene_context, character_state) → list[Phase]`:
    - Default order: `backpack_loss` → `item_loss` → `items` → `eat` → `combat×N` → `random` → `heal` → `choices`
    - Only include phases that apply (has items, must_eat, has encounters, etc.)
    - Multi-enemy: each enemy as separate `combat` entry in sequence
    - `random` phase: only for `random_outcomes` entries OR when ALL choices are random-gated
    - Mixed random+regular: random-gated choices stay in `choices` phase, no separate `random` phase
    - Override support: `phase_sequence_override` replaces computed sequence
    - Over-capacity injection: if character is over weapon/backpack limits and scene has no items phase, inject one
  - `run_automatic_phase(phase, character_state, scene_context) → PhaseResult`:
    - `eat`: consume 1 meal → use Hunting discipline → or apply -3 END penalty
    - `heal`: +1 END if character has Healing discipline AND no combat occurred in this scene (evasion counts as combat)
    - `item_loss`: remove specified item, or skip+log if character doesn't have it
    - `backpack_loss`: remove all backpack items, reset meals to 0
  - PhaseResult dataclass with `severity` field: `info`, `warn`, `danger`
  - Death-during-phase: if any automatic phase causes death (e.g., meal penalty), halt immediately, return death result with `parent_event_id`

### Acceptance Criteria

- Unit tests for all phase types (eat, heal, item_loss, backpack_loss)
- Unit test for death mid-eat (meal penalty kills character at low END)
- Unit test for death mid-combat (handled at combat level, verified here)
- Unit test for phase_sequence_override replacing computed sequence
- Unit test for multi-enemy phase entries (2 enemies → 2 combat entries)
- Unit test for over-capacity items phase injection
- Unit test for heal suppression after combat/evasion
- Unit test for hunting discipline as meal substitute

---

## Story 3.5: Inventory Management

**Status**: Not Started

### Description

Item slot management, equip/unequip, consumable usage, and endurance_max recalculation.

### Tasks

- [ ] Create `app/engine/inventory.py`:
  - Slot constraints:
    - Max 2 weapons
    - Max 8 backpack items
    - Unlimited special items
  - `can_pickup(state, item) → bool` — check slot limits (mandatory items override)
  - `pickup_item(state, item) → PickupResult` — add to inventory, handle mandatory override
  - `drop_item(state, character_item_id) → DropResult`
  - `equip_weapon(state, character_item_id) → EquipResult`
  - `unequip_weapon(state, character_item_id) → UnequipResult`
  - `use_consumable(state, character_item_id) → ConsumeResult`:
    - Validate item has `consumable: true` in properties
    - Apply effect (e.g., `endurance_restore` → apply_endurance_delta)
    - Remove item from inventory
  - `recompute_endurance_max(state) → int`:
    - `endurance_base` + sum of `endurance_bonus` from carried items
    - If new max < current endurance, clamp current to new max
  - `is_over_capacity(state) → bool` — True if weapons > 2 or backpack > 8

### Acceptance Criteria

- Unit tests for slot limits (can't pickup 3rd weapon, can't pickup 9th backpack item)
- Unit test for mandatory item override (pickup succeeds even when over limit)
- Unit test for consumable effect application (Healing Potion → +4 END)
- Unit test for consumable removes item after use
- Unit test for endurance_max recalculation on item gain (Chainmail +4)
- Unit test for endurance_max recalculation on item loss (Chainmail removed → max decreases, current clamped)
- Unit test for equip/unequip weapon toggle

---

## Story 3.6: Random Mechanics

**Status**: Not Started

### Description

Three distinct random resolution systems, each with its own logic.

### Tasks

- [ ] Create `app/engine/random.py`:
  - **Phase-based random**: `resolve_phase_random(outcomes, roll, roll_group) → PhaseRandomResult`
    - Match roll against range_min/range_max for the given roll_group
    - Effect types: gold_change, endurance_change, item_gain, item_loss, meal_change, scene_redirect
    - Apply effects immediately via meter functions
    - Scene redirect: flag for redirect, remaining auto phases (heal) complete first
  - **Scene-level exit**: `resolve_scene_exit_random(choices, roll) → target_scene_id`
    - All choices are random-gated (condition_type='random')
    - Roll determines which choice/target is selected
  - **Choice-triggered random**: `resolve_choice_triggered_random(outcome_bands, roll) → ChoiceRandomResult`
    - Outcome bands from choice_random_outcomes table
    - Roll determines target_scene_id and narrative_text
  - Multi-roll support:
    - Track `current_roll_group` and `rolls_remaining`
    - Redirect in multi-roll: skip remaining groups (redirect wins)

### Acceptance Criteria

- Unit tests for each mechanic independently
- Unit test for multi-roll sequences (2+ roll groups, effects applied per group)
- Unit test for redirect wins mid-sequence (group 1 redirects → group 2 skipped)
- Unit test for each effect type (gold_change, endurance_change, item_gain, item_loss, meal_change, scene_redirect)
- Unit test for roll matching against range bands

---

## Story 3.7: Death, Restart, Replay

**Status**: Not Started

### Description

Character lifecycle functions for death handling and state restoration from snapshots.

### Tasks

- [ ] Add to `app/engine/` (likely in a `lifecycle.py` or in `phases.py`):
  - `handle_death(state) → DeathResult`:
    - Mark is_alive = False
    - Clear scene_phase, scene_phase_index, active_combat_encounter_id, pending_choice_id
    - Increment version
  - `enter_death_scene(state) → DeathResult`:
    - Skip all phases immediately
    - Call handle_death
  - `restart_character(state, snapshot) → RestoredState`:
    - Restore all fields from snapshot (CS, END, gold, meals, items, disciplines)
    - Increment death_count AND current_run
    - Set is_alive = True
    - Place at book's start scene
    - Increment version
  - `replay_book(state, snapshot) → RestoredState`:
    - Same as restart but death_count NOT incremented
    - Only current_run incremented
    - Only available at victory scene
    - Increment version

### Acceptance Criteria

- Unit test for death marking (all fields cleared correctly)
- Unit test for death scene entry (phases skipped)
- Unit test for snapshot restore (field-by-field verification)
- Unit test for restart: death_count incremented, current_run incremented
- Unit test for replay: death_count NOT incremented, current_run incremented
- Unit test for version increment on all mutations

---

## Implementation Notes

### Engine Purity

The engine package is the most critical architectural boundary in the project. Every function must:
1. Accept only dataclass DTOs as input (no ORM models, no DB sessions)
2. Return plain dataclass results (no side effects)
3. Import only from standard library and other engine modules

The service layer (`app/services/`) is responsible for:
- Querying the DB and constructing DTOs
- Calling engine functions
- Persisting results back to DB
- Logging character events

### Testing Strategy

All engine tests are pure unit tests — no DB, no HTTP, millisecond execution. Target 90%+ coverage. Use parameterized tests for boundary conditions and modifier combinations.
