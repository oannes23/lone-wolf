# Parser: XHTML-to-Database Pipeline

Extracts game content from Project Aon XHTML files and loads it into the database. The parser is the **seed** for game content — after import, content is refined through the admin layer. The parser is re-runnable: it replaces `source='auto'` values but preserves `source='manual'` edits.

## Source Format

Source data comes from `all-books-simple.zip`, which contains both text and illustrations. This file is **not stored in the repo** — it is used for import and then removed.

`all-books-svg.zip` contains flow diagrams illustrating potential story paths. These may be useful for admin validation views but are not used in the player experience.

Each book is a single XHTML file (`en/xhtml-simple/lw/{slug}.htm`) containing:

- **Front matter**: title, dedication, story background, game rules, discipline descriptions, equipment rules, starting equipment list
- **Numbered sections**: ~350 per book, each in a `<div class="numbered">` block (these become "scenes" in our data model)
- **Illustrations**: `<img>` elements within sections
- **Combat Results Table**: `<table>` under `<a name="crtable">`
- **Back matter**: errata, license

### Section Structure (XHTML Source)

The source files use "section" terminology. The parser maps these to "scenes" in the database.

```html
<div class="numbered">
<h3><a name="sect1">1</a></h3>

<p>Narrative text...</p>
<p>More narrative...</p>
<p class="choice">If you wish to use your Kai Discipline of Sixth Sense, <a href="#sect141">turn to 141</a>.</p>
<p class="choice">If you wish to take the right path, <a href="#sect85">turn to 85</a>.</p>
</div>
```

### Combat Format

```html
<p class="combat">Kraan: <small>COMBAT SKILL</small> 16   <small>ENDURANCE</small> 24</p>
```

Pattern: `{Enemy Name}: COMBAT SKILL {cs}   ENDURANCE {end}`

Multi-enemy sections have multiple `<p class="combat">` elements.

### Choice Format

```html
<p class="choice">If you wish to use your Kai Discipline of Sixth Sense, <a href="#sect141">turn to 141</a>.</p>
<p class="choice">If you have 10 Gold Crowns and wish to pay him, <a href="#sect262">turn to 262</a>.</p>
<p class="choice">If you possess a Vordak Gem, <a href="#sect236">turn to 236</a>.</p>
<p class="choice"><a href="#sect139">Turn to 139</a>.</p>
```

Target scene is always in the `href`: `#sect{number}`.

## Pipeline Architecture

```
Extract (BeautifulSoup)  →  Transform (normalize + classify)  →  LLM Enrichment (Haiku)  →  Load (SQLAlchemy bulk insert)
                                                                   ├─ Choice rewriting
                                                                   ├─ Entity/item/foe extraction (→ game_objects)
                                                                   └─ Relationship inference (→ game_object_refs)
```

### Extract Phase

Uses BeautifulSoup4 to parse each XHTML file.

**Book metadata**:
- Title from `<title>` or `<h1>`
- Slug from filename
- Book number from slug prefix (e.g. `01fftd` → 1)
- Era determined by book number (1–5: kai, 6–12: magnakai, 13–20: grand_master, 21–28: new_order, 29: new_order)
- Start scene number: default 1

**Scenes** (from XHTML "sections"):
- Find all `<div class="numbered">` (or the single `<div>` containing numbered `<h3>` tags)
- Scene number from `<h3><a name="sect{N}">{N}</a></h3>`
- Narrative: all `<p>` elements that are not `class="choice"` or `class="combat"`
- Choices: all `<p class="choice">` elements
- Combat encounters: all `<p class="combat">` elements

**Illustrations**:
- Extract `<img>` elements within sections
- Copy image files to `static/images/{book_slug}/`
- Store relative path in `scenes.illustration_path`

**Combat Results Table**:
- Find `<a name="crtable">` → parent `<div>` → `<table>`
- Parse header row for combat ratio brackets
- Parse each data row: random number (0–9) × 13 ratio brackets
- Values are `{enemy_loss}/{hero_loss}` or `k/0` or `0/k`

**Disciplines**:
- Find `<a name="discplnz">` → extract each `<h4>` and following `<p>` elements
- Discipline name from `<h4>` text
- HTML id from `<a name="...">` inside `<h4>`
- Description from `<p>` elements until next `<h4>`

