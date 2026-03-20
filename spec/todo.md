# Spec TODO — Pre-Implementation Fixes

Tracked issues from the game-designer and architect spec reviews. Items 1-29 resolved via structured Q&A on 2026-03-19. Items 30-43 resolved via spec completion review on 2026-03-19.

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
- **Note**: All books use free choice for equipment selection (no random roll variant).

### 20. `book_starting_equipment` for books 1-5
- **Status**: Resolved
- **Decision**: Full equipment lists compiled for all 5 Kai books. See seed-data.md.
- **Note**: Pick limits vary: Book 1 = 1, Books 2-3 = 2, Book 4 = 6, Book 5 = 4. All use free choice.

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

## Spec Completion (Round 2)

### 30. Book 1 equipment: random roll vs free choice
- **Status**: Resolved
- **Spec**: seed-data.md, game-engine.md, api.md
- **Decision**: All books use free choice for equipment selection. No random-roll variant. Book 1 player picks 1 item from the equipment list, same mechanic as other books.
- **Action**: Remove all random-roll references from seed-data.md. Update api.md and game-engine.md wizard flow.

### 31. Starting gold and meals during character creation
- **Status**: Resolved
- **Spec**: api.md, game-engine.md
- **Decision**: Gold roll (random 0-9 for Book 1, random 0-9 + 10 for books 2-5) and fixed meals are auto-applied during the equipment wizard step, before the player picks items. Shown in the wizard UI.
- **Action**: Update api.md equipment wizard step response. Update game-engine.md wizard flow.

### 32. Multi-roll scenes API contract
- **Status**: Resolved
- **Spec**: api.md, game-engine.md
- **Decision**: Player calls `/roll` once per roll group. Response includes `rolls_remaining: N` and `current_roll_group: M`. Phase completes when all groups are resolved. If a roll triggers a `scene_redirect`, remaining roll groups are skipped (redirect wins).
- **Action**: Update api.md `/roll` response examples. Update game-engine.md random phase logic.

### 33. Password change endpoint
- **Status**: Resolved
- **Spec**: api.md
- **Decision**: Add `POST /auth/change-password`. Required fields: `current_password`, `new_password`. Updates password hash and sets `password_changed_at` timestamp. All prior tokens invalidated via `issued_at` check against `password_changed_at`.
- **Action**: Add endpoint to api.md auth section. Add `password_changed_at` to users table in data-model.md.

### 34. Meals upper bound
- **Status**: Resolved
- **Spec**: game-engine.md, data-model.md
- **Decision**: Meals capped at 8 (matches backpack capacity thematically). Overflow handled like gold — partial acceptance up to cap.
- **Action**: Update game-engine.md meter definitions. Update data-model.md field classification.

### 35. Special item bonuses during equipment wizard
- **Status**: Resolved
- **Spec**: game-engine.md, api.md
- **Decision**: `endurance_max` and `effective_combat_skill` are recalculated immediately when equipment is applied during the wizard step. Player sees correct stats at the confirm step.
- **Action**: Document in game-engine.md wizard flow.

### 36. Fixed equipment handling in wizard
- **Status**: Resolved
- **Spec**: api.md, game-engine.md
- **Decision**: Fixed items (e.g., Book 1 Axe + Map) are auto-added to inventory and displayed in the equipment wizard step as "included" (not selectable). Player sees what they get alongside their chooseable options.
- **Action**: Update api.md wizard GET response to show included_items.

### 37. Parser non-standard phase detection
- **Status**: Resolved
- **Spec**: parser.md
- **Decision**: Best-effort auto-detection from narrative text position. Parser examines where item mentions, combat encounters, and other events appear relative to each other in the narrative to infer non-standard phase ordering. Incorrect detections are overridden by admin via `phase_sequence_override`.
- **Action**: Already documented in parser.md. Confirm alignment.

### 38. Null target_scene_id handling at runtime
- **Status**: Resolved
- **Spec**: api.md, game-engine.md
- **Decision**: Choices with `target_scene_id = null` and no `choice_random_outcomes` are shown in the choices list with `available: false` and a reason like `"path_unavailable"`. Player can see the choice exists but cannot select it. Admin fixes via bug reports.
- **Action**: Update api.md choice response. Update game-engine.md choice filtering.

