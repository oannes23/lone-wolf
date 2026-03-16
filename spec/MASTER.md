# Lone Wolf CYOA — Master Spec Index

A Python FastAPI web server that lets players create accounts, log in, and play the Lone Wolf choose-your-own-adventure series. The system uses parsed Project Aon XHTML as seed data, then supports iterative content refinement via an admin layer. The application is **page-agnostic** — it presents a programmed CYOA experience rather than a faithful book rendering.

## Architecture Overview

- **Backend**: Python, FastAPI, SQLAlchemy ORM, Alembic migrations
- **Database**: SQLite (dev), PostgreSQL (prod)
- **Player UI**: HTMX + Jinja2, styled HTML narrative
- **Admin UI**: HTMX + Jinja2, content management + report triage
- **Parser**: XHTML import pipeline with Anthropic Haiku for text rewriting + entity extraction
- **Game Object Taxonomy**: Kind-based knowledge graph of characters, locations, creatures, organizations, items, foes, and scenes across all books, linked by tagged refs. Follows ops.md GameObject pattern.
- **Package manager**: `uv`

## Spec Documents

| Doc | Status | Description |
|-----|--------|-------------|
| [data-model.md](data-model.md) | 🟢 Specced | Database schema — content, player, admin, wizard, and taxonomy tables |
| [api.md](api.md) | 🟢 Specced | REST API design — auth, gameplay, admin, game objects, leaderboards |
| [game-engine.md](game-engine.md) | 🟢 Specced | Pure game logic — combat, disciplines, inventory, transitions |
| [parser.md](parser.md) | 🟢 Specced | XHTML extraction pipeline with LLM text rewriting |

## Key Architectural Decisions

