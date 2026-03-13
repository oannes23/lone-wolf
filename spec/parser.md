# Parser: XHTML-to-Database Pipeline

Extracts game content from Project Aon XHTML files and loads it into the database. The parser is the **seed** for game content — after import, content is refined through the admin layer. The parser is re-runnable: it replaces `source='auto'` values but preserves `source='manual'` edits.

## Source Format

Source data comes from `all-books-simple.zip`, which contains both text and illustrations. This file is **not stored in the repo** — it is used for import and then removed.

`all-books-svg.zip` contains flow diagrams illustrating potential story paths. These may be useful for admin validation views but are not used in the player experience.

Each book is a single XHTML file (`en/xhtml-simple/lw/{slug}.htm`) containing:

- **Front matter**: title, dedication, story background, game rules, discipline descriptions, equipment rules
- **Numbered sections**: ~350 per book, each in a `<div class="numbered">` block
- **Illustrations**: `<img>` elements within sections
- **Combat Results Table**: `<table>` under `<a name="crtable">`
- **Back matter**: errata, license

### Section Structure

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

Target section is always in the `href`: `#sect{number}`.

## Pipeline Architecture

```
Extract (BeautifulSoup)  →  Transform (normalize + classify)  →  LLM Enrichment (Haiku)  →  Load (SQLAlchemy bulk insert)
                                                                   ├─ Choice rewriting
                                                                   ├─ Entity extraction
                                                                   └─ Relationship inference
```

### Extract Phase

Uses BeautifulSoup4 to parse each XHTML file.

**Book metadata**:
- Title from `<title>` or `<h1>`
- Slug from filename
- Book number from slug prefix (e.g. `01fftd` → 1)
- Era determined by book number (1–5: kai, 6–12: magnakai, 13–20: grand_master, 21–28: new_order, 29: new_order)

**Sections**:
- Find all `<div class="numbered">` (or the single `<div>` containing numbered `<h3>` tags)
- Section number from `<h3><a name="sect{N}">{N}</a></h3>`
- Narrative: all `<p>` elements that are not `class="choice"` or `class="combat"`
- Choices: all `<p class="choice">` elements
- Combat encounters: all `<p class="combat">` elements

**Illustrations**:
- Extract `<img>` elements within sections
- Copy image files to `static/images/{book_slug}/`
- Store relative path in `sections.illustration_path`

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

### Transform Phase

**Normalize IDs**:
- Section references: `#sect{N}` → integer N
- Link section IDs to their database row IDs after initial insert

**Classify choice conditions**:

```python
def classify_condition(choice_text):
    text = choice_text.lower()

    # Discipline gate
    if "kai discipline of" in text or "discipline of" in text:
        discipline = extract_discipline_name(text)
        return ("discipline", discipline)

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

**Detect must-eat sections** (pattern + override):

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

Auto-detection is best-effort. False positives/negatives are corrected via the admin layer (which sets `source='manual'`).

**Detect section items** (pattern + override):

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

**Detect death sections**:
- Sections where narrative ends with death language ("your adventure is over", "your life ends", "you have failed") and no outgoing choices
- Some deaths are combat deaths (endurance reaches 0) — these are handled at runtime, not by the parser

**Detect victory sections**:
- Final sections of each book where the adventure completes successfully

**Validate cross-references**:
- Every choice target `sect{N}` must exist within the same book
- Log warnings for missing targets

**Extract combat details**:

```python
def parse_combat(combat_element):
    text = combat_element.get_text()
    # Pattern: "Enemy Name: COMBAT SKILL {cs}   ENDURANCE {end}"
    match = re.match(r"(.+?):\s*COMBAT SKILL\s*(\d+)\s+ENDURANCE\s*(\d+)", text)
    return {
        "enemy_name": match.group(1).strip(),
        "enemy_cs": int(match.group(2)),
        "enemy_end": int(match.group(3)),
    }
