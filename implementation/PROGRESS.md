# Implementation Progress

Overall tracker for the Lone Wolf CYOA project. Updated as epics and stories are completed.

## Epic Overview

| Epic | Name | Stories | Status | Phase | Dependencies |
|------|------|---------|--------|-------|-------------|
| 0 | [Spec Fixes & Pre-Implementation](epic-0-spec-fixes.md) | 3 | Complete | 0 | None |
| 1 | [Project Foundation & Database](epic-1-foundation.md) | 8 | Complete | 1 | Epic 0 |
| 2 | [Authentication & User Management](epic-2-auth.md) | 5 | Complete | 2 | Epic 1 |
| 3 | [Game Engine (Pure Functions)](epic-3-engine.md) | 7 | Complete | 2 | Epic 1 |
| 4 | [Character Creation & Wizard System](epic-4-wizard.md) | 5 | Complete | 3 | Epics 1, 3 |
| 5 | [Parser Pipeline](epic-5-parser.md) | 6 | Complete | 2-3 | Epic 1 |
| 6 | [Core Gameplay API](epic-6-gameplay-api.md) | 7 | Complete | 4 | Epics 2, 3, 4 |
| 7 | [Content Browse, Social & Admin API](epic-7-content-api.md) | 5 | Complete | 4 | Epics 1, 2 |
| 8 | [Player UI (HTMX + Pico CSS)](epic-8-player-ui.md) | 6 | Complete | 5 | Epics 6, 7 |
| 9 | [Admin UI (HTMX + Pico CSS)](epic-9-admin-ui.md) | 4 | Complete | 6 | Epics 7, 8 |

## Dependency Graph

```
Phase 0:  [E0 Spec Fixes]
               |
Phase 1:  [E1 Foundation + DB]
            /     |        \
Phase 2:  [E2 Auth] [E3 Engine] [E5 Parser]
            \       |          (parallel, off critical path)
Phase 3:    [E4 Wizard+Chars]
              \      |
Phase 4:  [E6 Gameplay API] [E7 Content+Admin API]
                  \         /    (parallel)
Phase 5:      [E8 Player UI]
                    |
Phase 6:      [E9 Admin UI]
```

**Critical path**: E0 → E1 → E3 → E4 → E6 → E8 → E9

**Key parallelization**: E2+E3+E5 all run concurrently after E1. E6+E7 run concurrently after E2+E3+E4.

## Story Status Key

- **Not Started** — No work begun
- **In Progress** — Active development
- **Complete** — Code written, tests passing, AC met
- **Blocked** — Waiting on dependency or decision

## Story Progress

### Epic 0: Spec Fixes & Pre-Implementation
| Story | Name | Status |
|-------|------|--------|
| 0.1 | Apply Approved Spec Bug Fixes | Complete |
| 0.2 | Apply Round-3 Decisions to Spec Documents | Complete |
| 0.3 | Compile Kai CRT Seed Data | Complete |

### Epic 1: Project Foundation & Database
| Story | Name | Status |
|-------|------|--------|
| 1.1 | Project Scaffolding | Complete |
| 1.2 | Config & Database Setup | Complete |
| 1.3 | Content Table Models & Migration | Complete |
| 1.4 | Taxonomy Table Models & Migration | Complete |
| 1.5 | Player Table Models & Migration | Complete |
| 1.6 | Wizard & Admin Table Models & Migration | Complete |
| 1.7 | Static Seed Data Script | Complete |
| 1.8 | Test Infrastructure | Complete |

### Epic 2: Authentication & User Management
| Story | Name | Status |
|-------|------|--------|
| 2.1 | Auth Service & JWT Utilities | Complete |
| 2.2 | Auth API Endpoints | Complete |
| 2.3 | Auth Middleware & Dependencies | Complete |
| 2.4 | Admin Auth & CLI | Complete |
| 2.5 | User Management Admin Endpoints | Complete |

