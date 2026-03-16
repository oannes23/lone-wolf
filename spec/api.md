# API Design

REST API built with FastAPI. All endpoints return JSON. Auth uses JWT bearer tokens. **All endpoints require authentication** — there is no public access.

**Architecture**: The JSON API is the primary interface. The HTMX player/admin UIs are a thin presentation layer that calls the API internally and renders Jinja2 templates. Illustrations are served as static files (no auth gate).

## Authentication

**Token expiry**: Access token = 24 hours. Refresh token = 90 days.

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
    "era": "kai",
    "start_scene_number": 1
  }
]
```

Query params: `?era=kai`, `?series=lone_wolf`

### `GET /books/{book_id}`

Book detail including scene count and discipline list.

```json
// Response 200
{
  "id": 1,
  "number": 1,
  "slug": "01fftd",
  "title": "Flight from the Dark",
  "era": "kai",
  "start_scene_number": 1,
  "scene_count": 350,
  "disciplines": [
    { "id": 1, "name": "Camouflage", "description": "..." }
  ]
}
```

### `GET /books/{book_id}/rules`

Returns the game rules, discipline descriptions, and equipment rules for a book.

## Characters

### Character Creation (Wizard-Based)

Character creation uses the generic wizard system. Three phases: **roll stats** (repeatable), **finalize** (creates character in wizard state), and **equip** (selects starting equipment).

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

- Stats are server-rolled (CS = base + random 0–9, END = base + random 0–9).
- The `roll_token` is a JWT signed with the app secret, with a **1-hour expiry**, encoding the rolled CS/END values.
- Base values depend on era (Kai: 10/20, Grand Master: 15/25, etc.).

#### `POST /characters`

Finalize a character with a previously rolled stat set. Character is created in wizard state (equipment step remaining).

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
  "endurance_max": 26,
  "endurance_current": 26,
  "gold": 0,
  "meals": 0,
  "death_count": 0,
  "current_run": 1,
  "version": 1,
  "disciplines": ["Camouflage", "Sixth Sense", "Healing", "Mindblast", "Mind Over Matter"],
  "active_wizard": { "type": "character_creation", "step": "equipment", "step_index": 2, "total_steps": 3 }
}
```

- Returns `400` if `roll_token` is expired or invalid.
- Returns `400` if the user has reached their `max_characters` limit (default: 3).
- Character enters the equipment wizard step automatically.

#### `GET /characters/{character_id}/wizard`

Get the current wizard step and available options. Works for both character creation and book advance wizards. Shared path: this is the same endpoint as `GET /gameplay/{character_id}/wizard` (see Book Advance Wizard).

```json
// Response 200 — Equipment selection (character creation)
{
  "wizard_type": "character_creation",
  "step": "equipment",
  "step_index": 2,
  "total_steps": 3,
  "available_equipment": {
    "weapons": [
      { "item_name": "Sword", "item_type": "weapon" },
      { "item_name": "Axe", "item_type": "weapon" },
      { "item_name": "Mace", "item_type": "weapon" }
    ],
    "backpack": [
      { "item_name": "Meal", "item_type": "meal" },
      { "item_name": "Rope", "item_type": "backpack" },
      { "item_name": "Healing Potion", "item_type": "backpack" }
    ]
  },
  "pick_limits": { "weapons": 1, "backpack": 8 }
}
```

#### `POST /characters/{character_id}/wizard`

Submit the current wizard step's choice.

```json
// Equipment step request
{
  "weapons": ["Axe"],
  "backpack_items": ["Meal", "Rope"]
}

// Response 200 — wizard complete
{
  "message": "Character equipped and ready",
  "wizard_complete": true,
  "character": {
    "id": 1,
    "name": "Silent Wolf",
    "combat_skill_base": 14,
    "endurance_base": 26,
    "endurance_max": 26,
    "endurance_current": 26,
    "gold": 0,
    "meals": 1,
    "weapons": [{ "name": "Axe", "is_equipped": true }],
    "backpack_items": ["Rope"],
    "special_items": [],
    "current_scene": { "number": 1, "book_id": 1 },
    "version": 1
  }
}
```