**Starting Equipment**:
- Extract equipment list from the rules/equipment section of each book
- Identify available weapons, backpack items, and gold options
- Populate `book_starting_equipment` table with category and pick limits

### Transform Phase

**Normalize IDs**:
- Section references: `#sect{N}` → integer N (mapped to scene numbers)
- Link scene IDs to their database row IDs after initial insert

**Classify choice conditions**:

```python
def classify_condition(choice_text):
    text = choice_text.lower()

    # Discipline gate
    if "kai discipline of" in text or "discipline of" in text:
        discipline = extract_discipline_name(text)
        return ("discipline", discipline)

    # OR conditions (e.g., "If you have Tracking or Huntmastery")
    or_match = re.search(r"if you have (\w+) or (\w+)", text)
    if or_match:
        return ("discipline", json.dumps({"any": [or_match.group(1), or_match.group(2)]}))

    # Item gate
    if "if you possess" in text or "if you have a" in text:
        item = extract_item_name(text)
        return ("item", item)

    # Gold gate
    gold_match = re.search(r"if you have (\d+) gold", text)
    if gold_match:
        return ("gold", gold_match.group(1))

    # Random number
    if "pick a number" in text or "random number" in text:
        return ("random", extract_range(text))

    return (None, None)
```

**Detect must-eat scenes** (pattern + override):

```python
def detect_must_eat(narrative_text):
    text = narrative_text.lower()
    patterns = [
        "you must eat a meal",
        "eat a meal here",
        "you need to eat",
        "mark off a meal",
    ]
    return any(p in text for p in patterns)
```

**Detect backpack loss scenes**:

```python
def detect_backpack_loss(narrative_text):
    text = narrative_text.lower()
    patterns = [
        "you lose your backpack",
        "your backpack is lost",
        "backpack and all its contents",
    ]
    return any(p in text for p in patterns)
```

**Detect scene items** (pattern + override):

```python
def detect_items(narrative_text):
    items = []
    text = narrative_text.lower()

    # Gold gains
    gold_match = re.search(r"(\d+) gold crowns?", text)
    if gold_match and ("find" in text or "gain" in text or "take" in text):
        items.append({"item_name": "Gold Crowns", "item_type": "gold",
                       "quantity": int(gold_match.group(1)), "action": "gain"})

    # Meal gains
    if "meal" in text and ("find" in text or "take" in text or "gain" in text):
        items.append({"item_name": "Meal", "item_type": "meal",
                       "quantity": 1, "action": "gain"})

    # Weapon/item gains — "you may take the {item}"
    take_match = re.search(r"you may take the (.+?)[\.,]", text)
    if take_match:
        items.append({"item_name": take_match.group(1).strip().title(),
                       "item_type": classify_item_type(take_match.group(1)),
                       "quantity": 1, "action": "gain"})

    # Item losses — "you lose your {item}"
    lose_match = re.search(r"you lose (?:your )?(.+?)[\.,]", text)
    if lose_match:
        items.append({"item_name": lose_match.group(1).strip().title(),
                       "item_type": classify_item_type(lose_match.group(1)),
                       "quantity": 1, "action": "lose"})

    return items
```

Auto-detection is best-effort. The intent is to capture the obvious cases; the admin layer corrects errors surfaced by player bug reports.

**Detect death scenes**:
- Scenes where narrative ends with death language ("your adventure is over", "your life ends", "you have failed") and no outgoing choices
- Some deaths are combat deaths (endurance reaches 0) — these are handled at runtime, not by the parser

**Detect victory scenes**:
- Final scenes of each book where the adventure completes successfully

**Validate cross-references**:
- Every choice target `sect{N}` must exist within the same book
- Log warnings for missing targets

**Extract combat details**:

```python
def parse_combat(combat_element):
    text = combat_element.get_text()
    match = re.match(r"(.+?):\s*COMBAT SKILL\s*(\d+)\s+ENDURANCE\s*(\d+)", text)
    return {
        "enemy_name": match.group(1).strip(),
        "enemy_cs": int(match.group(2)),
        "enemy_end": int(match.group(3)),
    }
```

