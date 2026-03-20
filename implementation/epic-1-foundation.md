# Epic 1: Project Foundation & Database

**Phase**: 1
**Dependencies**: Epic 0
**Status**: Not Started

Everything depends on this epic. Establishes the project scaffold, all database tables, migrations, and seed data. All 30 tables defined, test infrastructure ready.

---

## Story 1.1: Project Scaffolding

**Status**: Not Started

### Description

Set up the Python project structure with uv, FastAPI, and the full directory layout.

### Tasks

- [ ] Create `pyproject.toml` with uv configuration
  - Runtime deps: fastapi, uvicorn, sqlalchemy, alembic, pydantic, pydantic-settings, passlib[bcrypt], python-jose[cryptography], anthropic, beautifulsoup4, slowapi, jinja2, python-multipart
  - Dev deps: pytest, pytest-asyncio, httpx, pytest-cov, ruff, mypy
- [ ] Create `app/__init__.py`
- [ ] Create `app/main.py` with FastAPI app factory
- [ ] Create full directory structure:
  ```
  app/models/
  app/schemas/
  app/engine/
  app/services/
  app/routers/
  app/routers/admin/
  app/parser/
  scripts/
  static/css/
  static/js/
  static/images/
  templates/
  tests/unit/
  tests/integration/
  tests/scenarios/
  tests/helpers/
  tests/fixtures/
  ```
- [ ] Update `.gitignore` for Python/uv specifics
- [ ] Add ruff config to `pyproject.toml` (rules: E, F, W, I, UP, S, B, SIM, RUF)

### Acceptance Criteria

- `uv run uvicorn app.main:app` starts without errors
- All directories exist with `__init__.py` where needed
- `uv run ruff check .` passes

---

## Story 1.2: Config & Database Setup

**Status**: Not Started

### Description

Database configuration, SQLAlchemy engine setup, and Alembic initialization.

### Tasks

- [ ] Create `app/config.py` with pydantic-settings `Config` class
  - `DATABASE_URL` (default: `sqlite:///./lone_wolf.db`)
  - `JWT_SECRET` (required)
  - `JWT_ALGORITHM` (default: `HS256`)
  - `ACCESS_TOKEN_EXPIRE_HOURS` (default: 24)
  - `REFRESH_TOKEN_EXPIRE_DAYS` (default: 7)
  - `ADMIN_TOKEN_EXPIRE_HOURS` (default: 8)
  - `ROLL_TOKEN_EXPIRE_HOURS` (default: 1)
- [ ] Create `app/database.py`
  - SQLAlchemy engine creation from config
  - `SessionLocal` sessionmaker
  - `Base` declarative base
  - `get_db` FastAPI dependency (yields session, handles cleanup)
  - SQLite FK pragma enforcement via `@event.listens_for(engine, "connect")` listener
- [ ] Run `alembic init alembic`
- [ ] Configure `alembic/env.py` to use app config and Base metadata

### Acceptance Criteria

- `alembic upgrade head` runs successfully (empty migration state)
- SQLite FK pragma verified (test that FK violations raise errors)
- Config loads from environment variables

---

## Story 1.3: Content Table Models & Migration

**Status**: Not Started

### Description

All content tables that hold parsed book data: books, scenes, choices, combat encounters, and supporting tables.

### Tasks

