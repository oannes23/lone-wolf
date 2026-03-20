# Spec TODO — Pre-Implementation Fixes

Tracked issues from the game-designer and architect spec reviews. Resolved via structured Q&A on 2026-03-19.

## Mechanical Gaps

### 1. Unarmed combat penalty (-4 CS)
- **Status**: Resolved
- **Spec**: game-engine.md
- **Decision**: Add unarmed check to `effective_combat_skill()`. If no weapon equipped, apply -4 CS.
- **Action**: Update game-engine.md `effective_combat_skill()` pseudocode.

### 2. Enemy Mindblast
- **Status**: Resolved
- **Spec**: game-engine.md, data-model.md
- **Decision**: Model via `combat_modifiers` rows with `modifier_type='enemy_mindblast'`. Engine checks for this modifier; if present and character lacks Mindshield, apply -2 CS. Fix Mindshield description from "no END loss" to "immune to -2 CS penalty from enemy Mindblast." No schema change needed.
- **Action**: Update game-engine.md discipline table and `effective_combat_skill()`. Document `enemy_mindblast` modifier type.

### 3. Consumable item usage
- **Status**: Resolved
- **Spec**: api.md, game-engine.md
- **Decision**: Add `POST /gameplay/{character_id}/use-item` endpoint, available at any phase. Item effects are data-driven via game_object `properties` JSON (e.g., `{"consumable": true, "effect": "endurance_restore", "amount": 4}`). Engine applies effects via `apply_endurance_delta()`. Item is consumed (removed from inventory) on use.
- **Action**: Add endpoint to api.md. Add consumable item logic to game-engine.md. Document expected properties JSON shape.

### 4. Item-granted combat bonuses (Sommerswerd)
- **Status**: Resolved
- **Spec**: game-engine.md
- **Decision**: Store combat bonuses in item game_object `properties` JSON (e.g., `{"combat_bonus": 8, "special_vs": "undead", "damage_multiplier": 2}`). `effective_combat_skill()` checks equipped weapon's game_object properties. Content-as-Data pattern.
- **Action**: Update game-engine.md `effective_combat_skill()` pseudocode. Document properties shape for weapon items.

### 5. Gold deduction on gold-gated choices
- **Status**: Resolved
- **Spec**: api.md, game-engine.md
- **Decision**: Auto-deduct on `/choose`. When a choice with `condition_type='gold'` is selected, automatically deduct `int(condition_value)` gold and log a `gold_change` event.
- **Action**: Update api.md `/choose` docs. Update game-engine.md scene transition flow.

## Cross-Spec Inconsistencies

### 6. `combat_modifiers` missing `source` column
- **Status**: Resolved
- **Spec**: data-model.md
- **Decision**: Add `source String(10)` to `combat_modifiers` table definition.
- **Action**: Update data-model.md table definition.

### 7. `ref.clear` not in ops.md eight-operation vocabulary
- **Status**: Resolved
- **Spec**: game-engine.md
- **Decision**: Normalize to ops.md vocabulary. Use `ref.set` with `value: null` for singular ref clearing. For bulk list clearing (backpack_loss), use `ref.remove` with a list value.
- **Action**: Update game-engine.md Event Operations Mapping table.

### 8. Character creation wizard step mapping
- **Status**: Resolved
- **Spec**: game-engine.md, api.md, data-model.md
- **Decision**: Minimal wizard template. `character_creation` template has 2 steps: `pick_equipment` + `confirm`. Stat rolling (`POST /characters/roll`) and discipline/weapon skill selection (`POST /characters`) happen via dedicated pre-wizard endpoints. The wizard only governs equipment selection after character creation.
- **Action**: Document wizard template seed data in game-engine.md. Update api.md to clarify flow.

### 9. Discipline scoping: book vs era
- **Status**: Resolved
- **Spec**: data-model.md
- **Decision**: Era-scoped. Replace `book_id` FK with `era` column on `disciplines` table. One set of 10 Kai discipline rows shared by books 1-5. Parser creates discipline rows per era, not per book.
- **Action**: Update data-model.md table definition. Update parser.md extraction logic.

### 10. Missing unique constraints
- **Status**: Resolved
- **Spec**: data-model.md
- **Decision**: Add unique constraints:
  - `character_disciplines(character_id, discipline_id)`
  - `combat_rounds(character_id, combat_encounter_id, round_number)`
  - `book_transition_rules(from_book_id, to_book_id)`
- **Action**: Update data-model.md table definitions.

### 11. Refresh token storage
- **Status**: Resolved
- **Spec**: data-model.md, api.md
- **Decision**: Stateless JWT refresh tokens. No server-side storage. 90-day expiry. Cannot be individually revoked. Document that password change should include an `issued_at` check to invalidate old tokens.
- **Action**: Document in api.md auth section.

### 12. `character_events.seq` generation mechanism
- **Status**: Resolved
- **Spec**: data-model.md
- **Decision**: Application-level `SELECT MAX(seq)+1 WHERE character_id=?` within the same transaction. Safe because optimistic locking prevents concurrent character mutations.
- **Action**: Document in data-model.md character_events section.

