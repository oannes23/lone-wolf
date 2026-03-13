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

### `sections`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | Auto-increment |
| `book_id` | `Integer` FK → `books.id` | |
| `number` | `Integer` | Section number within book |
| `html_id` | `String(20)` | Anchor name, e.g. `sect1` |
| `narrative` | `Text` | Full narrative HTML (styled for display) |
| `is_death` | `Boolean` | Section results in character death |
| `is_victory` | `Boolean` | Section completes the book |
| `must_eat` | `Boolean` | Section requires a meal check |
| `illustration_path` | `String(255)` NULLABLE | Relative path to illustration image file |
| `phase_sequence_override` | `Text` NULLABLE | JSON array overriding the default phase sequence (see game-engine.md). Null = use computed default. |
| `source` | `String(10)` | `auto` or `manual` — controls parser re-run behavior |

**Unique constraint**: `(book_id, number)`

### `choices`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `section_id` | `Integer` FK → `sections.id` | Source section |
| `target_section_id` | `Integer` FK → `sections.id` NULLABLE | Destination (null if unresolvable) |
| `target_section_number` | `Integer` | Raw target number from XHTML |
| `raw_text` | `Text` | Original choice text from XHTML |
| `display_text` | `Text` | Rewritten text (Haiku-generated, page-agnostic) |
| `condition_type` | `String(30)` NULLABLE | `discipline`, `item`, `gold`, `random`, `none` |
| `condition_value` | `String(100)` NULLABLE | e.g. `Sixth Sense`, `Vordak Gem`, `10` |
| `ordinal` | `Integer` | Display order within section |
| `source` | `String(10)` | `auto` or `manual` |

### `combat_encounters`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `section_id` | `Integer` FK → `sections.id` | |
| `enemy_name` | `String(100)` | e.g. `Kraan`, `Giak 1` |
| `enemy_cs` | `Integer` | Enemy Combat Skill |
| `enemy_end` | `Integer` | Enemy Endurance |
| `ordinal` | `Integer` | Order within section (for multi-enemy) |
| `mindblast_immune` | `Boolean` | Enemy immune to Mindblast |
| `evasion_after_rounds` | `Integer` NULLABLE | Can evade after N rounds |
| `evasion_target` | `Integer` NULLABLE | Section number to turn to on evasion |
| `condition_type` | `String(30)` NULLABLE | `discipline`, `item`, `none`. If set, combat only triggers when condition is NOT met (e.g., combat if you lack Camouflage). Null = always fight. |
| `condition_value` | `String(100)` NULLABLE | e.g. `Camouflage`, `Vordak Gem`. The value that, if present, lets you SKIP this combat. |
| `source` | `String(10)` | `auto` or `manual` |

### `combat_results`

The standard Combat Results Table — same across all Kai-era books.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `book_id` | `Integer` FK → `books.id` | |
| `random_number` | `Integer` | 0–9 |
| `combat_ratio_min` | `Integer` | Lower bound of CR bracket |
| `combat_ratio_max` | `Integer` | Upper bound of CR bracket |
| `enemy_loss` | `Integer` NULLABLE | Null = kill (`k`) |
| `hero_loss` | `Integer` NULLABLE | Null = kill (`k`) |

The CRT has 13 combat ratio brackets × 10 random numbers = 130 rows per book. `NULL` in `enemy_loss` or `hero_loss` represents an instant kill (`k`).

### `disciplines`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `book_id` | `Integer` FK → `books.id` | Book that defines this discipline set |
| `era` | `String(20)` | `kai`, `magnakai`, `grand_master`, `new_order` |
| `name` | `String(50)` | e.g. `Camouflage`, `Weaponmastery` |
| `html_id` | `String(30)` | Anchor name, e.g. `camflage`, `wpnmstry` |
| `description` | `Text` | Rule text |
| `mechanical_effect` | `String(200)` NULLABLE | Machine-readable effect, e.g. `+2 CS`, `+1 END/section` |

### `section_items`

Items that can be picked up or lost in a section. Items with `action='gain'` require explicit player pickup (accept or decline) before the character can make choices.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `section_id` | `Integer` FK → `sections.id` | |
| `item_name` | `String(100)` | |
| `item_type` | `String(20)` | `weapon`, `backpack`, `special`, `gold`, `meal` |
| `quantity` | `Integer` | Default 1; for gold, the amount |
| `action` | `String(10)` | `gain` or `lose` |
| `phase_ordinal` | `Integer` | Position in the section's phase sequence (for items that appear before or after combat) |
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