- [ ] Create `app/models/content.py` with models:
  - `Book` — id, slug, number, title, era, series, start_scene_number, max_total_picks
  - `Scene` — id, game_object_id FK, book_id FK, number, html_id, narrative, is_death, is_victory, must_eat, loses_backpack, illustration_path, phase_sequence_override, source. Unique: (book_id, number)
  - `Choice` — id, scene_id FK, target_scene_id FK (nullable), target_scene_number, raw_text, display_text, condition_type, condition_value, ordinal, source
  - `ChoiceRandomOutcome` — id, choice_id FK, range_min, range_max, target_scene_id FK, target_scene_number, narrative_text, source. Unique: (choice_id, range_min, range_max)
  - `CombatEncounter` — id, scene_id FK, foe_game_object_id FK (nullable), enemy_name, enemy_cs, enemy_end, ordinal, mindblast_immune, evasion_after_rounds, evasion_target, evasion_damage (default 0), condition_type, condition_value, source
  - `CombatModifier` — id, combat_encounter_id FK, modifier_type, modifier_value, condition, source
  - `CombatResults` — id, era, random_number, combat_ratio_min, combat_ratio_max, enemy_loss (nullable), hero_loss (nullable)
  - `Discipline` — id, era, name, html_id, description, mechanical_effect. Unique: (era, name)
  - `SceneItem` — id, scene_id FK, game_object_id FK (nullable), item_name, item_type, quantity (default 1), action, is_mandatory (default false), phase_ordinal, source
  - `RandomOutcome` — id, scene_id FK, roll_group (default 0), range_min, range_max, effect_type, effect_value, narrative_text, ordinal, source. Unique: (scene_id, roll_group, range_min, range_max)
  - `WeaponCategory` — id, weapon_name (unique), category
- [ ] Add CHECK constraints for enum columns (era, source, item_type, action, condition_type, effect_type, modifier_type)
- [ ] Add all indexes per data-model.md spec
- [ ] Create Alembic migrations (content tables depend on game_objects for FKs — coordinate with Story 1.4)

### Acceptance Criteria

- All content tables created with correct columns, types, and constraints
- Unique constraints enforced
- Indexes created
- CHECK constraints prevent invalid enum values

---

## Story 1.4: Taxonomy Table Models & Migration

**Status**: Not Started

### Description

Game object taxonomy tables for the knowledge graph.

### Tasks

- [ ] Create `app/models/taxonomy.py` with models:
  - `GameObject` — id, kind, name, description (nullable), aliases (NOT NULL, default `'[]'`), properties (NOT NULL, default `'{}'`), first_book_id FK (nullable), source. Unique: (name, kind)
  - `GameObjectRef` — id, source_id FK, target_id FK, tags, metadata (nullable), source
  - `BookTransitionRule` — id, from_book_id FK, to_book_id FK, max_weapons, max_backpack_items, special_items_carry, gold_carries, new_disciplines_count, base_cs_override (nullable), base_end_override (nullable), notes (nullable). Unique: (from_book_id, to_book_id)
  - `BookStartingEquipment` — id, book_id FK, game_object_id FK (nullable), item_name, item_type, category, is_default, source
- [ ] Set `game_objects.properties` default to `'{}'` and `aliases` default to `'[]'` (NOT NULL)
- [ ] Add indexes: game_objects(kind), game_objects(kind, name), game_object_refs(source_id), game_object_refs(target_id), book_starting_equipment(book_id)
- [ ] Create Alembic migrations (game_objects must be created before scenes for FK)

### Acceptance Criteria

- Taxonomy tables created with correct constraints
- `properties` and `aliases` are NOT NULL with proper defaults
- FK relationships correct between game_objects, books, and content tables

---

## Story 1.5: Player Table Models & Migration

**Status**: Not Started

### Description

All player-facing tables: users, characters, inventory, decisions, combat history, and events.

### Tasks

