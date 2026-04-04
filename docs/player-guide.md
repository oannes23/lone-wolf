# Player Guide

Everything you need to register, create characters, and play through the Lone Wolf gamebooks.

---

## Getting Started

### Creating an Account

1. Open `http://127.0.0.1:8000/ui/login` in your browser.
2. Click **Create an account**.
3. Enter a username, email address, and password (8-128 characters).
4. Click **Create Account**, then log in with your credentials.

### Navigating the UI

The top navigation bar has:

- **Characters** — your character list
- **Books** — browse available books and their rules
- **Encyclopedia** — search game world entities (characters, items, creatures, locations)
- **Account** — change password
- **Log Out**
- **Theme toggle** — switch between light and dark mode (saved in your browser)

On mobile, these links are behind a hamburger menu.

---

## Characters

### Creating a Character

From the **Characters** page, click **Create New Character**.

**Step 1 — Roll Stats**

The game rolls your starting Combat Skill (10-19) and Endurance (20-29) using the Kai formula. You can re-roll as many times as you like. Click **Accept & Continue** when you're happy with the result.

**Step 2 — Name and Disciplines**

- Give your character a name.
- Choose exactly **5 Kai Disciplines** from the list of 10. Each discipline is described in the form. A counter shows how many you've selected.
- If you choose **Weaponskill**, a dropdown appears to select which weapon type you specialize in (giving +2 Combat Skill when wielding that weapon).

**Step 3 — Starting Equipment**

- Some items are automatically included (shown as "Included").
- Choose optional items up to the allowed limit. A counter tracks your selections.
- Starting gold and meals are shown.

**Step 4 — Confirm**

Review your character's name, stats, disciplines, and equipment. Click **Begin Adventure!** to start playing.

### Character List

Your characters page shows cards for each character with:

- Name, book, Combat Skill, Endurance, current scene, death count
- Status: **Alive**, **Dead**, or **Setup in progress**
- **Play** button to continue the adventure, or **Continue Setup** if a wizard is unfinished

### Character Sheet

Click a character's name to see the full sheet:

- **Stats**: Combat Skill, Endurance (current / max / base), Gold, Meals
- **Progress**: Death count, current run, current scene, scene phase
- **Disciplines**: listed with weapon category if applicable
- **Equipment**: item name, type (weapon / backpack / special), equipped status
- Links to **History** and **Play**

### Decision History

From the character sheet, click **History** to see every choice you've made:

- Run number, from scene, choice text, to scene, action type, timestamp
- Filter by run number to review a specific playthrough
- Paginated with a "Load More" button

---

## Playing the Game

### Reading Scenes

Each scene shows:

- **Stats bar** at the top — Combat Skill, Endurance (current/max), Gold, Meals
- **Scene number**
- **Illustration** (if available)
- **Narrative text** — the story
- **Phase results** — automatic outcomes that occurred when you entered the scene (e.g., meal consumed, healing applied, items lost)

### Making Choices

Choices appear as buttons below the narrative under **"What do you do?"**

- Available choices are clickable.
- **Unavailable choices** are grayed out with the reason shown (e.g., "Requires: Sixth Sense" or "Requires: Sword").
- Some choices trigger a **random roll** — these are marked with a "(Roll)" badge. Clicking them opens the roll phase.

### Combat

When you enter a scene with a combat encounter, the **combat panel** appears:

- **Combatants**: your stats and the enemy's stats side by side, with endurance bars
- **Combat Ratio**: your effective Combat Skill minus the enemy's (positive = advantage)
- **Round counter**: tracks how many rounds you've fought

Each round:

1. Click **Fight** to resolve the round.
2. The server rolls a number (0-9) and looks up the result on the Combat Results Table.
3. Both you and the enemy take damage based on the combat ratio and the roll.
4. Endurance bars update. They turn yellow when low and red when critical.

**Psi-surge**: If you have the Mindblast discipline, you can toggle Psi-surge on for +4 Combat Skill at the cost of 2 Endurance per round.

**Evasion**: Some combats allow you to flee after a minimum number of rounds. The UI shows when evasion becomes available. Evading costs Endurance but lets you escape to a specific scene.

Combat ends when one side reaches 0 Endurance or you successfully evade.

### Random Rolls

Some scenes or choices require a random number (0-9). The UI shows a prompt explaining what the roll is for. Click **Roll** — the outcome is determined automatically and applied.

### Items

When you find items in a scene, an **Items Found** panel appears:

- **Required items** are marked and must be accepted.
- **Optional items** can be accepted or declined individually.
- If your inventory is full, you'll need to drop something first (see Inventory Management below).

### Inventory Management

The **inventory drawer** is always accessible at the bottom of the scene. It shows:

- **Gold** and **Meals** counters
- **Weapons** (max 2 slots) — can be Equipped, Unequipped, or Dropped
- **Backpack Items** (max 8 slots) — can be Dropped
- **Special Items** — display only, cannot be dropped

Equipping a weapon matters for Weaponskill bonuses and certain choice conditions.

### Death and Restart

When your character dies (Endurance reaches 0), a death panel appears:

- Click **Restart from Book Start** to begin the current book again with your original stats.
- Your death count increments and a new run number begins.
- All your decision history from previous runs is preserved.

### Victory and Advancement

When you reach the victory scene of a book:

- **Advance to Next Book** — starts the book advancement wizard:
  1. Choose a new discipline (from those you haven't learned yet)
  2. Adjust your inventory for the next book's limits (choose which items to carry forward)
  3. Confirm and advance to the next book's starting scene
- **Replay This Book** — restart the same book (no death count increment)

---

## Reporting Problems

Every scene has a collapsible **Report a problem** section at the bottom. To submit a report:

1. Select one or more category tags: wrong items, meal issue, missing choice, combat issue, narrative error, discipline issue, or other.
2. Add a free-text description of what's wrong.
3. Submit — the report goes to the admin triage queue with your character and scene context attached.

---

## Browsing Content

### Books

The **Books** page lists all available books with their number, title, and era. Click a book to see:

- Era, starting scene number, total scenes, max discipline picks
- A collapsible list of disciplines available in that era with descriptions

### Encyclopedia

The **Encyclopedia** page lets you browse all game world entities:

- Filter by type (characters, items, creatures, locations, etc.)
- Search by name (live search with debounce)
- Each entry shows name, kind, aliases, and a description
- Click an entry for full details: description, aliases, first appearance, properties, and related entities

### Leaderboards

The **Leaderboards** page shows rankings across three categories:

- **Fewest Deaths** — players who completed a book with the fewest deaths
- **Fewest Decisions** — most efficient path through a book
- **Highest Endurance at Victory** — healthiest finish

Filter by book or view overall rankings. Each entry shows the player name, key stat, and a secondary stat.
