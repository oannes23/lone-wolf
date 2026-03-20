# Epic 2: Authentication & User Management

**Phase**: 2 (parallel with Epics 3 and 5)
**Dependencies**: Epic 1
**Status**: Not Started

JWT authentication for players and admins. Rate limiting on auth endpoints. Shared auth dependencies used by all subsequent epics.

---

## Story 2.1: Auth Service & JWT Utilities

**Status**: Not Started

### Description

Core JWT token creation and verification logic, password hashing, and token invalidation support.

### Tasks

- [ ] Create `app/services/auth_service.py`:
  - `create_token(data, token_type, expires_delta)` → JWT string
  - `decode_token(token, expected_type)` → payload dict (raises on invalid/expired)
  - `hash_password(password)` → bcrypt hash
  - `verify_password(plain, hashed)` → bool
- [ ] Four token types with distinct expiry:
  - Player access: 24h, claims: `{sub: user_id, username, type: "access", iat, exp}`
  - Player refresh: 7 days, claims: `{sub: user_id, username, type: "refresh", iat, exp}`
  - Admin access: 8h, claims: `{sub: admin_id, role: "admin", iat, exp}`
  - Roll token: 1h, claims: `{sub: user_id, cs, end, book_id, iat, exp}`
- [ ] `issued_at` check: compare token `iat` against user's `password_changed_at` — reject if token was issued before password change

### Acceptance Criteria

- Unit tests for token creation, verification, expiry for all 4 types
- Unit tests for password hash + verify round-trip
- Unit test: token issued before `password_changed_at` is rejected
- Unit test: token with wrong `type` claim is rejected

---

## Story 2.2: Auth API Endpoints

**Status**: Not Started

### Description

Player-facing authentication endpoints with rate limiting.

### Tasks

- [ ] Create `app/routers/auth.py` with endpoints:
  - `POST /auth/register` (201)
    - Request: `{username, email, password}`
    - Password validation: 8–128 characters
    - Returns: `{id, username, email}`
    - 400 on duplicate username/email
  - `POST /auth/login` (200)
    - Request: `{username, password}`
    - Returns: `{access_token, refresh_token, token_type: "bearer"}`
    - 400 on wrong credentials
  - `POST /auth/refresh` (200)
    - Request: `{refresh_token}`
    - Returns: `{access_token, token_type: "bearer"}`
    - Validates refresh token type and expiry
  - `POST /auth/change-password` (200, requires auth)
    - Request: `{current_password, new_password}`
    - Sets `password_changed_at` on user record
    - Returns: `{message: "Password changed. Please log in again."}`
    - 400 if current_password is incorrect
  - `GET /auth/me` (200, requires auth)
    - Returns: `{id, username, email}`
- [ ] Create `app/schemas/auth.py` with Pydantic request/response models
- [ ] Add rate limiting via slowapi:
  - `POST /auth/login`: 5/min per IP
  - `POST /auth/register`: 3/min per IP

### Acceptance Criteria

- Integration tests for all happy paths
- Integration tests for error cases: duplicate username, wrong password, expired token, invalid refresh token, short password, long password
- Rate limit returns 429 on excess requests

---

## Story 2.3: Auth Middleware & Dependencies

**Status**: Not Started

### Description

FastAPI dependencies for extracting and validating auth tokens, character ownership, and optimistic locking.

### Tasks

- [ ] Create `app/dependencies.py`:
  - `get_current_user(token: str = Depends(oauth2_scheme))` → User
    - Extract Bearer token, decode, validate type="access"
    - Check `iat` against `password_changed_at`
    - Look up user by `sub`, raise 401 if not found
  - `get_owned_character(character_id: int, user: User = Depends(get_current_user), db = Depends(get_db))` → Character
    - Verify character exists (404)
    - Verify belongs to user (403)
    - Verify not soft-deleted (404)
  - `verify_version(character: Character, version: int | None)`:
    - If `version` is None → raise 422 with `{detail, current_version}`
    - If `version != character.version` → raise 409 with `{detail, current_version, error_code: "VERSION_MISMATCH"}`
- [ ] Create standard error response shape: `{detail: str, error_code: str | None, current_version: int | None}`

### Acceptance Criteria

- Auth dependency correctly rejects expired tokens (401)
- Auth dependency correctly rejects tokens issued before password change (401)
- Ownership check blocks cross-user access (403)
- Ownership check returns 404 for deleted characters
- Version mismatch returns 409 with current_version
- Missing version returns 422

---

## Story 2.4: Admin Auth & CLI

**Status**: Not Started

### Description

Separate admin authentication system and CLI for bootstrapping the first admin.

### Tasks

- [ ] Add admin login endpoint to `app/routers/admin/auth.py`:
  - `POST /admin/auth/login` (200)
    - Request: `{username, password}`
    - Returns: `{access_token, token_type: "bearer"}` (8h expiry, no refresh)
    - Rate limiting: 5/min per IP
- [ ] Create `get_current_admin` dependency in `app/dependencies.py`:
  - Validates admin JWT (type check via `role: "admin"` claim)
  - Separate from player auth — admin token rejected on player endpoints, player token rejected on admin endpoints
- [ ] Create `scripts/create_admin.py`:
  - CLI args: `--username`, `--password`
  - Creates admin_users row with bcrypt-hashed password
  - Prints confirmation message

### Acceptance Criteria

- Admin login works and returns admin-scoped JWT
- Admin token rejected on player endpoints (401)
- Player token rejected on admin endpoints (401)
- `uv run python scripts/create_admin.py --username admin --password secret` creates admin
- Rate limit enforced on admin login

---

## Story 2.5: User Management Admin Endpoints

**Status**: Not Started

### Description

Admin endpoints for managing users and restoring deleted characters.

### Tasks

- [ ] Add to `app/routers/admin/`:
  - `PUT /admin/users/{id}` — update `max_characters` (admin auth required)
  - `PUT /admin/characters/{id}/restore` — restore soft-deleted character (set `is_deleted=false`, clear `deleted_at`)

### Acceptance Criteria

- Admin can modify user's max_characters
- Admin can restore a soft-deleted character
- Non-admin requests return 401
- Restoring a non-deleted character returns 400

---

## Implementation Notes

### Token Flow

```
Register → Login → Access Token (24h) + Refresh Token (7d)
                      ↓
              Use access token for API calls
                      ↓
              On expiry → POST /auth/refresh with refresh token
                      ↓
              On password change → all tokens invalidated
```

### Rate Limiting Strategy

Using slowapi with in-memory storage (sufficient for MVP). Key by IP address. Only auth endpoints rate-limited initially.
