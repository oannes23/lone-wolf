# Data Model

SQLAlchemy ORM with Alembic migrations. SQLite for local development, PostgreSQL for production.

## Content Tables

These tables are populated by the parser and are read-only at runtime (except via the admin layer).

### `books`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | Auto-increment |
| `slug` | `String(20)` UNIQUE | File stem, e.g. `01fftd` |
| `number` | `Integer` | Book number (1–29, 0 for `dotd`) |
| `title` | `String(200)` | Full title |
| `era` | `String(20)` | `kai`, `magnakai`, `grand_master`, `new_order` |
| `series` | `String(20)` | `lone_wolf` (future: `grey_star`, `freeway_warrior`) |
| `start_scene_number` | `Integer` | Starting scene number for this book. Default 1. |
| `max_total_picks` | `Integer` | Maximum items player may pick during equipment wizard step (Book 1 = 1, Book 2 = 2, Book 3 = 2, Book 4 = 6, Book 5 = 4). Single source of truth for pick limits. |

### `scenes`

Gameplay-specific data for each numbered passage. Each scene also has a corresponding `game_objects` entry (kind='scene') for taxonomy purposes.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | Auto-increment |
| `game_object_id` | `Integer` FK → `game_objects.id` ON DELETE RESTRICT | 1:1 link to the game_objects taxonomy entry for this scene |
| `book_id` | `Integer` FK → `books.id` ON DELETE RESTRICT | |
| `number` | `Integer` | Scene number within book |
| `html_id` | `String(20)` | Anchor name from source, e.g. `sect1` |
| `narrative` | `Text` | Full narrative HTML (styled for display) |
| `is_death` | `Boolean` | Scene results in character death |
| `is_victory` | `Boolean` | Scene completes the book |
| `must_eat` | `Boolean` | Scene requires a meal check |
| `loses_backpack` | `Boolean` | Scene causes loss of all backpack items and meals. Default false. |
| `illustration_path` | `String(255)` NULLABLE | Relative path to illustration image file |
| `phase_sequence_override` | `Text` NULLABLE | JSON array overriding the default phase sequence (see game-engine.md). Null = use computed default. |
| `source` | `String(10)` | `auto` or `manual` — controls parser re-run behavior |

**Unique constraint**: `(book_id, number)`

### `choices`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | Source scene |
| `target_scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT NULLABLE | Destination (null if unresolvable) |
| `target_scene_number` | `Integer` | Raw target number from XHTML |
| `raw_text` | `Text` | Original choice text from XHTML |
| `display_text` | `Text` | Rewritten text (Haiku-generated, page-agnostic) |
| `condition_type` | `String(30)` NULLABLE | `discipline`, `item`, `gold`, `random`, `none` |
| `condition_value` | `Text` NULLABLE | Simple string (e.g. `Sixth Sense`, `10`) or JSON for compound conditions (e.g. `{"any": ["Tracking", "Huntmastery"]}`) |
| `ordinal` | `Integer` | Display order within scene |
| `source` | `String(10)` | `auto` or `manual` |

### `choice_random_outcomes`

Outcome bands for choice-triggered random rolls. When a choice leads to a roll (e.g., "try to run away" → roll → different scenes), the parent choice has `target_scene_id = null` and outcome bands are stored here. The API returns these bands when the player selects the choice, then the player calls `/roll` to resolve.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `choice_id` | `Integer` FK → `choices.id` ON DELETE RESTRICT | Parent choice (has `target_scene_id = null`) |
| `range_min` | `Integer` | Lower bound of number range (0–9) |
| `range_max` | `Integer` | Upper bound of number range (0–9) |
| `target_scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | Destination scene for this outcome |
| `target_scene_number` | `Integer` | Raw target number from XHTML |
| `narrative_text` | `Text` NULLABLE | Flavor text for this outcome |
| `source` | `String(10)` | `auto` or `manual` |

**Unique constraint**: `(choice_id, range_min, range_max)`