```

**Detect evasion rules**:
- Look for patterns like "after three rounds of combat" + choice to evade
- Extract round threshold and evasion target section

**Detect Mindblast immunity**:
- Look for "immune to Mindblast" or "Mindblast has no effect" in section narrative near combat encounters

**Detect combat modifiers** (best-effort auto-detection):
- Look for patterns near combat encounters: "immune to Mindblast", "double damage", "undead", "you cannot use [discipline]", combat skill bonuses/penalties mentioned in narrative
- Create `combat_modifiers` rows for detected patterns
- Common modifier types: `mindblast_immune` (also set on encounter), `double_damage`, `undead`, `cs_bonus`, `cs_penalty`, `no_weaponskill`
- Admin corrects false positives/negatives via admin layer

**Detect conditional combat**:
- Look for patterns like "If you do not have [discipline]" or "If you do not possess [item]" near combat encounters
- Populate `condition_type` and `condition_value` on `combat_encounters`
- Common patterns: "If you do not have Camouflage", "Unless you possess the [item]"

**Detect random outcomes**:
- Look for "pick a number from the Random Number Table" in narrative
- Parse outcome bands from surrounding text (e.g., "If the number is 0-4, lose 3 Endurance points. If 5-9, you find 12 Gold Crowns.")
- Create `random_outcomes` rows with effect_type, effect_value, and narrative_text
- Distinct from choice-based random branching (which is handled via `condition_type='random'` on choices)

**Detect phase ordering**:
- By default, the game engine computes phase sequence from section properties (item_loss → items → eat → combat → heal → choices)
- Parser should detect non-standard ordering by examining the narrative position of items relative to combat (e.g., "you defeat the enemy and find a sword" = items AFTER combat)
- Non-standard sections get a `phase_sequence_override` JSON array written to the `sections` table
- This detection is best-effort; admin can correct via the admin layer

**Seed weapon categories**:
- Extract weapon names from combat encounter text, item gains, and discipline descriptions
- Map each weapon name to a category (Sword, Axe, Mace, etc.) using pattern matching and an initial seed list
- Populate the `weapon_categories` table
- Categories: Sword, Axe, Mace, Spear, Dagger, Bow, Quarterstaff, Warhammer, and others as encountered

### LLM Enrichment Phase (Haiku)

The parser uses Claude Haiku for three enrichment tasks. All require Anthropic API credentials. Per-book import has a cost proportional to section count.

#### LLM Result Caching

- **Decision**: Cache LLM results locally to avoid redundant API calls on re-runs.
- **Rationale**: Saves cost during development and iteration. Choice rewriting and entity extraction are deterministic for unchanged input text.
- **Implementation**: Hash the input text (SHA-256), store the LLM response in a local cache (SQLite file or JSON directory at `.parser_cache/`). On re-run, check cache before calling API. Cache is keyed by `(input_hash, task_type)` where task_type is `choice_rewrite`, `entity_extract`, etc.
- Cache is local-only, not committed to the repo. Can be cleared with `--no-cache` flag.

#### Choice Rewriting

Choice text is rewritten to be **page-agnostic**.

- **Decision**: Per-choice Haiku calls to rewrite choice text
- **Rationale**: The application should feel like a programmed CYOA, not a book reader. "Turn to page 141" breaks immersion.

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

#### Entity Extraction

Extracts world entities (characters, locations, creatures, organizations) from each section's narrative text. Entities are **global** — the LLM is given the current entity catalog and deduplicates against it, resolving name variations to existing entities where appropriate.

```python
async def extract_entities(
    narrative_text: str,
    book_slug: str,
    section_number: int,
    existing_entities: list[dict],  # current catalog for dedup
) -> dict:
    """
    Extract world entities from a section's narrative.

    Returns structured JSON:
    {
      "entities": [
        {
          "name": "Dorier",
          "entity_type": "character",
          "description": "A Sommlending merchant encountered on the road",
          "aliases": [],
          "existing_entity_id": null,  # or ID if matched to existing
          "properties": {"title": "merchant", "race": "Sommlending"},
          "role": "quest_giver",
          "context": "Dorier offers to sell you provisions for your journey"
        }
      ],
      "relationships": [
        {
          "entity_a": "Dorier",
          "entity_b": "Sommerlund",
          "relationship_category": "spatial",
          "relationship_type": "originates_from"
        }
      ]
    }
    """
    entity_names = [e["name"] for e in existing_entities]
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": (
                "Extract all named characters, locations, creatures, and organizations "
                "from this game book section narrative. For each entity, provide:\n"
                "- name (canonical form)\n"
                "- entity_type: character, location, creature, or organization\n"
                "- description: brief summary\n"
                "- aliases: alternate names used in text\n"
                "- role: how the entity appears in this section "
                "(combatant, quest_giver, ally, mentioned, visited, origin, obstacle, etc.)\n"
                "- context: one sentence describing what the entity does in this section\n"
                "- properties: type-specific metadata as JSON\n\n"
                "Also extract relationships between entities found.\n\n"
                "IMPORTANT: Check if any extracted entity matches an existing entity "
                f"(by name or alias). Known entities: {entity_names}\n"
                "If a match is found, use the existing name rather than creating a duplicate.\n\n"
                "Return valid JSON only.\n\n"
                f"Section {section_number} from book {book_slug}:\n{narrative_text}"
            )
        }]
    )
    return json.loads(response.content[0].text)