**Detect evasion rules**:
- Look for patterns like "after three rounds of combat" + choice to evade
- Extract round threshold, evasion target scene, and evasion damage amount

**Detect evasion damage**:
- Look for patterns like "lose N ENDURANCE points" near evasion text
- Default to 0 if no damage mentioned

**Detect Mindblast immunity**:
- Look for "immune to Mindblast" or "Mindblast has no effect" in scene narrative near combat encounters

**Detect combat modifiers** (best-effort auto-detection):
- Look for patterns near combat encounters: "immune to Mindblast", "double damage", "undead", "you cannot use [discipline]", combat skill bonuses/penalties mentioned in narrative
- Create `combat_modifiers` rows for detected patterns

**Detect conditional combat**:
- Look for patterns like "If you do not have [discipline]" or "If you do not possess [item]" near combat encounters
- Populate `condition_type` and `condition_value` on `combat_encounters`

**Detect random outcomes** (phase-based):
- Look for "pick a number from the Random Number Table" in narrative (not inside choice text)
- Parse outcome bands from surrounding text
- Create `random_outcomes` rows with effect_type, effect_value, and narrative_text

**Detect choice-triggered random**:
- Look for choices where the text contains "pick a number" or number range patterns
- If a choice leads to a roll with multiple outcomes (e.g., "try to escape — roll 0-2 caught, 3-9 free"), set `target_scene_id = null` on the parent choice
- Create `choice_random_outcomes` rows with range_min, range_max, target_scene_id, narrative_text

**Detect scene-level random exits**:
- If ALL choices in a scene have `condition_type='random'`, the scene is a random-exit scene
- Each choice has a number range in `condition_value` and its own `target_scene_id`

**Detect phase ordering**:
- By default, the game engine computes phase sequence from scene properties
- Parser should detect non-standard ordering by examining the narrative position of items relative to combat
- Non-standard scenes get a `phase_sequence_override` JSON array written to the `scenes` table

**Seed weapon categories**:
- Extract weapon names from combat encounter text, item gains, and discipline descriptions
- Map each weapon name to a category using pattern matching and an initial seed list
- Populate the `weapon_categories` table

### LLM Enrichment Phase (Haiku)

The parser uses Claude Haiku for enrichment tasks. All require Anthropic API credentials.

#### LLM Result Caching

- **Decision**: Cache LLM results locally to avoid redundant API calls on re-runs.
- **Implementation**: Hash the input text (SHA-256), store the LLM response in a local cache at `.parser_cache/`. Keyed by `(input_hash, task_type)`. Cache is local-only, not committed to the repo. Can be cleared with `--no-cache` flag.

#### Choice Rewriting

Choice text is rewritten to be **page-agnostic**.

```python
async def rewrite_choice_text(raw_text: str) -> str:
    """
    Rewrite a single choice text to remove page references and book phrasing.

    Examples:
      "If you wish to use your Kai Discipline of Sixth Sense, turn to 141."
        → "Use your Sixth Sense to investigate"
      "If you wish to take the right path into the wood, turn to 85."
        → "Take the right path into the wood"
      "Turn to 139."
        → "Continue"
    """
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"Rewrite this game book choice text to remove page references "
                       f"and 'If you wish to' preamble. Make it a direct, concise action. "
                       f"Return ONLY the rewritten text, nothing else.\n\n"
                       f"Original: {raw_text}"
        }]
    )
    return response.content[0].text.strip()
```

Both `raw_text` (original) and `display_text` (rewritten) are stored. The API serves `display_text`.

#### Entity Extraction (→ game_objects + game_object_refs)

Extracts game objects (characters, locations, creatures, organizations) from each scene's narrative text. Entities are **global** — the LLM is given the current game object catalog and deduplicates against it.