Distinct from `random_outcomes` (phase-based random effects) and from choices with `condition_type='random'` (scene-level random exits where ALL choices are random-gated). This table handles the third random pattern: player selects a specific choice, then rolls.

### `combat_encounters`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | |
| `foe_game_object_id` | `Integer` FK → `game_objects.id` ON DELETE RESTRICT NULLABLE | Link to foe game_object |
| `enemy_name` | `String(100)` | e.g. `Kraan`, `Giak 1` (denormalized from game_object if linked) |
| `enemy_cs` | `Integer` | Enemy Combat Skill |
| `enemy_end` | `Integer` | Enemy Endurance |
| `ordinal` | `Integer` | Order within scene (for multi-enemy) |
| `mindblast_immune` | `Boolean` | Enemy immune to Mindblast |
| `evasion_after_rounds` | `Integer` NULLABLE | Can evade after N rounds |
| `evasion_target` | `Integer` NULLABLE | Scene number to turn to on evasion |
| `evasion_damage` | `Integer` | Damage dealt to hero on evasion. Default 0. |
| `condition_type` | `String(30)` NULLABLE | `discipline`, `item`, `none`. If set, combat only triggers when condition is NOT met. Null = always fight. |
| `condition_value` | `String(100)` NULLABLE | e.g. `Camouflage`, `Vordak Gem`. The value that, if present, lets you SKIP this combat. |
| `source` | `String(10)` | `auto` or `manual` |

### `combat_results`

The standard Combat Results Table — era-scoped (same CRT shared by all books in an era).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `era` | `String(20)` | `kai`, `magnakai`, `grand_master`, `new_order`. One CRT per era, shared by all books in that era. |
| `random_number` | `Integer` | 0–9 |
| `combat_ratio_min` | `Integer` | Lower bound of CR bracket |
| `combat_ratio_max` | `Integer` | Upper bound of CR bracket |
| `enemy_loss` | `Integer` NULLABLE | Null = kill (`k`) |
| `hero_loss` | `Integer` NULLABLE | Null = kill (`k`) |

The CRT has 13 combat ratio brackets × 10 random numbers = 130 rows per era. `NULL` in `enemy_loss` or `hero_loss` represents an instant kill (`k`).

**Sentinel values for bracket edges**: Bracket 1 (CR ≤ −11) uses `combat_ratio_min = -999`. Bracket 13 (CR ≥ +11) uses `combat_ratio_max = 999`. CRT lookup query: `WHERE combat_ratio_min <= :ratio AND combat_ratio_max >= :ratio`.

### `disciplines`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `era` | `String(20)` | `kai`, `magnakai`, `grand_master`, `new_order`. Disciplines are era-scoped — one set per era, shared by all books in that era. |
| `name` | `String(50)` | e.g. `Camouflage`, `Weaponmastery` |
| `html_id` | `String(30)` | Anchor name, e.g. `camflage`, `wpnmstry` |
| `description` | `Text` | Rule text |
| `mechanical_effect` | `String(200)` NULLABLE | Machine-readable effect, e.g. `+2 CS`, `+1 END/scene` |

**Unique constraint**: `(era, name)`

### `scene_items`

Items that can be picked up or lost in a scene. Weapon/backpack/special items with `action='gain'` require explicit player pickup (accept or decline) before the character can make choices. Gold and meal items with `action='gain'` are auto-applied during phase progression (no accept/decline needed). Items with `is_mandatory=true` cannot be declined and override slot limits — the player gets the item even if over capacity; the next items phase forces resolution.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | |
| `game_object_id` | `Integer` FK → `game_objects.id` ON DELETE RESTRICT NULLABLE | Link to item game_object (taxonomy) |
| `item_name` | `String(100)` | Display name |
| `item_type` | `String(20)` | `weapon`, `backpack`, `special`, `gold`, `meal` |
| `quantity` | `Integer` | Default 1; for gold, the amount |
| `action` | `String(10)` | `gain` or `lose` |
| `is_mandatory` | `Boolean` | If true, item cannot be declined during items phase. Player must accept (managing inventory if needed). Default false. |
| `phase_ordinal` | `Integer` | Position in the scene's phase sequence |
| `source` | `String(10)` | `auto` or `manual` |

