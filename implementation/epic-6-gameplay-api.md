# Epic 6: Core Gameplay API

**Phase**: 4 (parallel with Epic 7)
**Dependencies**: Epics 2, 3, 4
**Status**: Not Started

Wires the pure engine functions to HTTP endpoints. This is the integration layer — services query the DB, construct DTOs, call engine functions, persist results, and log events. All within single transactions.

---

## Story 6.1: Scene Endpoint

**Status**: Not Started

### Description

Read-only endpoint that assembles the current scene state from persisted data.

### Tasks

- [ ] Create `GET /gameplay/{id}/scene` in `app/routers/gameplay.py`:
  - Requires auth + character ownership
  - Assembles response from current character state:
    - Scene narrative, illustration URL, scene_number
    - Phase computation from scene context
    - Auto-phase results reconstruction from character_events (eat, heal, item_loss, backpack_loss results)
    - Current phase state and phase_sequence
  - Phase-specific data:
    - `items` phase: pending_items list (scene_items not yet accepted/declined)
    - `combat` phase: encounter details (enemy name, CS, END remaining, rounds fought, evasion info)
    - `random` phase: roll button context
    - `choices` phase: filtered choice list with availability
  - Special scenes:
    - Death scene: `is_death: true`, no phases, only restart available
    - Victory scene: `is_victory: true`, replay/advance options
  - `version` included in response
- [ ] Create `app/services/gameplay_service.py` for scene assembly logic
- [ ] Create `app/schemas/gameplay.py` for response models

### Acceptance Criteria

- Integration test for each phase state (items, combat, random, choices)
- Integration test for death scene rendering
- Integration test for victory scene rendering
- Integration test: phase_results correctly reconstructed from character_events
- Integration test: choices filtered correctly (unavailable choices shown with reasons)
- Integration test: version present in response

---

## Story 6.2: Choose & Scene Transition

**Status**: Not Started

### Description

Make a choice to navigate to another scene. Runs all automatic phases at the target scene.

### Tasks

- [ ] Create `POST /gameplay/{id}/choose`:
  - Request: `{choice_id: int, version: int}`
  - Validations:
    - Version match (409 VERSION_MISMATCH)
    - Character in `choices` phase (409 WRONG_PHASE)
    - No pending items (409 PENDING_ITEMS)
    - No unresolved combat (409 COMBAT_UNRESOLVED)
    - Choice belongs to current scene
    - Choice is available (400 CHOICE_UNAVAILABLE)
  - Normal choice (target_scene_id not null, no random outcomes):
    - Transition to target scene
    - Run all automatic phases at new scene
    - Log decision_log entry
    - Return full scene state
  - Gold-gated choice:
    - Auto-deduct gold amount (int(condition_value))
    - Log gold_change event
    - Then proceed as normal choice
  - Choice-triggered random (choice has choice_random_outcomes):
    - Set pending_choice_id on character
    - Return `{requires_roll: true, choice_id, choice_text, outcome_bands, version}`
    - Do NOT transition yet

### Acceptance Criteria

- Integration test: normal choice transitions to target scene
- Integration test: automatic phases run at new scene (eat, heal results in phase_results)
- Integration test: gold-gated choice deducts gold and logs event
- Integration test: choice-triggered random returns requires_roll with outcome bands
- Integration test: 409 for pending items, unresolved combat, wrong phase, version mismatch
- Integration test: 400 for unavailable choice

---

## Story 6.3: Combat Endpoints

**Status**: Not Started

### Description

Combat round resolution and evasion, including multi-enemy and death handling.

### Tasks

- [ ] Create `POST /gameplay/{id}/combat/round`:
  - Request: `{use_psi_surge: bool, version: int}`
  - Validations: version match, character in combat phase, character alive
  - Server-generated random number (0–9)
  - CRT lookup via engine
  - Apply losses to both sides
  - Save combat_round row
  - If hero dead: halt, mark dead, log death event with parent_event_id
  - If enemy dead: combat_over = true, result = "win"
    - If more enemies: advance to next encounter
    - If no more enemies: advance phase
  - Response includes round details + combat state
- [ ] Create `POST /gameplay/{id}/combat/evade`:
  - Request: `{version: int}`
  - Validations: evasion allowed, rounds fought ≥ threshold
  - Apply evasion_damage via engine
  - Death priority: if evasion_damage kills hero, death at current scene (no transition)
  - On survival: transition to evasion_target scene, run automatic phases
  - Response: full scene response shape + evasion_damage field
