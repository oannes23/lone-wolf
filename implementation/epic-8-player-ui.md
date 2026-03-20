# Epic 8: Player UI (HTMX + Jinja2 + Pico CSS)

**Phase**: 5
**Dependencies**: Epics 6, 7
**Status**: Not Started

Mobile-first responsive player interface. Built with HTMX for dynamic interactions, Jinja2 for server-side rendering, and Pico CSS for classless/semantic styling. No JavaScript frameworks, no build step. All assets vendored locally.

## UI Framework Stack

- **HTMX** (~14kb gzipped) — dynamic interactions without JS frameworks (vendored in `static/js/`)
- **Pico CSS** (~10kb gzipped) — classless semantic CSS framework (vendored in `static/css/`)
  - Mobile-first responsive out of the box
  - Built-in dark/light mode via `prefers-color-scheme` + manual toggle
  - Semantic HTML auto-styled: `<article>`, `<section>`, `<nav>`, `<details>`, `<progress>`, etc.
  - Touch-friendly controls (44px minimum tap targets per WCAG)
- **Minimal custom CSS** (`static/css/app.css`) — only for game-specific elements (endurance bars, combat display, phase indicators)
- Fully self-contained: no CDN dependencies

## Responsive Design Approach

- Single-column layout on mobile, side panels on desktop (CSS grid/flexbox, Pico breakpoints)
- Game view: narrative + action area stacked on mobile, side-by-side on desktop
- Inventory: modal/drawer on mobile, sidebar on desktop
- No horizontal scrolling on any viewport

---

## Story 8.1: UI Scaffolding & Auth Pages

**Status**: Not Started

### Description

Base template, layout, authentication pages, and session management.

### Tasks

- [ ] Vendor Pico CSS and HTMX into `static/css/` and `static/js/`
- [ ] Create `templates/base.html`:
  - `<html data-theme="dark">`
  - `<head>` with vendored Pico CSS, HTMX, app.css
  - Responsive `<meta name="viewport" content="width=device-width, initial-scale=1">`
- [ ] Create `templates/layout/player.html`:
  - `<nav>` with hamburger menu on mobile (Pico `<details>` pattern), full nav on desktop
  - Navigation links: Characters, Books, Game Objects, Leaderboards
  - Logout link
- [ ] Create auth pages:
  - `templates/auth/login.html` — semantic `<form>` with username/password
  - `templates/auth/register.html` — semantic `<form>` with username/email/password
  - `templates/auth/change_password.html` — current + new password form
- [ ] Create thin FastAPI route layer (`app/routers/ui/auth.py`):
  - Calls JSON API internally
  - Sets httpOnly session cookies on login
  - 401 responses redirect to login page
- [ ] Dark/light mode toggle:
  - JavaScript to swap `data-theme` attribute on `<html>`
  - Persist preference in localStorage

### Acceptance Criteria

- User can register and log in on both mobile and desktop
- Responsive layout verified at 375px (mobile) and 1280px (desktop) widths
- Session cookies set correctly (httpOnly, secure in production)
- 401 redirects to login page
- Dark/light mode toggle works and persists

---

## Story 8.2: Character Creation UI

**Status**: Not Started

### Description

Multi-step character creation flow: roll stats → name + disciplines → equipment wizard.

### Tasks

- [ ] Create `templates/characters/roll.html`:
  - Display CS/END with formula breakdown in `<article>`
  - "Roll Again" button (HTMX swap, replaces stat display)
  - "Accept" button (proceeds to finalize)
- [ ] Create `templates/characters/create.html`:
  - Name `<input>` field
  - Discipline picker: 5 checkboxes in `<fieldset>` (10 Kai disciplines)
  - Weapon skill type `<select>` (conditionally visible when Weaponskill selected)
  - Submit button
- [ ] Create `templates/characters/wizard_equipment.html`:
  - Included items displayed in `<table>` (non-selectable, labeled "Included")
  - Auto-applied gold/meals shown
  - Available equipment as checkboxes with pick limit counter
  - Submit button
- [ ] Create `templates/characters/wizard_confirm.html`:
  - Summary of all selections
  - Final stats with equipment bonuses applied
  - Confirm button
- [ ] Version tracking via hidden `<input type="hidden" name="version">`
- [ ] All forms touch-friendly with appropriate input types

### Acceptance Criteria

- Full character creation flow works on mobile and desktop
- Stat roll updates without full page reload (HTMX)
- Discipline picker enforces exactly 5 selections (client-side validation)
- Weapon skill type field shows/hides based on Weaponskill selection
- Created character appears in character list

---

## Story 8.3: Scene & Choices UI

**Status**: Not Started

### Description

Core gameplay scene display with narrative, phase results, choices, and special scene types.

### Tasks

- [ ] Create `templates/gameplay/scene.html`:
  - Narrative display in `<article>` (rendered HTML from API)
  - Illustration as responsive `<img>` (max-width: 100%)
- [ ] Phase results banner:
  - `<aside>` element with role-based styling:
    - `info` → muted/default Pico colors
    - `warn` → amber/yellow via Pico CSS variables
    - `danger` → red via Pico CSS variables
  - Shows eat results, heal results, item loss, etc.
- [ ] Choice display:
  - `<button>` elements in vertical stack
  - Full-width on mobile, natural width on desktop
  - Unavailable choices: `<button disabled>` with condition label underneath
  - HTMX POST on click → transitions to new scene
- [ ] Death panel:
  - `<article>` with death narrative
  - "Restart from Book Start" button
- [ ] Victory panel:
  - `<article>` with victory narrative
  - "Replay Book" and "Advance to Next Book" buttons
