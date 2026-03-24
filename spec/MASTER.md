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
| [todo.md](todo.md) | 🟢 Resolved | Pre-implementation review findings — 49 items total (29 original + 14 spec completion + 8 deferred post-MVP) |
| [seed-data.md](seed-data.md) | 🟢 Specced | Kai-era seed data — weapon categories, starting equipment, transition rules, wizard templates |

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
- **Meals as counter**: Meals tracked as integer counter on characters, not as inventory items. Maximum 8. On pickup, partial acceptance up to cap. Do not count against backpack limit.
- **Foes as game objects**: Each unique enemy is a game_object (kind='foe'). `combat_encounters` references via `foe_game_object_id`. Enemy stats are also inline on the encounter for gameplay (denormalized).
- **Roll token**: JWT signed with app secret, 1-hour expiry. Unlimited rerolls. Character limit: configurable per user, default 3.
- **All eras**: Full support for Kai, Magnakai, Grand Master, and New Order (books 1–28+).
- **Auth required**: All endpoints require authentication. No public access. Any authenticated user can browse all books, rules, game objects, and leaderboards. Illustrations served as static files (no auth).
- **Token expiry**: Access token: 24 hours. Refresh token: 7 days.
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
- **Advance wizard explicit init**: `POST /gameplay/{id}/advance` required to start book advance wizard. No lazy-init. Replay available until player commits.
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
- **Meter pattern**: Endurance, gold, and meals are ops.md Meters with centralized boundary logic. All endurance mutations route through `apply_endurance_delta()` — single place for the death check. See game-engine.md Meter Semantics.
- **Operations layer**: `character_events.operations` JSON column records atomic ops.md operations (e.g., `meter.delta`, `ref.set`) alongside the semantic `event_type`. Dual-layer event design. See data-model.md character_events.
- **Causality tracking**: `parent_event_id` FK on character_events enables event chains (e.g., meal_penalty → death). `seq` column provides strict per-character ordering independent of timestamps. See data-model.md character_events.
- **Mandatory items**: `scene_items.is_mandatory` flag. When true, player cannot decline the item during the items phase — must accept (managing inventory if needed). See data-model.md scene_items.
- **Version required**: `version` field is required (not optional) on all state-mutating gameplay endpoints. Omitting returns 422. See api.md Optimistic Locking.
- **Redirect depth limit**: `MAX_REDIRECT_DEPTH = 5` prevents infinite redirect loops from misconfigured scene data. Follows ops.md cascade safety. See game-engine.md Meter Semantics.
- **Phase results severity**: `severity` field (`info`, `warn`, `danger`) on phase_results guides UI presentation of automatic phase outcomes. See game-engine.md Phase Progression.
- **Unarmed penalty**: -4 CS when no weapon equipped. Checked in `effective_combat_skill()`. See game-engine.md Combat Resolution.
- **Enemy Mindblast**: Modeled via `combat_modifiers` rows with `modifier_type='enemy_mindblast'`. Hero suffers -2 CS unless they have Mindshield. See game-engine.md Combat Resolution.
- **Consumable items**: `POST /gameplay/{id}/use-item` available at any phase. Effects data-driven via game_object `properties` JSON. See api.md and game-engine.md.
- **Item combat bonuses**: Stored in item game_object `properties` JSON (`combat_bonus`, `special_vs`, `damage_multiplier`). `effective_combat_skill()` checks equipped weapon properties. See game-engine.md.
- **Gold deduction on choose**: Gold-gated choices auto-deduct `int(condition_value)` gold on selection. See api.md and game-engine.md Scene Transition.
- **Era-scoped disciplines and CRT**: `disciplines` and `combat_results` use `era` column instead of `book_id` FK. One set per era, shared by all books in that era. See data-model.md.
- **Stateless refresh tokens**: JWT with 7-day expiry, no server storage. Password change invalidates via `issued_at` check. See api.md Authentication.
- **Advance wizard explicit init**: `POST /gameplay/{id}/advance` required to start book advance wizard. No lazy-init. Replay available until player commits. See api.md Book Advance Wizard.
- **Single wizard path**: `/characters/{id}/wizard` is the canonical path for both creation and advance wizards. No `/gameplay/` alias. See api.md.
- **Auto-apply gold/meals**: Gold and meal `scene_items` are auto-applied during phase progression (no accept/decline). Only weapon/backpack/special items need explicit pickup. See game-engine.md Phase Progression.
- **Mandatory items override limits**: Mandatory items bypass slot limits. Player gets the item even if over capacity. Next items phase forces resolution. See game-engine.md Inventory Constraints.
- **Engine DTOs**: `CharacterState`, `SceneContext`, `CombatContext` dataclasses define the engine's input contract. API layer populates from DB. See game-engine.md.
- **Multi-roll scenes**: `roll_group` column on `random_outcomes` supports multiple sequential rolls per scene. See data-model.md.
- **Admin content creation**: `POST /admin/{resource}` for all content resources. Sets `source='manual'`. See api.md Admin API.
- **Event seq generation**: Application-level `MAX(seq)+1` within transaction. Safe via optimistic locking. See data-model.md character_events.
- **Meal cap**: Meals capped at 8 (matches backpack capacity thematically). Overflow handled like gold — partial acceptance up to cap.
- **Book 1 equipment**: All books use free choice for equipment selection. No random-roll variant.
- **Equipment wizard**: Gold roll + fixed meals auto-applied during equipment step. Fixed items (e.g., Axe, Map) shown as "included" (not selectable). Player can freely re-pick before submitting. Item stat bonuses applied immediately.
- **Multi-roll scenes**: Player calls `/roll` once per roll group. Response includes `rolls_remaining` and `current_roll_group`. Scene redirect in any group skips remaining groups (redirect wins).
- **Password change**: `POST /auth/change-password` endpoint. Sets `password_changed_at`; all prior tokens rejected via `issued_at` check.
- **Unresolved choices**: Choices with null `target_scene_id` (no random outcomes) shown as `available: false` with `path_unavailable` reason.
- **Character names**: No uniqueness constraint. Duplicates allowed.
- **Parser phase detection**: Best-effort auto-detection of non-standard phase ordering from narrative text position. Admin overrides via `phase_sequence_override`.

