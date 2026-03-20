# Epic 7: Content Browse, Social & Admin API

**Phase**: 4 (parallel with Epic 6)
**Dependencies**: Epics 1, 2
**Status**: Not Started

Read-only content browsing, leaderboards, player bug reports, and admin CRUD. Touches different endpoints from Epic 6, so they can be developed in parallel.

---

## Story 7.1: Books API

**Status**: Not Started

### Description

Book listing and detail endpoints for content browsing.

### Tasks

- [ ] Create `app/routers/books.py`:
  - `GET /books` — list all books
    - Filterable by `?era=kai`, `?series=lone_wolf`
    - Response: `[{id, number, slug, title, era, start_scene_number}]`
  - `GET /books/{id}` — book detail
    - Include scene_count (aggregate query)
    - Include discipline list for the book's era
    - Response: `{id, number, slug, title, era, start_scene_number, scene_count, disciplines: [{id, name, description}]}`
  - `GET /books/{id}/rules` — game rules for a book
    - Discipline descriptions, equipment rules, combat rules
    - Derived from discipline table + book metadata
- [ ] Create `app/schemas/books.py` for response models

### Acceptance Criteria

- Integration test: list all books returns correct count
- Integration test: filter by era returns only matching books
- Integration test: book detail includes scene count and discipline list
- Integration test: rules endpoint returns discipline descriptions

---

## Story 7.2: Game Objects API

**Status**: Not Started

### Description

Browse the game object knowledge graph with filtering and ref traversal.

### Tasks

- [ ] Create `app/routers/game_objects.py`:
  - `GET /game-objects` — list with filtering
    - Query params: `?kind=character`, `?book_id=1`, `?search=wolf`, `?limit=50`, `?offset=0`
    - Search: case-insensitive match against name, description, and aliases
    - Response: `[{id, name, kind, description, aliases, first_appearance}]`
  - `GET /game-objects/{id}` — detail with properties and refs
    - Include properties JSON, aliases, tagged refs (first page)
    - Response: `{id, name, kind, description, aliases, properties, first_appearance, refs: [{target, tags, metadata}]}`
  - `GET /game-objects/{id}/refs` — paginated refs
    - Query params: `?tag=appearance`, `?direction=outgoing|incoming`, `?limit=50`, `?offset=0`
    - Response: `[{source|target, tags, metadata}]`
- [ ] Create `app/schemas/game_objects.py`

### Acceptance Criteria

- Integration test: filter by kind returns only matching objects
- Integration test: search finds objects by name, alias, and description
- Integration test: detail includes properties and refs
- Integration test: ref pagination works, direction filter works
- Integration test: tag filter on refs works

---

## Story 7.3: Leaderboards API

**Status**: Not Started

### Description

Aggregate statistics derived from existing gameplay tables.

### Tasks

- [ ] Create `app/routers/leaderboards.py`:
  - `GET /leaderboards/books/{book_id}` — per-book stats:
    - `completions`: count of characters that reached victory in this book
    - `fewest_deaths`: top N characters with lowest death_count who completed the book
    - `fewest_decisions`: top N characters with lowest decision_log count at completion
    - `highest_endurance_at_victory`: top N characters by END when reaching victory scene
    - `most_common_death_scenes`: scene numbers ranked by death event count
    - `discipline_popularity`: discipline pick rates across all characters who played this book
    - `item_usage`: item pickup rates from character_events
  - `GET /leaderboards/overall` — aggregate stats across all books
    - Total completions, total characters, most popular book, etc.
- [ ] Create `app/services/leaderboard_service.py` for aggregate queries
- [ ] Create `app/schemas/leaderboards.py`

### Acceptance Criteria

- Integration test with seeded completion data (create characters, simulate completions)
- Integration test: per-book stats return correct aggregates
- Integration test: empty leaderboard returns empty arrays (no errors)
- Integration test: limit parameter respected

---

## Story 7.4: Reports API

**Status**: Not Started

### Description

Player-facing bug report submission and listing.

### Tasks

- [ ] Create `app/routers/reports.py`:
  - `POST /reports` — create a bug report
    - Request: `{character_id: int | None, scene_id: int | None, tags: [str], free_text: str | None}`
    - Validate tags against predefined list: `wrong_items`, `meal_issue`, `missing_choice`, `combat_issue`, `narrative_error`, `discipline_issue`, `other`
    - Auto-populate user_id from auth
    - Response 201: `{id, status: "open", created_at}`
  - `GET /reports` — list own reports
    - Only reports belonging to authenticated user
    - Response: `[{id, tags, status, free_text, created_at}]`
- [ ] Create `app/schemas/reports.py`

### Acceptance Criteria

- Integration test: report creation with valid tags succeeds
- Integration test: invalid tag rejected (400)
- Integration test: own-reports-only filtering (user A can't see user B's reports)
- Integration test: character_id and scene_id auto-linked

---

## Story 7.5: Admin Content CRUD & Report Queue

**Status**: Not Started

### Description

Full CRUD for all content resources and report triage workflow. All admin endpoints require admin auth.

### Tasks

- [ ] Create admin content endpoints in `app/routers/admin/content.py`:
  - Standard CRUD pattern for each resource:
    - `POST /admin/{resource}` — create (sets source='manual')
    - `GET /admin/{resource}` — list with pagination/filters
    - `GET /admin/{resource}/{id}` — detail
    - `PUT /admin/{resource}/{id}` — update (sets source='manual')
    - `DELETE /admin/{resource}/{id}` — delete
  - Resources: books, scenes, choices, combat-encounters, combat-modifiers, scene-items, disciplines, book-transition-rules, weapon-categories, game-objects, game-object-refs, book-starting-equipment, wizard-templates (read-only)
- [ ] Create admin report endpoints in `app/routers/admin/reports.py`:
  - `GET /admin/reports` — list all reports
    - Filterable by `?status=open`, `?tags=meal_issue`
  - `GET /admin/reports/{id}` — detail with linked scene content
  - `PUT /admin/reports/{id}` — update status, admin_notes, resolved_by
  - `GET /admin/reports/stats` — aggregate stats (reports per tag, per book, resolution rate)
- [ ] Create admin event viewer:
  - `GET /admin/character-events` — filterable by character_id, event_type, scene_id
- [ ] Create `app/services/admin_service.py` for admin business logic

### Acceptance Criteria

- Integration test: CRUD operations for at least 3 resource types (books, scenes, choices)
- Integration test: source column set to 'manual' on create/update
- Integration test: wizard-templates are read-only (POST/PUT/DELETE return 405 or 403)
- Integration test: report triage workflow (open → triaging → resolved)
- Integration test: report stats return correct aggregates
- Integration test: character-events filterable by all params
- Integration test: all admin endpoints reject non-admin auth

---

## Implementation Notes

### Admin CRUD Pattern

All admin content endpoints follow the same pattern. Consider a generic helper:

```python
def create_crud_router(model, schema_create, schema_update, schema_response, read_only=False):
    router = APIRouter()
    # ... generate endpoints
    return router
```

This reduces boilerplate across 14+ resource types. However, some resources need custom logic (e.g., scenes with nested content), so keep the pattern flexible.

### Leaderboard Query Optimization

Leaderboard queries are aggregate-heavy. For MVP with SQLite, standard queries should be fast enough. If performance becomes an issue, consider:
- Materialized views (PostgreSQL)
- Cached results with TTL
- Background job to precompute stats
