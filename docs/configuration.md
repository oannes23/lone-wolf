# Configuration Reference

All configuration is via environment variables or a `.env` file in the project root. The `.env` file is loaded automatically by pydantic-settings. See `app/config.py` for the source of truth.

---

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `JWT_SECRET` | Secret key for signing JWT tokens. Use a long random string in production. |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./lone_wolf.db` | SQLAlchemy database URL. Use `postgresql://...` for production. |
| `JWT_ALGORITHM` | `HS256` | Algorithm for JWT signing. |
| `ACCESS_TOKEN_EXPIRE_HOURS` | `24` | Player access token lifetime in hours. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Player refresh token lifetime in days. |
| `ADMIN_TOKEN_EXPIRE_HOURS` | `8` | Admin session token lifetime in hours. |
| `ROLL_TOKEN_EXPIRE_HOURS` | `1` | Stat roll token lifetime in hours (anti-tampering). |
| `DEBUG_PLAYTEST` | `false` | Enable debug/playtest panel in gameplay UI. |
| `ANTHROPIC_API_KEY` | *(none)* | Required only for LLM enrichment during book import (`scripts/seed_db.py`). Not used at runtime. |

### Example `.env` file

```
JWT_SECRET=change-me-for-production
DATABASE_URL=sqlite:///./lone_wolf.db
```

A `.env.example` template is included in the repo.

---

## Database

### SQLite (development)

The default. A `lone_wolf.db` file is created in the project root when you run `alembic upgrade head`. Safe for single-user development. Foreign key enforcement is enabled via a SQLAlchemy event listener (`PRAGMA foreign_keys=ON`).

### PostgreSQL (production)

Set `DATABASE_URL=postgresql://user:pass@host:5432/dbname`. All Alembic migrations are forward-compatible with PostgreSQL. Run `uv run alembic upgrade head` against the production database to apply the schema.

---

## Authentication

### Player Auth

- Registration requires username, email, and password (8-128 characters).
- Login returns an **access token** (default 24 hours) and a **refresh token** (default 7 days).
- The refresh token can be exchanged for a new access token without re-login.
- Changing your password invalidates all previously issued tokens.
- In the browser UI, the access token is stored in an HTTP-only cookie (`session`). The JSON API uses `Authorization: Bearer <token>` headers.

### Admin Auth

- Admin accounts are separate from player accounts and can only be created via the CLI (`scripts/create_admin.py`).
- Admin login returns a single token (default 8 hours). There is no refresh token — re-authenticate after expiry.
- In the browser UI, the admin token is stored in an HTTP-only cookie (`admin_session`).

### Roll Tokens

Stat rolls during character creation produce a short-lived **roll token** (default 1 hour) that cryptographically binds the rolled values to prevent tampering. The token is consumed when the character is created.

---

## Rate Limiting

Powered by [SlowAPI](https://github.com/laurentS/slowapi). Limits are per-IP.

| Endpoint | Limit |
|----------|-------|
| `/auth/register` | 3 requests/minute |
| `/auth/login` | 5 requests/minute |
| `/characters/roll` | 10 requests/minute |
| `POST /characters` | 5 requests/minute |

UI login and registration endpoints share the same limits as their JSON API counterparts.

---

## Debug/Playtest Mode

Set `DEBUG_PLAYTEST=true` to enable a debug panel in the gameplay scene UI. This adds:

- Jump-to-scene selector (navigate to any scene directly)
- Add-item form (give your character arbitrary items)
- Death immunity notice
- Merge conflict display (from parser)

**Never enable in production.** This bypasses normal gameplay constraints.
