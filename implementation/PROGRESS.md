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
| 6 | [Core Gameplay API](epic-6-gameplay-api.md) | 7 | Not Started | 4 | Epics 2, 3, 4 |
| 7 | [Content Browse, Social & Admin API](epic-7-content-api.md) | 5 | Not Started | 4 | Epics 1, 2 |
| 8 | [Player UI (HTMX + Pico CSS)](epic-8-player-ui.md) | 6 | Not Started | 5 | Epics 6, 7 |
| 9 | [Admin UI (HTMX + Pico CSS)](epic-9-admin-ui.md) | 4 | Not Started | 6 | Epics 7, 8 |

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
| 6.1 | Scene Endpoint | Not Started |
| 6.2 | Choose & Scene Transition | Not Started |
| 6.3 | Combat Endpoints | Not Started |
| 6.4 | Item & Inventory Endpoints | Not Started |
| 6.5 | Roll Endpoint | Not Started |
| 6.6 | Restart, Replay & Advance Endpoints | Not Started |
| 6.7 | Character CRUD & History | Not Started |

### Epic 7: Content Browse, Social & Admin API
| Story | Name | Status |
|-------|------|--------|
| 7.1 | Books API | Not Started |
| 7.2 | Game Objects API | Not Started |
| 7.3 | Leaderboards API | Not Started |
| 7.4 | Reports API | Not Started |
| 7.5 | Admin Content CRUD & Report Queue | Not Started |

### Epic 8: Player UI (HTMX + Pico CSS)
| Story | Name | Status |
|-------|------|--------|
| 8.1 | UI Scaffolding & Auth Pages | Not Started |
| 8.2 | Character Creation UI | Not Started |
| 8.3 | Scene & Choices UI | Not Started |
| 8.4 | Combat & Random UI | Not Started |
| 8.5 | Items & Inventory UI | Not Started |
| 8.6 | Character Sheet, History & Browse | Not Started |

### Epic 9: Admin UI (HTMX + Pico CSS)
| Story | Name | Status |
|-------|------|--------|
| 9.1 | Admin Scaffolding & Auth | Not Started |
| 9.2 | Content Management Pages | Not Started |
| 9.3 | Report Triage UI | Not Started |
| 9.4 | User & Character Management | Not Started |

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
