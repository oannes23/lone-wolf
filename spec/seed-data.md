# Seed Data — Kai Era (Books 1-5)

Reference data for parser seeding and wizard templates. Compiled from Project Aon source material.

## Weapon Categories

The Weaponskill table in Kai books maps random rolls (0-9) to 9 distinct weapon types. These types define the categories for `weapon_categories` matching.

### `weapon_categories` rows

| weapon_name | category |
|-------------|----------|
| Sword | Sword |
| Broadsword | Sword |
| Short Sword | Sword |
| Sommerswerd | Sword |
| Axe | Axe |
| Mace | Mace |
| Spear | Spear |
| Magic Spear | Spear |
| Dagger | Dagger |
| Quarterstaff | Quarterstaff |
| Warhammer | Warhammer |

### Weaponskill Types (roll table)

| Roll | Type |
|------|------|
| 0 | Dagger |
| 1 | Spear |
| 2 | Mace |
| 3 | Short Sword |
| 4 | Warhammer |
| 5 | Sword |
| 6 | Axe |
| 7 | Sword |
| 8 | Quarterstaff |
| 9 | Broadsword |

Note: Rolls 5 and 7 both give Sword. This means Sword is twice as likely as other types.

### Special Weapon Properties (game_object `properties` JSON)

| Weapon | Properties |
|--------|-----------|
| Sommerswerd | `{"combat_bonus": 8, "special_vs": "undead", "damage_multiplier": 2, "item_type": "weapon", "category": "Sword", "is_special": true}` |
| Magic Spear | `{"combat_bonus": 0, "special_vs": "helghast", "item_type": "weapon", "category": "Spear", "is_special": true}` |
| Jewelled Mace | `{"combat_bonus": 0, "special_vs": "dhorgaan", "combat_bonus_vs_special": 5, "item_type": "weapon", "category": "Mace", "is_special": true}` |

### Special Item Properties (game_object `properties` JSON)

| Item | Properties |
|------|-----------|
| Chainmail Waistcoat | `{"endurance_bonus": 4, "item_type": "special", "is_special": true}` |
| Helmet | `{"endurance_bonus": 2, "item_type": "special", "is_special": true}` |
| Silver Helm | `{"combat_bonus": 2, "item_type": "special", "is_special": true}` |
| Padded Leather Waistcoat | `{"endurance_bonus": 2, "item_type": "special", "is_special": true}` |
| Shield | `{"combat_bonus": 2, "item_type": "special", "is_special": true}` |
| Healing Potion | `{"consumable": true, "effect": "endurance_restore", "amount": 4, "item_type": "backpack"}` |
| Potion of Laumspur | `{"consumable": true, "effect": "endurance_restore", "amount": 4, "item_type": "backpack"}` |

## Starting Equipment by Book

### Book 1: Flight from the Dark

**Fixed (given automatically):**
- Axe (weapon)
- Map of Sommerlund (special item)

**Choose 1:**

| item_name | item_type | category | notes |
|-----------|-----------|----------|-------|
| Broadsword | weapon | weapons | |
| Sword | weapon | weapons | |
| Helmet | special | special | +2 END bonus |
| Meal | meal | meals | qty: 2 |
| Chainmail Waistcoat | special | special | +4 END bonus |
| Mace | weapon | weapons | |
| Healing Potion | backpack | backpack | restores 4 END |
| Quarterstaff | weapon | weapons | |
| Spear | weapon | weapons | |
| Gold Crowns | gold | gold | qty: 12 |

**Gold:** Random 0-9 gold crowns (auto-applied during equipment step)
**Meals:** 1 meal (fixed, auto-applied during equipment step)
**Equipment picks:** 1

### Book 2: Fire on the Water

**Fixed (given automatically):**
- Seal of Hammerdal (special item)

**Choose any 2:**

| item_name | item_type | category |
|-----------|-----------|----------|
| Sword | weapon | weapons |
| Short Sword | weapon | weapons |
| Meal | meal | meals | (qty: 2) |
| Chainmail Waistcoat | special | special |
| Mace | weapon | weapons |
| Healing Potion | backpack | backpack |
| Quarterstaff | weapon | weapons |
| Spear | weapon | weapons |
| Shield | special | special |
| Broadsword | weapon | weapons |

**Gold:** Random 0-9 + 10 (added to existing total if continuing)
**Equipment picks:** 2

### Book 3: The Caverns of Kalte

**Fixed (given automatically):**
- Map of Kalte (special item)

**Choose any 2:**

| item_name | item_type | category |
|-----------|-----------|----------|
| Sword | weapon | weapons |
| Short Sword | weapon | weapons |
| Padded Leather Waistcoat | special | special |
| Spear | weapon | weapons |
| Mace | weapon | weapons |
| Warhammer | weapon | weapons |
| Axe | weapon | weapons |
| Potion of Laumspur | backpack | backpack |
| Quarterstaff | weapon | weapons |
| Meal | meal | meals | (qty: 1) |
| Broadsword | weapon | weapons |

