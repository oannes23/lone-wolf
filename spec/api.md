# API Design

REST API built with FastAPI. All endpoints return JSON. Auth uses JWT bearer tokens. **All endpoints require authentication** — there is no public access.

**Architecture**: The JSON API is the primary interface. The HTMX player/admin UIs are a thin presentation layer that calls the API internally and renders Jinja2 templates. Illustrations are served as static files (no auth gate).

## Authentication

### `POST /auth/register`

```json
// Request
{ "username": "silentWolf", "email": "wolf@kai.org", "password": "s3cret" }

// Response 201
{ "id": 1, "username": "silentWolf", "email": "wolf@kai.org" }
```

### `POST /auth/login`

```json
// Request
{ "username": "silentWolf", "password": "s3cret" }

// Response 200
{ "access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer" }
```

### `POST /auth/refresh`

```json
// Request
{ "refresh_token": "eyJ..." }

// Response 200
{ "access_token": "eyJ...", "token_type": "bearer" }
```

### `GET /auth/me`

Returns current user profile.

```json
// Response 200
{ "id": 1, "username": "silentWolf", "email": "wolf@kai.org" }
```

## Books

### `GET /books`

List all available books.

```json
// Response 200
[
  {
    "id": 1,
    "number": 1,
    "slug": "01fftd",
    "title": "Flight from the Dark",
    "era": "kai"
  }
]
```

Query params: `?era=kai`, `?series=lone_wolf`

### `GET /books/{book_id}`

Book detail including section count and discipline list.

```json
// Response 200
{
  "id": 1,
  "number": 1,
  "slug": "01fftd",
  "title": "Flight from the Dark",
  "era": "kai",
  "section_count": 350,
  "disciplines": [
    { "id": 1, "name": "Camouflage", "description": "..." }
  ]
}
```

### `GET /books/{book_id}/rules`

Returns the game rules, discipline descriptions, and equipment rules for a book.

## Characters

### Character Creation (Two-Phase)

Character creation is a two-phase process: **roll stats** (repeatable), then **finalize** (commits the character).

#### `POST /characters/roll`

Roll random stats for a new character. Can be called repeatedly until the player is satisfied. No character is persisted yet.

```json
// Request
{ "book_id": 1 }

// Response 200
{
  "roll_token": "abc123...",
  "combat_skill_base": 14,
  "endurance_base": 26,
  "era": "kai",
  "formula": { "cs": "10 + 4", "end": "20 + 6" }
}
```

- **Decision**: Stats are server-rolled (CS = base + random 0–9, END = base + random 0–9). Players can reroll as many times as they like, but cannot choose their numbers.
- **Rationale**: Avoids the tedious delete-and-recreate loop when players get bad stats, while still requiring them to roll rather than pick. Matches the spirit of the books' random number table.
- The `roll_token` is a JWT signed with the app secret, with a **1-hour expiry**, encoding the rolled CS/END values. It must be passed to the finalize endpoint to prove the stats were server-generated.
- Base values depend on era (Kai: 10/20, Grand Master: 15/25, etc.).

#### `POST /characters`

Finalize a character with a previously rolled stat set.

```json
// Request
{
  "name": "Silent Wolf",
  "book_id": 1,
  "roll_token": "abc123...",
  "discipline_ids": [1, 3, 5, 7, 9],
  "weapon_skill_type": "Sword"
}

// Response 201
{
  "id": 1,
  "name": "Silent Wolf",
  "combat_skill_base": 14,
  "endurance_base": 26,
  "endurance_current": 26,
  "gold": 0,
  "meals": 1,
  "death_count": 0,
  "current_run": 1,
  "disciplines": ["Camouflage", "Sixth Sense", "Healing", "Mindblast", "Mind Over Matter"],
  "current_section": { "number": 1, "book_id": 1 }
}
```

- Returns `400` if `roll_token` is expired or invalid.
- Returns `400` if the user has reached their `max_characters` limit (default: 3).
- A `character_book_starts` snapshot is automatically saved when a character is created.

### `GET /characters`

List all characters for the authenticated user.

### `GET /characters/{character_id}`

Full character sheet.