### Epic 3: Game Engine (Pure Functions)
| Story | Name | Status |
|-------|------|--------|
| 3.1 | Engine DTOs & Meter Semantics | Complete |
| 3.2 | Combat Resolution | Complete |
| 3.3 | Choice Filtering & Conditions | Complete |
| 3.4 | Phase Sequence & Progression | Complete |
| 3.5 | Inventory Management | Complete |
| 3.6 | Random Mechanics | Complete |
| 3.7 | Death, Restart, Replay | Complete |

### Epic 4: Character Creation & Wizard System
| Story | Name | Status |
|-------|------|--------|
| 4.1 | Stat Rolling & Roll Token | Complete |
| 4.2 | Character Creation Service | Complete |
| 4.3 | Equipment Wizard (Character Creation) | Complete |
| 4.4 | Book Advance Wizard | Complete |
| 4.5 | Wizard API Endpoints | Complete |

### Epic 5: Parser Pipeline
| Story | Name | Status |
|-------|------|--------|
| 5.1 | Parser Extract Phase | Complete |
| 5.2 | Parser Transform Phase | Complete |
| 5.3 | LLM Enrichment — Choice Rewriting | Complete |
| 5.4 | LLM Enrichment — Entity Extraction | Complete |
| 5.5 | Parser Load Phase | Complete |
| 5.6 | Parser CLI & Integration | Complete |

### Epic 6: Core Gameplay API
| Story | Name | Status |
|-------|------|--------|
| 6.1 | Scene Endpoint | Complete |
| 6.2 | Choose & Scene Transition | Complete |
| 6.3 | Combat Endpoints | Complete |
| 6.4 | Item & Inventory Endpoints | Complete |
| 6.5 | Roll Endpoint | Complete |
| 6.6 | Restart, Replay & Advance Endpoints | Complete |
| 6.7 | Character CRUD & History | Complete |

### Epic 7: Content Browse, Social & Admin API
| Story | Name | Status |
|-------|------|--------|
| 7.1 | Books API | Complete |
| 7.2 | Game Objects API | Complete |
| 7.3 | Leaderboards API | Complete |
| 7.4 | Reports API | Complete |
| 7.5 | Admin Content CRUD & Report Queue | Complete |

### Epic 8: Player UI (HTMX + Pico CSS)
| Story | Name | Status |
|-------|------|--------|
| 8.1 | UI Scaffolding & Auth Pages | Complete |
| 8.2 | Character Creation UI | Complete |
| 8.3 | Scene & Choices UI | Complete |
| 8.4 | Combat & Random UI | Complete |
| 8.5 | Items & Inventory UI | Complete |
| 8.6 | Character Sheet, History & Browse | Complete |

### Epic 9: Admin UI (HTMX + Pico CSS)
| Story | Name | Status |
|-------|------|--------|
| 9.1 | Admin Scaffolding & Auth | Complete |
| 9.2 | Content Management Pages | Complete |
| 9.3 | Report Triage UI | Complete |
| 9.4 | User & Character Management | Complete |

## Deviations & Notes

### Phase 2 Completion (2026-03-20)

Epics 2, 3, and 5 all completed in parallel as planned. All Phase 2 deliverables verified by file presence and test coverage:

- **Epic 2** — `app/services/auth_service.py`, `app/routers/auth.py`, `app/schemas/auth.py`, `app/dependencies.py`, `app/limiter.py`, `app/routers/admin/auth.py`, `app/routers/admin/users.py`, `scripts/create_admin.py`. Integration tests cover all endpoints and error paths.
- **Epic 3** — `app/engine/types.py`, `app/engine/meters.py`, `app/engine/combat.py`, `app/engine/conditions.py`, `app/engine/phases.py`, `app/engine/inventory.py`, `app/engine/random.py`, `app/engine/lifecycle.py`. Story 3.7 landed in `lifecycle.py` (not `phases.py` as originally suggested in the epic spec — acceptable deviation). Full unit test coverage for all eight modules.
- **Epic 5** — `app/parser/extract.py`, `app/parser/transform.py`, `app/parser/llm.py`, `app/parser/load.py`, `app/parser/pipeline.py`, `scripts/seed_db.py`. Includes `app/parser/types.py` as a separate module for parser-internal dataclasses (code-ahead addition, not noted in the epic spec).

