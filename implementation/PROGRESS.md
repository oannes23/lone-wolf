# Implementation Progress

Overall tracker for the Lone Wolf CYOA project. Updated as epics and stories are completed.

## Epic Overview

| Epic | Name | Stories | Status | Phase | Dependencies |
|------|------|---------|--------|-------|-------------|
| 0 | [Spec Fixes & Pre-Implementation](epic-0-spec-fixes.md) | 3 | Not Started | 0 | None |
| 1 | [Project Foundation & Database](epic-1-foundation.md) | 8 | Not Started | 1 | Epic 0 |
| 2 | [Authentication & User Management](epic-2-auth.md) | 5 | Not Started | 2 | Epic 1 |
| 3 | [Game Engine (Pure Functions)](epic-3-engine.md) | 7 | Not Started | 2 | Epic 1 |
| 4 | [Character Creation & Wizard System](epic-4-wizard.md) | 5 | Not Started | 3 | Epics 1, 3 |
| 5 | [Parser Pipeline](epic-5-parser.md) | 6 | Not Started | 2-3 | Epic 1 |
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
| 0.1 | Apply Approved Spec Bug Fixes | Not Started |
| 0.2 | Apply Round-3 Decisions to Spec Documents | Not Started |
| 0.3 | Compile Kai CRT Seed Data | Not Started |

### Epic 1: Project Foundation & Database
| Story | Name | Status |
|-------|------|--------|
| 1.1 | Project Scaffolding | Not Started |
| 1.2 | Config & Database Setup | Not Started |
| 1.3 | Content Table Models & Migration | Not Started |
| 1.4 | Taxonomy Table Models & Migration | Not Started |
| 1.5 | Player Table Models & Migration | Not Started |
| 1.6 | Wizard & Admin Table Models & Migration | Not Started |
| 1.7 | Static Seed Data Script | Not Started |
| 1.8 | Test Infrastructure | Not Started |

### Epic 2: Authentication & User Management
| Story | Name | Status |
|-------|------|--------|
| 2.1 | Auth Service & JWT Utilities | Not Started |
| 2.2 | Auth API Endpoints | Not Started |
| 2.3 | Auth Middleware & Dependencies | Not Started |
| 2.4 | Admin Auth & CLI | Not Started |
| 2.5 | User Management Admin Endpoints | Not Started |

### Epic 3: Game Engine (Pure Functions)
| Story | Name | Status |
|-------|------|--------|
| 3.1 | Engine DTOs & Meter Semantics | Not Started |
| 3.2 | Combat Resolution | Not Started |
| 3.3 | Choice Filtering & Conditions | Not Started |
| 3.4 | Phase Sequence & Progression | Not Started |
| 3.5 | Inventory Management | Not Started |
| 3.6 | Random Mechanics | Not Started |
| 3.7 | Death, Restart, Replay | Not Started |

### Epic 4: Character Creation & Wizard System
| Story | Name | Status |
|-------|------|--------|
| 4.1 | Stat Rolling & Roll Token | Not Started |
| 4.2 | Character Creation Service | Not Started |
| 4.3 | Equipment Wizard (Character Creation) | Not Started |
| 4.4 | Book Advance Wizard | Not Started |
| 4.5 | Wizard API Endpoints | Not Started |

### Epic 5: Parser Pipeline
| Story | Name | Status |
|-------|------|--------|
| 5.1 | Parser Extract Phase | Not Started |
| 5.2 | Parser Transform Phase | Not Started |
| 5.3 | LLM Enrichment — Choice Rewriting | Not Started |
| 5.4 | LLM Enrichment — Entity Extraction | Not Started |
| 5.5 | Parser Load Phase | Not Started |
| 5.6 | Parser CLI & Integration | Not Started |

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

_Track any spec deviations or implementation decisions made during development here._