A `character_book_starts` snapshot is automatically saved when the wizard completes.

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
  "endurance_max": 26,
  "endurance_current": 22,
  "gold": 15,
  "meals": 2,
  "death_count": 0,
  "current_run": 1,
  "version": 5,
  "disciplines": ["Camouflage", "Sixth Sense", "Healing", "Mindblast", "Mind Over Matter"],
  "weapons": [{ "name": "Axe", "is_equipped": true }],
  "backpack_items": ["Healing Potion"],
  "special_items": ["Map"],
  "is_alive": true,
  "current_scene": { "number": 141, "book_id": 1 },
  "active_wizard": null
}
```

### `GET /characters/{character_id}/history`

Decision log in chronological order. Filterable by run.

```json
// Response 200
[
  {
    "run_number": 1,
    "from_scene": 1,
    "to_scene": 141,
    "action_type": "choice",
    "choice_text": "Use your Sixth Sense to investigate",
    "created_at": "2025-01-15T10:30:00Z"
  }
]
```

Query params: `?limit=50`, `?offset=0`, `?run=1`

### `DELETE /characters/{character_id}`

Soft-delete a character. Sets `is_deleted = true` and `deleted_at` timestamp. Character no longer appears in `GET /characters` list and does not count toward `max_characters` limit.

## Gameplay

All gameplay endpoints require auth. The character must belong to the authenticated user. **All state-mutating endpoints accept an optional `version` field** for optimistic locking — if provided and it doesn't match the character's current version, the server returns 409.

### `GET /gameplay/{character_id}/scene`

Get the current scene with available actions.

```json
// Response 200 — in 'choices' phase
{
  "scene_number": 1,
  "narrative": "<p>You must make haste...</p>",
  "illustration_url": "/static/images/01fftd/sect1.png",
  "phase": "choices",
  "phase_index": 4,
  "phase_sequence": ["item_loss", "items", "eat", "heal", "choices"],
  "phase_results": [
    { "type": "eat", "result": "meal_consumed", "meals_remaining": 1 },
    { "type": "heal", "result": "healed", "amount": 1, "endurance_current": 23 }
  ],
  "choices": [
    {
      "id": 101,
      "text": "Use your Sixth Sense to investigate",
      "available": true,
      "condition": { "type": "discipline", "value": "Sixth Sense" },
      "has_random_outcomes": false
    },
    {
      "id": 102,
      "text": "Take the right path into the wood",
      "available": true,
      "condition": null,
      "has_random_outcomes": false
    }
  ],
  "combat": null,
  "pending_items": [],
  "is_death": false,
  "is_victory": false,
  "version": 5
}

// Response 200 — in 'items' phase
{
  "scene_number": 42,
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
  "is_victory": false,
  "version": 5
}

// Response 200 — in 'combat' phase
{
  "scene_number": 99,
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
  "is_victory": false,
  "version": 5
}

// Response 200 — in 'random' phase
{
  "scene_number": 200,
  "narrative": "...",
  "phase": "random",
  "phase_index": 0,
  "phase_sequence": ["random", "choices"],
  "choices": [...],
  "combat": null,
  "pending_items": [],
  "is_death": false,
  "is_victory": false,
  "version": 5
}
```

The `text` field on choices uses `display_text` (the Haiku-rewritten, page-agnostic version). The `available` flag is computed by the game engine. All choices are returned including unavailable ones.

### `POST /gameplay/{character_id}/choose`

Make a choice to navigate to another scene.

```json
// Request
{ "choice_id": 101, "version": 5 }

// Response 200 — normal choice (immediate transition)
{
  "scene_number": 141,
  "narrative": "...",
  "phase": "...",
  "phase_results": [...],
  "choices": [...],
  "combat": null,
  "pending_items": [],
  "is_death": false,
  "is_victory": false,
  "version": 6
}

// Response 200 — choice-triggered random (roll required)
{
  "requires_roll": true,
  "choice_id": 42,
  "choice_text": "Try to run away",
  "outcome_bands": [
    { "range_min": 0, "range_max": 2, "narrative_text": "You are caught!" },
    { "range_min": 3, "range_max": 9, "narrative_text": "You escape into the forest" }
  ],
  "version": 5
}
```

When `requires_roll` is true, the player must call `POST /gameplay/{character_id}/roll` to resolve. The roll auto-applies the outcome and transitions to the target scene.

Returns `400` if the choice is not available. Returns `409` if the character has unresolved combat, pending items, is not in the `choices` phase, or if version doesn't match.

### `POST /gameplay/{character_id}/combat/round`

Resolve one round of combat. Random number is server-generated.

```json
// Request
{ "use_psi_surge": false, "version": 5 }

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
  "psi_surge_active": false,
  "version": 6
}
```

When `combat_over` is `true`, includes `result`: `"win"` or `"loss"`.

### `POST /gameplay/{character_id}/combat/evade`

Evade combat (only if allowed after N rounds).

```json
// Request
{ "version": 5 }