### `weapon_categories`

Maps weapon names to categories for Weaponskill/Weaponmastery matching.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `weapon_name` | `String(100)` UNIQUE | e.g. `Broadsword`, `Short Sword` |
| `category` | `String(50)` | e.g. `Sword`, `Axe`, `Mace` |

Weaponskill/Weaponmastery bonuses apply when the equipped weapon's category matches the character's chosen weapon type. Parser seeds this table; admin can add/correct entries.

### `random_outcomes`

Outcome bands for phase-based random rolls. Each row represents one outcome for a number range within a scene's random phase. Distinct from choice-based random branching (which uses `condition_type='random'` on choices).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | |
| `roll_group` | `Integer` | Roll group within the scene. Default 0. Scenes with multiple sequential rolls use groups 0, 1, 2, etc. |
| `range_min` | `Integer` | Lower bound of number range (0–9) |
| `range_max` | `Integer` | Upper bound of number range (0–9) |
| `effect_type` | `String(30)` | `gold_change`, `endurance_change`, `item_gain`, `item_loss`, `meal_change`, `scene_redirect` |
| `effect_value` | `String(200)` | JSON: e.g. `{"amount": 5}`, `{"item_name": "Sword", "item_type": "weapon"}`, `{"scene_number": 200}` |
| `narrative_text` | `Text` NULLABLE | Flavor text describing this outcome to the player |
| `ordinal` | `Integer` | Display order within scene |
| `source` | `String(10)` | `auto` or `manual` |

**Unique constraint**: `(scene_id, roll_group, range_min, range_max)`

### `combat_modifiers`

Special combat rules that apply to specific encounters.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `combat_encounter_id` | `Integer` FK → `combat_encounters.id` ON DELETE RESTRICT | |
| `modifier_type` | `String(30)` | `cs_bonus`, `cs_penalty`, `double_damage`, `undead`, `enemy_mindblast`, etc. |
| `modifier_value` | `String(100)` NULLABLE | Numeric or descriptive |
| `condition` | `String(200)` NULLABLE | When the modifier applies |
| `source` | `String(10)` | `auto` or `manual` |

`enemy_mindblast` modifier type: when present, hero suffers -2 CS unless they have Mindshield discipline.

## Game Object Taxonomy

A Kind-based knowledge graph of the Lone Wolf universe. All world entities, items, foes, and scenes are unified as game objects with typed refs. Populated by LLM extraction during import, refined via admin. Follows the ops.md GameObject pattern.

### `game_objects`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `kind` | `String(30)` | `character`, `location`, `creature`, `organization`, `item`, `foe`, `scene` |
| `name` | `String(200)` | Canonical name |
| `description` | `Text` NULLABLE | LLM-generated or admin-written summary |
| `aliases` | `Text` NOT NULL | JSON array of alternate names (e.g. `["Lone Wolf", "Silent Wolf", "Grand Master"]`). Default `[]`. Never NULL — SQLAlchemy `default=list`, `server_default='[]'`. |
| `properties` | `Text` NOT NULL | JSON blob for kind-specific data (see below). Default `{}`. Never NULL — SQLAlchemy `default=dict`, `server_default='{}'`. |
| `first_book_id` | `Integer` FK → `books.id` ON DELETE RESTRICT NULLABLE | Book of first appearance |
| `source` | `String(10)` | `auto` or `manual` |

**Unique constraint**: `(name, kind)`

**Properties blob examples by kind**:
- character: `{"title": "Grand Master", "race": "Sommlending", "allegiance": "Kai"}`
- location: `{"region": "Sommerlund", "type": "city"}`
- creature: `{"species": "Kraan", "allegiance": "Darklords"}`
- organization: `{"type": "order", "base": "Kai Monastery"}`
- item: `{"item_type": "weapon", "category": "Sword", "is_special": false}`
- foe: `{"base_cs": 16, "base_end": 24, "mindblast_immune": false}`
- scene: `{"book_number": 1, "scene_number": 1}` (minimal — gameplay data lives in scenes table)