Outcome bands for phase-based random rolls. Each row represents one outcome for a number range within a section's random phase. Distinct from choice-based random branching (which uses `condition_type='random'` on choices).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `section_id` | `Integer` FK → `sections.id` | |
| `range_min` | `Integer` | Lower bound of number range (0–9) |
| `range_max` | `Integer` | Upper bound of number range (0–9) |
| `effect_type` | `String(30)` | `gold_change`, `endurance_change`, `item_gain`, `item_loss`, `meal_change`, `section_redirect` |
| `effect_value` | `String(200)` | JSON: e.g. `{"amount": 5}`, `{"item_name": "Sword", "item_type": "weapon"}`, `{"section_number": 200}` |
| `narrative_text` | `Text` NULLABLE | Flavor text describing this outcome to the player |
| `ordinal` | `Integer` | Display order within section |
| `source` | `String(10)` | `auto` or `manual` |

**Unique constraint**: `(section_id, range_min, range_max)`

### `combat_modifiers`

Special combat rules that apply to specific encounters.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `combat_encounter_id` | `Integer` FK → `combat_encounters.id` | |
| `modifier_type` | `String(30)` | `cs_bonus`, `cs_penalty`, `double_damage`, `undead`, etc. |
| `modifier_value` | `String(100)` NULLABLE | Numeric or descriptive |
| `condition` | `String(200)` NULLABLE | When the modifier applies |

## World Taxonomy Tables

A knowledge graph of the Lone Wolf universe. Populated by LLM extraction during import, refined via admin. Tracks characters, locations, creatures, and organizations across all books and sections — including both direct appearances and narrative references.

### `world_entities`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `name` | `String(200)` | Canonical name |
| `entity_type` | `String(30)` | `character`, `location`, `creature`, `organization` |
| `description` | `Text` NULLABLE | LLM-generated summary, refined by admin |
| `aliases` | `Text` NULLABLE | JSON array of alternate names (e.g. `["Lone Wolf", "Silent Wolf", "Grand Master"]`) |
| `first_book_id` | `Integer` FK → `books.id` NULLABLE | Book of first appearance |
| `first_section_id` | `Integer` FK → `sections.id` NULLABLE | Section of first appearance |
| `properties` | `Text` NULLABLE | JSON blob for type-specific data (see below) |
| `source` | `String(10)` | `auto` or `manual` |

**Unique constraint**: `(name, entity_type)`

**Properties blob examples by type**:
- Character: `{"title": "Grand Master", "race": "Sommlending", "allegiance": "Kai"}`
- Location: `{"region": "Sommerlund", "type": "city"}`
- Creature: `{"species": "Kraan", "allegiance": "Darklords"}`
- Organization: `{"type": "order", "base": "Kai Monastery"}`

### `world_entity_appearances`

Links entities to every section they appear in, including narrative references.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `entity_id` | `Integer` FK → `world_entities.id` | |
| `section_id` | `Integer` FK → `sections.id` | |
| `role` | `String(50)` | `combatant`, `quest_giver`, `ally`, `mentioned`, `visited`, `origin`, `obstacle`, etc. |
| `context` | `Text` NULLABLE | LLM-generated snippet describing the entity's role in this section |
| `source` | `String(10)` | `auto` or `manual` |

**Unique constraint**: `(entity_id, section_id)`

### `world_entity_relationships`

Typed, directed relationships between entities. Builds a knowledge graph.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `entity_a_id` | `Integer` FK → `world_entities.id` | Subject entity |
| `entity_b_id` | `Integer` FK → `world_entities.id` | Object entity |
| `relationship_category` | `String(20)` | `social`, `spatial`, `factional`, `temporal`, `causal` |
| `relationship_type` | `String(50)` | Freeform within category (e.g. `rules`, `trained_by`, `located_in`, `allied_with`) |
| `source` | `String(10)` | `auto` or `manual` |

**Unique constraint**: `(entity_a_id, entity_b_id, relationship_type)`

**Relationship categories and example types**:

| Category | Example Types |
|----------|---------------|
| `social` | `trained_by`, `betrayed`, `parent_of`, `serves` |
| `spatial` | `located_in`, `borders`, `contains`, `originates_from` |
| `factional` | `member_of`, `allied_with`, `enemy_of`, `rules` |
| `temporal` | `preceded_by`, `created`, `destroyed` |
| `causal` | `caused`, `prevented`, `enabled`, `forged` |

### `book_transition_rules`

Defines carry-over rules between books. Populated by parser or admin.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `from_book_id` | `Integer` FK → `books.id` | Book being completed |
| `to_book_id` | `Integer` FK → `books.id` | Next book |
| `max_weapons` | `Integer` | How many weapons can carry over |
| `max_backpack_items` | `Integer` | How many backpack items carry over |
| `special_items_carry` | `Boolean` | Whether special items carry over |
| `gold_carries` | `Boolean` | Whether gold carries over |
| `new_disciplines_count` | `Integer` | How many new disciplines the player picks |
| `base_cs_override` | `Integer` NULLABLE | New base CS if era changes (e.g., Grand Master = 15 + random) |
| `base_end_override` | `Integer` NULLABLE | New base END if era changes |
| `notes` | `Text` NULLABLE | Free text for special rules |