- **API-first**: JSON API is the primary interface. HTMX+Jinja2 UI is a thin presentation layer calling the API internally.
- **Page-agnostic**: Choice text is rewritten to remove "turn to page X" references. The app is a programmed CYOA, not a book reader.
- **Scene terminology**: The fundamental unit of gameplay is a "Scene" (renamed from "Section"). Scenes correspond to numbered sections in the original books.
- **Kind system (game_objects)**: All world entities, items, foes, and scenes are unified in a single `game_objects` table with a `kind` column (`character`, `location`, `creature`, `organization`, `item`, `foe`, `scene`). Follows the ops.md GameObject pattern. Tagged refs (`game_object_refs`) replace separate appearances and relationship tables.
- **Dual scene table**: `scenes` table holds gameplay-specific data (narrative, phases, death/victory flags). Each scene also has a `game_objects` entry (kind='scene') for taxonomy. 1:1 FK between them.
- **Content refinement**: Parser seeds data, then admin layer allows deliberate correction. `source` column (`auto`/`manual`) on key tables supports re-runnable parser that preserves manual edits. Admin edits take effect immediately (no draft/publish).
- **Server-generated RNG**: All random numbers generated server-side. No client-provided random values. Random scenes use "click to roll" UI.
- **Death = restart**: Characters restart from the beginning of their current book on death. A snapshot is saved at each book start. Death count is tracked. All decision history preserved with `run_number` tagging.
- **Scene phase system**: Each scene has an ordered sequence of phases (items → eat → combat → heal → choices). Arbitrary ordering per scene. Default computed at runtime; override stored per-scene for non-standard flows.
- **Explicit item pickup**: Players must accept or decline each item before making choices. Blocking — API returns 409 if choices attempted with pending items.
- **Item swap during pickup**: Inventory management (drop/equip/unequip) is available during the `items` phase, allowing players to drop items to make room before accepting new ones. Matches the books' "you may exchange" mechanic.
- **Character events**: Generic `character_events` table logs all state changes per phase step. Coexists with `decision_log` and `combat_rounds`.
- **Weapon categories**: Weaponskill/Weaponmastery use category matching (Sword category includes Broadsword, Short Sword, etc.) rather than exact name matching.
- **Generic wizard system**: Data-driven `wizard_templates` table defines multi-step wizards. Both character creation and book advance use the same wizard infrastructure. Steps are typed (`stat_roll`, `pick_disciplines`, `pick_equipment`, `pick_weapon_skill`, `inventory_adjust`, `confirm`) and configurable via JSON.
- **Equipment wizard**: Character creation includes a separate equipment selection step. Equipment lists per book stored in `book_starting_equipment`, linked to item game_objects.
- **Optimistic locking**: `version` column on characters. All state-mutating gameplay endpoints check version, return 409 on conflict. Prevents concurrent modification from multiple tabs/clients.
- **Endurance max**: Tracked separately from `endurance_base`. Lore-circle bonuses and permanent effects increase `endurance_max`. Healing caps at max, not base.
- **Gold overflow**: Partial acceptance — take up to the 50-crown cap. Auto-applied, no player decision.
- **Item loss skip**: If a scene requires losing an item the character doesn't have, skip silently and log a `character_event` of type `item_loss_skip`.
- **Backpack loss**: `loses_backpack` flag on scenes triggers bulk removal of all backpack items and meals.
- **OR conditions**: `condition_value` supports JSON for compound conditions (e.g., `{"any": ["Tracking", "Huntmastery"]}`).
- **Evasion damage**: Per-encounter `evasion_damage` column on `combat_encounters` (default 0).
- **Meals as counter**: Meals tracked as integer counter on characters, not as inventory items. Do not count against backpack limit.
- **Foes as game objects**: Each unique enemy is a game_object (kind='foe'). `combat_encounters` references via `foe_game_object_id`. Enemy stats are also inline on the encounter for gameplay (denormalized).
- **Roll token**: JWT signed with app secret, 1-hour expiry. Unlimited rerolls. Character limit: configurable per user, default 3.
- **All eras**: Full support for Kai, Magnakai, Grand Master, and New Order (books 1–28+).
- **Auth required**: All endpoints require authentication. No public access. Any authenticated user can browse all books, rules, game objects, and leaderboards. Illustrations served as static files (no auth).
- **Token expiry**: Access token: 24 hours. Refresh token: 90 days.
- **Admin bootstrap**: First admin created via CLI command (`scripts/create_admin.py`). No public admin registration endpoint.
- **Data-driven start scene**: `books.start_scene_number` column (default 1) instead of hardcoding.
- **Leaderboards**: Rich completion stats per book (fewest deaths, fewest decisions, highest END at victory, most common death scenes, discipline popularity, item usage rates). Derived from existing tables via aggregate queries.
- **Log + mutable state**: MVP uses mutable character state with an immutable event log for audit/history. Events are not the source of truth yet. Architecture is designed so full event-sourcing could be adopted later.
- **UI style**: Clean modern — minimal, dark-mode friendly, sans-serif.
- **Three random mechanics**: (1) Phase-based random — background effects (gold, END, items, redirect) from `random_outcomes`, auto-applied during phase progression. (2) Scene-level random exits — all choices are random-gated, player rolls from the `random` phase, auto-applied. (3) Choice-triggered random — player selects a choice that has outcome bands (`choice_random_outcomes`), `/choose` returns `requires_roll: true`, player calls `/roll`. All three auto-apply effects; `requires_confirm` is a UI hint only.
- **Mixed random + regular choices**: A scene can have both condition-gated choices (discipline/item) and random-exit choices. UI shows available choices alongside a roll button.
- **Death scenes skip phases**: On entering a scene with `is_death=true`, the phase sequence is skipped entirely. Character is marked dead immediately. Narrative is shown, no phases run.
- **Eat phase is automatic**: Meal consumption is auto-applied during phase progression (no player action). The scene response includes `phase_results` reporting what happened. No dedicated eat endpoint.
- **Heal phase always included**: The heal phase is always added to the phase sequence. At runtime, `should_heal` checks whether combat actually occurred (including conditional combats that were skipped).
- **Scene redirect queueing**: When a `random_outcome` has `effect_type='scene_redirect'`, remaining automatic phases (heal) still complete first. The redirect fires in place of the choices phase.
- **Advance wizard lazy init**: `GET /gameplay/{id}/wizard` at a victory scene with no active wizard auto-creates the advance wizard.
- **Conditional combat**: `combat_encounters` has `condition_type`/`condition_value` — combat is skipped if the character has the specified discipline/item.
- **Discipline stacking**: Configurable per character via `rule_overrides` JSON. Default: stack all tiers. Alternative: highest tier only.
- **Healing + evasion**: Evasion counts as combat — no healing in scenes where combat was evaded.
- **Soft delete**: Characters are soft-deleted (`is_deleted` flag). History preserved for analytics. Admin can restore.
- **Book replay**: Players can replay the current book (reset to snapshot) instead of advancing after victory.
- **No manual saves**: Character state is auto-tracked. Death restarts from book start.
- **LLM caching**: Parser caches LLM results locally (SHA-256 hash of input) to avoid redundant API calls on re-runs.
- **Combat modifier auto-detection**: Parser auto-detects Mindblast immunity, double damage, undead, and other combat modifiers from narrative text.
- **Testing**: pytest + httpx TestClient, SQLite in-memory. LLM calls mocked in tests.
- **Deployment**: Local only for MVP (`uv run`, SQLite).
- **Build order**: Parser → Engine → API → UI.
- **MVP scope**: Books 1–5 (Kai era) for initial playable vertical slice.

- **Roll auto-applies**: The `/roll` endpoint applies effects immediately. `requires_confirm` is a UI-only hint — the client shows the result and the player clicks confirm in the UI to proceed, but no server call is needed for the confirm itself.
- **Choice-triggered random data model**: New `choice_random_outcomes` table stores outcome bands per choice. Parent choice has `target_scene_id = null`. `/choose` returns `requires_roll: true` with outcome bands. Player then calls `/roll`.

## Open Questions

