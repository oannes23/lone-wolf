# Tutorials

Step-by-step walkthroughs for first-time use.

---

## Tutorial 1: Your First Game

This walkthrough takes you from zero to playing your first scene in Book 1: *Flight from the Dark*.

### 1. Register and Log In

Open `http://127.0.0.1:8000/ui/login`. Click **Create an account**, fill in your details, and log in. You'll land on the Characters page.

### 2. Roll Your Stats

Click **Create New Character**. The game rolls two numbers for you:

- **Combat Skill** (10-19) — determines how effective you are in combat. Higher is better.
- **Endurance** (20-29) — your health. When it hits 0, you die.

You can re-roll as many times as you want. A solid roll is CS 15+ and END 25+, but any roll is viable. Click **Accept & Continue** when you're satisfied.

### 3. Choose Your Disciplines

Name your character and choose exactly 5 out of 10 Kai Disciplines. Here's some tactical advice for your first playthrough:

| Discipline | Why it's useful |
|------------|-----------------|
| **Healing** | Regenerate Endurance between scenes. Strongly recommended. |
| **Sixth Sense** | Reveals hidden information and unlocks unique choices. |
| **Weaponskill** | +2 Combat Skill when wielding your chosen weapon type. Pick a common weapon like Sword. |
| **Hunting** | Never go hungry — meals are handled automatically, so you never lose Endurance from hunger. |
| **Mindblast** | +2 CS in combat (stacks with Weaponskill). Can also activate Psi-surge for +4 CS at a cost. |

The remaining five (Mind Over Matter, Animal Kinship, Tracking, Camouflage, Mindshield) each unlock specific choices throughout the books. They're all useful — pick what sounds interesting.

If you chose **Weaponskill**, select a weapon type from the dropdown. **Sword** is a safe choice since swords appear frequently.

### 4. Choose Starting Equipment

Some items are auto-included. You can choose additional optional items up to the limit shown. Tips:

- Take a weapon that matches your Weaponskill type if you chose that discipline.
- Meals are valuable if you don't have Hunting.
- A healing potion (Laumspur) can save your life in combat.

### 5. Confirm and Begin

Review your character and click **Begin Adventure!** You'll be placed at Scene 1 of Book 1.

### 6. Play Your First Scene

You'll see:

- The **stats bar** across the top showing your CS, END, Gold, and Meals.
- The **scene narrative** — read the story.
- **Choices** at the bottom — click one to advance.

Some choices may be grayed out with a requirement you don't meet. That's normal — your discipline choices affect which paths are available.

### 7. Your First Combat

When you encounter an enemy, the combat panel appears showing both combatants' stats. Look at the **Combat Ratio** — positive means you have the advantage.

Click **Fight** to resolve each round. The Combat Results Table determines damage to both sides. Keep fighting until the enemy's Endurance hits 0 (or yours does).

If you have Mindblast, consider toggling **Psi-surge** for tough fights (+4 CS, but costs 2 END per round).

### 8. Managing Your Inventory

Open the **inventory drawer** at the bottom of any scene. You can:

- **Equip** a weapon (important for Weaponskill bonus)
- **Drop** items to make room for better ones
- Track your Gold and Meals

### 9. If You Die

Don't worry — click **Restart from Book Start**. You keep the same character with original stats. Your death count goes up and a new "run" begins, but all your previous decision history is preserved.

---

## Tutorial 2: Setting Up as Admin

This walkthrough covers getting the full system operational: server, content, and admin tools.

### 1. Install and Start the Server

Follow the Quick Start in the [README](../README.md):

```bash
uv sync
# Create .env with JWT_SECRET=change-me-for-production
uv run alembic upgrade head
JWT_SECRET=change-me-for-production uv run python scripts/seed_static.py
JWT_SECRET=change-me-for-production uv run uvicorn app.main:app --reload
```

Verify the server is running by opening `http://127.0.0.1:8000/docs` (Swagger UI).

### 2. Create Your Admin Account

```bash
JWT_SECRET=change-me-for-production uv run python scripts/create_admin.py \
    --username admin \
    --password secret
```

### 3. Import Your First Book

Get the Project Aon XHTML file for Book 1 and run:

```bash
JWT_SECRET=change-me-for-production uv run python scripts/seed_db.py \
    --source-dir /path/to/xhtml/files \
    --book 1 \
    --skip-llm
```

Using `--skip-llm` skips the LLM enrichment step, making the import fast and requiring no API key. The game is fully playable without it.

### 4. Tour the Admin Dashboard

Log in at `http://127.0.0.1:8000/admin/ui/login`.

The dashboard shows:

- **Open Reports** — bug reports from players awaiting triage
- **Total Users** and **Total Characters** — system-wide counts
- **Books with Content** — how many books have imported scene data
- **Recent Reports** — the latest player submissions
- **Quick Links** — jump to content management, reports, or user management

### 5. Browse and Edit Content

Click **Content** in the nav bar. You'll see the resource type index with 13 categories.

Try browsing **Scenes**:

1. Click **Scenes** to see a paginated list of all scenes for the imported book.
2. Click any scene row to see its detail page.
3. Click **Edit** to modify the scene.
4. The scene editor shows the narrative HTML, boolean flags (death scene, victory scene, must eat, loses backpack), and linked content (choices, combat encounters, scene items).
5. Linked content items are read-only here but link to their own edit pages.

### 6. Triage a Bug Report

To test the report flow:

1. **As a player**: Log in via the player UI, play to any scene, open the "Report a problem" section at the bottom, select a tag, type a description, and submit.
2. **As an admin**: Go to **Reports** in the admin nav. You should see the new report with status "open".
3. Click the report to see details, including the linked scene narrative.
4. Change the status to "triaging", add an admin note, and save.
5. After investigating, change the status to "resolved" or "wont_fix".

---

## Tutorial 3: Advancing to Book 2

What happens after you complete Book 1: *Flight from the Dark*.

### Prerequisites

- Book 2 must be imported (via `seed_db.py --book 2`)
- A book transition rule must exist linking Book 1's victory to Book 2 (created by `seed_static.py`)

### 1. Reach the Victory Scene

Play through Book 1 until you reach the victory scene. The narrative will indicate you've completed the quest. A **victory panel** appears with two options:

- **Advance to Next Book** — continue your character's story
- **Replay This Book** — play Book 1 again from the start

Click **Advance to Next Book**.

### 2. The Advancement Wizard

**Step 1 — Choose a New Discipline**

You already have 5 disciplines. Choose 1 more from those you haven't learned yet. If you pick Weaponskill now, you'll also select a weapon type.

**Step 2 — Adjust Your Inventory**

The next book may have different equipment limits. Choose which weapons and backpack items to carry forward. Special items are carried automatically.

**Step 3 — Confirm**

Review your updated character — stats, 6 disciplines, and carried-forward equipment. Click **Confirm and Advance**.

### 3. Starting Book 2

Your character begins at Book 2's starting scene with:

- The same base stats (Combat Skill and Endurance reset to base values)
- All 6 disciplines
- The equipment you chose to carry forward
- New starting gold and meals for the era
- A fresh run counter for this book

Your Book 1 decision history is preserved and viewable from the character sheet.