// Response 200
{
  "scene_number": 106,
  "narrative": "...",
  "evasion_damage": 2,
  "version": 6
}
```

`evasion_damage` is per-encounter (from `combat_encounters.evasion_damage`, default 0). Returns `400` if evasion is not permitted.

### Meal Consumption (Automatic)

Eating is fully automatic during phase progression — there is no dedicated eat endpoint. When the `eat` phase is reached, the server auto-applies meal logic (consume meal, use Hunting discipline, or apply 3 END penalty). The result is included in `phase_results` on the scene response:

```json
// In GET /gameplay/{character_id}/scene → phase_results
{ "type": "eat", "result": "meal_consumed", "meals_remaining": 1 }
{ "type": "eat", "result": "hunting_used" }
{ "type": "eat", "result": "meal_penalty", "endurance_change": -3, "endurance_current": 19 }
```

### `POST /gameplay/{character_id}/item`

Resolve a pending scene item (accept or decline). During the `items` phase, the inventory endpoint is also available for dropping/swapping items to make room.

```json
// Request — accept
{ "scene_item_id": 15, "action": "accept", "version": 5 }

// Response 200
{
  "item_name": "Sword",
  "action": "accept",
  "pending_items_remaining": 1,
  "phase_complete": false,
  "inventory": {
    "weapons": [{ "name": "Axe", "is_equipped": true }, { "name": "Sword", "is_equipped": false }],
    "backpack_items": [],
    "special_items": ["Map"],
    "gold": 15,
    "meals": 2
  },
  "version": 6
}
```

- For gold items: partial acceptance up to the 50-crown cap. Response includes `actual_amount` if less than offered.
- Returns `400` if inventory constraints are violated on accept (2 weapons max, 8 backpack items max).
- Returns `409` if not in the `items` phase.

### `POST /gameplay/{character_id}/inventory`

Manage inventory (drop, equip, unequip). Available at any time, **including during the items phase** (allows swapping to make room for new items).

```json
// Request
{ "action": "drop", "item_name": "Axe", "version": 5 }

// Response 200
{
  "weapons": [{ "name": "Sword", "is_equipped": false }],
  "backpack_items": [],
  "special_items": ["Map"],
  "gold": 15,
  "meals": 2,
  "version": 6
}
```

Actions: `drop`, `equip`, `unequip`. Returns `400` if constraints are violated.

### `POST /gameplay/{character_id}/roll`

Roll a random number. Called in three contexts:

1. **Scene-level random exits** (`random` phase): All choices are random-gated. Player rolls, outcome determines which scene to navigate to. Effects auto-applied.
2. **Phase-based random** (`random` phase): Scene has `random_outcomes`. Roll applies an in-scene effect (gold, END, item, redirect). Effects auto-applied.
3. **Choice-triggered random** (after `/choose` returned `requires_roll: true`): Player already selected a choice with outcome bands. Roll resolves which outcome applies. Effects auto-applied.

All three auto-apply effects immediately. `requires_confirm` is a **UI-only hint** — the client shows the result and the player clicks a confirm button in the UI to proceed, but no server call is needed for the confirm itself.

```json
// Request
{ "version": 5 }

// Response 200 — phase-based random (in-scene effect)
{
  "random_type": "phase_effect",
  "random_number": 7,
  "outcome_text": "You find 12 Gold Crowns",
  "effect_type": "gold_change",
  "effect_applied": { "amount": 12 },
  "phase_complete": true,
  "requires_confirm": true,
  "version": 6
}

// Response 200 — scene-level random exit (all choices random-gated)
{
  "random_type": "scene_exit",
  "random_number": 3,
  "outcome_text": "Take the left path through the forest",
  "scene_number": 200,
  "narrative": "...",
  "phase_results": [...],
  "requires_confirm": true,
  "version": 6
}

// Response 200 — choice-triggered random (after /choose returned requires_roll)
{
  "random_type": "choice_outcome",
  "random_number": 7,
  "outcome_text": "You escape into the forest",
  "scene_number": 75,
  "narrative": "...",
  "phase_results": [...],
  "requires_confirm": true,
  "version": 6
}