**Next phase unlocked**: Epic 4 (Character Creation & Wizard System) may now begin. Epics 6 and 7 remain blocked on Epic 4 completion.

**Test count**: 771 tests passing (all unit + integration).

### Phase 2 Review Findings (addressed)
- **`get_db()` commit/rollback** — Session lifecycle was missing commit; added commit-on-success, rollback-on-exception pattern.
- **`combat_bonus_vs_special` CS replacement** — Was incorrectly applied as post-CRT damage delta; moved to `_get_weapon_cs_bonus` in `effective_combat_skill` for correct CRT bracket lookup.
- **Psi-surge timing** — END cost was deducted before CRT; moved to add to `hero_loss` after CRT resolution per spec.
- **Weaponskill discipline check** — Was missing `"Weaponskill" in state.disciplines` guard; added.
- **Psi-surge discipline check** — Was not verifying `"Psi-surge" in state.disciplines`; added.
- **Consumable effect lookup** — Was reading `properties["endurance_restore"]` directly; updated to support both `{effect, amount}` format (per spec) and legacy direct key format.
- **`verify_version` 409 response** — Was missing `error_code: "VERSION_MISMATCH"` in body; added structured error response.
- **Auth error messages** — Were leaking JWT internals; sanitized to generic messages.
- **MASTER.md refresh token** — Was incorrectly showing "90 days"; corrected to "7 days".
- **`compute_endurance_max` signature** — Added `disciplines` parameter to match spec (no-op for Kai era, ready for Magnakai lore-circle bonuses).
- **`phase_sequence_override` type** — Changed from `list[str]` to `list[dict]` per spec.
- **CharacterState** — Added `era`, `current_scene_id`, `scene_phase`, `scene_phase_index`, `active_combat_encounter_id` fields for downstream stories.
- **`damage_multiplier`** — Changed from hardcoded "undead" check to generic `special_vs` matching.

### Phase 3 Completion (2026-03-20)

Epic 4 completed. All 5 stories implemented with multi-reviewer gates after each story (code-reviewer, qa-engineer, tech-writer, game-designer, architect).

- **Epic 4** — `app/routers/characters.py` (roll, create, wizard endpoints), `app/routers/gameplay.py` (advance endpoint), `app/services/character_service.py`, `app/services/wizard_service.py`, `app/schemas/characters.py`. Full character lifecycle: roll → create → equipment wizard → play → victory → book advance wizard.

**Files created**: `app/routers/characters.py`, `app/routers/gameplay.py`, `app/services/character_service.py`, `app/services/wizard_service.py`

**Files modified**: `app/schemas/characters.py`, `app/main.py`, `app/models/player.py` (CharacterDiscipline.discipline relationship), `app/dependencies.py` (existing, used by new endpoints)

**Test count**: 844 tests passing (61 new Epic 4 integration tests).

**Next phase unlocked**: Epics 6 (Core Gameplay API) and 7 (Content Browse, Social & Admin API) may now begin in parallel.

### Phase 3 Review Findings (addressed)
- **Flat error_code format** — Error responses initially nested error_code inside detail dict; refactored to flat top-level format matching version conflict handler convention.
- **weapon_skill_type without Weaponskill** — Initially rejected with 400; changed to silently ignore per spec ("it is ignored").
- **Weapon category casing** — Test fixtures used lowercase categories ("sword"); production seed uses title-case ("Sword"). Fixed all test fixtures to match production.
- **Discipline name "Mind Blast" vs "Mindblast"** — Test fixture used incorrect name with space; corrected to match production seed.
- **disciplines_json snapshot key** — Used "weapon_type" instead of "weapon_category" per data-model spec; corrected.
- **endurance_current at wizard completion** — New characters with armor bonuses started below full health; fixed to set endurance_current = endurance_max for character creation (not book advance).
- **Duplicate discipline IDs** — Added explicit check with clear error message (was caught incidentally by DB query returning fewer rows).
- **Weapon category validation in advance** — Was missing in handle_discipline_step; added to match character_service pattern.
- **Version required on /advance** — POST /gameplay/{id}/advance was missing version requirement per spec todo #68; added AdvanceRequest schema with verify_version.
- **int(raw_version) error handling** — Added try/except for malformed version in post_wizard to prevent 500.

