# Epic 10: Refactoring & Spec Sync

**Phase**: 7
**Dependencies**: Epics 0-9 (all complete)
**Status**: Complete

Service layer restructuring to resolve deferred code quality findings from the Phase 4 review, plus spec document sync to match implementation reality. All changes are internal refactoring (no new features, no behavioral changes). The existing 1434-test suite provides the safety net — all tests must pass unchanged after every story.

**Guiding principle**: This epic restructures internals only. Public API contracts, response shapes, endpoint paths, and database schema are unchanged. The only external artifact changes are spec document updates.

---

## Pre-Implementation Review Summary

Three specialist agents (architect, code-reviewer, tech-writer) validated all 8 original deferred findings against the current codebase on 2026-03-22. Results:

| Original Finding | Confirmed? | Verdict |
|-----------------|-----------|---------|
| 1. `choose` endpoint ~200 lines in router | Yes (207 lines) | Fix — extract to service |
| 2. `gameplay_service.py` god-file | Yes (2130 lines) | Fix — split into 4-5 modules |
| 3. Circular imports via deferred `_build_character_state` | Yes (4 deferred import sites) | Fix — resolved by state_builder extraction |
| 4. DRY violations (endurance_max 3x, death-clearing 4x, DecisionLog 5x, CombatContext 2x) | Yes, all confirmed | Fix — shared helpers |
| 5. N+1 queries in leaderboard service | Yes (2 per-char COUNT loops) | Fix — SQL aggregation |
| 6. Spec field name mismatches | Yes (14 divergences in api.md) | Fix — update spec |
| 7. Missing error codes in api.md | Yes (7 codes) | Fix — update spec |
| 8. Admin CRUD boilerplate (1378 lines) | Yes, but **skip** | Skip — stable, low ROI, abstraction risk |

**New findings from review:**

| New Finding | Source | Verdict |
|-------------|--------|---------|
| 9. UI router duplicates full choose logic (164 lines) | Architect, Code-reviewer | Fix — resolved by Story 10.2 |
| 10. Inconsistent version conflict handling (4 inline try/except vs global handler) | Code-reviewer | Fix — normalize to global handler |
| 11. SceneContext building duplicated in combat_service (62 lines) | Architect | Fix — resolved by Story 10.1 |
| 12. `_build_character_state` is private but imported across 6 module boundaries | Code-reviewer | Fix — promote to public in state_builder |
| 13. Leaderboard username placeholder (`user_42` instead of actual username) | Architect | Fix — use actual username |
| 14. data-model.md combat_rounds unique constraint missing run_number | Tech-writer | Fix — spec sync |
| 15. MASTER.md two stale "90 day" refresh token references | Tech-writer | Fix — spec sync |

---

## Execution Plan

```
Phase 1 (parallel):
  10.1 — Extract state_builder.py (prerequisite for 10.2, 10.3, 10.4)
  10.5 — Spec sync (independent, no code changes)
  10.6 — Normalize version conflict handling (independent)

Phase 2 (after 10.1, parallel):
  10.2 — Extract process_choose to service
  10.3 — Extract shared helpers (DRY fixes)

Phase 3 (after 10.2, 10.3):
  10.4 — Split gameplay_service.py into focused modules

Phase 4 (after 10.4):
  10.7 — Fix leaderboard N+1 queries
```

**Critical path**: 10.1 → 10.2 + 10.3 → 10.4 → 10.7 (4 phases)
**Total Stories**: 7

---

## Story 10.1: Extract State Builder Module

**Status**: Complete
**Agent**: backend-dev
**Dependencies**: None (prerequisite for 10.2, 10.3, 10.4)

### Description

Extract `_build_character_state` and `_build_scene_context` from `gameplay_service.py` into a new `app/services/state_builder.py` module. This breaks the circular import cycle between `gameplay_service` and `combat_service`, and establishes the shared foundation for the subsequent split.

### Tasks

- [ ] Create `app/services/state_builder.py`
- [ ] Move `_build_character_state` (gameplay_service.py lines 113-204) → `build_character_state` (drop underscore — it is a public cross-module function)
- [ ] Move `_build_scene_context` (gameplay_service.py lines 572-669) → `build_scene_context`
- [ ] Update all import sites:
  - `app/services/gameplay_service.py` — internal calls (9+ sites)
  - `app/services/combat_service.py` — 4 deferred imports at lines 140, 227, 397, 602 → top-level imports from state_builder
  - `app/routers/gameplay.py` — line 38 direct import
  - `app/routers/ui/gameplay.py` — line 151 deferred import → top-level import from state_builder