## Player Tables

### `users`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `username` | `String(50)` UNIQUE | |
| `email` | `String(255)` UNIQUE | |
| `password_hash` | `String(255)` | bcrypt |
| `max_characters` | `Integer` | Maximum characters this user can create. Default: 3. Configurable by admin. |
| `created_at` | `DateTime` | |

### `characters`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `user_id` | `Integer` FK → `users.id` | |
| `name` | `String(100)` | Player-chosen name |
| `book_id` | `Integer` FK → `books.id` | Current book |
| `current_section_id` | `Integer` FK → `sections.id` NULLABLE | Current position |
| `section_phase` | `String(20)` NULLABLE | Current phase within section: `items`, `eat`, `combat`, `heal`, `choices`. Null if no active phase processing. |
| `section_phase_index` | `Integer` NULLABLE | Index into the section's phase sequence (0-based). Tracks position in arbitrary phase ordering. |
| `active_combat_encounter_id` | `Integer` FK → `combat_encounters.id` NULLABLE | Set when combat begins, cleared on win/loss/evasion. Allows combat resume on reconnect. |
| `wizard_step` | `String(20)` NULLABLE | Book advance wizard step: `discipline`, `inventory`, `confirm`. Null when not in wizard. |
| `combat_skill_base` | `Integer` | Initial CS (10 + random 0–9) |
| `endurance_base` | `Integer` | Initial END (20 + random 0–9) |
| `endurance_current` | `Integer` | Current END |
| `gold` | `Integer` | 0–50 |
| `meals` | `Integer` | Meal count |
| `is_alive` | `Boolean` | |
| `is_deleted` | `Boolean` | Soft delete flag. Deleted characters are hidden from player lists but preserved for analytics. Admin can restore. |
| `deleted_at` | `DateTime` NULLABLE | When the character was soft-deleted |
| `death_count` | `Integer` | Number of times this character has died and restarted |
| `current_run` | `Integer` | Current run number (starts at 1) |
| `rule_overrides` | `Text` NULLABLE | JSON blob for per-character rule config (e.g., `{"discipline_stacking": "stack"}`). Null = use defaults. See game-engine.md. |
| `created_at` | `DateTime` | |
| `updated_at` | `DateTime` | |

### `character_disciplines`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` | |
| `discipline_id` | `Integer` FK → `disciplines.id` | |
| `weapon_type` | `String(30)` NULLABLE | Only for Weaponskill/Weaponmastery |

### `character_items`

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` | |
| `item_name` | `String(100)` | |
| `item_type` | `String(20)` | `weapon`, `backpack`, `special`, `meal` |
| `is_equipped` | `Boolean` | For weapons |

### `character_book_starts`

Snapshot of character state at the beginning of each book, used for death-restart.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` | |
| `book_id` | `Integer` FK → `books.id` | |
| `combat_skill_base` | `Integer` | |
| `endurance_base` | `Integer` | |
| `endurance_current` | `Integer` | |
| `gold` | `Integer` | |
| `meals` | `Integer` | |
| `items_json` | `Text` | JSON array of character items at book start |
| `disciplines_json` | `Text` | JSON array of discipline IDs at book start |
| `created_at` | `DateTime` | |

**Unique constraint**: `(character_id, book_id)`

### `decision_log`

Every choice the character makes, for full history and replay. Tagged by run.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` | |
| `run_number` | `Integer` | Which attempt at this book (1-indexed) |
| `from_section_id` | `Integer` FK → `sections.id` | |
| `to_section_id` | `Integer` FK → `sections.id` | |
| `choice_id` | `Integer` FK → `choices.id` NULLABLE | Null for combat/random outcomes |
| `action_type` | `String(20)` | `choice`, `combat_win`, `combat_evasion`, `random`, `death`, `restart` |
| `details` | `Text` NULLABLE | JSON blob for combat rounds, items gained/lost, etc. |
| `created_at` | `DateTime` | |

### `combat_rounds`

Full round-by-round combat history. Current combat state derived from latest round.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` | |
| `combat_encounter_id` | `Integer` FK → `combat_encounters.id` | |
| `round_number` | `Integer` | 1-indexed |
| `random_number` | `Integer` | Server-generated, 0–9 |
| `combat_ratio` | `Integer` | Computed CR for this round |
| `enemy_loss` | `Integer` NULLABLE | Null = instant kill |
| `hero_loss` | `Integer` NULLABLE | Null = instant kill |
| `enemy_end_remaining` | `Integer` | Enemy endurance after this round |
| `hero_end_remaining` | `Integer` | Hero endurance after this round |
| `psi_surge_used` | `Boolean` | Whether Psi-surge was active this round |
| `created_at` | `DateTime` | |