```json
// Response 200
{
  "id": 1,
  "name": "Silent Wolf",
  "book": { "id": 1, "title": "Flight from the Dark" },
  "combat_skill_base": 14,
  "endurance_base": 26,
  "endurance_current": 22,
  "gold": 15,
  "meals": 2,
  "death_count": 0,
  "current_run": 1,
  "disciplines": ["Camouflage", "Sixth Sense", "Healing", "Mindblast", "Mind Over Matter"],
  "weapons": [{ "name": "Axe", "is_equipped": true }],
  "backpack_items": ["Meal", "Healing Potion"],
  "special_items": ["Map"],
  "is_alive": true,
  "current_section": { "number": 141, "book_id": 1 }
}
```

### `GET /characters/{character_id}/history`

Decision log in chronological order. Filterable by run.

```json
// Response 200
[
  {
    "run_number": 1,
    "from_section": 1,
    "to_section": 141,
    "action_type": "choice",
    "choice_text": "Use your Sixth Sense to investigate",
    "created_at": "2025-01-15T10:30:00Z"
  }
]
```

Query params: `?limit=50`, `?offset=0`, `?run=1`

### `DELETE /characters/{character_id}`

Soft-delete a character. Sets `is_deleted = true` and `deleted_at` timestamp. Character and all history are preserved in the database for analytics. Admin can restore via `PUT /admin/users/{id}`. Character no longer appears in `GET /characters` list and does not count toward `max_characters` limit.

## Gameplay

All gameplay endpoints require auth. The character must belong to the authenticated user.

### `GET /gameplay/{character_id}/section`

Get the current section with available actions. The response includes the current **phase** the character is in, which determines what actions are available.

```json
// Response 200 — in 'choices' phase (most common)
{
  "section_number": 1,
  "narrative": "<p>You must make haste...</p>",
  "illustration_url": "/static/images/01fftd/sect1.png",
  "phase": "choices",
  "phase_index": 4,
  "phase_sequence": ["item_loss", "items", "eat", "heal", "choices"],
  "choices": [
    {
      "id": 101,
      "text": "Use your Sixth Sense to investigate",
      "available": true,
      "condition": { "type": "discipline", "value": "Sixth Sense" }
    },
    {
      "id": 102,
      "text": "Take the right path into the wood",
      "available": true,
      "condition": null
    }
  ],
  "combat": null,
  "pending_items": [],
  "is_death": false,
  "is_victory": false
}

// Response 200 — in 'items' phase (must resolve before choosing)
{
  "section_number": 42,
  "narrative": "...",
  "phase": "items",
  "phase_index": 0,
  "phase_sequence": ["items", "combat", "choices"],
  "choices": [...],
  "combat": null,
  "pending_items": [
    { "id": 15, "item_name": "Sword", "item_type": "weapon", "quantity": 1 },
    { "id": 16, "item_name": "Gold Crowns", "item_type": "gold", "quantity": 12 }
  ],
  "is_death": false,
  "is_victory": false
}

// Response 200 — in 'combat' phase
{
  "section_number": 99,
  "narrative": "...",
  "phase": "combat",
  "phase_index": 1,
  "phase_sequence": ["items", "combat", "choices"],
  "choices": [...],
  "combat": {
    "encounter_id": 7,
    "enemy_name": "Kraan",
    "enemy_cs": 16,
    "enemy_end_remaining": 24,
    "hero_end_remaining": 22,
    "rounds_fought": 0,
    "can_evade": false
  },
  "pending_items": [],
  "is_death": false,
  "is_victory": false
}

// Response 200 — in 'random' phase (click to roll)
{
  "section_number": 200,
  "narrative": "...",
  "phase": "random",
  "phase_index": 0,
  "phase_sequence": ["random", "choices"],
  "choices": [...],
  "combat": null,
  "pending_items": [],
  "is_death": false,
  "is_victory": false
}
```

The `text` field on choices uses `display_text` (the Haiku-rewritten, page-agnostic version). The `available` flag is computed by the game engine based on the character's current disciplines, items, and gold. All choices are returned including unavailable ones (with `available: false` and condition shown).

### `POST /gameplay/{character_id}/choose`

