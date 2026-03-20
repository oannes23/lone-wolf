# Epic 0: Spec Fixes & Pre-Implementation

**Phase**: 0
**Dependencies**: None
**Status**: Not Started

Documentation-only epic. No code. Applies approved but unapplied spec changes from the todo.md review rounds before any implementation begins.

---

## Story 0.1: Apply Approved Spec Bug Fixes

**Status**: Not Started

Apply the 7 approved fixes (todo items A–G) to their respective spec documents.

### Tasks

- [ ] **A.** Fix `POST /characters` response example in api.md — change `total_steps: 3, step_index: 2` to `total_steps: 2, step_index: 0` per resolved 2-step wizard (todo #8)
- [ ] **B.** Fix Laumspur amount in game-engine.md — change `amount: 2` to `amount: 4` (matches seed-data.md and source books)
- [ ] **C.** Remove Gold Crowns from `pending_items` example in api.md — gold is auto-applied per todo #13 and should not appear as a pending item
- [ ] **D.** Fix parser.md Load Phase numbering — step 7 is missing (jumps 6→8), renumber sequentially
- [ ] **E.** Fix parser.md Load Phase step 2 — says `FK → books` for disciplines; should say "era-scoped, no book FK" per todo #9
- [ ] **F.** Fix parser.md Load Phase step 11 — says `FK → books` for combat_results; should say "era-scoped" per todo #29
- [ ] **G.** Rename `character_disciplines.weapon_type` → `weapon_category` in data-model.md to match `weapon_categories.category` and glossary usage

### Acceptance Criteria

- All 7 fixes applied to the correct spec documents
- No contradictions remain between the fixes and surrounding spec text
- todo.md items A–G marked as applied

---

## Story 0.2: Apply Round-3 Decisions to Spec Documents

**Status**: Not Started

Apply ~25 resolved decisions from todo items 50–82 that haven't been written into the spec docs yet. These are design decisions that were resolved during the pre-epic readiness review but not yet reflected in the actual spec files.

### Tasks

- [ ] Add `pending_choice_id` nullable FK column to `characters` table in data-model.md (todo #59)
- [ ] Add `max_total_picks` Integer column to `books` table in data-model.md (todo #70)
- [ ] Remove `max_picks_in_category` from `book_starting_equipment` in data-model.md (todo #70)
- [ ] Add `error_code` string field to error response shape in api.md (todo #66)
- [ ] Add error_code enum table to api.md: `VERSION_MISMATCH`, `PENDING_ITEMS`, `COMBAT_UNRESOLVED`, `WRONG_PHASE`, `CHARACTER_DEAD`, `WIZARD_ACTIVE`, `CHOICE_UNAVAILABLE`, `INVENTORY_FULL`, `OVER_CAPACITY`, `NOT_IN_COMBAT`, `ITEM_NOT_CONSUMABLE`, `PATH_UNAVAILABLE`, `MAX_CHARACTERS`, `INVALID_ROLL_TOKEN`, `RATE_LIMITED` (todo #66)
- [ ] Add JWT payload schemas to api.md auth section (todo #73):
  - Player access: `{sub, username, type: "access", iat, exp}`
  - Player refresh: `{sub, username, type: "refresh", iat, exp}`
  - Admin: `{sub, role: "admin", iat, exp}`
  - Roll: `{sub, cs, end, book_id, iat, exp}`
- [ ] Document password policy (8–128 chars, no complexity requirements) in api.md (todo #71)
- [ ] Document admin token expiry (8h, no refresh) in api.md (todo #72)
- [ ] Update refresh token lifetime from 90 days to 7 days in api.md (todo #74)
- [ ] Add `scene_phase` state diagram to game-engine.md (todo #63) — valid interactive values: `items`, `combat`, `random`, `choices`; automatic phases (`eat`, `heal`, `item_loss`, `backpack_loss`) never stored
- [ ] Add "Death During Phase Progression" section to game-engine.md (todo #52)
- [ ] Add `endurance_max` recalculation invariant section to game-engine.md (todo #61)
- [ ] Update book advance wizard to 4 steps in seed-data.md and api.md: `pick_disciplines` → `pick_equipment` → `inventory_adjust` → `confirm` (todo #56)
- [ ] Add ON DELETE annotations to all FK definitions in data-model.md (todo #80)
- [ ] Add snapshot JSON schemas to data-model.md `character_book_starts` section (todo #76)
- [ ] Add wizard state JSON schemas to data-model.md `character_wizard_progress` section (todo #77)
- [ ] Add "Transaction Boundaries" section to game-engine.md (todo #79)
- [ ] Add "Scene Response Assembly" section to game-engine.md — document GET /scene as read-only (todo #60)
- [ ] Document `game_objects.properties` and `aliases` as NOT NULL with defaults (`{}` and `[]`) in data-model.md (todo #81)
- [ ] Add `apply_special_weapon_effects()` to game-engine.md (todo #50)
- [ ] Add combat-phase restriction to use-item endpoint in api.md (todo #51)
- [ ] Document mixed random + regular choice handling in game-engine.md (todo #55)
- [ ] Add Weaponskill inline selection during book advance discipline step in api.md (todo #57)
- [ ] Add Book 1 only restriction to `POST /characters` in api.md (todo #58)
- [ ] Update `POST /gameplay/{id}/item` to use `scene_item_id` and `POST /gameplay/{id}/inventory` + `/use-item` to use `character_item_id` in api.md (todo #69)

### Acceptance Criteria

- All ~25 resolved decisions applied to their respective spec documents
- Spec documents internally consistent after all changes
- No contradictions between data-model.md, api.md, game-engine.md, and seed-data.md

---

## Story 0.3: Compile Kai CRT Seed Data

**Status**: Not Started

Compile the full 130-row Kai Combat Results Table from Project Aon source material into seed-data.md. Required for combat engine testing and the static seed script.

### Tasks

- [ ] Compile all 13 CR brackets × 10 random numbers = 130 rows
- [ ] Use sentinel values: `combat_ratio_min = -999` for bracket 1 (CR ≤ −11), `combat_ratio_max = 999` for bracket 13 (CR ≥ +11)
- [ ] Use `NULL` for instant kill (`k`) entries in `enemy_loss` and `hero_loss`
- [ ] Verify data against known bracket/roll combinations from source material
- [ ] Add as "Combat Results Table (Kai Era)" section in seed-data.md

### CRT Bracket Ranges

| Bracket | combat_ratio_min | combat_ratio_max |
|---------|-----------------|-----------------|
| 1 | -999 | -11 |
| 2 | -10 | -9 |
| 3 | -8 | -7 |
| 4 | -6 | -5 |
| 5 | -4 | -3 |
| 6 | -2 | -1 |
| 7 | 0 | 0 |
| 8 | 1 | 2 |
| 9 | 3 | 4 |
| 10 | 5 | 6 |
| 11 | 7 | 8 |
| 12 | 9 | 10 |
| 13 | 11 | 999 |

### Acceptance Criteria

- Full 130-row CRT present in seed-data.md
- Sentinel values used for bracket edges
- NULL used for instant kill entries
- Data verified against at least 5 known bracket/roll values from source books