- [ ] Remove all deferred `from app.services.gameplay_service import _build_character_state` patterns
- [ ] Also move `transition_to_scene` deferred import in `combat_service.py:602` — if `transition_to_scene` stays in gameplay_service, this deferred import remains acceptable for now (resolved fully in Story 10.4)
- [ ] Run full test suite — all 1434 tests must pass with zero changes

### Acceptance Criteria

- `app/services/state_builder.py` exists with `build_character_state` and `build_scene_context`
- Zero deferred imports of `_build_character_state` remain in the codebase
- `combat_service.py` imports `build_character_state` at top level (no deferred import)
- All 1434 tests pass unchanged
- No behavioral changes

### Spec Refs

- PROGRESS.md Phase 4 deferred finding #3 (circular imports)

---

## Story 10.2: Extract Choose Logic to Service Layer

**Status**: Complete
**Agent**: backend-dev
**Dependencies**: Story 10.1

### Description

Extract the ~207 lines of business logic from the `choose` endpoint in the API router (and the ~164-line duplicate in the UI router) into a `process_choose` service function. Both routers become thin wrappers — the API returns JSON, the UI redirects.

### Tasks

- [ ] Create `process_choose(db, character, choice_id) -> ChooseResult` in `app/services/gameplay_service.py` (or a new `choose_service.py` if preferred during the 10.4 split)
  - The function handles: pending item check, combat check, scene load, choice availability filtering, gold deduction + event logging, random outcome band assembly, DecisionLog creation, and `transition_to_scene` call
  - Returns a result dataclass/dict with the scene response data, or raises typed exceptions for error cases (PENDING_ITEMS, COMBAT_UNRESOLVED, WRONG_PHASE, CHOICE_UNAVAILABLE, PATH_UNAVAILABLE)
- [ ] Refactor `app/routers/gameplay.py` `choose` endpoint (lines 91-297) to call `process_choose`. Router retains only: auth, version check, and response formatting
- [ ] Refactor `app/routers/ui/gameplay.py` `choose` handler (lines 114-277) to call `process_choose`. UI router retains only: session handling, redirect logic, error flash messages
- [ ] The pending items check in the API router (lines 158-191) currently uses a different detection mechanism than `_count_pending_items` in gameplay_service — consolidate to use the existing helper
- [ ] Ensure the `DecisionLog` creation that was inline in both routers is now inside `process_choose` (eliminates 2 of the 5 duplication sites from Finding 4d)
- [ ] Run full test suite — all tests must pass unchanged

### Acceptance Criteria

- `process_choose` exists as a service function
- API router `choose` endpoint is ≤40 lines (auth + version check + call + response formatting)
- UI router `choose` handler is ≤30 lines (session + call + redirect)
- No `DecisionLog(...)` construction in any router file
- No deferred import of `_build_character_state` in any router file
- All tests pass unchanged
- No behavioral changes to API responses or UI redirects

### Spec Refs

- PROGRESS.md Phase 4 deferred finding #1 (choose endpoint)
- PROGRESS.md Phase 4 deferred finding #4d (DecisionLog DRY)

---

## Story 10.3: Extract Shared Helpers for DRY Violations

**Status**: Complete
**Agent**: backend-dev
**Dependencies**: Story 10.1

### Description

Create shared helper functions to consolidate the four categories of duplicated logic across the service layer.

### Tasks

#### 10.3a: Death state clearing → `mark_character_dead(character)`

- [ ] Create helper (in `app/services/state_builder.py` or a new `app/services/helpers.py`)
- [ ] Sets: `is_alive = False`, `scene_phase = None`, `scene_phase_index = None`, `active_combat_encounter_id = None`, `pending_choice_id = None`
- [ ] Update 4 call sites:
  - `gameplay_service.py:839-842` (death scene)
  - `gameplay_service.py:883-886` (auto-phase death)
  - `combat_service.py:479-482` (combat death)
  - `combat_service.py:652-655` (evasion death)

#### 10.3b: Endurance max recalculation → `recalculate_endurance_max(db, character)`