Make a choice to navigate to another section.

```json
// Request
{ "choice_id": 101 }

// Response 200
{
  "section_number": 141,
  "narrative": "...",
  "choices": [...],
  "combat": null,
  "items_available": [],
  "must_eat": false
}
```

Returns `400` if the choice is not available (missing discipline/item/gold). Returns `409` if the character is dead, has unresolved combat, has pending items, or is not in the `choices` phase.

### `POST /gameplay/{character_id}/combat/round`

Resolve one round of combat. Random number is server-generated.

```json
// Request
{ "use_psi_surge": false }

// Response 200
{
  "round": 3,
  "enemy_name": "Kraan",
  "combat_ratio": -2,
  "random_number": 5,
  "enemy_loss": 6,
  "hero_loss": 3,
  "enemy_endurance_remaining": 12,
  "hero_endurance_remaining": 19,
  "combat_over": false,
  "can_evade": false,
  "psi_surge_active": false
}
```

- **Decision**: `random_number` removed from request body. Server generates all random numbers.
- **Decision**: `use_psi_surge` added to request body. Only relevant for characters with the Psi-surge discipline; ignored otherwise.

When `combat_over` is `true`, includes `result`: `"win"` or `"loss"`.

On `"loss"` (hero dies), the character is marked dead and a `death` action is logged. See restart endpoint.

### `POST /gameplay/{character_id}/combat/evade`

Evade combat (only if allowed after N rounds).

```json
// Response 200
{
  "section_number": 106,
  "narrative": "...",
  "evasion_damage": 2
}
```

Returns `400` if evasion is not permitted.

### `POST /gameplay/{character_id}/eat`

Consume a meal when required.

```json
// Response 200
{
  "meals_remaining": 1,
  "endurance_change": 0,
  "hunting_used": false
}
```

If the character has no meals and no Hunting/Huntmastery discipline, they lose 3 END.

### `POST /gameplay/{character_id}/item`

Resolve a pending section item (accept or decline). Required during the `items` phase.

```json
// Request — accept
{ "section_item_id": 15, "action": "accept" }

// Request — decline
{ "section_item_id": 15, "action": "decline" }

// Response 200
{
  "item_name": "Sword",
  "action": "accept",
  "pending_items_remaining": 1,
  "phase_complete": false,
  "inventory": {
    "weapons": [{ "name": "Axe", "is_equipped": true }, { "name": "Sword", "is_equipped": false }],
    "backpack_items": ["Meal"],
    "special_items": ["Map"],
    "gold": 15
  }
}
```

Returns `400` if inventory constraints are violated on accept (2 weapons max, 8 backpack items max, 50 gold max) — player must drop an existing item first or decline. Returns `409` if not in the `items` phase. When `phase_complete` is true, the phase auto-advances. A `character_event` is logged for each accept/decline.

### `POST /gameplay/{character_id}/inventory`

Manage inventory (drop, equip, unequip). Available at any time.

```json
// Request
{ "action": "drop", "item_name": "Axe" }

// Response 200
{
  "weapons": [{ "name": "Sword", "is_equipped": false }],
  "backpack_items": ["Meal"],
  "special_items": ["Map"],
  "gold": 15
}
```

Actions: `drop`, `equip`, `unequip`. Returns `400` if constraints are violated.

### `POST /gameplay/{character_id}/roll`

Roll a random number during the `random` phase. Player clicks to trigger; server generates the number. Uses "show then confirm" UI pattern — result is displayed, player clicks "Continue" to proceed.

```json
// Response 200 — phase-based random (in-section effect)
{
  "random_number": 7,
  "outcome_text": "You find 12 Gold Crowns",
  "effect_type": "gold_change",
  "effect_applied": { "amount": 12 },
  "phase_complete": true,
  "requires_confirm": true
}

// Response 200 — choice-based random (section branching)
{
  "random_number": 3,
  "outcome_text": "Take the left path through the forest",
  "target_section_number": 200,
  "phase_complete": true,
  "requires_confirm": true
}
```

Returns `409` if not in the `random` phase. A `character_event` of type `random_roll` is logged. For choice-based random, the matching choice is auto-selected and the character navigates on confirm.

