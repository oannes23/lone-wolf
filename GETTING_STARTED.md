# Getting Started

This guide covers everything needed to run the Lone Wolf CYOA server locally, import book content, and play through the UI.

---

## Prerequisites

- **Python 3.11+** (Python 3.12 recommended — that is what the venv resolves to)
- **uv** — install from https://docs.astral.sh/uv/getting-started/installation/ or `curl -LsSf https://astral.sh/uv/install.sh | sh`

You do not need to create a virtualenv manually; `uv` manages it automatically.

---

## 1. Install Dependencies

```bash
cd /path/to/lone-wolf
uv sync
```

This installs all runtime and dev dependencies into `.venv/`.

---

## 2. Configure Environment

The app requires a `JWT_SECRET` at minimum. Create a `.env` file in the project root:

```
JWT_SECRET=change-me-for-production
```

All other settings have defaults (`DATABASE_URL` defaults to `sqlite:///./lone_wolf.db`). See `app/config.py` for the full list.

---

## 3. Run Migrations

```bash
uv run alembic upgrade head
```

This creates `lone_wolf.db` and applies all migrations in `alembic/versions/` in order. Safe to re-run — it is idempotent against an already-current database.

---

## 4. Seed Static Reference Data

Populate books, disciplines, the Combat Results Table, weapon categories, wizard templates, and book transition rules:

```bash
JWT_SECRET=change-me-for-production uv run python scripts/seed_static.py
```

This is idempotent (upserts). Run it again any time you need to reset reference data to the canonical values without touching player data.

---

## 5. Start the Server

```bash
JWT_SECRET=change-me-for-production uv run uvicorn app.main:app --reload
```

The server listens on `http://127.0.0.1:8000` by default.

- Interactive API docs: `http://127.0.0.1:8000/docs`
- UI (register/login/play): `http://127.0.0.1:8000/ui/login`

---

## 6. Try the UI

1. Open `http://127.0.0.1:8000/ui/login` in a browser.
2. Click **Register** and create an account.
3. Log in with those credentials.
4. Go to **Characters** and create a new character for Book 1 (*Flight from the Dark*).
5. The creation wizard walks through discipline selection and starting equipment.
6. Once the character is created, click **Play** to start reading scenes and making choices.

All combat, inventory management, and meal checks are handled automatically — you only need to choose.

---

## 7. Admin Access

Create an admin account with the `create_admin` script:

```bash
JWT_SECRET=change-me-for-production uv run python scripts/create_admin.py \
    --username admin \
    --password secret
```

The script exits with a non-zero code if the username already exists.

Once created, the admin UI is at `http://127.0.0.1:8000/admin/ui/login`. Admin users can:

- Browse and edit game content (scenes, choices, encounters)
- View user accounts and character data
- Access admin reports

---

## 8. Import Books with the Parser

Books 1 and 2 come pre-seeded (via `seed_static.py`). To import scene content and narrative from the actual Project Aon XHTML files, run the parser pipeline.

**Obtain source files.** Download the Project Aon English XHTML files for Lone Wolf. The expected format is one `.xhtml` file per book, named with the slug prefix (e.g. `01fftd.xhtml`).

**Run the parser.**

```bash
# Import all supported books (1-5), with LLM enrichment
JWT_SECRET=change-me-for-production uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files

# Import a single book
JWT_SECRET=change-me-for-production uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files \
    --book 1

# Skip LLM calls (fast, no API key needed — uses raw choice text)
JWT_SECRET=change-me-for-production uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files \
    --skip-llm

# Dry run (extract and transform only, no DB writes)
JWT_SECRET=change-me-for-production uv run python scripts/seed_db.py \
    --source-dir /path/to/aon/xhtml/files \
    --dry-run
```

**Parser options summary:**

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

The LLM enrichment steps require an `ANTHROPIC_API_KEY` environment variable. If you do not have one, use `--skip-llm`.

---

## 9. Run Tests

```bash
# All tests
uv run pytest

# With coverage
uv run pytest --cov=app --cov-report=term-missing

# Unit tests only
uv run pytest tests/unit/

# Integration tests only
uv run pytest tests/integration/
```

Tests use an in-memory SQLite database and do not require a running server or any environment variables beyond what pytest fixtures inject.

---

## Quick Reference

| Task | Command |
|------|---------|
| Install deps | `uv sync` |
| Run migrations | `uv run alembic upgrade head` |
| Seed reference data | `JWT_SECRET=x uv run python scripts/seed_static.py` |
| Start server | `JWT_SECRET=x uv run uvicorn app.main:app --reload` |
| Create admin | `JWT_SECRET=x uv run python scripts/create_admin.py --username admin --password secret` |
| Import books | `JWT_SECRET=x uv run python scripts/seed_db.py --source-dir /path/to/xhtml` |
| Run tests | `uv run pytest` |
| Lint | `uv run ruff check app/ tests/` |
| Type check | `uv run mypy app/` |