// Response 200 — phase-based random with scene_redirect
{
  "random_type": "phase_effect",
  "random_number": 2,
  "outcome_text": "You fall through a trapdoor",
  "effect_type": "scene_redirect",
  "scene_number": 150,
  "narrative": "...",
  "phase_results": [
    { "type": "heal", "result": "healed", "amount": 1, "endurance_current": 23 }
  ],
  "requires_confirm": true,
  "version": 6
}
```

For `scene_redirect` outcomes, remaining automatic phases (heal) complete before the redirect fires. The redirect replaces the choices phase.

Returns `409` if not in the `random` phase and no pending choice-triggered roll.

### `POST /gameplay/{character_id}/restart`

Restart a dead character from the beginning of the current book.

```json
// Request
{ "version": 5 }

// Response 200
{
  "message": "Character restored to book start",
  "death_count": 1,
  "current_run": 2,
  "scene_number": 1,
  "combat_skill_base": 14,
  "endurance_base": 26,
  "endurance_max": 26,
  "endurance_current": 26,
  "version": 6
}
```

Returns `400` if the character is alive.

### `POST /gameplay/{character_id}/replay`

Replay the current book from the beginning (available at victory scenes instead of advancing).

```json
// Request
{ "version": 5 }

// Response 200
{
  "message": "Replaying from book start",
  "current_run": 3,
  "scene_number": 1,
  "combat_skill_base": 14,
  "endurance_base": 26,
  "endurance_max": 26,
  "endurance_current": 26,
  "version": 6
}
```

Returns `400` if the character is not at a victory scene. Returns `409` if the character has already entered the advance wizard.

### Book Advance Wizard

Uses the generic wizard system. **Lazy initialization**: calling `GET /gameplay/{character_id}/wizard` at a victory scene with no active wizard auto-creates the advance wizard (creates `character_wizard_progress` row, sets `active_wizard_id`). The character must be at a victory scene and must not have already started a replay.

#### `GET /gameplay/{character_id}/wizard`

Returns the current wizard step. Same endpoint as `GET /characters/{character_id}/wizard` — both paths resolve to the same handler. If the character is at a victory scene with no active wizard, the advance wizard is auto-created on this call.

```json
// Response 200 — Step 1: Discipline selection
{
  "wizard_type": "book_advance",
  "step": "discipline",
  "step_index": 0,
  "total_steps": 3,
  "book": { "id": 2, "title": "Fire on the Water" },
  "available_disciplines": [
    { "id": 11, "name": "Tracking", "description": "..." }
  ],
  "disciplines_to_pick": 1
}

// Response 200 — Step 2: Inventory adjustment
{
  "wizard_type": "book_advance",
  "step": "inventory",
  "step_index": 1,
  "total_steps": 3,
  "current_weapons": [{ "name": "Sword" }, { "name": "Axe" }],
  "max_weapons": 2,
  "current_backpack": ["Healing Potion"],
  "max_backpack": 8,
  "special_items_carrying": ["Map"]
}

// Response 200 — Step 3: Confirmation
{
  "wizard_type": "book_advance",
  "step": "confirm",
  "step_index": 2,
  "total_steps": 3,
  "summary": {
    "new_book": "Fire on the Water",
    "combat_skill": 14,
    "endurance_base": 26,
    "endurance_max": 28,
    "disciplines": ["Camouflage", "Sixth Sense", "Healing", "Mindblast", "Mind Over Matter", "Tracking"],
    "weapons": ["Sword", "Axe"],
    "gold": 15
  }
}
```

#### `POST /gameplay/{character_id}/wizard`

Submit the current step's choice (same endpoint as character creation wizard).

```json
// Step 1 request
{ "discipline_id": 11 }

// Step 2 request
{ "keep_weapons": ["Sword"], "keep_backpack": ["Healing Potion"] }

// Step 3 request
{ "confirm": true }