- [ ] Multi-enemy combat:
  - Phase sequence has separate combat entry per enemy (by ordinal)
  - On enemy defeat, phase advances to next combat or next non-combat phase
  - Client calls GET /scene to see next combat state

### Acceptance Criteria

- Integration test: round resolution with CRT lookup
- Integration test: psi-surge (+4 CS, +2 END cost)
- Integration test: evasion after N rounds
- Integration test: evasion into death (damage kills hero)
- Integration test: multi-enemy combat (defeat first enemy, advance to second)
- Integration test: death in combat (hero END reaches 0)
- Integration test: conditional combat skip (character has required discipline)
- Integration test: combat_over returns result field

---

## Story 6.4: Item & Inventory Endpoints

**Status**: Not Started

### Description

Accept/decline pending scene items and manage inventory at any time.

### Tasks

- [ ] Create `POST /gameplay/{id}/item`:
  - Request: `{scene_item_id: int, action: "accept" | "decline", version: int}`
  - Accept:
    - Slot limit enforcement (400 INVENTORY_FULL unless mandatory)
    - Add to character_items
    - Log item_pickup event
    - Recalculate endurance_max
  - Decline:
    - 400 if item is mandatory
    - Log item_decline event
  - Gold/meal items are auto-applied during phase progression (never pending)
  - Response: item details, pending_items_remaining, phase_complete flag, current inventory
- [ ] Create `POST /gameplay/{id}/inventory`:
  - Request: `{action: "drop" | "equip" | "unequip", character_item_id: int, version: int}`
  - Available at any phase (including items phase for swapping)
  - Drop: remove item, recalculate endurance_max, log event
  - Equip/unequip: toggle is_equipped on weapons
  - Response: current inventory, version
- [ ] Create `POST /gameplay/{id}/use-item`:
  - Request: `{character_item_id: int, version: int}`
  - 400 if scene_phase = 'combat' (ITEM_NOT_CONSUMABLE or specific error)
  - 400 if item not consumable (no `consumable: true` in properties)
  - Apply effect via engine (endurance_restore → apply_endurance_delta)
  - Remove item from inventory
  - Recalculate endurance_max
  - Log item_consumed event
  - Response: effect details, inventory, version

### Acceptance Criteria

- Integration test: accept item adds to inventory
- Integration test: decline item removes from pending
- Integration test: mandatory item cannot be declined (400)
- Integration test: accept when inventory full returns 400 (unless mandatory)
- Integration test: gold overflow (partial acceptance, actual_amount < offered)
- Integration test: inventory swap during items phase (drop old, accept new)
- Integration test: consumable use (Healing Potion → +4 END)
- Integration test: consumable blocked during combat (400)
- Integration test: endurance_max recalculated on item gain/loss

---

## Story 6.5: Roll Endpoint

**Status**: Not Started

### Description

Single roll endpoint that dispatches to the correct random handler based on character state.

### Tasks

- [ ] Create `POST /gameplay/{id}/roll`:
  - Request: `{version: int}`
  - Server-generated random number (0–9)
  - Dispatch logic:
    1. If `pending_choice_id` set → resolve choice-triggered random
       - Look up choice_random_outcomes for the pending choice
       - Match roll against range bands
       - Clear pending_choice_id
       - Transition to target scene, run automatic phases
       - Response: `{random_type: "choice_outcome", random_number, outcome_text, scene_number, narrative, phase_results}`
    2. If `scene_phase='random'` AND scene has `random_outcomes` → resolve phase-based random
       - Match roll against range bands for current roll_group
       - Apply effect (gold_change, endurance_change, item_gain, item_loss, meal_change, scene_redirect)
       - Track rolls_remaining and current_roll_group
       - Scene redirect: complete heal phase first, then redirect
       - Response: `{random_type: "phase_effect", random_number, effect_type, effect_applied, rolls_remaining, current_roll_group, phase_complete}`
    3. If `scene_phase='random'` AND all choices are random-gated → resolve scene-level exit
       - Match roll against choice conditions
       - Transition to determined target scene, run automatic phases
       - Response: `{random_type: "scene_exit", random_number, outcome_text, scene_number, narrative, phase_results}`
  - 409 if not in random phase and no pending choice
  - Multi-roll: rolls_remaining > 0 means player calls /roll again
  - Redirect depth limit: MAX_REDIRECT_DEPTH = 5

### Acceptance Criteria