### `game_object_refs`

Minimal tagged refs following the ops.md pattern. Replaces separate appearances and relationship tables. A single unified table for all inter-object links.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `source_id` | `Integer` FK → `game_objects.id` ON DELETE RESTRICT | |
| `target_id` | `Integer` FK → `game_objects.id` ON DELETE RESTRICT | |
| `tags` | `Text` | JSON array encoding category + type/role (see examples below) |
| `metadata` | `Text` NULLABLE | JSON blob for context, notes, quantities, etc. |
| `source` | `String(10)` | `auto` or `manual` |

Tags encode both the relationship category and the specific type/role. Examples:
- Entity appears in scene: `["appearance", "combatant"]`, metadata: `{"context": "Kraan attacks from above"}`
- Spatial relationship: `["spatial", "located_in"]`, metadata: `{"notes": "Capital city of Sommerlund"}`
- Social relationship: `["social", "trained_by"]`
- Factional: `["factional", "member_of"]`
- Item wielded by character: `["factional", "wields"]`

**Tag categories**: `appearance`, `social`, `spatial`, `factional`, `temporal`, `causal`

**Uniqueness**: Application-level enforcement on `(source_id, target_id, tags)`.

### `book_transition_rules`

Defines carry-over rules between books. Populated by parser or admin.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `from_book_id` | `Integer` FK → `books.id` ON DELETE RESTRICT | Book being completed |
| `to_book_id` | `Integer` FK → `books.id` ON DELETE RESTRICT | Next book |
| `max_weapons` | `Integer` | How many weapons can carry over |
| `max_backpack_items` | `Integer` | How many backpack items carry over |
| `special_items_carry` | `Boolean` | Whether special items carry over |
| `gold_carries` | `Boolean` | Whether gold carries over |
| `new_disciplines_count` | `Integer` | How many new disciplines the player picks |
| `base_cs_override` | `Integer` NULLABLE | New base CS if era changes |
| `base_end_override` | `Integer` NULLABLE | New base END if era changes |
| `notes` | `Text` NULLABLE | Free text for special rules |

**Unique constraint**: `(from_book_id, to_book_id)`

### `book_starting_equipment`

Available equipment for character creation per book. Drives the equipment wizard step.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `book_id` | `Integer` FK → `books.id` ON DELETE RESTRICT | |
| `game_object_id` | `Integer` FK → `game_objects.id` ON DELETE RESTRICT NULLABLE | Link to item game_object |
| `item_name` | `String(100)` | Display name |
| `item_type` | `String(20)` | `weapon`, `backpack`, `special`, `gold`, `meal` |
| `category` | `String(30)` | Grouping for display (e.g., `weapons`, `backpack`, `special`) |
| `is_default` | `Boolean` | Whether this item is given automatically (not a choice) |
| `source` | `String(10)` | `auto` or `manual` |

Note: The pick limit is stored on `books.max_total_picks` (not per-row). `max_picks_in_category` has been removed — the limit is global, not per-category.

## Player Tables

### `users`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `username` | `String(50)` UNIQUE | |
| `email` | `String(255)` UNIQUE | |
| `password_hash` | `String(255)` | bcrypt |
| `max_characters` | `Integer` | Maximum characters this user can create. Default: 3. Configurable by admin. |
| `password_changed_at` | `DateTime` NULLABLE | Set on password change. Tokens with `issued_at` before this value are rejected. |
| `created_at` | `DateTime` | |

