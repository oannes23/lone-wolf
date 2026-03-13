# Lone Wolf: Choose Your Own Adventure

A FastAPI web server that lets players create accounts, log in, and play the **Lone Wolf** choose-your-own-adventure gamebook series. Players can run multiple characters at different points in the story, with full decision history and automatic bookkeeping (combat, inventory, disciplines, meals).

## Scope

The initial release covers the **Lone Wolf** series (29 books + Day of the Damned special). Grey Star and Freeway Warrior are future expansions.

### Lone Wolf Eras

| Era | Books | Disciplines |
|-----|-------|-------------|
| Kai | 1–5 | 10 basic Kai Disciplines, pick 5 |
| Magnakai | 6–12 | 10 upgraded disciplines + Lore-circles |
| Grand Master | 13–20 | Grand Master disciplines, higher base stats |
| New Order | 21–28 | Training new Kai Lords |
| Finale | 29 | Series conclusion |

## Tech Stack

- **Runtime**: Python 3.12+, FastAPI, Uvicorn
- **Database**: SQLAlchemy ORM + Alembic migrations (SQLite local, PostgreSQL production)
- **Validation**: Pydantic v2
- **Parsing**: BeautifulSoup4 (XHTML → database)
- **Auth**: PyJWT + bcrypt
- **Testing**: pytest + httpx
- **Package management**: `uv`

## Project Structure

```
lone-wolf/
├── src/lonewolf/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Settings (env-based)
│   ├── database.py          # SQLAlchemy engine + session
│   ├── models/              # ORM models
│   │   ├── content.py       # Books, sections, choices, combat, disciplines
│   │   └── player.py        # Users, characters, inventory, decision log
│   ├── schemas/             # Pydantic request/response schemas
│   ├── routers/             # API route modules
│   │   ├── auth.py          # Register, login, refresh, me
│   │   ├── books.py         # Book listing, detail, rules
│   │   ├── characters.py    # Character CRUD, sheet, history
│   │   └── gameplay.py      # Section navigation, combat, inventory, meals
│   ├── engine/              # Pure game logic (no HTTP/DB)
│   │   ├── combat.py        # CRT lookup, combat ratio, round resolution
│   │   ├── state.py         # Section transitions, choice filtering
│   │   ├── inventory.py     # Item constraints, backpack, weapons, gold
│   │   └── rules.py         # Discipline effects, meal mechanics, era rules
│   ├── parser/              # XHTML-to-DB pipeline
│   │   ├── extract.py       # BeautifulSoup extraction
│   │   ├── transform.py     # Normalization, classification, validation
│   │   └── load.py          # Bulk insert to database
│   └── auth/                # JWT token handling + password hashing
├── tests/
├── assets/                  # Source data (zip files)
├── spec/                    # Design documents
├── scripts/
│   └── seed_db.py           # Parse + load all books
├── pyproject.toml
└── alembic.ini
```

## Setup

```bash
# Install dependencies
uv sync

# Parse books and seed the database
uv run python scripts/seed_db.py

# Run the server
uv run uvicorn src.lonewolf.main:app --reload

# Run tests
uv run pytest
```

## Source Data

Game content comes from [Project Aon](https://www.projectaon.org/), provided as two zip archives in `assets/`:

- **all-books-simple.zip** — XHTML books (Lone Wolf: `en/xhtml-simple/lw/*.htm`)
- **all-books-svg.zip** — Graphviz flowcharts of story structure (reference/debug)

Each XHTML file is a single book containing ~350 numbered sections with narrative text, choices, combat encounters, item pickups, discipline checks, and the Combat Results Table.

## Design Documents

- [Data Model](spec/data-model.md) — Database schema (content + player tables)
- [API](spec/api.md) — REST endpoint design
- [Game Engine](spec/game-engine.md) — Combat, inventory, disciplines, and state machine logic
- [Parser](spec/parser.md) — XHTML-to-database extraction pipeline