- [ ] Create `app/models/player.py` with models:
  - `User` — id, username (unique), email (unique), password_hash, max_characters (default 3), password_changed_at (nullable), created_at
  - `Character` — id, user_id FK, name, book_id FK, current_scene_id FK (nullable), scene_phase (nullable), scene_phase_index (nullable), active_combat_encounter_id FK (nullable, ON DELETE SET NULL), pending_choice_id FK (nullable), combat_skill_base, endurance_base, endurance_max, endurance_current, gold, meals, is_alive, is_deleted (default false), deleted_at (nullable), death_count (default 0), current_run (default 1), version (default 1), rule_overrides (nullable), created_at, updated_at
  - `CharacterDiscipline` — id, character_id FK, discipline_id FK, weapon_category (nullable). Unique: (character_id, discipline_id)
  - `CharacterItem` — id, character_id FK, game_object_id FK (nullable), item_name, item_type, is_equipped (default false)
  - `CharacterBookStart` — id, character_id FK, book_id FK, combat_skill_base, endurance_base, endurance_max, endurance_current, gold, meals, items_json, disciplines_json, created_at. Unique: (character_id, book_id)
  - `DecisionLog` — id, character_id FK, run_number, from_scene_id FK, to_scene_id FK, choice_id FK (nullable), action_type, details (nullable), created_at
  - `CombatRound` — id, character_id FK, combat_encounter_id FK, round_number, random_number, combat_ratio, enemy_loss (nullable), hero_loss (nullable), enemy_end_remaining, hero_end_remaining, psi_surge_used (default false), created_at. Unique: (character_id, combat_encounter_id, round_number)
  - `CharacterEvent` — id, character_id FK, scene_id FK, run_number, event_type, phase (nullable), details (nullable), seq, operations (nullable), parent_event_id FK (nullable, self-referencing, ON DELETE SET NULL), created_at
- [ ] Handle circular FK: `characters.active_wizard_id` ↔ `character_wizard_progress.character_id`
  - Migration A: Create characters WITHOUT `active_wizard_id`
  - Migration B: Create `character_wizard_progress` (Story 1.6)
  - Migration C: ALTER TABLE characters ADD COLUMN `active_wizard_id` FK (ON DELETE SET NULL)
- [ ] Add all indexes per data-model.md spec
- [ ] Set ON DELETE behavior per spec: RESTRICT for most FKs, SET NULL for active_combat_encounter_id, active_wizard_id, parent_event_id

### Acceptance Criteria

- All player tables created with correct columns, types, constraints
- Circular FK resolved across migrations
- Optimistic locking `version` column present on characters
- All indexes created
- ON DELETE behaviors correct

---

## Story 1.6: Wizard & Admin Table Models & Migration

**Status**: Not Started

### Description

Wizard system tables and admin tables.

### Tasks

- [ ] Create `app/models/wizard.py` with models:
  - `WizardTemplate` — id, name (unique), description (nullable)
  - `WizardTemplateStep` — id, template_id FK, step_type, config (nullable), ordinal
  - `CharacterWizardProgress` — id, character_id FK, wizard_template_id FK, current_step_index (default 0), state (nullable), started_at, completed_at (nullable)
- [ ] Create `app/models/admin.py` with models:
  - `AdminUser` — id, username (unique), password_hash, created_at
  - `Report` — id, user_id FK, character_id FK (nullable), scene_id FK (nullable), tags, free_text (nullable), status (default 'open'), admin_notes (nullable), resolved_by FK → admin_users (nullable), created_at, updated_at
- [ ] Add CHECK constraints for status enum on reports
- [ ] Add indexes: character_wizard_progress(character_id, completed_at), reports(status, created_at)
- [ ] Create Alembic migrations in correct order

### Acceptance Criteria

- All 30 tables exist after running `alembic upgrade head`
- `alembic upgrade head` → `alembic downgrade base` → `alembic upgrade head` succeeds (full reversibility)

---

## Story 1.7: Static Seed Data Script

**Status**: Not Started

### Description

Idempotent script to populate all reference data that the application needs before any books are parsed.

### Tasks

- [ ] Create `scripts/seed_static.py` with idempotent loaders for:
  - **Book stubs** (5 Kai-era books): title, slug, number, era, series, start_scene_number, max_total_picks
    - Book 1: "Flight from the Dark", `01fftd`, 1, kai, lone_wolf, 1, 1
    - Book 2: "Fire on the Water", `02fotw`, 2, kai, lone_wolf, 1, 2
    - Book 3: "The Caverns of Kalte", `03tcok`, 3, kai, lone_wolf, 1, 2
    - Book 4: "The Chasm of Doom", `04tcod`, 4, kai, lone_wolf, 1, 6
    - Book 5: "Shadow on the Sand", `05sots`, 5, kai, lone_wolf, 1, 4
  - **Kai disciplines** (10 rows from spec): Camouflage, Hunting, Sixth Sense, Tracking, Healing, Weaponskill, Mindshield, Mindblast, Animal Kinship, Mind Over Matter
  - **Kai CRT** (130 rows from seed-data.md, compiled in Story 0.3)
  - **Weapon categories** (11 rows from seed-data.md)
  - **Wizard templates**:
    - `character_creation`: 2 steps (pick_equipment ordinal 0, confirm ordinal 1)
    - `book_advance`: 4 steps (pick_disciplines 0, pick_equipment 1, inventory_adjust 2, confirm 3)
  - **Book transition rules** (4 rows: 1→2, 2→3, 3→4, 4→5)
  - **Book starting equipment** (all 5 books from seed-data.md)