- [ ] Create helper that: queries remaining character_items, loads game_object properties, builds ItemState list, calls `compute_endurance_max`, sets `character.endurance_max`, clamps `endurance_current` to new max if exceeded
- [ ] Update 3 call sites:
  - `gameplay_service.py:1218` (item accept)
  - `gameplay_service.py:1351` (inventory drop)
  - `gameplay_service.py:1486` (use-item)

#### 10.3c: DecisionLog creation → `log_decision(db, character, ...)`

- [ ] Create helper in `app/events.py` alongside `log_character_event`
- [ ] Signature: `log_decision(db, character, from_scene_id, to_scene_id, choice_id, action_type, details=None)`
- [ ] Update remaining call sites (after Story 10.2 eliminates the router sites):
  - `gameplay_service.py:1705-1715` (choice-triggered random)
  - `gameplay_service.py:2103-2113` (scene-exit random)
  - `lifecycle_service.py:243-254` (restart/replay — already has a local helper `_log_decision_log_entry`, consolidate)

#### 10.3d: CombatContext construction → consolidate

- [ ] Have `_get_combat_state` in gameplay_service call `_build_combat_context` from combat_service instead of duplicating the build
- [ ] This requires the import direction to work (state_builder extraction from 10.1 should make this possible)
- [ ] If import direction is still problematic, move `_build_combat_context` to state_builder.py

- [ ] Run full test suite — all tests must pass unchanged

### Acceptance Criteria

- `mark_character_dead` helper exists and is used at all 4 death sites
- `recalculate_endurance_max` helper exists and is used at all 3 recalc sites
- `log_decision` helper exists in `app/events.py` and is used at all DecisionLog creation sites
- CombatContext construction exists in exactly one location
- Grep for `is_alive = False` in service files returns only `mark_character_dead` (plus lifecycle_service restart which sets `is_alive = True`)
- All tests pass unchanged
- No behavioral changes

### Spec Refs

- PROGRESS.md Phase 4 deferred finding #4 (DRY violations)

---

## Story 10.4: Split gameplay_service.py into Focused Modules

**Status**: Complete
**Agent**: backend-dev
**Dependencies**: Stories 10.1, 10.2, 10.3

### Description

Split the remaining `gameplay_service.py` (which should be significantly smaller after Stories 10.1-10.3) into focused, single-responsibility modules. This is the largest mechanical refactor — it must be done atomically.

### Tasks

- [ ] Create `app/services/scene_service.py`:
  - `get_scene_state` and assembly helpers
  - `_compute_phase_sequence`, `_reconstruct_phase_results`
  - `_build_choices`, `_get_pending_items`, `_get_combat_state` (or its replacement from 10.3d)
- [ ] Create `app/services/transition_service.py`:
  - `transition_to_scene`
  - `_apply_state_changes_to_character`
  - `_log_phase_result`
  - `_auto_apply_gold_meal_items`
  - All automatic phase execution logic
- [ ] Create `app/services/item_service.py`:
  - `process_item_action`
  - `process_inventory_action`
  - `process_use_item`
  - All item/inventory private helpers
- [ ] Create `app/services/roll_service.py`:
  - `process_roll`
  - `_resolve_choice_triggered_random`
  - `_resolve_phase_random`
  - `_handle_scene_redirect`
  - `_advance_random_phase`
  - `_resolve_scene_exit_random`
- [ ] Keep `app/services/gameplay_service.py` as a thin re-export facade if needed for backward compatibility during the transition, or delete it entirely if all import sites are updated
- [ ] Update all import sites across routers, other services, and UI routers
- [ ] Resolve the remaining deferred import of `transition_to_scene` in `combat_service.py:602` — now importable from `transition_service.py` directly
- [ ] Run full test suite — all tests must pass unchanged

### Acceptance Criteria

- `gameplay_service.py` either deleted or reduced to ≤50 lines (re-exports only)
- Four new service modules exist, each ≤600 lines
- Zero deferred imports remain anywhere in the services directory
- All cross-service imports are top-level
- All 1434+ tests pass unchanged
- No behavioral changes

### Spec Refs

- PROGRESS.md Phase 4 deferred finding #2 (god-file)
- PROGRESS.md Phase 4 deferred finding #3 (circular imports — final resolution)

---

## Story 10.5: Spec Sync

**Status**: Complete
**Agent**: tech-writer
**Dependencies**: None (independent, can run in Phase 1)

### Description

Update spec documents to match implementation reality. 18 discrete fixes across 3 spec files, cataloged by tech-writer review on 2026-03-22. No code changes.

### Tasks