- Grand Master and New Order discipline mechanical effects need detailed research from the source books
- Exact book transition carry-over rules per book pair (to populate `book_transition_rules`)
- SVG flow diagrams from `all-books-svg.zip` — potentially useful for admin validation views
- Lore-circle bonus application timing and stacking rules for later eras (Grand Master lore-circles still TODO)
- Game object taxonomy: tuning LLM entity extraction prompts for accuracy and dedup quality across 28+ books
- Game object taxonomy: how the entity catalog scales with context window when processing later books (filtering strategies)
- Seeding the `weapon_categories` table: need to compile the full list of weapon names across all 29 books
- Parser logic for detecting non-standard phase ordering (items after combat, etc.) from narrative text position
- Wizard template seed data: exact step sequences and configs for `character_creation` and `book_advance` wizards
- `book_starting_equipment` data: equipment lists for each Kai-era book need compilation from source material

## Resolved Questions

- ~~Random mechanics count~~ → Three distinct types: phase-based (background effects), scene-level exits (roll-only scenes), choice-triggered (choose then roll). New `choice_random_outcomes` table for the third type.
- ~~Roll confirmation flow~~ → `/roll` auto-applies effects. `requires_confirm` is a UI-only hint. No `/confirm` endpoint.
- ~~Choice-triggered random API flow~~ → `/choose` returns `requires_roll: true` with outcome bands. Player calls `/roll` to resolve.
- ~~Mixed random + regular choices~~ → Supported. Scene can have both gated choices and random exits.
- ~~Death scene phase handling~~ → Skip all phases immediately. Mark dead on entry. Narrative shown, no phases run.
- ~~Eat phase interactivity~~ → Fully automatic. No `/eat` endpoint. Result reported in `phase_results` on scene response.
- ~~Heal phase with conditional combat~~ → Always include heal phase. Runtime check via `should_heal` determines if combat actually occurred.
- ~~Advance wizard initiation~~ → Lazy init: `GET /gameplay/{id}/wizard` at victory scene auto-creates the advance wizard.
- ~~Scene redirect from random~~ → Remaining phases complete first. Redirect fires in place of choices phase.

- ~~Healing discipline interaction with combat evasion~~ → Evasion counts as combat. No healing.
- ~~Discipline stacking across tiers~~ → Configurable per character, default: stack.
- ~~Random scene mechanics~~ → Two distinct mechanics: phase-based (effects) and choice-based (branching).
- ~~Conditional combat modeling~~ → condition_type/condition_value on combat_encounters.
- ~~Character deletion~~ → Soft delete with is_deleted flag.
- ~~Book replay~~ → Allowed, resets to snapshot like death restart.
- ~~Manual saves~~ → None. Auto-tracked state only.
- ~~LLM caching~~ → Local cache of parser LLM results.
- ~~Combat modifier detection~~ → Auto-detect all patterns in parser.
- ~~MVP scope~~ → Books 1–5 (Kai era).
- ~~Reroll limit~~ → Unlimited.
- ~~Illustration URLs~~ → API returns fully-formed URLs.
- ~~Admin CRUD style~~ → Strict REST for MVP.
- ~~Browse auth~~ → Any authenticated user can browse all content.
- ~~Starting equipment~~ → Equipment wizard step in character creation, data-driven from `book_starting_equipment` table.
- ~~Gold overflow~~ → Partial acceptance, take up to 50 cap.
- ~~Item loss when missing~~ → Skip silently, log `character_event` of type `item_loss_skip`.
- ~~Item swap during pickup~~ → Allowed. Inventory management available during items phase.
- ~~Admin creation~~ → CLI command (`scripts/create_admin.py`).
- ~~Token expiry~~ → 24h access, 90 day refresh.
- ~~Concurrent requests~~ → Optimistic locking with `version` column, 409 on conflict.
- ~~Evasion damage~~ → Per encounter, `evasion_damage` column on `combat_encounters`, default 0.
- ~~Endurance cap~~ → Separate `endurance_max`, increased by lore-circles and permanent bonuses.
- ~~OR conditions on choices~~ → JSON `condition_value` (e.g., `{"any": ["Tracking", "Huntmastery"]}`).
- ~~Backpack loss modeling~~ → `loses_backpack` flag on scenes.
- ~~Meal tracking~~ → Counter only (`characters.meals`), not inventory items.
- ~~Items in taxonomy~~ → Kind system. Items are game_objects (kind='item').
- ~~Starting scene~~ → Data-driven via `books.start_scene_number`.
- ~~Social features~~ → Rich leaderboards (deaths, decisions, END, death scenes, discipline popularity, item usage).
- ~~Event sourcing depth~~ → Log + mutable state for MVP.
- ~~Foe modeling~~ → Foes as game_objects (kind='foe'), `combat_encounters` references them.
- ~~Section vs scene~~ → "Scene" terminology adopted everywhere.
- ~~Wizard pattern~~ → Generic data-driven `wizard_templates` system. Character creation and book advance use the same infrastructure.