## Open Questions

See [todo.md](todo.md) items 42-49 for deferred post-MVP questions. All remaining open questions are non-blocking for Kai-era (books 1-5) implementation.

## Resolved Questions

- ~~Random mechanics count~~ → Three distinct types: phase-based (background effects), scene-level exits (roll-only scenes), choice-triggered (choose then roll). New `choice_random_outcomes` table for the third type.
- ~~Roll confirmation flow~~ → `/roll` auto-applies effects. `requires_confirm` is a UI-only hint. No `/confirm` endpoint.
- ~~Choice-triggered random API flow~~ → `/choose` returns `requires_roll: true` with outcome bands. Player calls `/roll` to resolve.
- ~~Mixed random + regular choices~~ → Supported. Scene can have both gated choices and random exits.
- ~~Death scene phase handling~~ → Skip all phases immediately. Mark dead on entry. Narrative shown, no phases run.
- ~~Eat phase interactivity~~ → Fully automatic. No `/eat` endpoint. Result reported in `phase_results` on scene response.
- ~~Heal phase with conditional combat~~ → Always include heal phase. Runtime check via `should_heal` determines if combat actually occurred.
- ~~Advance wizard initiation~~ → Explicit init: `POST /gameplay/{id}/advance` required. No lazy-init on GET. Replay available until player commits.
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
- ~~Token expiry~~ → 24h access, 7-day refresh.
- ~~Concurrent requests~~ → Optimistic locking with `version` column, 409 on conflict.
- ~~Evasion damage~~ → Per encounter, `evasion_damage` column on `combat_encounters`, default 0.
- ~~Endurance cap~~ → Separate `endurance_max`, increased by lore-circles and permanent bonuses.
- ~~OR conditions on choices~~ → JSON `condition_value` (e.g., `{"any": ["Tracking", "Huntmastery"]}`).
- ~~Backpack loss modeling~~ → `loses_backpack` flag on scenes.
- ~~Meal tracking~~ → Counter only (`characters.meals`), not inventory items.
- ~~Items in taxonomy~~ → Kind system. Items are game_objects (kind='item').
- ~~Starting scene~~ → Data-driven via `books.start_scene_number`.
- ~~Social features~~ → Rich leaderboards (deaths, decisions, END, death scenes, discipline popularity, item usage).
- ~~Event sourcing depth~~ → Log + mutable state for MVP. The `character_events.operations` JSON column serves as the migration seam — if full event-sourcing is adopted later, operations already record the atomic mutations needed for replay.
- ~~Foe modeling~~ → Foes as game_objects (kind='foe'), `combat_encounters` references them.
- ~~Section vs scene~~ → "Scene" terminology adopted everywhere.
- ~~Wizard pattern~~ → Generic data-driven `wizard_templates` system. Character creation and book advance use the same infrastructure.
- ~~Unarmed combat~~ → -4 CS penalty when no weapon equipped.
- ~~Enemy Mindblast~~ → `combat_modifiers` with `modifier_type='enemy_mindblast'`. -2 CS unless hero has Mindshield.
- ~~Consumable items~~ → `POST /gameplay/{id}/use-item`. Effects data-driven via game_object properties.
- ~~Item combat bonuses~~ → Stored in item game_object `properties` JSON. `effective_combat_skill()` checks equipped weapon.
- ~~Gold deduction~~ → Auto-deduct on `/choose` for gold-gated choices.
- ~~Discipline scoping~~ → Era-scoped. `disciplines` uses `era` column, not `book_id` FK.
- ~~CRT scoping~~ → Era-scoped. `combat_results` uses `era` column, not `book_id` FK.
- ~~Refresh tokens~~ → Stateless JWT, no server storage, 7-day expiry.
- ~~Wizard endpoint path~~ → Single canonical path: `/characters/{id}/wizard`.
- ~~Wizard template seed data~~ → `character_creation`: 2 steps (pick_equipment, confirm). `book_advance`: 3 steps (pick_disciplines, inventory_adjust, confirm).
- ~~Gold/meal pickup~~ → Auto-applied during phase progression. No accept/decline needed.
- ~~Mandatory item deadlock~~ → Mandatory items override slot limits. Next items phase forces resolution.
- ~~Engine purity~~ → DTOs (`CharacterState`, `SceneContext`, `CombatContext`) define engine input contract.
- ~~Multi-roll scenes~~ → `roll_group` column on `random_outcomes`.
- ~~Admin content creation~~ → `POST /admin/{resource}` for all resources.
- ~~Event seq generation~~ → Application-level `MAX(seq)+1` within transaction.
- ~~Mindshield Kai-era effect~~ → Enemy Mindblast occurs in books 3-5 (Helghast, Darklord servants). Mindshield is not a trap pick.
- ~~Weapon categories~~ → 11 weapons across 7 categories for Kai era. Warhammer is its own category. See seed-data.md.
- ~~Starting equipment~~ → Full equipment lists compiled for all 5 Kai books. All books use free choice with varying pick limits. See seed-data.md.
- ~~Book transition rules~~ → 4 uniform Kai-to-Kai rows. Keep everything, pick 1 new discipline, +10+random gold. See seed-data.md.
- ~~Wizard template seed data~~ → character_creation: 2 steps. book_advance: 3 steps. All books use free choice for equipment. See seed-data.md.
- ~~Mandatory items~~ → Deferred to post-parse admin workflow. Parser seeds all as is_mandatory=false.
- ~~Meals upper bound~~ → Capped at 8 (backpack capacity). Overflow = partial acceptance.
- ~~Book 1 equipment mechanic~~ → Free choice for all books. No random-roll variant.
- ~~Starting gold/meals~~ → Auto-applied during equipment wizard step. Gold server-rolled, meals fixed per book.
- ~~Multi-roll API~~ → Repeated `/roll` calls per group. `rolls_remaining` + `current_roll_group` in response. Redirect wins mid-sequence.
- ~~Password change~~ → `POST /auth/change-password`. `password_changed_at` column on users for token invalidation.
- ~~Null target_scene_id~~ → Show choice as unavailable with `path_unavailable` condition.
- ~~Character name uniqueness~~ → No constraint. Duplicates allowed.
- ~~Equipment wizard re-pick~~ → Freely change selections before submitting.
- ~~Parser phase detection~~ → Best-effort auto-detect. Admin overrides via `phase_sequence_override`.
- ~~Item bonuses during wizard~~ → Immediate recalculation. Confirm step shows correct stats.
- ~~Fixed equipment in wizard~~ → Auto-granted, shown as "included" (not selectable).
- ~~Scene redirect mid-roll~~ → Redirect wins. Remaining roll groups skipped. Heal still completes before redirect fires.