```python
async def extract_entities(
    narrative_text: str,
    book_slug: str,
    scene_number: int,
    existing_game_objects: list[dict],  # current catalog for dedup
) -> dict:
    """
    Extract game objects from a scene's narrative.

    Returns structured JSON:
    {
      "entities": [
        {
          "name": "Dorier",
          "kind": "character",
          "description": "A Sommlending merchant encountered on the road",
          "aliases": [],
          "existing_game_object_id": null,
          "properties": {"title": "merchant", "race": "Sommlending"},
          "role": "quest_giver",
          "context": "Dorier offers to sell you provisions for your journey"
        }
      ],
      "relationships": [
        {
          "source_name": "Dorier",
          "target_name": "Sommerlund",
          "tags": ["spatial", "originates_from"],
          "metadata": null
        }
      ]
    }
    """
    entity_names = [e["name"] for e in existing_game_objects]
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
                "Extract all named characters, locations, creatures, and organizations "
                "from this game book scene narrative. For each entity, provide:\n"
                "- name (canonical form)\n"
                "- kind: character, location, creature, or organization\n"
                "- description: brief summary\n"
                "- aliases: alternate names used in text\n"
                "- role: how the entity appears in this scene "
                "(combatant, quest_giver, ally, mentioned, visited, origin, obstacle, etc.)\n"
                "- context: one sentence describing what the entity does in this scene\n"
                "- properties: kind-specific metadata as JSON\n\n"
                "Also extract relationships between entities as tagged refs with:\n"
                "- source_name, target_name\n"
                "- tags: array with category + type (e.g., ['spatial', 'located_in'], ['factional', 'member_of'])\n\n"
                "IMPORTANT: Check if any extracted entity matches an existing game object "
                f"(by name or alias). Known entities: {entity_names}\n"
                "If a match is found, use the existing name rather than creating a duplicate.\n\n"
                "Return valid JSON only.\n\n"
                f"Scene {scene_number} from book {book_slug}:\n{narrative_text}"
            )
        }]
    )
    return json.loads(response.content[0].text)
```

**Deduplication strategy**: The LLM receives the current game object name list with each call. For very large catalogs, the list can be filtered to objects of the same kind or from the same book/era.

**Processing order**: Books are processed in order (1→29) so that entities from earlier books are in the catalog when later books reference them.

**Game object creation for items and foes**: In addition to LLM-extracted entities, the parser creates game_objects for:
- **Foes** (kind='foe'): Each unique enemy name becomes a game_object. Properties include base_cs, base_end. The `combat_encounters` row references via `foe_game_object_id`.
- **Items** (kind='item'): Each unique item name becomes a game_object. Properties include item_type, category. The `scene_items` row references via `game_object_id`.
- **Scenes** (kind='scene'): Each scene gets a game_object entry. The `scenes` row references via `game_object_id`.

#### Relationship Inference (→ game_object_refs)

Relationships are extracted alongside entity extraction. The LLM identifies relationships and outputs them as tagged refs:

| Tag Category | When to use |
|-------------|-------------|
| `appearance` | Entity appears in a scene: `["appearance", "{role}"]` |
| `social` | Personal relationships: `["social", "trained_by"]`, `["social", "parent_of"]` |
| `spatial` | Geographic relationships: `["spatial", "located_in"]`, `["spatial", "borders"]` |
| `factional` | Group/political: `["factional", "member_of"]`, `["factional", "enemy_of"]` |
| `temporal` | Time-based: `["temporal", "preceded_by"]`, `["temporal", "created"]` |
| `causal` | Cause/effect: `["causal", "caused"]`, `["causal", "prevented"]` |

Relationships are additive — new refs discovered in later scenes/books are added without removing earlier ones.

### Load Phase

Bulk insert order (respecting foreign keys):

1. `books`
2. `disciplines` (era-scoped, no book FK)
3. `game_objects` with kind='scene' (one per scene, for taxonomy)
4. `scenes` (FK → books, FK → game_objects) — includes `phase_sequence_override`, `loses_backpack`
5. `choices` (FK → scenes) — target_scene_id resolved in second pass
6. `choice_random_outcomes` (FK → choices, FK → scenes) — for choice-triggered random
7. `game_objects` with kind='foe' (from combat encounter extraction)
8. `combat_encounters` (FK → scenes, FK → game_objects for foe)
9. `combat_modifiers` (FK → combat_encounters)
10. `combat_results` (era-scoped)
11. `game_objects` with kind='item' (from item extraction)
12. `scene_items` (FK → scenes, FK → game_objects for items)
13. `random_outcomes` (FK → scenes)
14. `weapon_categories` (standalone)
15. `game_objects` with kind='character', 'location', 'creature', 'organization' (from LLM extraction)
16. `game_object_refs` (tagged refs for all appearances and relationships)
17. `book_starting_equipment` (FK → books, FK → game_objects)

