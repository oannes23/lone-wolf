# FAQ & Troubleshooting

---

## Setup Issues

### "JWT_SECRET" error on startup

The server requires `JWT_SECRET` to be set. Either create a `.env` file in the project root:

```
JWT_SECRET=change-me-for-production
```

Or pass it as an environment variable:

```bash
JWT_SECRET=change-me-for-production uv run uvicorn app.main:app --reload
```

For development, any string works. For production, use a long random value (e.g., `openssl rand -hex 32`).

### "No such table" or database errors

You need to run migrations first:

```bash
uv run alembic upgrade head
```

If the database is corrupted, delete `lone_wolf.db` and re-run migrations followed by `seed_static.py`.

### Server starts but UI shows no books

You need to seed static reference data:

```bash
JWT_SECRET=x uv run python scripts/seed_static.py
```

This populates books, disciplines, the Combat Results Table, weapon categories, and wizard templates. For actual scene narrative content, you also need to import books with `seed_db.py` (see the [Admin Guide](admin-guide.md#importing-books)).

### Parser fails with "file not found"

Check that `--source-dir` points to the directory containing the `.xhtml` files, not a file path. Expected file naming: `01fftd.xhtml`, `02fotw.xhtml`, etc. Use `--verbose` for detailed stage-by-stage output.

### Parser fails with "ANTHROPIC_API_KEY" error

Either set the `ANTHROPIC_API_KEY` environment variable, or add `--skip-llm` to skip LLM enrichment:

```bash
JWT_SECRET=x uv run python scripts/seed_db.py --source-dir /path/to/xhtml --skip-llm
```

Without LLM enrichment, raw choice text from the XHTML is used as-is. The game is still fully playable.

---

## Gameplay Issues

### No choices available at this scene

This may indicate the book content was not fully imported. Check the admin content UI to verify the scene has linked choices. If the scene should have choices, report the issue using the in-scene bug report form.

### Character stuck in combat / cannot proceed

Combat continues until one side reaches 0 Endurance or you evade (if available). If evasion is available, it becomes active after a certain number of rounds — the UI shows a hint when evasion is not yet available. If combat seems unwinnable, report it via the bug report form.

### Discipline check fails but I have the discipline

Some choices require a specific discipline. The requirement is shown on the grayed-out choice button (e.g., "Requires: Sixth Sense"). Check your character sheet to confirm which disciplines you have — the condition might require a different discipline than you expect.

### "Setup in progress" on character card

Your character has an active wizard (character creation or book advancement) that was not completed. Click "Continue Setup" on the character card to finish the wizard steps. You cannot play until the wizard is completed.

### Inventory full — cannot accept item

Weapons are limited to 2 slots, backpack items to 8 slots. Drop an existing item via the inventory drawer at the bottom of the scene before accepting a new one. Special items do not count against these limits.

### Meals and hunger

Some scenes require eating a meal (flagged by the game engine). If you have the **Hunting** discipline, meals are handled automatically. Without Hunting, if you have 0 meals when a meal is required, you lose Endurance. Stock up on meals when they are offered.

---

## Admin Issues

### Cannot log into admin UI

Admin accounts are **separate** from player accounts. You need to create one via the CLI:

```bash
JWT_SECRET=x uv run python scripts/create_admin.py --username admin --password secret
```

The admin UI is at `http://127.0.0.1:8000/admin/ui/login`. Admin tokens expire after 8 hours (configurable via `ADMIN_TOKEN_EXPIRE_HOURS` in `.env`).

### Content changes not appearing in the player UI

Edits take effect immediately — there is no cache to clear. Make sure you saved the form (you should see the detail page with updated values after saving). If editing scene narrative HTML, check for unclosed tags that might break rendering.

### How to reset a book's content and re-import

Use the `--reset` flag with `seed_db.py` to drop existing content for the specified book before loading:

```bash
JWT_SECRET=x uv run python scripts/seed_db.py --source-dir /path/to/xhtml --book 1 --reset
```

Player data (characters, decision history) is not affected by content resets.

### Report statuses explained

| Status | Meaning |
|--------|---------|
| `open` | Newly submitted, needs triage |
| `triaging` | Admin is investigating |
| `resolved` | Issue was fixed |
| `wont_fix` | Issue was reviewed and intentionally left as-is |

---

## Development

### Running tests

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

### Linting and type checking

```bash
# Lint
uv run ruff check app/ tests/

# Type check
uv run mypy app/
```

### DEBUG_PLAYTEST mode

Set `DEBUG_PLAYTEST=true` in `.env` to enable a debug panel in the gameplay scene. This adds jump-to-scene, add-item, death immunity, and merge conflict display. See [Configuration](configuration.md#debugplaytest-mode) for details.