### `characters`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `user_id` | `Integer` FK → `users.id` ON DELETE RESTRICT | |
| `name` | `String(100)` | Player-chosen name |
| `book_id` | `Integer` FK → `books.id` ON DELETE RESTRICT | Current book |
| `current_scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT NULLABLE | Current position |
| `scene_phase` | `String(20)` NULLABLE | Current phase within scene: `items`, `combat`, `random`, `choices`. Null if no active phase. Automatic phases (`eat`, `heal`, `item_loss`, `backpack_loss`) are never stored here — they complete atomically during transitions. |
| `scene_phase_index` | `Integer` NULLABLE | Index into the scene's phase sequence (0-based). |
| `active_combat_encounter_id` | `Integer` FK → `combat_encounters.id` ON DELETE SET NULL NULLABLE | Set when combat begins, cleared on win/loss/evasion. |
| `active_wizard_id` | `Integer` FK → `character_wizard_progress.id` ON DELETE SET NULL NULLABLE | Set when character is in any wizard (creation, book advance). Null when not in a wizard. |
| `pending_choice_id` | `Integer` FK → `choices.id` ON DELETE RESTRICT NULLABLE | Set when `/choose` returns `requires_roll: true`, cleared on `/roll` resolution. Classified as Ref field. |
| `combat_skill_base` | `Integer` | Initial CS (10 + random 0–9) |
| `endurance_base` | `Integer` | Initial END (20 + random 0–9) |
| `endurance_max` | `Integer` | Maximum END (base + permanent bonuses like lore-circles). Healing caps at this value. |
| `endurance_current` | `Integer` | Current END |
| `gold` | `Integer` | 0–50. On pickup, partial acceptance up to cap (auto-applied). |
| `meals` | `Integer` | Meal count. 0–8 (capped at 8). On pickup, partial acceptance up to cap. Sole source of truth for meals — meals are NOT tracked as character_items. Do not count against backpack limit. |
| `is_alive` | `Boolean` | |
| `is_deleted` | `Boolean` | Soft delete flag. |
| `deleted_at` | `DateTime` NULLABLE | When the character was soft-deleted |
| `death_count` | `Integer` | Number of times this character has died and restarted |
| `current_run` | `Integer` | Current run number (starts at 1) |
| `version` | `Integer` | Optimistic locking counter. Incremented on every state mutation. Default 1. |
| `rule_overrides` | `Text` NULLABLE | JSON blob for per-character rule config. Null = use defaults. See game-engine.md. |
| `created_at` | `DateTime` | |
| `updated_at` | `DateTime` | |

### `character_disciplines`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT | |
| `discipline_id` | `Integer` FK → `disciplines.id` ON DELETE RESTRICT | |
| `weapon_category` | `String(30)` NULLABLE | Only for Weaponskill/Weaponmastery |

**Unique constraint**: `(character_id, discipline_id)`

### `character_items`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT | |
| `game_object_id` | `Integer` FK → `game_objects.id` ON DELETE RESTRICT NULLABLE | Link to item game_object (taxonomy). Parser links when possible. |
| `item_name` | `String(100)` | |
| `item_type` | `String(20)` | `weapon`, `backpack`, `special` |
| `is_equipped` | `Boolean` | For weapons |

Note: Meals are tracked as the `meals` integer on `characters`, NOT as `character_items` rows.

### `character_book_starts`

Snapshot of character state at the beginning of each book, used for death-restart.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT | |
| `book_id` | `Integer` FK → `books.id` ON DELETE RESTRICT | |
| `combat_skill_base` | `Integer` | |
| `endurance_base` | `Integer` | |
| `endurance_max` | `Integer` | Snapshot of endurance_max at book start |
| `endurance_current` | `Integer` | |
| `gold` | `Integer` | |
| `meals` | `Integer` | |
| `items_json` | `Text` | JSON array of character items at book start |
| `disciplines_json` | `Text` | JSON array of discipline IDs at book start |
| `created_at` | `DateTime` | |

**Unique constraint**: `(character_id, book_id)`

**Snapshot JSON schemas**:

`items_json` — array of item objects:
```json
[
  {"item_name": "Sword", "item_type": "weapon", "is_equipped": true, "game_object_id": 42},
  {"item_name": "Healing Potion", "item_type": "backpack", "is_equipped": false, "game_object_id": null}
]
```
Fields: `item_name` (str), `item_type` (str: `weapon`, `backpack`, `special`), `is_equipped` (bool), `game_object_id` (int or null).

`disciplines_json` — array of discipline objects:
```json
[
  {"discipline_id": 3, "weapon_category": null},
  {"discipline_id": 6, "weapon_category": "Sword"}
]
```
Fields: `discipline_id` (int), `weapon_category` (str or null — only set for Weaponskill/Weaponmastery entries).

### `decision_log`

Every choice the character makes, for full history and replay. Tagged by run.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT | |
| `run_number` | `Integer` | Which attempt at this book (1-indexed) |
| `from_scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | |
| `to_scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | |
| `choice_id` | `Integer` FK → `choices.id` ON DELETE RESTRICT NULLABLE | Null for combat/random outcomes |
| `action_type` | `String(20)` | `choice`, `combat_win`, `combat_evasion`, `random`, `death`, `restart`, `replay` |
| `details` | `Text` NULLABLE | JSON blob for combat rounds, items gained/lost, etc. |
| `created_at` | `DateTime` | |

### `combat_rounds`

Full round-by-round combat history. Current combat state derived from latest round.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT | |
| `combat_encounter_id` | `Integer` FK → `combat_encounters.id` ON DELETE RESTRICT | |
| `round_number` | `Integer` | 1-indexed |
| `random_number` | `Integer` | Server-generated, 0–9 |
| `combat_ratio` | `Integer` | Computed CR for this round |
| `enemy_loss` | `Integer` NULLABLE | Null = instant kill |
| `hero_loss` | `Integer` NULLABLE | Null = instant kill |
| `enemy_end_remaining` | `Integer` | Enemy endurance after this round |
| `hero_end_remaining` | `Integer` | Hero endurance after this round |
| `psi_surge_used` | `Boolean` | Whether Psi-surge was active this round |
| `created_at` | `DateTime` | |

**Unique constraint**: `(character_id, combat_encounter_id, round_number)`

### `character_events`

Generic state-change audit trail. One row per phase step completion. Tracks every meaningful state change a character undergoes, tied to the scene and run that caused it. Events follow the ops.md dual-layer design: `event_type` carries semantic meaning (what happened), while `operations` records atomic mutations (the mechanical layer). The `seq` column provides strict per-character ordering. The `parent_event_id` enables causality tracking — when one event triggers another (e.g., meal penalty causing death), the child references its parent.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT | |
| `scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT | Scene where the event occurred |
| `run_number` | `Integer` | Which attempt at this book |
| `event_type` | `String(30)` | `item_pickup`, `item_decline`, `item_loss`, `item_loss_skip`, `item_consumed`, `meal_consumed`, `meal_penalty`, `gold_change`, `endurance_change`, `healing`, `combat_start`, `combat_end`, `combat_skipped`, `evasion`, `death`, `restart`, `replay`, `discipline_gained`, `book_advance`, `random_roll`, `backpack_loss` |
| `phase` | `String(20)` NULLABLE | Which scene phase produced this event |
| `details` | `Text` NULLABLE | JSON blob with event-specific data |
| `seq` | `Integer` | Per-character sequence number. Strict ordering independent of timestamp. Generated via `SELECT MAX(seq)+1 WHERE character_id=?` within the same transaction. Safe because optimistic locking prevents concurrent character mutations. |
| `operations` | `Text` NULLABLE | JSON array of ops.md operations (e.g., `[{"op": "meter.delta", "field": "endurance_current", "delta": -3}]`). Records mechanical mutations alongside semantic event_type. |
| `parent_event_id` | `Integer` FK → `character_events.id` ON DELETE SET NULL NULLABLE | Causality chain. Points to the event that triggered this one (e.g., meal_penalty → death). Null for root events. |
| `created_at` | `DateTime` | |