**Two-pass scene/choice loading**:
1. First pass: insert all scenes, get their IDs
2. Second pass: resolve `target_scene_number` → `target_scene_id`

**Source column handling for re-runs**:

```python
def upsert_with_source(table, key_columns, data):
    existing = query(table, **{k: data[k] for k in key_columns})
    if existing and existing.source == 'manual':
        return  # preserve manual edits
    elif existing:
        update(existing, data, source='auto')
    else:
        insert(data, source='auto')
```

Tables with `source` column: `scenes`, `choices`, `combat_encounters`, `combat_modifiers`, `scene_items`, `random_outcomes`, `choice_random_outcomes`, `game_objects`, `game_object_refs`.

## CLI Interface

```bash
# Parse and load all Lone Wolf books
uv run python scripts/seed_db.py

# Parse a single book
uv run python scripts/seed_db.py --book 01fftd

# Parse with verbose logging
uv run python scripts/seed_db.py --verbose

# Validate only (no database writes)
uv run python scripts/seed_db.py --dry-run

# Reset and reload (clears all auto-sourced data, preserves manual)
uv run python scripts/seed_db.py --reset

# Skip LLM enrichment (no choice rewriting or entity extraction)
uv run python scripts/seed_db.py --skip-llm

# Skip only entity extraction (still rewrite choices)
uv run python scripts/seed_db.py --skip-entities

# Extract entities only (skip choice rewriting, useful for re-running entity pass)
uv run python scripts/seed_db.py --entities-only

# Bypass LLM cache (force fresh API calls)
uv run python scripts/seed_db.py --no-cache
```

The script:
1. Unzips the XHTML source to a temp directory
2. Filters to `en/xhtml-simple/lw/*.htm` files
3. **Processes books in order** (1→29) so game object catalog builds up for deduplication
4. Runs extract → transform → LLM enrichment → load for each book
5. Creates game_objects for scenes, foes, and items alongside content tables
6. Extracts illustrations to `static/images/{book_slug}/`
7. Extracts starting equipment lists to `book_starting_equipment`
8. Reports summary (scenes parsed, choices found, combat encounters, items detected, game objects created, refs created, rewrites performed, warnings)

## Known Edge Cases

### Multi-line combat
Some sections have combat text split across elements or with modifiers in surrounding paragraphs.

### Conditional combat
Some combats only happen if you lack a certain discipline or item. These are embedded in choice text rather than standalone combat paragraphs.

### Cross-book references
A few sections reference rules or items from previous books (especially in Magnakai+). The parser handles these per-book — cross-book logic is handled at runtime by the game engine.

### Day of the Damned (`dotd.htm`)
Special standalone book with different structure. Parsed separately with its own slug and `number = 0`.

### Book 29 (`29tsoc.htm`)
Added later to the Project Aon archive. Follows the standard format but may have minor structural differences.

### Inconsistent HTML
Some books use slightly different class names or structures. The parser should log warnings for unrecognized patterns rather than failing.

### OR conditions in choices
Some choices gate on multiple disciplines/items ("If you have Tracking or Huntmastery"). The parser detects these and outputs JSON `condition_value` (e.g., `{"any": ["Tracking", "Huntmastery"]}`).

### Backpack loss scenes
Some scenes cause loss of all backpack contents. Parser detects these and sets `loses_backpack = true` on the scene.

## Content Refinement Workflow

The parser is the starting point, not the final word. The intended workflow:

```
1. Parser seeds database with auto-detected content (scenes, game objects, refs)
2. Players play the game
3. Players file bug reports ("meal wasn't deducted", "wrong item gained", etc.)
4. Admins review reports in the admin queue
5. Admins correct content via the admin UI (sets source='manual')
6. If parser is improved, re-run replaces only auto-sourced values
7. Manual edits are always preserved
```

This iterative approach means the parser doesn't need to be perfect — it just needs to be good enough to bootstrap playable content.