### Phase 4 Completion (2026-03-21)

Epics 6 and 7 completed in parallel as planned. All 12 stories implemented with 5-agent review (code-reviewer, qa-engineer, tech-writer, game-designer, architect).

- **Epic 6** — `app/services/gameplay_service.py` (scene assembly, choose, roll, items), `app/services/combat_service.py` (round resolution, evasion), `app/services/lifecycle_service.py` (restart, replay), `app/events.py` (event logging helper), `app/schemas/gameplay.py`. Router additions to `app/routers/gameplay.py` (11 endpoints) and `app/routers/characters.py` (6 CRUD/history endpoints).
- **Epic 7** — `app/routers/books.py`, `app/routers/game_objects.py`, `app/routers/leaderboards.py`, `app/routers/reports.py`, `app/routers/admin/content.py` (14 resource types), `app/routers/admin/reports.py`, `app/services/leaderboard_service.py`. Schemas: `books.py`, `game_objects.py`, `leaderboards.py`, `reports.py`, `admin.py` (47 schema classes).

**Files created**: 20 new files (6 routers, 4 services, 6 schemas, 1 helper, 12 test files)

**Files modified**: `app/main.py` (router registration), `app/routers/characters.py`, `app/routers/gameplay.py`, `app/schemas/characters.py`, `app/schemas/admin.py`

**Test count**: 1163 tests passing (319 new Phase 4 integration tests).

**Next phase unlocked**: Epic 8 (Player UI) may now begin.

### Phase 4 Review Findings (addressed)
- **Test isolation (`db.commit()` → `db.flush()`)** — New test files from the initial implementation session used `db.commit()` instead of `db.flush()`, breaking conftest's savepoint-based isolation. Caused 65 cascading failures in the full suite. Fixed across 5 test files (88 replacements total).
- **Admin report stats test isolation** — `TestAdminReportStats` used absolute count assertions against global aggregate queries. Refactored to baseline-relative assertions.
- **Error code `COMBAT_PHASE` → `WRONG_PHASE`** — use-item during combat returned undocumented `COMBAT_PHASE` error code; spec requires `WRONG_PHASE`. Fixed in service, router, and tests.
- **Missing advance happy-path test** — Story 6.6 AC required a test proving `/advance` starts a wizard at a victory scene. Added.
- **`db.commit()` in reports router** — `create_report` called `db.commit()` directly, breaking the session middleware pattern. Changed to `db.flush()`.

### Phase 4 Review Findings (deferred — future improvements)
- **`choose` endpoint business logic** — ~200 lines of business logic in the router should be extracted to a `process_choose()` service function.
- **`gameplay_service.py` god-file** — 2130 lines covering 5+ concerns. Natural split: scene_service, transition_service, item_service, roll_service, state_builder.
- **Circular imports** — `combat_service` and `lifecycle_service` import private `_build_character_state` from `gameplay_service` via deferred imports. Should be extracted to shared module.
- **DRY violations** — Endurance_max recalculation (4x), combat context building (2x), death state clearing (5x), DecisionLog creation (4x) — all candidates for shared helpers.
- **N+1 queries in leaderboard service** — Loads all completed characters into memory then loops. Should use SQL-level aggregation.
- **Spec mismatches** — Several api.md examples use different field names than the implementation (combat round fields, `evasion_possible` vs `evasion_available`, `item_name` vs `character_item_id`). Implementation is generally richer/better; spec examples need updating.
- **Missing error codes in spec** — `NOT_IN_RANDOM_PHASE`, `REDIRECT_DEPTH_EXCEEDED`, `ADVANCE_NOT_ALLOWED`, `NO_NEXT_BOOK`, `CHARACTER_ALIVE`, `NOT_AT_VICTORY`, `ITEM_MANDATORY` all used in code but absent from api.md error table.
- **Admin CRUD boilerplate** — 1700 lines for 14 resource types following identical pattern. A generic CRUD factory would reduce to ~200 lines.