```

**Deduplication strategy**: The LLM receives the current entity name list with each call. As entities accumulate across sections and books, the list grows. For very large catalogs, the list can be filtered to entities of the same type or from the same book/era to keep context manageable.

**Processing order matters**: Books should be processed in order (1→29) so that entities introduced in earlier books are in the catalog when later books reference them.

#### Relationship Inference

Relationships between entities are extracted alongside entity extraction (see above). The LLM identifies relationships it observes in the narrative and categorizes them:

| Category | When to use |
|----------|-------------|
| `social` | Personal relationships: `trained_by`, `parent_of`, `betrayed`, `serves` |
| `spatial` | Geographic relationships: `located_in`, `borders`, `contains`, `originates_from` |
| `factional` | Group/political relationships: `member_of`, `allied_with`, `enemy_of`, `rules` |
| `temporal` | Time-based relationships: `preceded_by`, `created`, `destroyed` |
| `causal` | Cause/effect relationships: `caused`, `prevented`, `enabled`, `forged` |

Relationships are additive — the same pair of entities may have multiple relationships of different types. New relationships discovered in later sections/books are added without removing earlier ones.

### Load Phase

Bulk insert order (respecting foreign keys):

1. `books`
2. `disciplines` (FK → books)
3. `sections` (FK → books) — includes `phase_sequence_override` for non-standard sections
4. `choices` (FK → sections) — target_section_id resolved in second pass
5. `combat_encounters` (FK → sections)
6. `combat_modifiers` (FK → combat_encounters)
7. `combat_results` (FK → books)
8. `section_items` (FK → sections) — includes `phase_ordinal` for positioning
9. `random_outcomes` (FK → sections) — outcome bands for random phases
10. `weapon_categories` (standalone) — seeded from extracted weapon names
11. `world_entities` (FK → books, sections for first_appearance)
12. `world_entity_appearances` (FK → world_entities, sections)
13. `world_entity_relationships` (FK → world_entities)

**Two-pass choice loading**:
1. First pass: insert all sections, get their IDs
2. Second pass: resolve `target_section_number` → `target_section_id`

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

Tables with `source` column: `sections`, `choices`, `combat_encounters`, `section_items`, `random_outcomes`, `world_entities`, `world_entity_appearances`, `world_entity_relationships`.

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
3. **Processes books in order** (1→29) so entity catalog builds up for deduplication
4. Runs extract → transform → LLM enrichment → load for each book
5. Extracts illustrations to `static/images/{book_slug}/`
6. Reports summary (sections parsed, choices found, combat encounters, items detected, entities extracted, relationships found, rewrites performed, warnings)

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

## Content Refinement Workflow

The parser is the starting point, not the final word. The intended workflow:

```
1. Parser seeds database with auto-detected content
2. Players play the game
3. Players file bug reports ("meal wasn't deducted", "wrong item gained", etc.)
4. Admins review reports in the admin queue
5. Admins correct content via the admin UI (sets source='manual')
6. If parser is improved, re-run replaces only auto-sourced values
7. Manual edits are always preserved
```

This iterative approach means the parser doesn't need to be perfect — it just needs to be good enough to bootstrap playable content.
