# Epic 4: Character Creation & Wizard System

**Phase**: 3
**Dependencies**: Epics 1, 3
**Status**: Not Started

Character creation flow (roll → create → equip) and book advance wizard. Uses the generic wizard infrastructure from the database (wizard_templates) and pure engine logic for validation.

---

## Story 4.1: Stat Rolling & Roll Token

**Status**: Not Started

### Description

Stateless stat rolling endpoint that returns a signed JWT encoding the rolled values.

### Tasks

- [ ] Create `POST /characters/roll` endpoint in `app/routers/characters.py`:
  - Request: `{book_id: int}`
  - Validate book exists and is Book 1 (MVP restriction)
  - Generate: CS = 10 + random(0,9), END = 20 + random(0,9) for Kai era
  - Create roll_token JWT (1h expiry) encoding: `{sub: user_id, cs, end, book_id, iat, exp}`
  - Response 200: `{roll_token, combat_skill_base, endurance_base, era, formula: {cs, end}}`
- [ ] Endpoint is stateless — no DB writes, can be called repeatedly
- [ ] Requires player auth

### Acceptance Criteria

- Integration test: roll returns valid CS range (10–19) and END range (20–29) for Kai era
- Integration test: roll_token decodes correctly with expected claims
- Integration test: expired roll_token (mock time) rejected at character creation
- Integration test: invalid book_id returns 404
- Integration test: non-Book-1 book_id returns 400 (MVP restriction)

---

## Story 4.2: Character Creation Service

**Status**: Not Started

### Description

Create a character from a roll token, with disciplines selected and the equipment wizard auto-started.

### Tasks

- [ ] Create `POST /characters` endpoint:
  - Request: `{name, book_id, roll_token, discipline_ids: [int], weapon_skill_type: str | None}`
  - Validations:
    - Roll token valid, not expired, book_id matches
    - book_id must be Book 1 (MVP)
    - User has not reached max_characters (only count non-deleted characters)
    - Exactly 5 Kai disciplines selected
    - All discipline_ids valid and belong to Kai era
    - weapon_skill_type required if Weaponskill discipline chosen, must be valid category
    - weapon_skill_type must be null/absent if Weaponskill not chosen
  - Create character with:
    - Stats from roll token
    - endurance_max = endurance_base (recalculated after equipment)
    - endurance_current = endurance_base
    - gold = 0, meals = 0 (applied during equipment wizard)
    - is_alive = true, version = 1, current_run = 1
  - Create character_disciplines rows
  - Auto-start equipment wizard:
    - Find character_creation wizard template
    - Create character_wizard_progress row (step_index = 0)
    - Set character.active_wizard_id
  - Response 201 with character details + active_wizard info
- [ ] Create `app/services/character_service.py` for business logic
- [ ] Create `app/schemas/characters.py` for request/response models

### Acceptance Criteria