- [ ] Use upsert-on-unique-key pattern for all inserts
- [ ] Script should be runnable via `uv run python scripts/seed_static.py`

### Acceptance Criteria

- `uv run python scripts/seed_static.py` populates all reference data
- Re-running the script is idempotent (no duplicates, no errors)
- All 5 books, 10 disciplines, 130 CRT rows, 11 weapon categories, 2 wizard templates, 4 transition rules, and all starting equipment rows present

---

## Story 1.8: Test Infrastructure

**Status**: Not Started

### Description

Test fixtures, factories, and configuration for the full test suite.

### Tasks

- [ ] Create `tests/conftest.py`:
  - In-memory SQLite engine with FK pragma enforcement
  - Session-scoped table creation (create_all from Base)
  - Function-scoped transaction rollback (each test gets a clean state)
  - TestClient fixture with DB dependency override
- [ ] Create `tests/factories.py` with helper functions:
  - `make_book(**overrides)` → Book
  - `make_scene(book, **overrides)` → Scene
  - `make_choice(scene, **overrides)` → Choice
  - `make_encounter(scene, **overrides)` → CombatEncounter
  - `make_character(user, book, **overrides)` → Character
  - `make_user(**overrides)` → User
  - `make_game_object(**overrides)` → GameObject
- [ ] Create `tests/fixtures/seed_data.py`:
  - Minimal Kai-era reference data: 10 disciplines, sample CRT rows, weapon categories, wizard templates, 1 book stub
  - Function to load all fixtures into a test session
- [ ] Create `tests/helpers/auth.py`:
  - `register_and_login(client, username, password)` → tokens
  - `auth_headers(access_token)` → dict
- [ ] Create engine purity test: verify `app/engine/` imports no forbidden modules (`models`, `database`, `services`, `routers`, `fastapi`, `sqlalchemy`)

### Acceptance Criteria

- `uv run pytest --collect-only` succeeds (no import errors)
- All fixtures are importable and usable
- Engine purity test passes
- TestClient correctly uses in-memory SQLite

---

## Implementation Notes

### Migration Ordering

Migrations must be created in dependency order:

1. `001_books` — books table
2. `002_game_objects` — game_objects, game_object_refs
3. `003_static_lookups` — weapon_categories, disciplines, combat_results
4. `004_scenes` — scenes (FK → books, game_objects)
5. `005_content_sub_tables` — choices, choice_random_outcomes, combat_encounters, combat_modifiers, scene_items, random_outcomes
6. `006_taxonomy` — book_transition_rules, book_starting_equipment
7. `007_wizard_templates` — wizard_templates, wizard_template_steps
8. `008_admin` — admin_users
9. `009_users` — users
10. `010_characters` — characters (WITHOUT active_wizard_id)
11. `011_character_children` — character_disciplines, character_items, character_book_starts, decision_log, combat_rounds, character_events
12. `012_wizard_progress` — character_wizard_progress
13. `013_character_wizard_fk` — ALTER TABLE characters ADD active_wizard_id
14. `014_reports` — reports

### Key Constraints

- SQLite FK pragma must be enforced on every connection
- `game_objects.properties` and `aliases` must be NOT NULL with defaults
- `character_disciplines.weapon_category` (not `weapon_type`)
- CRT uses sentinel values (-999, 999) for bracket edges