Coexists with `decision_log` (navigation/choice history) and `combat_rounds` (round-by-round combat detail). The events table captures state mutations; the other tables capture gameplay decisions and combat mechanics.

### Field Classification (Spec / Status / Meter / Ref / Metadata)

Classification of each `characters` column by ops.md field layer:

| Column | Layer | Notes |
|--------|-------|-------|
| `name` | Spec | Player-authored |
| `combat_skill_base` | Spec | Set at creation, changed on era transition |
| `endurance_base` | Spec | Set at creation, changed on era transition |
| `endurance_max` | Status | Computed from endurance_base + lore-circle bonuses |
| `endurance_current` | Meter | Bounded [0, endurance_max]. Underflow = death |
| `gold` | Meter | Bounded [0, 50]. Overflow = partial acceptance |
| `meals` | Meter | Bounded [0, 8]. Overflow = partial acceptance |
| `is_alive` | Status | Derived from endurance_current reaching 0 |
| `current_scene_id` | Ref | Current position |
| `active_combat_encounter_id` | Ref | Current combat |
| `active_wizard_id` | Ref | Current wizard |
| `pending_choice_id` | Ref | Set during choice-triggered roll, cleared on resolution |
| `death_count`, `current_run` | Spec | Incremented on restart/replay |
| `version` | Metadata | Optimistic locking counter |
| `rule_overrides` | Spec | Per-character config |
| `scene_phase`, `scene_phase_index` | Status | Derived from phase progression |
| Timestamps, `is_deleted`, `user_id`, `book_id` | Metadata/Ref | System fields |

