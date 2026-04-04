# Lone Wolf: Choose Your Own Adventure

A FastAPI web server that lets players create accounts, log in, and play the **Lone Wolf** choose-your-own-adventure gamebook series through a browser UI. Players can run multiple characters at different points in the story, with full decision history and automatic bookkeeping — combat, inventory, disciplines, and meals are all handled by the game engine.

## Features

- Browser-based UI (HTMX + Pico CSS) — no frontend build step
- Full game engine: CRT-based combat, inventory management, Kai disciplines, meals
- Character creation wizard with stat rolling, discipline selection, and starting equipment
- Multi-character support — play different books and paths simultaneously
- Book advancement system (victory → next book with new disciplines and equipment)
- Death, restart, and replay mechanics with full decision history
- Leaderboards (fewest deaths, fewest decisions, highest endurance)
- Encyclopedia of game world entities (characters, locations, creatures, items)
- Admin system for content management and bug report triage
- Parser pipeline to import books from Project Aon XHTML files (with optional LLM enrichment)
- SQLite (local) / PostgreSQL (production)

## Quick Start

### Prerequisites

- **Python 3.11+** (3.12 recommended)
- **uv** — install from https://docs.astral.sh/uv/getting-started/installation/

### Setup

```bash
# 1. Install dependencies
uv sync

# 2. Create .env file
echo "JWT_SECRET=change-me-for-production" > .env

# 3. Run database migrations
uv run alembic upgrade head

# 4. Seed static reference data (books, disciplines, CRT, etc.)
uv run python scripts/seed_static.py

# 5. Start the server
uv run uvicorn app.main:app --reload

# 6. Open http://127.0.0.1:8000/ui/login — register and play
```

You do not need to create a virtualenv manually; `uv` manages it automatically.

### Quick Reference

| Task | Command |
|------|---------|
| Install deps | `uv sync` |
| Run migrations | `uv run alembic upgrade head` |
| Seed reference data | `uv run python scripts/seed_static.py` |
| Start server | `uv run uvicorn app.main:app --reload` |
| Create admin | `uv run python scripts/create_admin.py --username admin --password secret` |
| Import books | `uv run python scripts/seed_db.py --source-dir /path/to/xhtml` |
| Run tests | `uv run pytest` |
| Lint | `uv run ruff check app/ tests/` |
| Type check | `uv run mypy app/` |

> All commands assume `JWT_SECRET` is set in `.env`. If not, prefix commands with `JWT_SECRET=x`.

## Project Structure

```
lone-wolf/
├── app/
│   ├── main.py              # FastAPI application (create_app factory)
│   ├── config.py            # Settings (env-based via pydantic-settings)
│   ├── database.py          # SQLAlchemy engine + session
│   ├── models/              # ORM models (content, player, admin, taxonomy, wizard)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── routers/             # API route modules
│   │   ├── auth.py          # Register, login, refresh, me
│   │   ├── books.py         # Book listing, detail, rules
│   │   ├── characters.py    # Character CRUD, sheet, history, wizard
│   │   ├── gameplay.py      # Scene navigation, combat, inventory, items, rolls
│   │   ├── game_objects.py  # Encyclopedia entities
│   │   ├── leaderboards.py  # Rankings
│   │   ├── reports.py       # Player bug reports
│   │   ├── admin/           # Admin API (content CRUD, reports, users)
│   │   └── ui/              # HTMX UI routes (player + admin)
│   ├── services/            # Business logic layer
│   ├── engine/              # Pure game logic (no HTTP/DB)
│   │   ├── combat.py        # CRT lookup, combat ratio, round resolution
│   │   ├── conditions.py    # Choice availability filtering
│   │   ├── inventory.py     # Item constraints, backpack, weapons
│   │   ├── phases.py        # Automatic phase processing
│   │   └── lifecycle.py     # Character lifecycle (restart, replay, advance)
│   ├── parser/              # XHTML-to-DB pipeline
│   └── utils/               # Shared utilities
├── templates/               # Jinja2 HTML templates (HTMX + Pico CSS)
├── static/                  # CSS, JS, images
├── scripts/
│   ├── seed_static.py       # Load reference data (books, disciplines, CRT)
│   ├── seed_db.py           # Parse + load book content from XHTML
│   └── create_admin.py      # Create admin user account
├── tests/                   # pytest suite (unit + integration)
├── alembic/                 # Database migrations
├── spec/                    # Internal design documents
├── docs/                    # User-facing documentation
└── pyproject.toml
```

## Tech Stack

- **Runtime**: Python 3.12+, FastAPI, Uvicorn
- **Database**: SQLAlchemy ORM + Alembic migrations (SQLite local, PostgreSQL production)
- **Validation**: Pydantic v2
- **Auth**: JWT (python-jose) + bcrypt (passlib)
- **UI**: Jinja2 + HTMX + Pico CSS
- **Parsing**: BeautifulSoup4 (XHTML → database)
- **LLM**: Anthropic SDK (optional, for content enrichment during import)
- **Testing**: pytest + httpx
- **Package management**: `uv`

## Scope

The initial release covers the **Lone Wolf** series. Grey Star and Freeway Warrior are future expansions.

### Lone Wolf Eras

| Era | Books | Disciplines |
|-----|-------|-------------|
| Kai | 1–5 | 10 basic Kai Disciplines, pick 5 |
| Magnakai | 6–12 | 10 upgraded disciplines + Lore-circles |
| Grand Master | 13–20 | Grand Master disciplines, higher base stats |
| New Order | 21–28 | Training new Kai Lords |
| Finale | 29 | Series conclusion |

## Source Data

Game content comes from [Project Aon](https://www.projectaon.org/), provided as XHTML files — one per book. Each file contains ~350 numbered sections with narrative text, choices, combat encounters, item pickups, discipline checks, and the Combat Results Table.

## Documentation

- [Player Guide](docs/player-guide.md) — registration, character creation, gameplay
- [Admin Guide](docs/admin-guide.md) — setup, content management, report triage
- [Tutorials](docs/tutorials.md) — step-by-step walkthroughs
- [FAQ & Troubleshooting](docs/faq.md) — common issues and solutions
- [Configuration Reference](docs/configuration.md) — environment variables and settings

## Design Documents

Internal design specifications (for development reference):

- [Data Model](spec/data-model.md) — database schema (content + player tables)
- [API](spec/api.md) — REST endpoint design
- [Game Engine](spec/game-engine.md) — combat, inventory, disciplines, and state machine logic
- [Parser](spec/parser.md) — XHTML-to-database extraction pipeline
- [Glossary](spec/glossary.md) — terminology reference