// Final response 200
{
  "message": "Advanced to Fire on the Water",
  "wizard_complete": true,
  "scene_number": 1,
  "character": { ... },
  "version": 7
}
```

Returns `400` if the character hasn't reached a victory scene. Returns `404` if there's no next book.

## Game Object Taxonomy

Browse the game object knowledge graph. All endpoints require auth.

### `GET /game-objects`

List game objects with filtering.

```json
// Response 200
[
  {
    "id": 1,
    "name": "Lone Wolf",
    "kind": "character",
    "description": "The last of the Kai Lords...",
    "aliases": ["Silent Wolf", "Grand Master"],
    "first_appearance": { "book": "Flight from the Dark", "scene": 1 }
  }
]
```

Query params: `?kind=character`, `?kind=item`, `?book_id=1`, `?search=wolf`, `?limit=50`, `?offset=0`

### `GET /game-objects/{id}`

Game object detail with tagged refs.

```json
// Response 200
{
  "id": 1,
  "name": "Lone Wolf",
  "kind": "character",
  "description": "The last of the Kai Lords...",
  "aliases": ["Silent Wolf", "Grand Master"],
  "properties": { "title": "Grand Master", "race": "Sommlending", "allegiance": "Kai" },
  "first_appearance": { "book_id": 1, "scene_number": 1 },
  "refs": [
    {
      "target": { "id": 5, "name": "Kai Order", "kind": "organization" },
      "tags": ["factional", "member_of"],
      "metadata": null
    },
    {
      "target": { "id": 100, "name": "Scene 1: Flight Begins", "kind": "scene" },
      "tags": ["appearance", "protagonist"],
      "metadata": { "context": "Lone Wolf flees the destruction of the Kai Monastery" }
    }
  ]
}
```

### `GET /game-objects/{id}/refs`

Paginated refs for a game object.

Query params: `?tag=appearance`, `?tag=factional`, `?direction=outgoing`, `?limit=50`, `?offset=0`

## Leaderboards

### `GET /leaderboards/books/{book_id}`

Per-book completion stats.

```json
// Response 200
{
  "book": { "id": 1, "title": "Flight from the Dark" },
  "completions": 42,
  "fewest_deaths": [
    { "username": "silentWolf", "death_count": 0, "decisions": 23 }
  ],
  "fewest_decisions": [
    { "username": "tracker99", "decisions": 18, "death_count": 1 }
  ],
  "highest_endurance_at_victory": [
    { "username": "healerMain", "endurance": 28, "death_count": 0 }
  ],
  "most_common_death_scenes": [
    { "scene_number": 99, "death_count": 15 }
  ],
  "discipline_popularity": [
    { "discipline": "Healing", "pick_rate": 0.85 }
  ],
  "item_usage": [
    { "item_name": "Sommerswerd", "pickup_rate": 0.72 }
  ]
}
```

Query params: `?limit=10` (top N per category)

### `GET /leaderboards/overall`

Aggregate stats across all books.

## Reports

### `POST /reports`

Submit a bug report.

```json
// Request
{
  "character_id": 1,
  "scene_id": 42,
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

All admin endpoints use separate auth (JWT from `admin_users` table). Prefixed with `/admin/`. First admin created via CLI command (`scripts/create_admin.py`).

### Authentication

#### `POST /admin/auth/login`

```json
// Request
{ "username": "admin", "password": "..." }

// Response 200
{ "access_token": "eyJ...", "token_type": "bearer" }
```

No `POST /admin/auth/register` endpoint — admins are created via CLI only.

### Content Management

CRUD endpoints for content tables. All follow the same pattern:

- `GET /admin/{resource}` — list with pagination and filters
- `GET /admin/{resource}/{id}` — detail view
- `PUT /admin/{resource}/{id}` — update (sets `source` to `manual`)
- `DELETE /admin/{resource}/{id}` — delete

Resources: `books`, `scenes`, `choices`, `combat-encounters`, `combat-modifiers`, `scene-items`, `disciplines`, `book-transition-rules`, `weapon-categories`, `game-objects`, `game-object-refs`, `book-starting-equipment`, `wizard-templates` (read-only for MVP)

Admin can also manage users and characters:
- `PUT /admin/users/{id}` — update `max_characters` and other user settings
- `PUT /admin/characters/{id}/restore` — restore a soft-deleted character

Admin can view character events (read-only):
- `GET /admin/character-events` — list events, filterable by `?character_id=1&event_type=death&scene_id=42`

Content edits take effect immediately (no draft/publish workflow).

### Report Queue

- `GET /admin/reports` — list reports, filterable by `?status=open&tags=meal_issue`
- `GET /admin/reports/{id}` — report detail with linked scene content
- `PUT /admin/reports/{id}` — update status, add admin notes, assign resolved_by
- `GET /admin/reports/stats` — aggregate stats (reports per category, per book, resolution rate)

## Optimistic Locking

All state-mutating gameplay endpoints accept an optional `version` field in the request body. If provided:
- The server compares it to the character's current `version`
- If they match, the operation proceeds and `version` is incremented
- If they don't match, the server returns 409:

```json
{
  "detail": "Character state has changed. Please refresh and retry.",
  "current_version": 6
}
```

All responses that include character state also include the current `version`.

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
| 409 | Conflict (character is dead, combat not resolved, wizard step out of order, version mismatch) |
| 422 | Validation error (Pydantic) |