### Phase 5 Completion (2026-03-22)

Epic 8 complete. All 6 stories implemented. Final tech writer review passed.

- **Epic 8 Story 8.4** (Combat & Random UI) — Implemented inside `templates/gameplay/scene.html` rather than as separate template files. Combat section includes enemy/hero endurance bars (`<progress>`), Fight button, Psi-surge toggle (conditional on discipline), round counter, evasion button (conditional on `can_evade`), and evasion-hint text. Random roll section handles all three roll types (choice-triggered, phase-based, scene-level exit). All Story 8.4 AC met.

- **Epic 8 Story 8.5** (Items & Inventory UI) — Implemented inside `templates/gameplay/scene.html`. Pending items panel shows per-item accept/decline buttons; mandatory items show accept only with "Required" badge. Inventory drawer (`<details>`) is always visible with weapons (equip/unequip/drop), backpack items (drop), special items (display-only), slot counters, gold and meals meters. All Story 8.5 AC met.

**Spec deviation**: Stories 8.4 and 8.5 were specified as separate template files (`combat.html`, `random.html`, `items.html`, `inventory.html`). Implementation merges all into `scene.html` using conditional blocks and a persistent inventory drawer. This is a better architectural choice — it avoids redirect chains between phase templates and keeps the full game state visible at all times. All behavioral AC is satisfied.

**Bugs resolved from Phase 2 review** (all four fixed):
1. Dead link in `sheet.html` — corrected to `/ui/game/{id}`.
2. `scene_id_int` context gap — fixed; bug report form reads `character.current_scene_id` directly.
3. Advance wizard sub-routes — resolved by unified `POST /ui/characters/{id}/wizard` with `step` dispatch.
4. Missing `/ui/game/{id}/advance` route — implemented in `app/routers/ui/gameplay.py`.

**Next phase unlocked**: Epic 9 (Admin UI) may now begin.

---

### Phase 5 Progress (2026-03-22)

Epic 8 Stories 8.2, 8.3, and 8.6 implemented. Three additional routers added and all spec-required templates delivered.

- **Epic 8 Story 8.2** — `app/routers/ui/characters.py` (roll, create, wizard routes), `templates/characters/roll.html`, `templates/characters/partials/stats_display.html`, `templates/characters/create.html`, `templates/characters/wizard_equipment.html`, `templates/characters/wizard_confirm.html`.
- **Epic 8 Story 8.3** — `app/routers/ui/gameplay.py` (scene, choose, restart, replay, report routes), `templates/gameplay/scene.html`.
- **Epic 8 Story 8.6** — Character sheet and history routes added to `app/routers/ui/characters.py`. `app/routers/ui/browse.py` (books, game objects, leaderboards routes). Templates: `templates/characters/sheet.html`, `templates/characters/history.html`, `templates/characters/history_rows.html`, `templates/characters/wizard_disciplines.html`, `templates/characters/wizard_inventory.html`, `templates/characters/wizard_advance_confirm.html`, `templates/books/list.html`, `templates/books/detail.html`, `templates/game_objects/list.html`, `templates/game_objects/_results.html`, `templates/game_objects/detail.html`, `templates/leaderboards/index.html`, `templates/leaderboards/_content.html`.

**Tech writer review findings (2026-03-22)** — Four bugs identified that must be resolved before Story AC is fully satisfied. See `implementation/epic-8-player-ui.md` Tech Writer Notes for details:

1. Dead link in `sheet.html`: `/ui/characters/{id}/play` does not exist; should be `/ui/game/{id}`.
2. `scene_id_int` not in template context in `scene.html` — bug reports always record `scene_id = 0`.
3. Advance wizard sub-routes (`/wizard/disciplines`, `/wizard/inventory`, `/wizard/confirm`) not registered in characters router.
4. `POST /ui/game/{character_id}/advance` not implemented in gameplay router — "Advance to Next Book" button will 404.