- [ ] Bug report:
  - `<details>` collapsible at bottom of scene
  - `<form>` inside with tag checkboxes and free text `<textarea>`
  - HTMX submit

### Acceptance Criteria

- Player can navigate scenes on mobile with one-thumb operation
- Desktop layout uses wider viewport effectively
- Phase results displayed with correct severity styling
- Unavailable choices visually distinct and non-interactive
- Death and victory panels show correct options
- Bug report submits without page reload

---

## Story 8.4: Combat & Random UI

**Status**: Not Started

### Description

Combat round-by-round display and random number rolling interface.

### Tasks

- [ ] Create `templates/gameplay/combat.html`:
  - Combat panel in `<article>`:
    - Enemy name and stats
    - `<progress>` bars for enemy and hero END (Pico-styled)
    - "Fight" `<button>` (full-width, easy tap target)
  - Psi-surge toggle (checkbox or button, if available)
  - Round result displayed inline via HTMX swap
  - Evasion button: conditionally visible after N rounds, full-width on mobile
  - Combat over state: shows "win" or "loss" result, "Continue" button
- [ ] Create `templates/gameplay/random.html`:
  - Phase-based random: large "Roll" `<button>`, result in `<article>`, "Continue" button
  - Choice-triggered random: outcome bands displayed in `<table>`, roll button
  - Multi-roll: button text changes to "Roll Again" when rolls_remaining > 0
  - Scene-level random: roll button, result shows transition target

### Acceptance Criteria

- Combat interactions work smoothly on touch screens (large tap targets)
- END bars update after each round via HTMX
- Evasion button appears at correct round threshold
- Random roll results display clearly
- Multi-roll sequence works (roll again button appears)

---

## Story 8.5: Items & Inventory UI

**Status**: Not Started

### Description

Pending item accept/decline and full inventory management interface.

### Tasks

- [ ] Create `templates/gameplay/items.html`:
  - Pending items: `<article>` per item with accept/decline `<button>` row
  - Mandatory items: accept only (no decline button), labeled "Required"
  - HTMX updates as items are accepted/declined
- [ ] Create `templates/gameplay/inventory.html`:
  - `<details>` drawer on mobile (expandable), `<aside>` sidebar on desktop
  - Sections:
    - Weapons: with equip/unequip toggle button per weapon
    - Backpack items: with drop button
    - Special items: display only
    - Gold counter
    - Meals counter
  - Drop via `<button>` per item
  - Equip/unequip via HTMX toggle
  - Use consumable: `<button>` on each consumable item
  - Slot counters: "Weapons: 1/2", "Backpack: 5/8"

### Acceptance Criteria

- Inventory management works on mobile without horizontal scroll
- Accept/decline updates pending list via HTMX (no full page reload)
- Mandatory items show accept only
- Drop/equip/unequip work via HTMX
- Consumable use works via HTMX
- Slot counters update after inventory changes

---

## Story 8.6: Character Sheet, History & Browse

**Status**: Not Started

### Description

Character detail views, decision history, book advance wizard, and content browsing pages.

### Tasks

- [ ] Create `templates/characters/sheet.html`:
  - Semantic `<dl>` for stats (CS, END, gold, meals, death_count, run)
  - `<table>` for items and disciplines
  - Current scene info
- [ ] Create `templates/characters/history.html`:
  - Paginated `<table>` with columns: scene, action, choice text, timestamp
  - Run filter `<select>`
  - "Load More" via HTMX (append to table)
- [ ] Create book advance wizard templates:
  - `templates/characters/wizard_disciplines.html` — discipline selection
  - `templates/characters/wizard_inventory.html` — drop items to fit limits
  - `templates/characters/wizard_advance_confirm.html` — summary + confirm
  - Same 4-step flow pattern as creation wizard
- [ ] Create browse pages:
  - `templates/books/list.html` — book cards in `<article>` elements
  - `templates/books/detail.html` — book info with discipline list in `<details>`
  - `templates/game_objects/list.html` — kind filter `<select>` + search `<input>`, results as `<article>` cards
  - `templates/game_objects/detail.html` — properties, refs list
  - `templates/leaderboards/index.html` — `<table>` per stat category with book `<select>` filter

### Acceptance Criteria

- Character sheet displays all stats and inventory
- Decision history loads more entries via HTMX
- Book advance wizard works through all 4 steps
- Books browser shows all books with discipline lists
- Game objects browser filterable by kind and searchable
- Leaderboards display per-book stats
- All browse features work on mobile (tables scroll horizontally only when truly necessary)

---

## Implementation Notes

### UI Route Layer

The UI routes are thin wrappers that:
1. Call the JSON API endpoints internally (using the same service layer)
2. Render Jinja2 templates with the response data
3. Handle session cookies for auth

```python
@router.get("/game/{character_id}")
async def game_scene(character_id: int, request: Request, db = Depends(get_db)):
    user = get_user_from_session(request)
    scene_data = gameplay_service.get_scene(db, character_id, user)
    return templates.TemplateResponse("gameplay/scene.html", {"scene": scene_data, ...})
```

### HTMX Patterns

- `hx-post` / `hx-get` for API calls
- `hx-target` to specify what to replace
- `hx-swap` modes: innerHTML, outerHTML, afterbegin
- `hx-trigger` for events (click, change)
- `hx-indicator` for loading states
- `hx-vals` for hidden form values (version tracking)

### Custom CSS (app.css)

Minimal additions beyond Pico:
- Endurance bar colors (green → yellow → red based on percentage)
- Phase result severity colors (info/warn/danger)
- Combat display layout
- Sticky inventory drawer on mobile
- "Required" badge for mandatory items
