# Epic 5: Parser Pipeline

**Phase**: 2–3 (parallel with Epics 2, 3, 4 — off the critical path)
**Dependencies**: Epic 1 only
**Status**: Not Started

XHTML import pipeline for Project Aon book files. CLI tool that extracts content, transforms it with LLM assistance, and loads it into the database. Never imported by the API at runtime — completely standalone.

The project uses test fixture data while the parser is being built. This epic is off the critical path.

---

## Story 5.1: Parser Extract Phase

**Status**: Not Started

### Description

BeautifulSoup4 extraction of raw data from Project Aon XHTML files.

### Tasks

- [ ] Create `app/parser/extract.py` with extraction functions:
  - `extract_book_metadata(xhtml_path) → BookData`:
    - Title from `<title>` or `<h1>`
    - Slug from filename stem (e.g., `01fftd`)
    - Book number parsed from slug prefix
    - Era determined by book number range (1–5 = kai)
  - `extract_scenes(soup) → list[SceneData]`:
    - Find `<div class="numbered">` blocks
    - Extract scene number from `<a name="sect{N}">` anchors
    - Extract narrative HTML (styled for display)
    - Extract `html_id` from anchor name
  - `extract_choices(scene_soup) → list[ChoiceData]`:
    - Find `<p class="choice">` elements
    - Extract raw choice text
    - Parse target scene number from "turn to" references
  - `extract_combat_encounters(scene_soup) → list[CombatData]`:
    - Find `<p class="combat">` or similar combat blocks
    - Parse enemy name, CS, END
  - `extract_crt(soup) → list[CRTRow]`:
    - Find `<a name="crtable">` section
    - Parse the full Combat Results Table
  - `extract_disciplines(soup) → list[DisciplineData]`:
    - Find `<a name="discplnz">` section
    - Parse discipline names, html_ids, descriptions
  - `extract_starting_equipment(soup) → list[EquipmentData]`:
    - Parse equipment list from relevant section
  - `copy_illustrations(xhtml_dir, book_slug, dest_dir)`:
    - Copy illustration images to `static/images/{book_slug}/`

### Acceptance Criteria

- Unit tests with sample XHTML snippets for each extraction type
- Tests use small inline XHTML fixtures (not full book files)
- Each extraction function handles missing/malformed elements gracefully

---

## Story 5.2: Parser Transform Phase

**Status**: Not Started

### Description

Classification and detection functions that transform raw extracted data into structured game data.

### Tasks

- [ ] Create `app/parser/transform.py` with detection functions:
  - `classify_condition(choice_text) → (condition_type, condition_value)`:
    - Detect discipline checks ("If you have the Kai Discipline of...")
    - Detect item checks ("If you possess a...")
    - Detect gold checks ("If you have N Gold Crowns...")
    - Detect random ("pick a number from the Random Number Table")
    - Detect compound OR conditions
  - `detect_must_eat(narrative) → bool` — meal check scenes
  - `detect_backpack_loss(narrative) → bool` — backpack loss scenes
  - `detect_items(narrative, choices) → list[SceneItemData]` — items gained/lost
  - `detect_death_scene(narrative, choices) → bool` — no outgoing choices, death language
  - `detect_victory_scene(narrative, choices) → bool` — book completion markers
  - `parse_combat(combat_block) → CombatEncounterData` — enemy name, CS, END
  - `detect_evasion(narrative) → (rounds, target, damage) | None` — evasion rules
  - `detect_mindblast_immunity(narrative) → bool`
  - `detect_combat_modifiers(narrative) → list[ModifierData]`
  - `detect_conditional_combat(narrative) → (condition_type, condition_value) | None`
  - `detect_random_outcomes(narrative) → list[RandomOutcomeData]` — phase-based random effects
  - `detect_choice_triggered_random(choices) → list[ChoiceRandomOutcomeData]`
  - `detect_scene_level_random_exits(choices) → bool` — all choices random-gated
  - `detect_phase_ordering(narrative) → list[str] | None` — best-effort non-standard phase detection

### Acceptance Criteria

- Unit tests for each detection function with positive and negative cases
- Tests cover common patterns from Books 1–5
- Graceful handling of edge cases (ambiguous text, missing patterns)

---

## Story 5.3: LLM Enrichment — Choice Rewriting

**Status**: Not Started

### Description

Use Claude Haiku to rewrite choice text to be page-agnostic ("turn to 141" → action-oriented text).

### Tasks

- [ ] Create `app/parser/llm.py`:
  - `rewrite_choice(raw_text, scene_narrative) → display_text`:
    - Prompt Haiku to rewrite removing page references
    - Keep the semantic meaning and player-facing options
  - LLM result caching:
    - Cache key: SHA-256 hash of (prompt + raw_text + narrative context)
    - Cache dir: `.parser_cache/`
    - Load from cache on hit, call API on miss
  - `--no-cache` flag support to bypass cache
  - `--skip-llm` flag support to skip all LLM calls (use raw_text as display_text)
  - Both `raw_text` and `display_text` stored on choices