### 39. Character name uniqueness
- **Status**: Resolved
- **Spec**: data-model.md
- **Decision**: No uniqueness constraint on character names. Players can name characters whatever they want, including duplicating names across their own characters.

### 40. Equipment wizard re-pick
- **Status**: Resolved
- **Spec**: api.md
- **Decision**: The equipment wizard step allows the player to freely change their selections before submitting. Standard wizard UX — the player builds a selection and submits all at once. Re-submitting with different selections is allowed.

### 41. Scene redirect during multi-roll
- **Status**: Resolved
- **Spec**: game-engine.md
- **Decision**: If a roll group triggers a `scene_redirect` effect, remaining roll groups are skipped. Redirect wins immediately. Heal phase still completes before the redirect fires (consistent with existing redirect behavior).

## Deferred — Post-MVP

### 42. Grand Master / New Order discipline details
- **Status**: Deferred
- **Reason**: Not needed for Kai-era MVP (books 1-5). Requires source book research for Grand Master lore-circles and New Order starting conditions.
- **Affected**: game-engine.md discipline tables, data-model.md

### 43. SVG flow diagrams
- **Status**: Deferred
- **Reason**: Potentially useful for admin validation views but not needed for MVP.

### 44. Later-era lore-circles
- **Status**: Deferred
- **Reason**: Grand Master lore-circle groupings and bonuses need source research. Not needed for Kai era (no lore-circles in books 1-5).

### 45. Knowledge graph fog-of-war
- **Status**: Deferred
- **Reason**: Post-MVP feature idea. Should browsing be limited to entities the player has encountered?

### 46. Run comparison API
- **Status**: Deferred
- **Reason**: Future enhancement. `GET /characters/{id}/runs/compare` for side-by-side run stats.

### 47. LLM entity extraction prompt tuning
- **Status**: Deferred
- **Reason**: Parser implementation detail. Tuning Haiku prompts for accuracy and dedup quality. Not a spec decision.

### 48. Entity catalog scaling
- **Status**: Deferred
- **Reason**: Parser implementation detail. How the entity catalog is filtered when it grows too large for the LLM context window. Only relevant for later books.