- Integration test: valid creation flow (roll → create) succeeds
- Integration test: expired roll_token returns 400 with INVALID_ROLL_TOKEN error_code
- Integration test: max_characters limit enforced (deleted characters don't count)
- Integration test: wrong discipline count (4 or 6) returns 400
- Integration test: missing weapon_skill_type with Weaponskill selected returns 400
- Integration test: character created with active wizard (active_wizard_id set)

---

## Story 4.3: Equipment Wizard (Character Creation)

**Status**: Not Started

### Description

Equipment selection step for new characters. Auto-applies gold and meals, lets player pick from available equipment.

### Tasks

- [ ] Implement `GET /characters/{id}/wizard` for equipment step:
  - Response includes:
    - `wizard_type: "character_creation"`
    - `step: "equipment"`, `step_index: 0`, `total_steps: 2`
    - `included_items`: fixed items auto-granted (e.g., Axe, Map of Sommerlund for Book 1)
    - `auto_applied`: `{gold: N, gold_formula: "random 0-9", meals: M}` — server-rolled gold shown for transparency
    - `available_equipment`: chooseable items from book_starting_equipment (non-default, non-gold, non-meal)
    - `pick_limit`: from books.max_total_picks
- [ ] Implement `POST /characters/{id}/wizard` for equipment step:
  - Request: `{selected_items: [str]}` (item names from available list)
  - Validate: number of selections ≤ pick_limit
  - Apply:
    - Add fixed items to character_items
    - Add selected items to character_items
    - Apply auto-rolled gold (random 0-9 for Book 1)
    - Apply fixed meals (1 for Book 1)
    - Recalculate endurance_max if armor picked (Chainmail +4, Helmet +2)
    - Equip first weapon automatically
  - Advance wizard to confirm step (step_index = 1)
  - Allow re-pick: re-submitting replaces previous selections
- [ ] Implement confirm step:
  - `POST /characters/{id}/wizard` with `{confirm: true}`
  - Finalize: save character_book_starts snapshot, place character at book's start_scene
  - Clear active_wizard_id, mark wizard progress completed
  - Response includes full character state with correct stats

### Acceptance Criteria

- Integration test: full wizard flow (GET → POST equipment → POST confirm)
- Integration test: re-pick before confirm (submit different selections)
- Integration test: stat recalculation when armor picked (Chainmail gives +4 endurance_max)
- Integration test: character_book_starts snapshot created on confirm
- Integration test: character placed at start scene after confirm
- Integration test: active_wizard_id cleared after confirm
- Integration test: pick_limit enforced (too many items returns 400)

---

## Story 4.4: Book Advance Wizard

**Status**: Not Started

### Description

4-step wizard for advancing to the next book after reaching a victory scene.

### Tasks

- [ ] Implement `POST /gameplay/{id}/advance` endpoint:
  - Validates: character at victory scene, no active wizard, no replay started
  - Looks up book_transition_rules for current_book → next_book
  - Returns 404 if no next book
  - Creates wizard_progress with book_advance template (4 steps)
  - Sets active_wizard_id
  - Response 201 with first step info
- [ ] Implement 4-step wizard flow via `GET/POST /characters/{id}/wizard`:
  - **Step 0 — pick_disciplines**: select new discipline(s) per transition rules
    - Show only disciplines not yet learned
    - If Weaponskill selected, require weapon_type inline
    - disciplines_to_pick from book_transition_rules.new_disciplines_count
  - **Step 1 — pick_equipment**: select from new book's starting equipment
    - Same pattern as character creation equipment step
    - Auto-apply new book's fixed items and gold roll
  - **Step 2 — inventory_adjust**: drop items to fit transition rules
    - Show current inventory with max_weapons, max_backpack limits from transition rules
    - Player drops items until within limits
  - **Step 3 — confirm**: finalize all changes
    - Apply new disciplines, equipment, inventory adjustments
    - Save new character_book_starts snapshot
    - Place at new book's start_scene
    - Recalculate endurance_max
    - Clear active_wizard_id
- [ ] Create `app/services/wizard_service.py` for wizard orchestration
- [ ] Create `app/engine/wizard.py` for pure validation logic

### Acceptance Criteria

- Integration test: full 4-step advance flow (disciplines → equipment → inventory → confirm)
- Integration test: replay blocked after advance wizard started (409)
- Integration test: advance blocked if not at victory scene (400)
- Integration test: advance blocked if wizard already active (409)
- Integration test: advance returns 404 if no next book
- Integration test: carry-over rules applied correctly (items, gold, disciplines)
- Integration test: Weaponskill selection during discipline step
- Integration test: endurance_max recalculated after advance

---

## Story 4.5: Wizard API Endpoints

**Status**: Not Started

### Description

Single canonical API path for both wizard types, with step dispatch.

### Tasks

- [ ] Implement unified wizard endpoints in `app/routers/characters.py`:
  - `GET /characters/{id}/wizard`:
    - Returns 404 when no active wizard (active_wizard_id is null)
    - Dispatches to correct step renderer based on wizard type + current step
  - `POST /characters/{id}/wizard`:
    - Dispatches to correct step handler based on wizard type + current step
    - Step types: pick_disciplines, pick_equipment, inventory_adjust, confirm
    - Each handler validates input, applies changes, advances step
    - Final step (confirm) completes wizard
- [ ] Wizard step dispatch mapping:
  ```
  step_type → handler function
  pick_disciplines → handle_discipline_selection
  pick_equipment → handle_equipment_selection
  inventory_adjust → handle_inventory_adjustment
  confirm → handle_confirmation
  ```

### Acceptance Criteria

- Both creation and advance wizards work through the same endpoints
- 404 returned when no wizard is active
- Correct step handler invoked based on current step_type
- Step progression works correctly (step_index increments)
- Cannot skip steps or go backwards

---

## Implementation Notes

### Wizard State Management

The `character_wizard_progress.state` JSON column accumulates selections across steps:

**Character Creation State**:
```json
{
  "gold": 7,
  "meals": 1,
  "selected_items": [
    {"item_name": "Sword", "item_type": "weapon", "game_object_id": null}
  ]
}
```

**Book Advance State**:
```json
{
  "new_disciplines": [11],
  "weapon_type": "Sword",
  "selected_equipment": [
    {"item_name": "Shield", "item_type": "special"}
  ],
  "kept_weapons": ["Sword", "Axe"],
  "kept_backpack": ["Healing Potion"],
  "gold_rolled": 15
}
```

### Snapshot Format

`character_book_starts.items_json`:
```json
[
  {"item_name": "Axe", "item_type": "weapon", "is_equipped": true, "game_object_id": null},
  {"item_name": "Map of Sommerlund", "item_type": "special", "is_equipped": false, "game_object_id": null}
]
```

`character_book_starts.disciplines_json`:
```json
[
  {"discipline_id": 1, "weapon_type": null},
  {"discipline_id": 6, "weapon_type": "Sword"}
]
```