## Wizard Tables

Data-driven wizard system used by both character creation and book advance.

### `wizard_templates`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `name` | `String(50)` UNIQUE | e.g., `character_creation`, `book_advance` |
| `description` | `Text` NULLABLE | |

### `wizard_template_steps`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `template_id` | `Integer` FK → `wizard_templates.id` ON DELETE RESTRICT | |
| `step_type` | `String(30)` | `stat_roll`, `pick_disciplines`, `pick_equipment`, `pick_weapon_skill`, `inventory_adjust`, `confirm` |
| `config` | `Text` NULLABLE | JSON config for the step (e.g., `{"count": 5}` for discipline count, `{"categories": ["weapons", "backpack"]}` for equipment) |
| `ordinal` | `Integer` | Order within the wizard |

### `character_wizard_progress`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT | |
| `wizard_template_id` | `Integer` FK → `wizard_templates.id` ON DELETE RESTRICT | |
| `current_step_index` | `Integer` | 0-based index into wizard_template_steps |
| `state` | `Text` NULLABLE | JSON blob for accumulated wizard state (selected disciplines, rolled stats, equipment choices, etc.) |
| `started_at` | `DateTime` | |
| `completed_at` | `DateTime` NULLABLE | |

**Wizard state JSON schemas** (stored in `state` column):

Character creation state (accumulated as player progresses through `pick_equipment` and `confirm` steps):
```json
{
  "gold": 7,
  "meals": 1,
  "selected_items": [
    {"item_name": "Sword", "item_type": "weapon", "game_object_id": 12}
  ]
}
```

Book advance state (accumulated as player progresses through `pick_disciplines`, `pick_equipment`, `inventory_adjust`, and `confirm` steps):
```json
{
  "new_disciplines": [11],
  "weapon_category": "Sword",
  "kept_weapons": ["Sword", "Axe"],
  "kept_backpack": ["Healing Potion"],
  "gold_rolled": 14
}
```
Fields: `new_disciplines` (list of discipline IDs), `weapon_category` (str or null — only set when picked discipline is Weaponskill/Weaponmastery), `kept_weapons` (list of weapon names to carry forward), `kept_backpack` (list of backpack item names), `gold_rolled` (int — the gold roll result, added to existing gold).

## Admin Tables

### `admin_users`

Separate from player accounts. First admin created via CLI command (`scripts/create_admin.py`).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `username` | `String(50)` UNIQUE | |
| `password_hash` | `String(255)` | bcrypt |
| `created_at` | `DateTime` | |

### `reports`

