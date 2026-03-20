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
| `inventory_adjust` | 1 | `null` (limits from book_transition_rules) |
| `confirm` | 2 | `null` |

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