**Gold:** Random 0-9 + 10 (added to existing total)
**Equipment picks:** 2

### Book 4: The Chasm of Doom

**Fixed (given automatically):**
- Map of the Southlands (special item)

**Choose up to 6:**

| item_name | item_type | category |
|-----------|-----------|----------|
| Warhammer | weapon | weapons |
| Dagger | weapon | weapons |
| Potion of Laumspur | backpack | backpack | (qty: 2) |
| Sword | weapon | weapons |
| Spear | weapon | weapons |
| Meal | meal | meals | (qty: 5) |
| Mace | weapon | weapons |
| Chainmail Waistcoat | special | special |
| Shield | special | special |

**Gold:** Random 0-9 + 10 (added to existing total)
**Equipment picks:** 6

### Book 5: Shadow on the Sand

**Fixed (given automatically):**
- Map of the Desert Empire (special item)

**Choose up to 4:**

| item_name | item_type | category |
|-----------|-----------|----------|
| Dagger | weapon | weapons |
| Potion of Laumspur | backpack | backpack |
| Sword | weapon | weapons |
| Spear | weapon | weapons |
| Meal | meal | meals | (qty: 2) |
| Mace | weapon | weapons |
| Shield | special | special |

**Gold:** Random 0-9 + 10 (added to existing total)
**Equipment picks:** 4

## Book Transition Rules

All Kai-to-Kai transitions follow the same pattern. Stats are NOT re-rolled.

### `book_transition_rules` rows

| from_book | to_book | max_weapons | max_backpack_items | special_items_carry | gold_carries | new_disciplines_count | base_cs_override | base_end_override | notes |
|-----------|---------|-------------|-------------------|--------------------|--------------|-----------------------|-----------------|------------------|-------|
| 1 | 2 | 2 | 8 | true | true | 1 | null | null | Player may exchange carried weapons during equipment selection |
| 2 | 3 | 2 | 8 | true | true | 1 | null | null | Player may exchange carried weapons during equipment selection |
| 3 | 4 | 2 | 8 | true | true | 1 | null | null | Player may exchange carried weapons during equipment selection |
| 4 | 5 | 2 | 8 | true | true | 1 | null | null | Player may exchange carried weapons during equipment selection |

**Transition flow:**
1. Carry over all items, gold, disciplines, stats as-is
2. Pick 1 new Kai discipline (from those not yet learned)
3. Receive new book's fixed starting equipment (map, special items)
4. Roll for additional gold (random 0-9 + 10, added to existing, capped at 50)
5. Choose N items from new book's equipment list (may exchange carried weapons)

### Kai Rank Progression

| Disciplines | Rank |
|-------------|------|
| 5 | Initiate |
| 6 | Aspirant |
| 7 | Guardian |
| 8 | Warmarn |
| 9 | Savant |
| 10 | Master |

## Wizard Template Seed Data

### `character_creation` template

| step_type | ordinal | config |
|-----------|---------|--------|
| `pick_equipment` | 0 | `{"book_id": "<from books table>"}` |
| `confirm` | 1 | `null` |

Pre-wizard steps (dedicated endpoints):
- `POST /characters/roll` — rolls CS and END, returns roll_token
- `POST /characters` — creates character with name, book_id, roll_token, discipline_ids, weapon_skill_type; auto-starts equipment wizard

### `book_advance` template

| step_type | ordinal | config |
|-----------|---------|--------|
| `pick_disciplines` | 0 | `{"count": 1}` (from book_transition_rules.new_disciplines_count) |
| `pick_equipment` | 1 | `{"book_id": "<from books table>"}` |
| `inventory_adjust` | 2 | `null` (limits from book_transition_rules) |
| `confirm` | 3 | `null` |

Pre-wizard step (dedicated endpoint):
- `POST /gameplay/{id}/advance` — starts the wizard; transition rules looked up from book_transition_rules

### Equipment Wizard Notes

**All books use free choice**: All books present a pick-from-list with `max_picks_in_category` limits.

**Gold during equipment**: Each book adds random gold (0-9 for Book 1, 0-9 + 10 for books 2-5). This is rolled server-side during the equipment step and auto-applied.

**Meals during equipment**: Fixed meals per book are auto-applied during the equipment step (e.g., Book 1 gives 1 meal).

**Fixed items**: Auto-granted and shown in the equipment wizard UI as "included" (not selectable). Player sees them alongside chooseable items.

### Special Item Stat Bonuses

Items with `endurance_bonus` in their properties increase `endurance_max` while carried. Items with `combat_bonus` add to `effective_combat_skill()` while carried (as special items, not just equipped weapons). Loss of the item triggers recalculation of the affected stat.