- Integration test for choice-triggered random resolution
- Integration test for phase-based random with gold_change effect
- Integration test for scene-level random exit
- Integration test for multi-roll scene (2 roll groups)
- Integration test for scene_redirect (heal completes before redirect)
- Integration test for redirect depth limit (409 on depth > 5)
- Integration test: 409 when not in random phase and no pending choice

---

## Story 6.6: Restart, Replay & Advance Endpoints

**Status**: Not Started

### Description

Character lifecycle endpoints for death restart, victory replay, and book advance.

### Tasks

- [ ] Create `POST /gameplay/{id}/restart`:
  - Request: `{version: int}`
  - 400 if character is alive (CHARACTER_DEAD reversed — character must be dead)
  - Restore from character_book_starts snapshot
  - Increment death_count AND current_run
  - Set is_alive = true
  - Place at book's start scene, run automatic phases
  - Log restart event and decision_log entry
  - Response: restored stats, scene_number, version
- [ ] Create `POST /gameplay/{id}/replay`:
  - Request: `{version: int}`
  - 400 if not at victory scene
  - 409 if advance wizard already started (WIZARD_ACTIVE)
  - Restore from snapshot
  - Increment current_run only (NOT death_count)
  - Log replay event and decision_log entry
  - Response: restored stats, scene_number, version
- [ ] Create `POST /gameplay/{id}/advance`:
  - Delegates to wizard system (Epic 4.4)
  - 400 if not at victory scene
  - 409 if wizard active or replay already started
  - 404 if no next book

### Acceptance Criteria

- Integration test: restart dead character (snapshot restore, death_count incremented)
- Integration test: restart alive character returns 400
- Integration test: replay at victory (snapshot restore, death_count NOT incremented)
- Integration test: replay when not at victory returns 400
- Integration test: replay blocked after advance started (409)
- Integration test: advance starts wizard, returns first step
- Integration test: advance when not at victory returns 400
- Integration test: advance when no next book returns 404

---

## Story 6.7: Character CRUD & History

**Status**: Not Started

### Description

Character listing, detail, soft delete, and history/event browsing endpoints.

### Tasks

- [ ] Create character endpoints in `app/routers/characters.py`:
  - `GET /characters` — list user's active (non-deleted) characters
  - `GET /characters/{id}` — full character sheet (stats, items, disciplines, current scene, wizard status)
  - `DELETE /characters/{id}` — soft delete (set is_deleted=true, deleted_at=now)
    - Deleted characters don't count toward max_characters
  - `GET /characters/{id}/history` — decision log
    - Filterable by run (?run=1)
    - Paginated (?limit=50, ?offset=0)
    - Chronological order
  - `GET /characters/{id}/events` — character events in seq order
    - Filterable by event_type, run, scene_id
    - Paginated
  - `GET /characters/{id}/runs` — per-run summaries
    - Run number, started_at, outcome (death/in_progress/victory), death_scene, decision_count, scenes_visited

### Acceptance Criteria

- Integration test: list characters (only shows non-deleted)
- Integration test: character detail includes full inventory and disciplines
- Integration test: soft delete (character disappears from list, doesn't count toward limit)
- Integration test: history filterable by run, paginated
- Integration test: events filterable by event_type and run
- Integration test: runs endpoint returns correct per-run summaries

---

## Implementation Notes

### Transaction Boundaries

Each gameplay endpoint executes within a single DB transaction:
1. Load character + verify ownership + verify version
2. Load scene context / combat context
3. Construct engine DTOs
4. Call engine function(s)
5. Persist state changes (character fields, items, events)
6. Increment version
7. Commit

Partial failures roll back completely. The optimistic locking version check prevents concurrent modifications.

### Event Logging Pattern

All state mutations log character_events with:
- `event_type`: semantic meaning (what happened)
- `operations`: JSON array of ops.md operations (mechanical mutations)
- `parent_event_id`: causality chain (e.g., meal_penalty → death)
- `seq`: generated via MAX(seq)+1 within transaction

Create helper: `app/events.py` → `log_character_event(db, character_id, ...)` that handles seq generation.

### Scene Transition Flow

```
/choose → validate → deduct gold? → set pending_choice_id? → transition?
  ↓ (if normal transition)
enter new scene → check death scene → compute phases → run auto phases
  ↓
backpack_loss? → item_loss? → auto-apply gold/meal items → eat phase → combat? → random? → heal? → choices
  ↓
return scene state with phase_results
```