### 49. Mandatory items identification
- **Status**: Deferred (same as #22)
- **Reason**: Parser seeds all as `is_mandatory=false`. Admin corrects via player bug reports. Intended content refinement workflow.

---

## Round 3: Pre-Epic Readiness Review (2026-03-19)

Nine specialist agents (game-designer, frontend-dev, architect, qa-engineer, db-admin, backend-dev, tech-writer, code-reviewer, orchestrator) reviewed the full spec suite in parallel. Items below are deduplicated and cross-validated across agents. Spec bugs (A–G) need no decision — just fix. Design questions (50–82) need clarification before epic/story creation.

### Spec Bugs (fix during next spec update)

- **A. api.md POST /characters response example**: Shows `total_steps: 3, step_index: 2` — should be `total_steps: 2, step_index: 0` per resolved 2-step wizard (todo #8). *(tech-writer)* — **Approved** — **Applied 2026-03-19**
- **B. game-engine.md Laumspur amount**: Shows `amount: 2`; seed-data.md shows `amount: 4`. Source books confirm 4. *(game-designer, qa-engineer)* — **Approved** — **Applied 2026-03-19**
- **C. api.md pending_items example**: Gold Crowns listed in `pending_items`, but gold is auto-applied per spec (todo #13) — should not appear as a pending item. *(tech-writer)* — **Approved** — **Applied 2026-03-19**
- **D. parser.md Load Phase numbering**: Step 7 missing (jumps 6→8). Renumber sequentially. *(tech-writer, db-admin)* — **Approved** — **Applied 2026-03-19**
- **E. parser.md Load Phase step 2**: Says `FK → books` for disciplines; should say "era-scoped, no book FK" per todo #9. *(tech-writer)* — **Approved** — **Applied 2026-03-19**
- **F. parser.md Load Phase step 11**: Says `FK → books` for combat_results; should say "era-scoped" per todo #29. *(tech-writer, qa-engineer)* — **Approved** — **Applied 2026-03-19**
- **G. data-model.md column name**: `character_disciplines.weapon_type` should be `weapon_category` to match `weapon_categories.category` and glossary usage. *(tech-writer)* — **Approved** — **Applied 2026-03-19**

### Game Mechanics

### 50. Special weapon combat mechanics (Sommerswerd, Magic Spear, Jewelled Mace)
- **Status**: Resolved
- **Flagged by**: game-designer, code-reviewer
- **Spec**: game-engine.md, seed-data.md
- **Decision**: Foe type matching via `combat_modifiers.modifier_type` (e.g., `'undead'`, `'helghast'`). Engine checks equipped weapon's `special_vs` against modifier types on the encounter. `damage_multiplier` doubles CRT `enemy_loss` value against matching foes. `combat_bonus_vs_special` replaces (does not stack with) the base `combat_bonus`.
- **Action**: Add `apply_special_weapon_effects()` to game-engine.md. Update `effective_combat_skill()` to check `combat_bonus_vs_special`. Add damage multiplier application to combat round resolution.

### 51. Consumable item timing during combat
- **Status**: Resolved
- **Flagged by**: game-designer
- **Spec**: api.md, game-engine.md
- **Decision**: No consumable usage during combat (book-accurate). `POST /gameplay/{id}/use-item` returns 400 if `scene_phase = 'combat'`. Items can be used before combat starts or after it ends.
- **Action**: Add combat-phase restriction to use-item endpoint in api.md and game-engine.md.

### 52. Death-during-phase interruption
- **Status**: Resolved
- **Flagged by**: game-designer, qa-engineer
- **Spec**: game-engine.md
- **Decision**: Immediately halt phase progression on death. Log `death` event with `parent_event_id` pointing to causing event. Clear `scene_phase`, `scene_phase_index`, `active_combat_encounter_id`. Only `restart` available.
- **Action**: Add "Death During Phase Progression" section to game-engine.md.

### 53. Multi-enemy combat API flow
- **Status**: Resolved
- **Flagged by**: game-designer, backend-dev, qa-engineer
- **Spec**: game-engine.md, api.md
- **Decision**: Separate combat phases per enemy. Each enemy is a separate `combat` entry in the phase sequence, sorted by ordinal. Phase system advances naturally between enemies. Client sees `combat_over: true` for current enemy, then calls `GET /scene` which shows next combat phase.
- **Action**: Update game-engine.md phase sequence computation and combat resolution sections. Add multi-enemy example to api.md.

### 54. Evasion-into-death priority
- **Status**: Resolved
- **Flagged by**: qa-engineer
- **Spec**: game-engine.md
- **Decision**: Death takes priority. Character dies at current scene. Evasion does not complete. Consistent with death-halts-immediately (#52).
- **Action**: Add note to game-engine.md `evade_combat()` pseudocode.

### 55. Mixed random + regular choice scenes
- **Status**: Resolved
- **Flagged by**: game-designer, tech-writer
- **Spec**: game-engine.md
- **Decision**: Choices phase handles both. No separate `random` phase for mixed scenes. Random-gated choices appear in the choices list alongside regular choices. Player selects a random-gated choice → `/choose` returns `requires_roll: true` → `/roll` resolves it. The `random` phase is only for `random_outcomes` table entries (phase-based random effects) and for scenes where ALL exits are random.
- **Action**: Update game-engine.md `compute_phase_sequence()` and add a "Mixed Random/Regular Scenes" clarification.

### Wizard & Character Flow

### 56. Book advance wizard: equipment selection step
- **Status**: Resolved
- **Flagged by**: game-designer, backend-dev
- **Spec**: game-engine.md, seed-data.md
- **Decision**: Add a `pick_equipment` step to book_advance, making it 4 steps: `pick_disciplines` → `pick_equipment` → `inventory_adjust` → `confirm`. Clean separation between gaining new equipment and managing carried inventory.
- **Action**: Update seed-data.md wizard template. Update game-engine.md and api.md wizard flows.

### 57. Weaponskill selection during book advance
- **Status**: Resolved
- **Flagged by**: game-designer, qa-engineer
- **Spec**: game-engine.md, api.md
- **Decision**: Inline in the `pick_disciplines` wizard step. When the selected discipline is Weaponskill/Weaponmastery, the step response includes a required `weapon_type` field. POST to advance the step validates it. Weapon type is always free choice from the category list — no random roll, even for books that mention random selection in source material.
- **Action**: Update game-engine.md wizard step processing. Update api.md wizard POST validation.

### 58. Character starting book restriction
- **Status**: Resolved
- **Flagged by**: game-designer, tech-writer
- **Spec**: api.md
- **Decision**: Book 1 only for MVP. `POST /characters` validates `book_id` must be Book 1. Data model already supports later expansion.
- **Action**: Add validation note to api.md `POST /characters`.

### State Management

### 59. Pending choice-triggered roll state
- **Status**: Resolved
- **Flagged by**: backend-dev, qa-engineer, architect
- **Spec**: data-model.md, api.md, game-engine.md
- **Decision**: Add nullable `pending_choice_id Integer FK → choices.id` on `characters`. Set when `/choose` returns `requires_roll: true`, cleared on `/roll` resolution. Classified as Ref field.
- **Action**: Add column to data-model.md `characters` table. Update field classification. Update api.md `/roll` precondition docs.

### 60. Automatic phase execution timing
- **Status**: Resolved
- **Flagged by**: backend-dev, architect, frontend-dev
- **Spec**: game-engine.md, api.md
- **Decision**: Transition endpoints (`/choose`, `/roll`, `/restart`, `/replay`, `/combat/evade`) run all automatic phases synchronously before returning. `GET /scene` is strictly read-only — it assembles the response from current state and persisted phase results. Phase results are stored in `character_events` and reconstructed for display.
- **Action**: Add "Scene Response Assembly" section to game-engine.md. Document GET /scene as read-only in api.md.

### 61. `endurance_max` recalculation triggers
- **Status**: Resolved
- **Flagged by**: architect, backend-dev, qa-engineer, game-designer, db-admin, tech-writer
- **Spec**: game-engine.md, data-model.md
- **Decision**: Recalculate `endurance_max` on: item pickup, item drop, item loss, backpack loss, discipline change, wizard completion, restart/replay. If `endurance_current > new endurance_max` after any recalculation, clamp `endurance_current` to the new max.
- **Action**: Add "endurance_max Recalculation Invariant" section to game-engine.md listing all trigger points.

### 62. Mandatory item over-capacity resolution
- **Status**: Resolved
- **Flagged by**: game-designer, qa-engineer, tech-writer
- **Spec**: game-engine.md
- **Decision**: If character is over weapon or backpack capacity at the start of any items phase, block progression until player drops items to within limits via `/inventory`. If the next scene has no items phase, inject one at the start of the phase sequence. Player chooses what to drop.
- **Action**: Update game-engine.md Items Phase section with over-capacity blocking rule and phase injection.

### 63. `scene_phase` valid values enumeration
- **Status**: Resolved
- **Flagged by**: qa-engineer, frontend-dev
- **Spec**: game-engine.md, data-model.md
- **Decision**: Add a formal state diagram to game-engine.md. Valid `scene_phase` values: `items`, `combat`, `random`, `choices` (interactive phases the client can see). Automatic phases (`eat`, `heal`, `item_loss`, `backpack_loss`) are never stored in `scene_phase` — they complete atomically during transitions. `null` means: no active phase (character is dead, in wizard, at a death/victory scene, or between scenes).
- **Action**: Add `scene_phase` state diagram to game-engine.md. Update data-model.md field classification.

### API Contract

### 64. Post-combat client flow
- **Status**: Resolved
- **Flagged by**: frontend-dev, backend-dev
- **Spec**: api.md
- **Decision**: Final combat round returns combat results only (`combat_over: true`, `result`, round details). Client calls `GET /scene` to see the next phase state. This keeps the round endpoint focused on combat and lets GET /scene be the single source for full scene state.
- **Action**: Document post-combat flow in api.md combat section.

### 65. Combat evade response shape
- **Status**: Resolved
- **Flagged by**: frontend-dev
- **Spec**: api.md
- **Decision**: `/combat/evade` returns the full scene response shape (same as `/choose`) for consistency. Includes `evasion_damage` as an additional field. Automatic phases at the target scene run before the response is returned (per #60).
- **Action**: Update api.md `/combat/evade` response example to full scene shape.

### 66. Error code taxonomy
- **Status**: Resolved
- **Flagged by**: architect, code-reviewer, frontend-dev, backend-dev
- **Spec**: api.md
- **Decision**: Add `error_code` string field to all error responses alongside `detail`. Define enum: `VERSION_MISMATCH`, `PENDING_ITEMS`, `COMBAT_UNRESOLVED`, `WRONG_PHASE`, `CHARACTER_DEAD`, `WIZARD_ACTIVE`, `CHOICE_UNAVAILABLE`, `INVENTORY_FULL`, `OVER_CAPACITY`, `NOT_IN_COMBAT`, `ITEM_NOT_CONSUMABLE`, `PATH_UNAVAILABLE`, `MAX_CHARACTERS`, `INVALID_ROLL_TOKEN`, `RATE_LIMITED`. Frontend branches on `error_code`, displays `detail` to user.
- **Action**: Add error code enum table and update error response shape in api.md.

### 67. Missing API response schemas
- **Status**: Resolved — deferred to implementation
- **Flagged by**: frontend-dev, backend-dev, tech-writer
- **Spec**: api.md
- **Decision**: Define response schemas during the relevant epic implementation rather than all upfront. Affected endpoints: `GET /characters` (list), `GET /leaderboards/overall`, `GET /books/{book_id}/rules`, `GET /game-objects/{id}/refs`, `GET /reports`, `GET /admin/reports/{id}`, `GET /admin/reports/stats`, admin CRUD endpoints.

### 68. Version requirement on advance and use-item
- **Status**: Resolved
- **Flagged by**: code-reviewer, backend-dev
- **Spec**: api.md
- **Decision**: Require `version` in the request body for both `POST /gameplay/{id}/advance` and `POST /gameplay/{id}/use-item`. Consistent with the optimistic locking invariant: all state-mutating gameplay endpoints require version.
- **Action**: Update api.md request examples for both endpoints.

### 69. Item identification for duplicates
- **Status**: Resolved
- **Flagged by**: code-reviewer, frontend-dev, backend-dev, architect
- **Spec**: api.md
- **Decision**: Use `character_item_id` (PK from `character_items`) as the identifier for `/inventory` and `/use-item` requests. Include `character_item_id` in the character inventory response. `item_name` remains for display.
- **Action**: Update api.md `/inventory` and `/use-item` request schemas. Update character response inventory section.

### 70. `max_picks_in_category` semantics
- **Status**: Resolved
- **Flagged by**: architect
- **Spec**: data-model.md, seed-data.md
- **Decision**: The pick limit is global (not per-category). Remove `max_picks_in_category` from `book_starting_equipment` rows. Add `max_total_picks` to the `books` table (Book 1 = 1, Book 2 = 2, Book 3 = 2, Book 4 = 6, Book 5 = 4). Single source of truth.
- **Action**: Update data-model.md `books` table (add `max_total_picks`). Remove `max_picks_in_category` from `book_starting_equipment`. Update seed-data.md.

### Auth & Security

### 71. Password policy
- **Status**: Resolved
- **Flagged by**: code-reviewer, qa-engineer
- **Spec**: api.md
- **Decision**: Minimum 8 characters, maximum 128 characters. No complexity requirements beyond length.
- **Action**: Add password validation rules to api.md auth section.

### 72. Admin token expiry
- **Status**: Resolved
- **Flagged by**: code-reviewer, backend-dev, frontend-dev
- **Spec**: api.md
- **Decision**: 8-hour admin access token. No refresh token. Admins re-authenticate on expiry.
- **Action**: Document admin token expiry in api.md admin auth section.

### 73. JWT payload claims
- **Status**: Resolved
- **Flagged by**: backend-dev
- **Spec**: api.md
- **Decision**: Player access: `{sub, username, type: "access", iat, exp}`. Player refresh: `{sub, username, type: "refresh", iat, exp}`. Admin: `{sub, role: "admin", iat, exp}`. Roll: `{sub, cs, end, book_id, iat, exp}`.
- **Action**: Add JWT payload schemas to api.md auth section.

### 74. Refresh token revocation strategy
- **Status**: Resolved
- **Flagged by**: code-reviewer
- **Spec**: api.md
- **Decision**: Accept risk for MVP. Reduce refresh token lifetime from 90 days to 7 days. Stateless — no server-side denylist. Password change invalidates all prior tokens via `issued_at` check against `password_changed_at`. Document as accepted risk.
- **Action**: Update api.md refresh token lifetime. Add accepted-risk note.

### Data Completeness

### 75. CRT seed data (Kai era)
- **Status**: Resolved
- **Flagged by**: game-designer, qa-engineer, orchestrator, db-admin
- **Spec**: seed-data.md
- **Decision**: Compile the full 130-row Kai CRT from source material (Project Aon) into seed-data.md as canonical reference. Also used for the static seed script and combat test fixtures.
- **Action**: Add "Combat Results Table (Kai Era)" section to seed-data.md with all 130 rows.

### 76. Snapshot JSON formats
- **Status**: Resolved
- **Flagged by**: backend-dev, qa-engineer, db-admin
- **Spec**: data-model.md
- **Decision**: `items_json`: `[{"item_name": str, "item_type": str, "is_equipped": bool, "game_object_id": int|null}]`. `disciplines_json`: `[{"discipline_id": int, "weapon_type": str|null}]` (weapon_type only for Weaponskill/Weaponmastery entries).
- **Action**: Add JSON shape documentation to data-model.md `character_book_starts` section.

### 77. Wizard accumulated state JSON format
- **Status**: Resolved
- **Flagged by**: db-admin
- **Spec**: data-model.md, game-engine.md
- **Decision**: Character creation state: `{gold: int, meals: int, selected_items: [{item_name, item_type, game_object_id}]}`. Book advance state: `{new_disciplines: [int], weapon_type: str|null, kept_weapons: [str], kept_backpack: [str], gold_rolled: int}`.
- **Action**: Add wizard state JSON schemas to data-model.md `character_wizard_progress` section.

### Architecture

### 78. Seed data loading strategy
- **Status**: Resolved
- **Flagged by**: orchestrator, db-admin
- **Spec**: MASTER.md
- **Decision**: Separate idempotent `scripts/seed_static.py` for reference data (CRT, disciplines, weapon categories, wizard templates, book transition rules, book starting equipment). Parser handles content data (scenes, choices, encounters, game objects). Run order: `alembic upgrade head` → `seed_static.py` → parser (optional).
- **Action**: Document in MASTER.md build order. Add `seed_static.py` to the scripts section.

### 79. Transaction boundaries
- **Status**: Resolved
- **Flagged by**: architect, db-admin
- **Spec**: game-engine.md, data-model.md
- **Decision**: Each gameplay endpoint executes within a single DB transaction. Version check, state mutation, event logging, and version increment are all atomic. Partial failures roll back completely.
- **Action**: Add "Transaction Boundaries" section to game-engine.md or data-model.md.

### 80. ON DELETE FK behavior
- **Status**: Resolved
- **Flagged by**: db-admin
- **Spec**: data-model.md
- **Decision**: Characters → child tables: RESTRICT (never hard-delete characters). Users → characters: RESTRICT. Content tables → gameplay children: RESTRICT. `characters.active_combat_encounter_id`: SET NULL. `characters.active_wizard_id`: SET NULL. `character_events.parent_event_id` self-FK: SET NULL.
- **Action**: Add ON DELETE annotations to all FK definitions in data-model.md.

### 81. `game_objects.properties` NULL handling
- **Status**: Resolved
- **Flagged by**: db-admin
- **Spec**: data-model.md
- **Decision**: Default to `{}` (empty dict), never NULL. SQLAlchemy model uses `default=dict` and `server_default='{}'`. Same treatment for `game_objects.aliases` (default `[]`).
- **Action**: Update data-model.md column definitions. Add NOT NULL with default.

### 82. CRT bracket sentinel values
- **Status**: Resolved
- **Flagged by**: qa-engineer
- **Spec**: data-model.md
- **Decision**: Bracket 1 (CR ≤ −11): `combat_ratio_min = -999`. Bracket 13 (CR ≥ +11): `combat_ratio_max = 999`. Engine's `ratio_to_bracket()` uses `WHERE combat_ratio_min <= ratio AND combat_ratio_max >= ratio`.
- **Action**: Document sentinel values in data-model.md `combat_results` section and in seed-data.md CRT table.