Player-submitted bug reports.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `user_id` | `Integer` FK → `users.id` ON DELETE RESTRICT | Reporter |
| `character_id` | `Integer` FK → `characters.id` ON DELETE RESTRICT NULLABLE | Character at time of report |
| `scene_id` | `Integer` FK → `scenes.id` ON DELETE RESTRICT NULLABLE | Scene where issue occurred |
| `tags` | `Text` | JSON array of category tags |
| `free_text` | `Text` NULLABLE | Optional description |
| `status` | `String(20)` | `open`, `triaging`, `resolved`, `wont_fix` |
| `admin_notes` | `Text` NULLABLE | Admin triage notes |
| `resolved_by` | `Integer` FK → `admin_users.id` ON DELETE RESTRICT NULLABLE | |
| `created_at` | `DateTime` | |
| `updated_at` | `DateTime` | |

**Report tags** (predefined, multi-select): `wrong_items`, `meal_issue`, `missing_choice`, `combat_issue`, `narrative_error`, `discipline_issue`, `other`

## Relationships

```
books 1──∞ scenes 1──∞ choices 1──∞ choice_random_outcomes
                  1──∞ combat_encounters 1──∞ combat_modifiers
                  1──∞ scene_items
                  1──∞ random_outcomes
combat_results scoped by era (not FK to books)
disciplines scoped by era (not FK to books)
books 1──∞ book_transition_rules (as from_book or to_book)
books 1──∞ book_starting_equipment

scenes ∞──1 game_objects (game_object_id, 1:1)
combat_encounters ∞──1 game_objects (foe_game_object_id)
scene_items ∞──1 game_objects (game_object_id, nullable)

game_objects 1──∞ game_object_refs (as source)
game_objects 1──∞ game_object_refs (as target)

weapon_categories (standalone lookup)

wizard_templates 1──∞ wizard_template_steps
wizard_templates 1──∞ character_wizard_progress

users 1──∞ characters 1──∞ character_disciplines
                      1──∞ character_items
                      1──∞ character_book_starts
                      1──∞ decision_log
                      1──∞ combat_rounds
                      1──∞ character_events
                      1──∞ character_wizard_progress
characters ∞──1 combat_encounters (active_combat_encounter_id)
characters ∞──1 character_wizard_progress (active_wizard_id)
character_items ∞──1 game_objects (game_object_id, nullable)
users 1──∞ reports
```

## Indexes

- `scenes(book_id, number)` — unique, fast lookup by book + scene number
- `choices(scene_id)` — all choices for a scene
- `combat_encounters(scene_id)` — combats in a scene
- `combat_results(era, random_number, combat_ratio_min)` — CRT lookup
- `characters(user_id)` — list user's characters
- `characters(user_id, is_deleted)` — list user's active characters
- `decision_log(character_id, run_number, created_at)` — character history per run
- `combat_rounds(character_id, combat_encounter_id, round_number)` — combat state lookup
- `character_events(character_id, scene_id, created_at)` — events per scene visit
- `character_events(character_id, event_type)` — filter by event type
- `character_events(character_id, seq)` — ordered event replay
- `character_events(parent_event_id)` — causality chain traversal
- `reports(status, created_at)` — admin queue ordering
- `game_objects(kind)` — filter by kind
- `game_objects(kind, name)` — lookup by kind + name
- `game_object_refs(source_id)` — outgoing refs
- `game_object_refs(target_id)` — incoming refs
- `weapon_categories(category)` — lookup weapons by category
- `random_outcomes(scene_id, roll_group)` — outcomes for a scene's random phase by group
- `choice_random_outcomes(choice_id)` — outcome bands for choice-triggered random
- `book_starting_equipment(book_id)` — equipment list per book
- `character_disciplines(character_id, discipline_id)` — has_discipline() lookups (also unique constraint)
- `character_items(character_id, item_type)` — count_weapons() / count_backpack() checks
- `character_wizard_progress(character_id, completed_at)` — finding active wizards
- `decision_log(character_id, run_number)` — per-run aggregation

## Migration Strategy

- Alembic with auto-generation from SQLAlchemy models
- Content tables seeded by the parser (`scripts/seed_db.py`)
- Player tables created empty on first migration
- Wizard templates seeded by a fixture script or parser
- First admin created via CLI command (`scripts/create_admin.py`)
- Illustrations stored on filesystem at `static/images/{book_slug}/`; paths stored in `scenes.illustration_path`