#### api.md — Response Example Updates (14 changes)

- [ ] **Combat round response** (POST /gameplay/{id}/combat/round): Replace `round`→`round_number`, `enemy_loss`→`enemy_damage`, `hero_loss`→`hero_damage`, `enemy_endurance_remaining`→`enemy_end_remaining`, `hero_endurance_remaining`→`hero_end_remaining`, `psi_surge_active`→`psi_surge_used`. Remove `enemy_name` from example. Add `result` and `evasion_available` fields
- [ ] **Combat state in scene response** (GET /gameplay/{id}/scene): Replace `evasion_possible`→`evasion_available`, add `can_evade` as separate field. Add `hero_effective_cs` and `combat_ratio`
- [ ] **Inventory request** (POST /gameplay/{id}/inventory): Replace `item_name`→`character_item_id` (int)
- [ ] **Inventory response**: Rewrite to show `{ action, inventory: list[InventoryItemOut], version }` structure
- [ ] **Use-item request** (POST /gameplay/{id}/use-item): Replace `item_name`→`character_item_id` (int)
- [ ] **Use-item response**: Rewrite to show `{ effect_applied, endurance_current, endurance_max, inventory, version }` structure
- [ ] **Character detail response** (GET /characters/{id}): Rewrite — flat `book_title` instead of nested `book` object, unified `items` list with `character_item_id` instead of separate `weapons`/`backpack_items`/`special_items`, rich `disciplines` objects with `weapon_category`
- [ ] **History response** (GET /characters/{id}/history): Replace `from_scene`→`scene_number`, `to_scene`→`target_scene_number`
- [ ] **Events response** (GET /characters/{id}/events): Decide whether `operations` field is exposed — if not, remove from example
- [ ] **Wizard advance step requests**: Replace `discipline_id` (singular)→`discipline_ids` (list), add `version` to all step request examples
- [ ] **Wizard advance init**: Change `total_steps: 4` → `total_steps: 3`, remove `pick_equipment` step from book advance wizard examples
- [ ] **Wizard inventory step response**: Replace `special_items_carrying`→`current_special` (list of item objects), add `max_backpack_items`
- [ ] **Advance endpoint request**: Replace "no body needed" with `{ "version": 5 }` example
- [ ] **Restart/replay responses**: Note that implementation returns full `SceneResponse` shape (not the simplified example currently shown)

#### api.md — Error Code Table (7 additions)

- [ ] Add: `NOT_IN_RANDOM_PHASE` (409), `REDIRECT_DEPTH_EXCEEDED` (409), `ADVANCE_NOT_ALLOWED` (409), `NO_NEXT_BOOK` (404), `CHARACTER_ALIVE` (400), `NOT_AT_VICTORY` (400), `ITEM_MANDATORY` (400)

#### data-model.md (2 changes)

- [ ] **combat_rounds unique constraint**: Add `run_number` to constraint — `(character_id, combat_encounter_id, run_number, round_number)`
- [ ] **scenes.game_object_id**: Mark as NULLABLE with note about parser populating it

#### MASTER.md (2 changes)

- [ ] **Line 149**: Change "90 day refresh" → "7-day refresh"
- [ ] **Line 170**: Change "90-day expiry" → "7-day expiry"

### Acceptance Criteria

- All 18 spec fixes applied
- api.md response examples match the actual Pydantic schema field names in `app/schemas/`
- Error code table includes all error codes grep-able in the router files
- No dead links in any spec document
- No stale resolved-question entries contradict current key decisions
- Zero code changes — spec only

### Spec Refs

- PROGRESS.md Phase 4 deferred findings #6, #7 (spec mismatches, missing error codes)
- Tech-writer review catalog (2026-03-22)

---

## Story 10.6: Normalize Version Conflict Handling

**Status**: Complete
**Agent**: backend-dev
**Dependencies**: None (independent, can run in Phase 1)

### Description

Four gameplay endpoints handle `VersionConflictError` with inline `try/except` blocks, while six others rely on the global exception handler in `main.py`. Both produce the same 409 response shape. Normalize to the global handler everywhere.

### Tasks

- [ ] Remove inline `try/except VersionConflictError` from:
  - `app/routers/gameplay.py` `choose` endpoint (lines 127-137)
  - `app/routers/gameplay.py` `combat_round` endpoint (lines 476-486)
  - `app/routers/gameplay.py` `combat_evade` endpoint (lines 537-548)
  - `app/routers/gameplay.py` `roll` endpoint (lines 786-796)