| Item | Bonus Type | Value | Applied To |
|------|-----------|-------|------------|
| Chainmail Waistcoat | endurance_bonus | +4 | endurance_max (while carried) |
| Helmet | endurance_bonus | +2 | endurance_max (while carried) |
| Padded Leather Waistcoat | endurance_bonus | +2 | endurance_max (while carried) |
| Silver Helm | combat_bonus | +2 | effective_combat_skill (while carried) |
| Shield | combat_bonus | +2 | effective_combat_skill (while carried) |

## Combat Results Table (Kai Era)

One CRT per era, shared by all books in that era. The Kai era covers Books 1-5. 13 combat ratio brackets x 10 random numbers = 130 rows. `NULL` in `enemy_loss` or `hero_loss` represents an instant kill (`k`). Sentinel values: `combat_ratio_min = -999` for bracket 1 (CR <= -11); `combat_ratio_max = 999` for bracket 13 (CR >= +11).

Source: Project Aon Lone Wolf gamebooks, Kai series (Books 1-5).

Last verified: 2026-03-19

### `combat_results` rows (era = 'kai')

| era | random_number | combat_ratio_min | combat_ratio_max | enemy_loss | hero_loss |
|-----|--------------|-----------------|-----------------|------------|-----------|
| kai | 0 | -999 | -11 | 6 | NULL |
| kai | 0 | -10 | -9 | 7 | NULL |
| kai | 0 | -8 | -7 | 8 | NULL |
| kai | 0 | -6 | -5 | 9 | NULL |
| kai | 0 | -4 | -3 | 10 | NULL |
| kai | 0 | -2 | -1 | 11 | NULL |
| kai | 0 | 0 | 0 | 12 | NULL |
| kai | 0 | 1 | 2 | 14 | NULL |
| kai | 0 | 3 | 4 | 16 | NULL |
| kai | 0 | 5 | 6 | 18 | NULL |
| kai | 0 | 7 | 8 | NULL | NULL |
| kai | 0 | 9 | 10 | NULL | NULL |
| kai | 0 | 11 | 999 | NULL | NULL |
| kai | 1 | -999 | -11 | 0 | NULL |
| kai | 1 | -10 | -9 | 0 | 8 |
| kai | 1 | -8 | -7 | 0 | 8 |
| kai | 1 | -6 | -5 | 1 | 7 |
| kai | 1 | -4 | -3 | 2 | 6 |
| kai | 1 | -2 | -1 | 3 | 6 |
| kai | 1 | 0 | 0 | 4 | 5 |
| kai | 1 | 1 | 2 | 5 | 5 |
| kai | 1 | 3 | 4 | 6 | 4 |
| kai | 1 | 5 | 6 | 7 | 4 |
| kai | 1 | 7 | 8 | 8 | 3 |
| kai | 1 | 9 | 10 | 9 | 3 |
| kai | 1 | 11 | 999 | 10 | 2 |
| kai | 2 | -999 | -11 | 0 | NULL |
| kai | 2 | -10 | -9 | 0 | 8 |
| kai | 2 | -8 | -7 | 1 | 7 |
| kai | 2 | -6 | -5 | 2 | 6 |
| kai | 2 | -4 | -3 | 3 | 6 |
| kai | 2 | -2 | -1 | 4 | 5 |
| kai | 2 | 0 | 0 | 5 | 5 |
| kai | 2 | 1 | 2 | 6 | 4 |
| kai | 2 | 3 | 4 | 7 | 4 |
| kai | 2 | 5 | 6 | 8 | 3 |
| kai | 2 | 7 | 8 | 9 | 3 |
| kai | 2 | 9 | 10 | 10 | 2 |
| kai | 2 | 11 | 999 | 11 | 2 |
| kai | 3 | -999 | -11 | 0 | 6 |
| kai | 3 | -10 | -9 | 1 | 6 |
| kai | 3 | -8 | -7 | 2 | 5 |
| kai | 3 | -6 | -5 | 3 | 5 |
| kai | 3 | -4 | -3 | 4 | 5 |
| kai | 3 | -2 | -1 | 5 | 4 |
| kai | 3 | 0 | 0 | 6 | 4 |
| kai | 3 | 1 | 2 | 7 | 4 |
| kai | 3 | 3 | 4 | 8 | 3 |
| kai | 3 | 5 | 6 | 9 | 3 |
| kai | 3 | 7 | 8 | 10 | 2 |
| kai | 3 | 9 | 10 | 11 | 2 |
| kai | 3 | 11 | 999 | 12 | 1 |
| kai | 4 | -999 | -11 | 0 | 6 |
| kai | 4 | -10 | -9 | 2 | 5 |
| kai | 4 | -8 | -7 | 3 | 5 |
| kai | 4 | -6 | -5 | 4 | 4 |
| kai | 4 | -4 | -3 | 5 | 4 |
| kai | 4 | -2 | -1 | 6 | 4 |
| kai | 4 | 0 | 0 | 7 | 3 |
| kai | 4 | 1 | 2 | 8 | 3 |
| kai | 4 | 3 | 4 | 9 | 3 |
| kai | 4 | 5 | 6 | 10 | 2 |
| kai | 4 | 7 | 8 | 11 | 2 |
| kai | 4 | 9 | 10 | 12 | 1 |
| kai | 4 | 11 | 999 | 14 | 1 |
| kai | 5 | -999 | -11 | 1 | 6 |
| kai | 5 | -10 | -9 | 3 | 5 |
| kai | 5 | -8 | -7 | 4 | 4 |
| kai | 5 | -6 | -5 | 5 | 4 |
| kai | 5 | -4 | -3 | 6 | 3 |
| kai | 5 | -2 | -1 | 7 | 3 |
| kai | 5 | 0 | 0 | 8 | 3 |
| kai | 5 | 1 | 2 | 9 | 2 |
| kai | 5 | 3 | 4 | 10 | 2 |
| kai | 5 | 5 | 6 | 11 | 2 |
| kai | 5 | 7 | 8 | 12 | 1 |
| kai | 5 | 9 | 10 | 14 | 1 |
| kai | 5 | 11 | 999 | 16 | 0 |
| kai | 6 | -999 | -11 | 2 | 5 |
| kai | 6 | -10 | -9 | 4 | 4 |
| kai | 6 | -8 | -7 | 5 | 4 |
| kai | 6 | -6 | -5 | 6 | 3 |
| kai | 6 | -4 | -3 | 7 | 3 |
| kai | 6 | -2 | -1 | 8 | 2 |
| kai | 6 | 0 | 0 | 9 | 2 |
| kai | 6 | 1 | 2 | 10 | 2 |
| kai | 6 | 3 | 4 | 11 | 1 |
| kai | 6 | 5 | 6 | 12 | 1 |
| kai | 6 | 7 | 8 | 14 | 0 |
| kai | 6 | 9 | 10 | 16 | 0 |
| kai | 6 | 11 | 999 | 18 | 0 |
| kai | 7 | -999 | -11 | 3 | 5 |
| kai | 7 | -10 | -9 | 5 | 4 |
| kai | 7 | -8 | -7 | 6 | 3 |
| kai | 7 | -6 | -5 | 7 | 3 |
| kai | 7 | -4 | -3 | 8 | 2 |
| kai | 7 | -2 | -1 | 9 | 2 |
| kai | 7 | 0 | 0 | 10 | 2 |
| kai | 7 | 1 | 2 | 11 | 1 |
| kai | 7 | 3 | 4 | 12 | 1 |
| kai | 7 | 5 | 6 | 14 | 0 |
| kai | 7 | 7 | 8 | 16 | 0 |
| kai | 7 | 9 | 10 | 18 | 0 |
| kai | 7 | 11 | 999 | NULL | 0 |
| kai | 8 | -999 | -11 | 4 | 4 |
| kai | 8 | -10 | -9 | 6 | 3 |
| kai | 8 | -8 | -7 | 7 | 3 |
| kai | 8 | -6 | -5 | 8 | 2 |
| kai | 8 | -4 | -3 | 9 | 2 |
| kai | 8 | -2 | -1 | 10 | 2 |
| kai | 8 | 0 | 0 | 11 | 1 |
| kai | 8 | 1 | 2 | 12 | 1 |
| kai | 8 | 3 | 4 | 14 | 0 |
| kai | 8 | 5 | 6 | 16 | 0 |
| kai | 8 | 7 | 8 | 18 | 0 |
| kai | 8 | 9 | 10 | NULL | 0 |
| kai | 8 | 11 | 999 | NULL | 0 |
| kai | 9 | -999 | -11 | 5 | 4 |
| kai | 9 | -10 | -9 | 7 | 3 |
| kai | 9 | -8 | -7 | 8 | 2 |
| kai | 9 | -6 | -5 | 9 | 2 |
| kai | 9 | -4 | -3 | 10 | 1 |
| kai | 9 | -2 | -1 | 11 | 1 |
| kai | 9 | 0 | 0 | 12 | 0 |
| kai | 9 | 1 | 2 | 14 | 0 |
| kai | 9 | 3 | 4 | 16 | 0 |
| kai | 9 | 5 | 6 | 18 | 0 |
| kai | 9 | 7 | 8 | NULL | 0 |
| kai | 9 | 9 | 10 | NULL | 0 |
| kai | 9 | 11 | 999 | NULL | 0 |