---

### Phase 6 Completion (2026-03-22)

Epic 9 complete. All 4 stories implemented with 5-agent review gates (code-reviewer, qa-engineer, tech-writer, game-designer, architect). Architect reviewed at key moments (Stories 9.1, 9.2, and final Epic).

- **Epic 9 Story 9.1** — `app/routers/ui/admin.py` (login, logout, dashboard routes), `templates/layout/admin.html`, `templates/admin/login.html`, `templates/admin/dashboard.html`. Separate `admin_session` cookie with `AdminLoginRequired` exception handler and redirect to `/admin/ui/login`. Admin layout uses purple accent via `.admin-layout` CSS override to distinguish from player UI.
- **Epic 9 Story 9.2** — `app/routers/ui/admin_content.py` (full CRUD for 14 resource types), `templates/admin/content/index.html`, `list.html`, `detail.html`, `scene_edit.html`. Data-driven `RESOURCE_CONFIG` dict. Scene detail loads linked choices, combat encounters, and scene items in `<details>` expandables. Wizard templates are read-only (405). Source badge on edit/list views.
- **Epic 9 Story 9.3** — `app/routers/ui/admin_reports.py` (list, detail, triage, stats routes), `templates/admin/reports/list.html`, `detail.html`, `stats.html`. Status and tag filter, color-coded status badges, linked scene snippet, `resolved_by` auto-set on terminal statuses.
- **Epic 9 Story 9.4** — `app/routers/ui/admin_users.py` (users, characters, events, restore routes), `templates/admin/users/list.html`, `_max_chars_cell.html`, `templates/admin/characters/list.html`, `_row.html`, `templates/admin/events/list.html`. HTMX inline `max_characters` edit. HTMX soft-delete restore.

**All 4 routers registered** in `app/main.py` under `prefix="/admin/ui"`.

**Shared utility extracted**: `app/utils/json_fields.py` — `parse_json_list`, `parse_json_dict`, `parse_json_dict_or_none`. Deduplicated `_parse_tags` from 4 files across the codebase.

**Test count**: 1434 tests passing (108 new Epic 9 integration tests).

**Cross-navigation**: Users → Characters (username links), Characters → Events (ID links).

**Tech Writer Review Notes (2026-03-22)**:

1. `admin/login.html` does not use `{% block admin_title %}` — it extends `base.html` directly (intentional: the login page must not show the admin nav). The `{% block title %}Admin Login{% endblock %}` it uses is correct.
2. Dashboard "Total Characters" quick link goes to `/admin/ui/users` (not `/admin/ui/characters`). Minor UX issue — clicking "View characters" from the dashboard lands on the users list rather than the characters list. No dead link, but the label is misleading.
3. The `_row.html` character partial renders `<td>` cells without a wrapping `<tr>`. The HTMX restore endpoint targets `#char-row-{id}` with `hx-swap="innerHTML"`. This replaces the `<tr>` contents with bare `<td>` cells, which is valid HTML and the intended pattern.
4. `admin/content/detail.html` uses `--pico-del-color` for the delete button border. This CSS variable is not defined in `app.css` but is provided by Pico CSS. Acceptable dependency.
5. No dead links found across all templates. All nav links, breadcrumbs, cross-links, and action URLs verified against registered routes.
6. All CSS classes used in admin templates (`admin-layout`, `admin-nav`, `admin-dashboard-grid`, `admin-card`, `admin-card-title`, `admin-card-value`, `admin-card-value-warn`, `admin-card-value-ok`, `admin-card-link`, `admin-recent-reports`, `admin-quick-links`, `source-badge`, `source-badge-auto`, `source-badge-manual`, `status-badge`, `status-badge-open`, `status-badge-triaging`, `status-badge-resolved`, `status-badge-wont_fix`, `tag-badge`, `admin-filters`, `filter-row`, `table-wrapper`, `pagination`, `report-details`, `scene-snippet`, `scene-narrative`, `inline-number-input`, `max-chars-cell`, `small`, `details-cell`, `muted-note`, `alert`, `alert-error`, `alert-success`) are defined in `static/css/app.css`.
7. Spec called for an `<input type="number">` inside a `<form>` for inline max_characters edit. Implementation uses two layers: the `<form>` wraps an `<input>` with `hx-trigger="change"` and redundant `hx-post`/`hx-target`/`hx-swap` attrs on the `<input>` itself. Functionally correct; the input-level HTMX attrs are redundant (the form-level attrs fire first on submit, but the input-level attrs fire on `change` before submit). Works as intended.