- [ ] Verify the global handler in `app/main.py` (line 62) produces the same response shape: `{ "error_code": "VERSION_MISMATCH", "detail": "...", "current_version": N }`
- [ ] If there are any differences in response shape between the inline handlers and the global handler, normalize the global handler to be the canonical version
- [ ] Run full test suite — all tests must pass unchanged

### Acceptance Criteria

- Zero `except VersionConflictError` in any router file
- All state-mutating gameplay endpoints return identical 409 shape on version conflict
- Global handler is the single source of truth for version conflict responses
- All tests pass unchanged
- ~28 lines of duplicated error handling removed

### Spec Refs

- Code-reviewer finding #12 (inconsistent version handling)

---

## Story 10.7: Fix Leaderboard N+1 Queries

**Status**: Complete
**Agent**: backend-dev
**Dependencies**: Story 10.4 (or can run independently if preferred — no import overlap)

### Description

Replace per-character COUNT loops and Python-side JSON parsing in `leaderboard_service.py` with SQL-level aggregation. Fix the username placeholder bug.

### Tasks

- [ ] **`_build_fewest_deaths`**: Replace the per-character `COUNT(DecisionLog)` loop with a single `GROUP BY character_id` query
- [ ] **`_build_fewest_decisions`**: Same as above — these two functions have near-identical bodies and can potentially be merged into a shared helper with a sort-key parameter
- [ ] **`_build_highest_endurance`**: Replace `f"user_{char.user_id}"` placeholder with actual username lookup (use the same batch-load pattern as the other leaderboard functions)
- [ ] **`_build_item_usage`**: Document current Python-side JSON grouping as a known limitation for SQLite (which lacks native JSON functions). Acceptable for MVP data volumes. Add a code comment noting that PostgreSQL migration would allow `jsonb_extract_path` aggregation
- [ ] Add test coverage for leaderboard correctness with >1 completed character to catch regressions

### Acceptance Criteria

- `_build_fewest_deaths` and `_build_fewest_decisions` use SQL `GROUP BY` aggregation, not Python loops with per-row queries
- `_build_highest_endurance` shows actual usernames, not `user_N` placeholders
- `_build_item_usage` has a code comment documenting the SQLite limitation
- All existing leaderboard tests pass unchanged
- At least one new test verifies correct ordering with multiple completed characters

### Spec Refs

- PROGRESS.md Phase 4 deferred finding #5 (N+1 queries)

---

## What Is NOT In This Epic

The following were evaluated and deliberately excluded:

### Admin CRUD Boilerplate (Original Finding #8)

**Reason**: All three reviewers agreed this is low priority. The 1378 lines of admin CRUD in `app/routers/admin/content.py` are verbose but stable, individually testable, and simple to understand. A generic CRUD factory would save lines but introduce indirection, make debugging harder, and create a "framework within the framework." Skip unless the resource type count grows significantly.

### Parser Files (load.py, transform.py, extract.py, pipeline.py)

**Reason**: Parser files are 500-700 lines each but are ETL code with warranted complexity. They are not on the critical runtime path and are not actively modified.

### wizard_service.py (1182 lines)

**Reason**: Complex wizard state machine with warranted complexity. Well-structured internally with clear step dispatch.

### Post-MVP Features (todo items 42-49)

**Reason**: These are feature additions (Grand Master disciplines, SVG diagrams, fog-of-war, run comparison API), not refactoring. They belong in a separate epic when the team is ready to expand beyond Kai era.

---

## Risk Assessment

- **Test safety**: 1434 existing tests provide strong regression coverage. All refactoring stories are internal restructuring with zero behavioral changes.
- **Atomic commits**: Each story should be committable independently. Stories 10.1-10.3 can each be merged without requiring the others to be complete.
- **Story 10.4 is the riskiest**: It touches the most files and has the most import-site updates. Should be done last, after helpers are extracted and the file is smaller.
- **Spec sync (10.5) is zero-risk**: Documentation-only changes. Can be merged at any time.

---

## Success Metrics

After this epic:

- No file in `app/services/` exceeds 600 lines
- Zero deferred imports in the services directory
- Zero duplicated business logic between API and UI routers
- Every DRY violation identified in Phase 4 review is resolved
- api.md examples match implementation schema field names exactly
- api.md error table is complete (all error codes documented)