### 13. Meal/gold scene_item pickup interactivity
- **Status**: Resolved
- **Spec**: game-engine.md, api.md
- **Decision**: Auto-apply. Gold and meal `scene_items` with `action='gain'` are auto-applied during phase progression (no accept/decline). Gold uses partial acceptance up to cap. Meals increment counter. Only weapon/backpack/special items require explicit accept/decline. Auto-applied items are reported in `phase_results`.
- **Action**: Update game-engine.md items phase logic. Update api.md scene response docs.

## Player Experience Issues

### 14. Advance wizard lazy-init blocks replay
- **Status**: Resolved
- **Spec**: api.md
- **Decision**: Require explicit `POST /gameplay/{character_id}/advance` to start the advance wizard. No lazy-init on GET. Replay remains available until the player explicitly commits to advancing. GET /characters/{id}/wizard returns 404 until advance is initiated.
- **Action**: Add `POST /gameplay/{id}/advance` endpoint to api.md. Remove lazy-init language. Update game-engine.md wizard flow.

### 15. Evasion info not surfaced before threshold
- **Status**: Resolved
- **Spec**: api.md
- **Decision**: Include `evasion_possible: true` and `evasion_after_rounds: N` in combat response even before the threshold is reached.
- **Action**: Update api.md combat response example.

### 16. Multiple random rolls per scene
- **Status**: Resolved
- **Spec**: game-engine.md, data-model.md
- **Decision**: Add `roll_group` Integer (default 0) to `random_outcomes`. Unique constraint becomes `(scene_id, roll_group, range_min, range_max)`. Random phase iterates through groups sequentially, one roll per group.
- **Action**: Update data-model.md table definition and unique constraint. Update game-engine.md random phase logic.

## Missing Indexes

### 17. Additional indexes needed
- **Status**: Resolved
- **Spec**: data-model.md
- **Decision**: Add indexes:
  - `character_disciplines(character_id, discipline_id)`
  - `character_items(character_id, item_type)`
  - `character_wizard_progress(character_id, completed_at)`
  - `decision_log(character_id, run_number)`
- **Action**: Update data-model.md Indexes section.

## Data Compilation Tasks (Blocking for Playability)

### 18. Weapon categories for books 1-5
- **Status**: Resolved
- **Decision**: 11 weapon entries across 7 categories compiled from source material. See seed-data.md.
- **Note**: Corrected spec's example categories — Warhammer is its own category (not under Mace). Removed non-acquirable weapons (Battle Axe, Javelin, etc.).

### 19. Wizard template seed data
- **Status**: Resolved
- **Decision**: `character_creation`: 2 steps (pick_equipment, confirm). `book_advance`: 3 steps (pick_disciplines, inventory_adjust, confirm). See seed-data.md.
- **Note**: Book 1 equipment uses random roll (0-9) instead of free choice. Wizard step must handle this variant.

### 20. `book_starting_equipment` for books 1-5
- **Status**: Resolved
- **Decision**: Full equipment lists compiled for all 5 Kai books. See seed-data.md.
- **Note**: Pick limits vary: Book 1 = 1 (random), Books 2-3 = 2, Book 4 = 6, Book 5 = 4.

### 21. `book_transition_rules` for books 1-5
- **Status**: Resolved
- **Decision**: 4 uniform rows (all Kai-to-Kai: keep everything, pick 1 new discipline). See seed-data.md.
- **Note**: Gold during transition = random 0-9 + 10, added to existing total (capped at 50).

### 22. Mandatory items identification
- **Status**: Resolved — deferred to post-parse
- **Decision**: Parser seeds all as `is_mandatory=false`. Admin corrects via player bug reports. This is the intended content refinement workflow.

## Minor / Cleanup

### 23. `choice_random_outcomes` missing from parser.md source-column list
- **Status**: Resolved
- **Decision**: Add `choice_random_outcomes` to the parser.md source-column table list.
- **Action**: Update parser.md.

### 24. Admin content creation endpoints
- **Status**: Resolved
- **Decision**: Add `POST /admin/{resource}` for all content resources. Sets `source='manual'`.
- **Action**: Update api.md admin section.

### 25. Wizard endpoint dual-path
- **Status**: Resolved
- **Decision**: Single canonical path: `/characters/{id}/wizard`. No dual-path. Both creation and advance wizards accessed through this path.
- **Action**: Update api.md to remove `/gameplay/{id}/wizard` references.

### 26. Healing discipline description inconsistency
- **Status**: Resolved
- **Decision**: Change description to "+1 END per scene if no combat occurred. Applied during heal phase."
- **Action**: Update game-engine.md discipline table.

### 27. Mandatory item + full inventory deadlock
- **Status**: Resolved
- **Decision**: Mandatory items override slot limits. Player gets the item even if over capacity (temporary over-limit state). Next items phase forces resolution back to within limits before proceeding.
- **Action**: Update game-engine.md inventory constraints and items phase logic.

### 28. Engine input contracts (DTOs)
- **Status**: Resolved
- **Decision**: Define `CharacterState`, `SceneContext`, `CombatContext` dataclasses in the spec. API layer populates from DB. Engine functions accept only these types.
- **Action**: Add DTO definitions to game-engine.md.

### 29. `combat_results` per-book redundancy
- **Status**: Resolved
- **Spec**: data-model.md
- **Decision**: Era-scoped. Replace `book_id` FK with `era` column on `combat_results`. One CRT per era (130 rows for Kai). Same change as disciplines (#9).
- **Action**: Update data-model.md table definition.
