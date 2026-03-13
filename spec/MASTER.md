# Lone Wolf CYOA — Master Spec Index

A Python FastAPI web server that lets players create accounts, log in, and play the Lone Wolf choose-your-own-adventure series. The system uses parsed Project Aon XHTML as seed data, then supports iterative content refinement via an admin layer. The application is **page-agnostic** — it presents a programmed CYOA experience rather than a faithful book rendering.

## Architecture Overview

- **Backend**: Python, FastAPI, SQLAlchemy ORM, Alembic migrations
- **Database**: SQLite (dev), PostgreSQL (prod)
- **Player UI**: HTMX + Jinja2, styled HTML narrative
- **Admin UI**: HTMX + Jinja2, content management + report triage
- **Parser**: XHTML import pipeline with Anthropic Haiku for text rewriting + entity extraction
- **World taxonomy**: Knowledge graph of characters, locations, creatures, organizations across all books
- **Package manager**: `uv`

## Spec Documents

| Doc | Status | Description |
|-----|--------|-------------|
| [data-model.md](data-model.md) | 🟢 Specced | Database schema — content, player, admin, and operational tables |
| [api.md](api.md) | 🟢 Specced | REST API design — auth, gameplay, admin, reports |
| [game-engine.md](game-engine.md) | 🟢 Specced | Pure game logic — combat, disciplines, inventory, transitions |
| [parser.md](parser.md) | 🟢 Specced | XHTML extraction pipeline with LLM text rewriting |

## Key Architectural Decisions

- **API-first**: JSON API is the primary interface. HTMX+Jinja2 UI is a thin presentation layer calling the API internally.
- **Page-agnostic**: Choice text is rewritten to remove "turn to page X" references. The app is a programmed CYOA, not a book reader.
- **Content refinement**: Parser seeds data, then admin layer allows deliberate correction. `source` column (`auto`/`manual`) on key tables supports re-runnable parser that preserves manual edits. Admin edits take effect immediately (no draft/publish).
- **Server-generated RNG**: All random numbers generated server-side. No client-provided random values. Random sections use "click to roll" UI.
- **Death = restart**: Characters restart from the beginning of their current book on death. A snapshot is saved at each book start. Death count is tracked. All decision history preserved with `run_number` tagging.
- **Section phase system**: Each section has an ordered sequence of phases (items → eat → combat → heal → choices). Arbitrary ordering per section. Default computed at runtime; override stored per-section for non-standard flows.
- **Explicit item pickup**: Players must accept or decline each item before making choices. Blocking — API returns 409 if choices attempted with pending items.
- **Character events**: Generic `character_events` table logs all state changes per phase step. Coexists with `decision_log` and `combat_rounds`.
- **Weapon categories**: Weaponskill/Weaponmastery use category matching (Sword category includes Broadsword, Short Sword, etc.) rather than exact name matching.
- **Wizard state**: Explicit `wizard_step` column on characters (not derived). Combat state tracked via `active_combat_encounter_id`.
- **Roll token**: JWT signed with app secret, 1-hour expiry. Unlimited rerolls. Character limit: configurable per user, default 3.
- **All eras**: Full support for Kai, Magnakai, Grand Master, and New Order (books 1–28+).
- **Auth required**: All endpoints require authentication. No public access. Any authenticated user can browse all books, rules, and world entities. Illustrations served as static files (no auth).
- **UI style**: Clean modern — minimal, dark-mode friendly, sans-serif.
- **World taxonomy**: LLM-extracted knowledge graph of world entities (characters, locations, creatures, organizations) with typed relationships. Global entities deduplicated across all books. Eventual goal: generate new narrative possibilities by combining world elements.
- **Two random mechanics**: Phase-based random rolls apply in-section effects (gold, END, items, redirect). Choice-based random rolls branch to different sections via number ranges. Both use "show then confirm" UI pattern.
- **Conditional combat**: `combat_encounters` has `condition_type`/`condition_value` — combat is skipped if the character has the specified discipline/item.
- **Discipline stacking**: Configurable per character via `rule_overrides` JSON. Default: stack all tiers. Alternative: highest tier only.
- **Healing + evasion**: Evasion counts as combat — no healing in sections where combat was evaded.
- **Soft delete**: Characters are soft-deleted (`is_deleted` flag). History preserved for analytics. Admin can restore.
- **Book replay**: Players can replay the current book (reset to snapshot) instead of advancing after victory.
- **No manual saves**: Character state is auto-tracked. Death restarts from book start.
- **LLM caching**: Parser caches LLM results locally (SHA-256 hash of input) to avoid redundant API calls on re-runs.
- **Combat modifier auto-detection**: Parser auto-detects Mindblast immunity, double damage, undead, and other combat modifiers from narrative text.
- **Testing**: pytest + httpx TestClient, SQLite in-memory. LLM calls mocked in tests.
- **Deployment**: Local only for MVP (`uv run`, SQLite).
- **Build order**: Parser → Engine → API → UI.
- **MVP scope**: Books 1–5 (Kai era) for initial playable vertical slice.

## Open Questions

- Grand Master and New Order discipline mechanical effects need detailed research from the source books
- Exact book transition carry-over rules per book pair (to populate `book_transition_rules`)
- SVG flow diagrams from `all-books-svg.zip` — potentially useful for admin validation views
- Lore-circle bonus application timing and stacking rules for later eras (Grand Master lore-circles still TODO)
- World taxonomy: tuning LLM entity extraction prompts for accuracy and dedup quality across 28+ books
- World taxonomy: how the entity catalog scales with context window when processing later books (filtering strategies)
- Seeding the `weapon_categories` table: need to compile the full list of weapon names across all 29 books
- Parser logic for detecting non-standard phase ordering (items after combat, etc.) from narrative text position

## Resolved Questions

- ~~Healing discipline interaction with combat evasion~~ → Evasion counts as combat. No healing.
- ~~Discipline stacking across tiers~~ → Configurable per character, default: stack.
- ~~Random section mechanics~~ → Two distinct mechanics: phase-based (effects) and choice-based (branching).
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