### `POST /gameplay/{character_id}/restart`

Restart a dead character from the beginning of the current book.

```json
// Response 200
{
  "message": "Character restored to book start",
  "death_count": 1,
  "current_run": 2,
  "section_number": 1,
  "combat_skill_base": 14,
  "endurance_base": 26,
  "endurance_current": 26
}
```

- Restores character state from the `character_book_starts` snapshot
- Increments `death_count` and `current_run`
- Clears `active_combat_encounter_id`, `section_phase`, `section_phase_index`, `wizard_step`
- Logs a `restart` action in `decision_log` and a `restart` event in `character_events`
- Returns `400` if the character is alive

### `POST /gameplay/{character_id}/replay`

Replay the current book from the beginning (available at victory sections instead of advancing).

```json
// Response 200
{
  "message": "Replaying from book start",
  "current_run": 3,
  "section_number": 1,
  "combat_skill_base": 14,
  "endurance_base": 26,
  "endurance_current": 26
}
```

- Restores character state from `character_book_starts` snapshot (same as death restart)
- Increments `current_run` but NOT `death_count`
- Logs `replay` in `decision_log` and `character_events`
- Returns `400` if the character is not at a victory section
- Returns `409` if the character has already entered the advance wizard

### Book Advance Wizard

Multi-step process for transitioning a character from one book to the next.

#### `GET /gameplay/{character_id}/advance-book`

Returns the current wizard step and required choices.

```json
// Response 200 — Step 1: Discipline selection
{
  "step": "discipline",
  "book": { "id": 2, "title": "Fire on the Water" },
  "available_disciplines": [
    { "id": 11, "name": "Tracking", "description": "..." }
  ],
  "disciplines_to_pick": 1
}

// Response 200 — Step 2: Inventory adjustment
{
  "step": "inventory",
  "current_weapons": [{ "name": "Sword" }, { "name": "Axe" }],
  "max_weapons": 2,
  "current_backpack": ["Meal", "Healing Potion"],
  "max_backpack": 8,
  "special_items_carrying": ["Map"]
}

// Response 200 — Step 3: Confirmation
{
  "step": "confirm",
  "summary": {
    "new_book": "Fire on the Water",
    "combat_skill": 14,
    "endurance": 26,
    "disciplines": ["Camouflage", "Sixth Sense", "Healing", "Mindblast", "Mind Over Matter", "Tracking"],
    "weapons": ["Sword", "Axe"],
    "gold": 15
  }
}
```

#### `POST /gameplay/{character_id}/advance-book`

Submit the current step's choice.

```json
// Step 1 request
{ "discipline_id": 11 }

// Step 2 request
{ "keep_weapons": ["Sword"], "keep_backpack": ["Meal"] }

// Step 3 request
{ "confirm": true }

// Final response 200
{
  "message": "Advanced to Fire on the Water",
  "section_number": 1,
  "character": { ... }
}
```

Returns `400` if the character hasn't reached a victory section. Returns `404` if there's no next book.

A new `character_book_starts` snapshot is saved after the wizard completes.

## World Taxonomy

Browse the world knowledge graph. All endpoints require auth.

### `GET /world/entities`

List world entities with filtering.

```json
// Response 200
[
  {
    "id": 1,
    "name": "Lone Wolf",
    "entity_type": "character",
    "description": "The last of the Kai Lords...",
    "aliases": ["Silent Wolf", "Grand Master"],
    "first_appearance": { "book": "Flight from the Dark", "section": 1 },
    "appearance_count": 287
  }
]
```

Query params: `?type=character`, `?book_id=1`, `?search=wolf`, `?limit=50`, `?offset=0`

### `GET /world/entities/{entity_id}`

Entity detail with appearances and relationships.

```json
// Response 200
{
  "id": 1,
  "name": "Lone Wolf",
  "entity_type": "character",
  "description": "The last of the Kai Lords...",
  "aliases": ["Silent Wolf", "Grand Master"],
  "properties": { "title": "Grand Master", "race": "Sommlending", "allegiance": "Kai" },
  "first_appearance": { "book_id": 1, "section_number": 1 },
  "appearances": [
    {
      "book": "Flight from the Dark",
      "section_number": 1,
      "role": "protagonist",
      "context": "Lone Wolf flees the destruction of the Kai Monastery"
    }
  ],
  "relationships": [
    {
      "entity": { "id": 5, "name": "Kai Order", "entity_type": "organization" },
      "direction": "outgoing",
      "relationship_category": "factional",
      "relationship_type": "member_of"
    }
  ]
}
```