### Acceptance Criteria

- Unit test with mocked LLM (verify prompt construction, response handling)
- Unit test for cache hit behavior (LLM not called)
- Unit test for cache miss behavior (LLM called, result cached)
- Unit test for --skip-llm mode (raw_text used as display_text)

---

## Story 5.4: LLM Enrichment — Entity Extraction

**Status**: Not Started

### Description

Extract game entities from scene narratives and build the knowledge graph.

### Tasks

- [ ] Add to `app/parser/llm.py`:
  - `extract_entities(narrative, book_id, existing_catalog) → list[GameObjectData]`:
    - Prompt Haiku to identify characters, locations, creatures, organizations
    - Deduplicate against running entity catalog (books processed in order)
    - Return new entities with kind, name, description, aliases
  - `infer_relationships(entities, scene_context) → list[GameObjectRefData]`:
    - Prompt Haiku to identify relationships between entities
    - Return refs with tags and metadata
  - Game object creation for:
    - Items (kind='item') from scene_items
    - Foes (kind='foe') from combat_encounters
    - Scenes (kind='scene') from scenes
  - CLI flags: `--skip-entities`, `--entities-only`

### Acceptance Criteria

- Unit test with mocked LLM for entity extraction
- Unit test for deduplication against existing catalog
- Unit test for correct game_object kinds (item, foe, scene)
- Unit test for --skip-entities flag

---

## Story 5.5: Parser Load Phase

**Status**: Not Started

### Description

Bulk database insertion respecting FK dependency order, with source-aware upsert logic.

### Tasks

- [ ] Create `app/parser/load.py`:
  - `load_book(db, book_data, scenes, choices, encounters, items, ...) → LoadResult`:
    - Insert in FK dependency order (18 steps):
      1. Book (upsert)
      2. Disciplines (era-scoped, upsert)
      3. Game objects — scenes (upsert)
      4. Scenes (upsert, FK → books, game_objects)
      5. Game objects — items (upsert)
      6. Game objects — foes (upsert)
      7. Choices (insert scenes first, then resolve target_scene_id in second pass)
      8. Choice random outcomes
      9. Combat encounters
      10. Combat modifiers
      11. Scene items
      12. Random outcomes
      13. Combat results (era-scoped, upsert)
      14. Game objects — other entities (upsert)
      15. Game object refs (upsert)
      16. Weapon categories (upsert)
      17. Book starting equipment (upsert)
      18. Book transition rules (upsert)
    - Two-pass scene/choice loading: insert all scenes → resolve target_scene_id for choices
  - `upsert_with_source(db, model, data, unique_key)`:
    - If existing row has `source='manual'` → skip (preserve manual edits)
    - If existing row has `source='auto'` → update
    - If no existing row → insert with `source='auto'`

### Acceptance Criteria

- Integration test: load sample book data, verify all rows inserted
- Integration test: FK integrity verified (no orphan references)
- Integration test: manual rows preserved on re-run (source='manual' not overwritten)
- Integration test: auto rows updated on re-run (source='auto' refreshed)
- Integration test: two-pass choice resolution (target_scene_id correctly resolved)

---

## Story 5.6: Parser CLI & Integration

**Status**: Not Started

### Description

CLI wrapper that orchestrates the full pipeline: extract → transform → LLM → load.

### Tasks

- [ ] Create `scripts/seed_db.py` with CLI interface:
  - Arguments:
    - `--book N` — parse specific book number
    - `--verbose` — detailed output
    - `--dry-run` — extract and transform without loading
    - `--reset` — drop and recreate content for specified book(s)
    - `--skip-llm` — skip all LLM calls
    - `--skip-entities` — skip entity extraction
    - `--entities-only` — only run entity extraction (skip other transforms)
    - `--no-cache` — bypass LLM cache
  - Books processed in ascending order (1→5 for MVP)
  - Summary report printed on completion:
    - Scenes, choices, encounters, items, game objects, refs, rewrites, warnings
- [ ] Create `app/parser/pipeline.py`:
  - `run_pipeline(book_path, options) → PipelineResult`:
    - Orchestrate: extract → transform → LLM enrich → load
    - Collect and report warnings

### Acceptance Criteria

- Full pipeline runs for Book 1 without errors (end-to-end integration test)
- Summary report printed with counts for all entity types
- --dry-run completes without DB writes
- --skip-llm completes without API calls
- CLI help text shows all available options

---

## Implementation Notes

### File Locations

Project Aon XHTML files are expected in a configurable directory. The parser reads from these files and writes to the database and `static/images/`.

### LLM Cache Structure

```
.parser_cache/
  {sha256_hash}.json  # cached LLM responses
```

Each cache entry contains the prompt, response, and metadata (timestamp, model used).

### Source Column Contract

- `source='auto'` — created/updated by the parser. Will be overwritten on re-run.
- `source='manual'` — created/edited by admin. Parser will NOT overwrite.

This enables the iterative refinement workflow: parser seeds initial data, admin corrects via bug reports, re-running parser preserves all manual edits.