### `character_events`

Generic state-change audit trail. One row per phase step completion. Tracks every meaningful state change a character undergoes, tied to the section and run that caused it.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `Integer` PK | |
| `character_id` | `Integer` FK → `characters.id` | |
| `section_id` | `Integer` FK → `sections.id` | Section where the event occurred |
| `run_number` | `Integer` | Which attempt at this book |
| `event_type` | `String(30)` | `item_pickup`, `item_decline`, `item_loss`, `meal_consumed`, `meal_penalty`, `gold_change`, `endurance_change`, `healing`, `combat_start`, `combat_end`, `evasion`, `death`, `restart`, `discipline_gained`, `book_advance`, `random_roll` |
| `phase` | `String(20)` NULLABLE | Which section phase produced this event |
| `details` | `Text` NULLABLE | JSON blob with event-specific data (e.g., `{"item_name": "Sword", "item_type": "weapon"}` or `{"end_change": -3, "reason": "no_meal"}`) |
| `created_at` | `DateTime` | |

Coexists with `decision_log` (navigation/choice history) and `combat_rounds` (round-by-round combat detail). The events table captures state mutations; the other tables capture gameplay decisions and combat mechanics.

## Admin Tables

### `admin_users`

Separate from player accounts.

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
| `user_id` | `Integer` FK → `users.id` | Reporter |
| `character_id` | `Integer` FK → `characters.id` NULLABLE | Character at time of report |
| `section_id` | `Integer` FK → `sections.id` NULLABLE | Section where issue occurred |
| `tags` | `Text` | JSON array of category tags |
| `free_text` | `Text` NULLABLE | Optional description |
| `status` | `String(20)` | `open`, `triaging`, `resolved`, `wont_fix` |
| `admin_notes` | `Text` NULLABLE | Admin triage notes |
| `resolved_by` | `Integer` FK → `admin_users.id` NULLABLE | |
| `created_at` | `DateTime` | |
| `updated_at` | `DateTime` | |

**Report tags** (predefined, multi-select): `wrong_items`, `meal_issue`, `missing_choice`, `combat_issue`, `narrative_error`, `discipline_issue`, `other`

## Relationships

```
books 1──∞ sections 1──∞ choices
                    1──∞ combat_encounters 1──∞ combat_modifiers
                    1──∞ section_items
                    1──∞ random_outcomes
                    1──∞ world_entity_appearances
books 1──∞ combat_results
books 1──∞ disciplines
books 1──∞ book_transition_rules (as from_book or to_book)

world_entities 1──∞ world_entity_appearances
world_entities ∞──∞ world_entities (via world_entity_relationships)

weapon_categories (standalone lookup)

users 1──∞ characters 1──∞ character_disciplines
                      1──∞ character_items
                      1──∞ character_book_starts
                      1──∞ decision_log
                      1──∞ combat_rounds
                      1──∞ character_events
characters ∞──1 combat_encounters (active_combat_encounter_id)
users 1──∞ reports
```

## Indexes

- `sections(book_id, number)` — unique, fast lookup by book + section number
- `choices(section_id)` — all choices for a section
- `combat_encounters(section_id)` — combats in a section
- `combat_results(book_id, random_number, combat_ratio_min)` — CRT lookup
- `characters(user_id)` — list user's characters
- `decision_log(character_id, run_number, created_at)` — character history per run
- `combat_rounds(character_id, combat_encounter_id, round_number)` — combat state lookup
- `character_events(character_id, section_id, created_at)` — events per section visit
- `character_events(character_id, event_type)` — filter by event type
- `reports(status, created_at)` — admin queue ordering
- `world_entities(entity_type)` — filter by category
- `world_entity_appearances(entity_id)` — all appearances of an entity
- `world_entity_appearances(section_id)` — all entities in a section
- `world_entity_relationships(entity_a_id)` — outgoing relationships
- `world_entity_relationships(entity_b_id)` — incoming relationships
- `weapon_categories(category)` — lookup weapons by category
- `random_outcomes(section_id)` — outcomes for a section's random phase
- `characters(user_id, is_deleted)` — list user's active characters (filter soft-deleted)

## Migration Strategy

- Alembic with auto-generation from SQLAlchemy models
- Content tables seeded by the parser (`scripts/seed_db.py`)
- Player tables created empty on first migration
- Illustrations stored on filesystem at `static/images/{book_slug}/`; paths stored in `sections.illustration_path`