Query params for appearances: `?book_id=1`, `?role=combatant`

### `GET /world/entities/{entity_id}/appearances`

Paginated list of all sections where this entity appears.

Query params: `?book_id=1`, `?role=combatant`, `?limit=50`, `?offset=0`

### `GET /world/relationships`

Browse relationships across the knowledge graph.

```json
// Response 200
[
  {
    "entity_a": { "id": 1, "name": "Lone Wolf", "entity_type": "character" },
    "entity_b": { "id": 5, "name": "Kai Order", "entity_type": "organization" },
    "relationship_category": "factional",
    "relationship_type": "member_of"
  }
]
```

Query params: `?entity_id=1`, `?category=factional`, `?type=member_of`, `?limit=50`, `?offset=0`

## Reports

### `POST /reports`

Submit a bug report.

```json
// Request
{
  "character_id": 1,
  "section_id": 42,
  "tags": ["meal_issue", "wrong_items"],
  "free_text": "I should have lost a meal here but didn't"
}

// Response 201
{ "id": 1, "status": "open", "created_at": "..." }
```

**Tags** (multi-select): `wrong_items`, `meal_issue`, `missing_choice`, `combat_issue`, `narrative_error`, `discipline_issue`, `other`

### `GET /reports`

List own reports.

## Admin API

All admin endpoints use separate auth (JWT from `admin_users` table). Prefixed with `/admin/`.

### Authentication

#### `POST /admin/auth/login`

```json
// Request
{ "username": "admin", "password": "..." }

// Response 200
{ "access_token": "eyJ...", "token_type": "bearer" }
```

### Content Management

CRUD endpoints for content tables. All follow the same pattern:

- `GET /admin/{resource}` — list with pagination and filters
- `GET /admin/{resource}/{id}` — detail view
- `PUT /admin/{resource}/{id}` — update (sets `source` to `manual`)
- `DELETE /admin/{resource}/{id}` — delete

Resources: `books`, `sections`, `choices`, `combat-encounters`, `combat-modifiers`, `section-items`, `disciplines`, `book-transition-rules`, `weapon-categories`, `world-entities`, `world-entity-appearances`, `world-entity-relationships`

Admin can also manage user limits:
- `PUT /admin/users/{id}` — update `max_characters` and other user settings

Admin can view character events (read-only):
- `GET /admin/character-events` — list events, filterable by `?character_id=1&event_type=death&section_id=42`
- Content edits take effect immediately (no draft/publish workflow).

### Report Queue

- `GET /admin/reports` — list reports, filterable by `?status=open&tags=meal_issue`
- `GET /admin/reports/{id}` — report detail with linked section content
- `PUT /admin/reports/{id}` — update status, add admin notes, assign resolved_by
- `GET /admin/reports/stats` — aggregate stats (reports per category, per book, resolution rate)

## Rate Limiting

### Decision
Basic rate limiting on auth endpoints only.

### Rationale
Prevents brute-force password attacks without adding complexity to gameplay endpoints.

### Implementation
- `POST /auth/login`: 5 attempts per minute per IP
- `POST /auth/register`: 3 attempts per minute per IP
- `POST /admin/auth/login`: 5 attempts per minute per IP
- Gameplay endpoints: no rate limiting initially

## Error Responses

All errors follow a consistent shape:

```json
{
  "detail": "Character does not belong to authenticated user"
}
```

| Status | Meaning |
|--------|---------|
| 400 | Invalid action (constraint violation, unavailable choice, character alive for restart) |
| 401 | Missing or invalid auth token |
| 403 | Resource belongs to another user |
| 404 | Resource not found |
| 409 | Conflict (e.g. character is dead, combat not resolved, wizard step out of order) |
| 422 | Validation error (Pydantic) |
