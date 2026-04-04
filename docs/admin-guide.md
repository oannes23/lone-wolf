# Admin Guide

This guide covers everything needed to set up, operate, and maintain the Lone Wolf CYOA server.

---

## Creating an Admin Account

Admin accounts are separate from player accounts and can only be created via the CLI:

```bash
JWT_SECRET=change-me-for-production uv run python scripts/create_admin.py \
    --username admin \
    --password secret
```

The script exits with a non-zero code if the username already exists.

Once created, log in at `http://127.0.0.1:8000/admin/ui/login`. Admin sessions last 8 hours by default (configurable via `ADMIN_TOKEN_EXPIRE_HOURS`).

---

## Seeding Static Reference Data

Static data includes books, disciplines, the Combat Results Table, weapon categories, wizard templates, book transition rules, and starting equipment definitions:

```bash
JWT_SECRET=change-me-for-production uv run python scripts/seed_static.py
```

This is **idempotent** — it upserts all reference data without touching player data. Run it again any time you need to reset reference data to canonical values (e.g., after pulling code changes that update seed data).

---

## Importing Books

### Obtaining Source Files

Game content comes from [Project Aon](https://www.projectaon.org/). You need the English XHTML files for Lone Wolf. The expected format is one `.xhtml` file per book, named with the book's slug prefix:

| Book | File |
|------|------|
| 1 — Flight from the Dark | `01fftd.xhtml` |
| 2 — Fire on the Water | `02fotw.xhtml` |
| 3 — The Caverns of Kalte | `03tcok.xhtml` |
| 4 — The Chasm of Doom | `04tcod.xhtml` |
| 5 — Shadow on the Sand | `05sots.xhtml` |

### Running the Parser

```bash
# Import all supported books (1-5), with LLM enrichment
JWT_SECRET=x uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files

# Import a single book
JWT_SECRET=x uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files \
    --book 1

# Skip LLM calls (fast, no API key needed)
JWT_SECRET=x uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files \
    --skip-llm

# Dry run (extract and transform only, no DB writes)
JWT_SECRET=x uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files \
    --dry-run
```

### Parser Options

| Flag | Effect |
|------|--------|
| `--book N` | Process only book number N (1-5) |
| `--skip-llm` | Skip all LLM calls; raw choice text is used as-is |
| `--skip-entities` | Skip entity extraction; LLM still rewrites choices |
| `--entities-only` | Run entity extraction only; skip choice rewriting |
| `--no-cache` | Bypass LLM response cache (force fresh API calls) |
| `--reset` | Drop existing book content before loading |
| `--dry-run` | No DB writes; useful for validating source files |
| `--merge-report` | Write `merge_report_{slug}.json` with conflict details |
| `--verbose` | Print stage-by-stage output |

### LLM Enrichment

The parser can optionally use Claude to:

- **Rewrite choice text** — removes page-number references (e.g., "turn to 147") and produces clean player-facing wording
- **Extract entities** — identifies characters, items, creatures, and locations from scene narratives and creates game objects with relationships

This requires an `ANTHROPIC_API_KEY` environment variable. Results are cached in `.parser_cache/` to avoid redundant API calls. If you don't have an API key, use `--skip-llm` — the game is fully playable without enrichment.

### Re-importing

To replace a book's content, use `--reset` to drop existing content before loading:

```bash
JWT_SECRET=x uv run python scripts/seed_db.py \
    --source-dir /path/to/xhtml --book 1 --reset
```

Player data (characters, decision history) is not affected.

---

## Admin Dashboard

The dashboard at `http://127.0.0.1:8000/admin/ui/login` shows:

- **Open Reports** — count of unresolved player bug reports (highlighted if non-zero)
- **Total Users** — registered player count
- **Total Characters** — total characters across all players
- **Books with Content** — number of books that have imported scene data
- **Recent Reports** — table of latest reports with status, tags, and timestamps
- **Quick Links** — shortcuts to triage reports, browse content, and manage users

---

## Content Management

Navigate to **Content** in the admin nav bar to browse and edit game content. There are 13 resource types:

### Commonly Edited

| Resource | What it represents |
|----------|--------------------|
| **Scenes** | Numbered story sections with narrative text, flags (death/victory/must eat/loses backpack), and linked content |
| **Choices** | Player decisions linking one scene to another, with optional conditions and random outcomes |
| **Combat Encounters** | Enemy definitions with name, Combat Skill, Endurance, and evasion rules |
| **Scene Items** | Items offered to players at specific scenes |

### Reference Data

| Resource | What it represents |
|----------|--------------------|
| **Books** | Series entries with era, starting scene, max discipline picks |
| **Disciplines** | Kai/Magnakai disciplines with descriptions and effects |
| **Weapon Categories** | Weapon types (Sword, Axe, Dagger, etc.) |
| **Combat Modifiers** | Difficulty adjustments applied to combat encounters |
| **Game Objects** | Entity knowledge graph (characters, locations, creatures, items) |
| **Game Object Refs** | Tagged relationships between game objects |
| **Book Starting Equipment** | Equipment pools available during character creation per book |
| **Book Transition Rules** | Rules for advancing from one book to the next |
| **Wizard Templates** | Character creation/advancement wizard definitions (read-only) |

### Editing Content

Each resource type has a list view with filtering, pagination, and an **+ New** button (where applicable). Click a row to view its detail page, then **Edit** to modify it.

**Scene editor** is the most feature-rich — it includes:

- Narrative text (HTML, rendered as-is in the player UI)
- Boolean flags: Is Death Scene, Is Victory Scene, Must Eat, Loses Backpack
- Phase sequence override
- Linked content sections showing associated choices, combat encounters, and scene items (read-only, with links to their own edit pages)

### Source Badges

Content shows a source badge:

- **imported** — generated by the parser pipeline (`seed_db.py`)
- **manual** — created or edited through the admin UI

---

## Report Triage

Players can submit bug reports from any scene in the game. Reports include category tags and a free-text description.

### Report Categories

Players can tag reports with: wrong items, meal issue, missing choice, combat issue, narrative error, discipline issue, or other.

### Triage Workflow

1. New reports arrive with status **open**
2. Navigate to **Reports** in the admin nav
3. Filter by status or tags to find reports needing attention
4. Click a report to see full details, including the linked scene narrative
5. Update the status:
   - **triaging** — you're investigating
   - **resolved** — the issue has been fixed
   - **wont_fix** — reviewed and intentionally left as-is
6. Add admin notes to document your findings

### Report Statistics

The reports page shows aggregate stats: totals by status, by tag, and resolution rate.

---

## User Management

Navigate to **Users** in the admin nav to see all registered players:

- Username, email, character count, registration date
- **Max characters per user** — editable inline in the table (controls how many characters a player can create)

Click a user's character count to jump to their characters, filtered by that user.

---

## Character Inspection

Navigate to **Characters** from a user row or the admin nav. Filter by:

- User ID
- Book ID
- Active/deleted status

Each character shows name, stats, book, alive status, current scene, and death count.

### Character Events

The **Events** section (accessible from the admin nav) shows a chronological log of everything that has happened to characters:

- Filter by character ID, event type, or scene ID
- Event types include: combat start/end, choice, death, restart, item pickup, meal consumed, healing, and more
- Useful for debugging player-reported issues — find the character, filter to the relevant scene, and trace what happened

### Restoring Deleted Characters

Players can soft-delete their characters. To restore one:

Use `PUT /admin/characters/{id}/restore` via the API (or the admin UI if available).