---

### Phase 5 Start (2026-03-22)

Epic 8 Story 8.1 (UI Scaffolding & Auth Pages) implemented. Phase 5 is now in progress.

- **Epic 8 Story 8.1** — `app/routers/ui/auth.py`, `app/ui_dependencies.py`, `templates/base.html`, `templates/layout/player.html`, `templates/auth/login.html`, `templates/auth/register.html`, `templates/auth/change_password.html`. Router registered in `app/main.py`. Static file mount added.

**Files created**: `app/routers/ui/__init__.py`, `app/routers/ui/auth.py`, `app/ui_dependencies.py`, `templates/base.html`, `templates/layout/player.html`, `templates/auth/login.html`, `templates/auth/register.html`, `templates/auth/change_password.html`

**Files modified**: `app/main.py` (static mount, LoginRequired handler, ui_auth router registration)

**Story 8.1 Tech Writer Notes**:
- UI router prefix is `/ui` (not `/ui/auth`) — all auth routes are `/ui/login`, `/ui/register`, `/ui/change-password`, `/ui/logout`. Consistent with the player layout nav links.
- `app/ui_dependencies.py` uses service layer directly (not internal HTTP calls). This is correct and preferable to the loosely-worded epic description of "calls JSON API internally."
- `change_password` UI handler re-issues a fresh JWT and updates the session cookie immediately — the user stays logged in. The JSON `POST /auth/change-password` endpoint (per api.md) returns a message saying "Please log in again"; the UI layer improves on this by keeping the session alive transparently. The behaviour difference is intentional and appropriate for the UI layer.
- `secure=False` on cookie `set_cookie` calls is noted in comments as production-only. Acceptable for local MVP.
- `player.html` nav has duplicate `id="theme-toggle-btn"` — the mobile `<details>` block and the desktop block both render a button with the same id. In practice only one is visible at a time, but duplicate ids are invalid HTML. Minor; does not affect functionality.
- Auth pages (`login.html`, `register.html`) extend `base.html` directly and include a small inline `<script>` to apply the stored theme before render — avoids flash of wrong theme. `change_password.html` extends `layout/player.html` (correct — requires auth).
- Vendored static assets (`pico.min.css`, `htmx.min.js`, `app.css`) are referenced but the actual files are not committed in this story. Expected — asset vendoring may follow separately.

---

### Epic 1 Review Findings (addressed)
- **CombatRound.run_number added** — spec omitted `run_number` on `combat_rounds`; without it, unique constraint collides on death/restart. Added column and updated unique constraint to `(character_id, combat_encounter_id, run_number, round_number)`.
- **Meter CHECK constraints added** — gold [0,50], meals [0,8], endurance_current >= 0 enforced at DB level per ops.md meter pattern.
- **scene_phase co-nullability CHECK** — `scene_phase` and `scene_phase_index` must both be null or both non-null.
- **Migration FK ordering fixed** — content tables now created before player tables for PostgreSQL compatibility.
- **GameObjectRef.tags made NOT NULL** — spec implies always-present; default empty JSON array.
- **Content model relationships added** — Scene.game_object, CombatEncounter.foe_game_object, SceneItem.game_object for eager loading.
- **get_settings() cached with @lru_cache** — prevents re-parsing env on every call.
- **Table count: 28** (not 30 as originally estimated in epic spec).
