# Epic 8: Player UI (HTMX + Jinja2 + Pico CSS)

**Phase**: 5
**Dependencies**: Epics 6, 7
**Status**: Complete (2026-03-22)

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

**Status**: Complete (2026-03-22)

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

**Status**: Complete (2026-03-22)

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

**Status**: Complete (2026-03-22)

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

**Status**: Complete (2026-03-22)

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

**Status**: Complete (2026-03-22)

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

**Status**: Complete (2026-03-22)

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
1. Call the service layer directly (same DB session, no internal HTTP round-trip)
2. Render Jinja2 templates with the response data
3. Handle session cookies for auth

Note: the epic description says "calls JSON API internally" but Story 8.1 calls the service
layer directly (e.g., `db.query(User)`, `hash_password`, `verify_password`). This is the
correct approach — internal HTTP calls would add unnecessary latency and coupling. The
MASTER.md architectural note ("calls the API internally") is intentionally loose; direct
service calls satisfy that intent. No spec change needed.

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

---

### Tech Writer Notes — Phase 2 Review (2026-03-22)

Stories 8.2, 8.3, and 8.6 reviewed against all templates and router code.

**Terminology**: Game terminology (Scene, Choice, Discipline, Combat Skill, Endurance, Gold Crowns, Meals, Run, Phase) is used correctly throughout all templates. No implementation-vocabulary leakage detected. "Encyclopedia" label in nav (`layout/player.html`) is consistent with the game objects browse pages (`game_objects/list.html` title, `game_objects/detail.html` back-link label). This is a player-friendly label rather than the spec term "Game Object" — appropriate for the UI layer.

**Template naming**: All templates specified in Stories 8.2, 8.3, and 8.6 are present and correctly named. Two additional partial templates were added (`characters/partials/stats_display.html` for HTMX stat roll fragment, `characters/history_rows.html` for HTMX "Load More" rows). These are code-ahead additions not in the spec; both are correct design choices.

**Route paths**: All UI route prefixes are consistent. Characters router uses `/ui/characters/*`. Browse router uses `/ui/books/*`, `/ui/game-objects/*`, `/ui/leaderboards`. Gameplay router uses `/ui/game/*`. No overlap or ambiguity.

**Bugs found (require fixes before claiming Story AC):**

1. **Dead link in sheet.html** — `templates/characters/sheet.html` line 16: `href="/ui/characters/{{ character.id }}/play"`. Route `/ui/characters/{id}/play` does not exist. Correct URL is `/ui/game/{{ character.id }}`.

2. **Missing `scene_id_int` in template context** — `templates/gameplay/scene.html` line 215 references `{{ scene_id_int if scene_id_int else 0 }}` in the bug report form, but `scene_id_int` is never added to the template context by `gameplay.py`'s `scene_page()`. The `SceneResponse` schema has no `scene_id` field. Result: every submitted bug report records `scene_id = 0`. Fix: pass `scene_id_int` in context (requires adding `scene_id` to `SceneResponse` or resolving it in the router from `character.current_scene_id`).

3. **Missing advance wizard sub-routes** — `templates/characters/wizard_disciplines.html`, `wizard_inventory.html`, and `wizard_advance_confirm.html` POST to `/ui/characters/{id}/wizard/disciplines`, `/ui/characters/{id}/wizard/inventory`, and `/ui/characters/{id}/wizard/confirm` respectively. None of these sub-routes are registered in `app/routers/ui/characters.py`. The router handles `POST /ui/characters/{character_id}/wizard` only (which covers `pick_equipment` and `confirm` steps for the creation wizard). The advance wizard steps need their own route handlers.

4. **Missing advance route in gameplay router** — `templates/gameplay/scene.html` references `action="/ui/game/{{ character.id }}/advance"` in the victory panel. This route (`POST /ui/game/{character_id}/advance`) does not exist in `app/routers/ui/gameplay.py`. This means clicking "Advance to Next Book" will 404.

Items 3 and 4 are Story 8.6 scope (book advance wizard). Items 1 and 2 are Story 8.6 and Story 8.3 scope respectively. Stories should be marked Complete only after these are resolved.

---

### Tech Writer Notes — Final Review (2026-03-22)

All 6 stories reviewed against all templates and router code. Epic 8 is **Complete**.

**All four Phase 2 bugs resolved:**

1. Dead link in `sheet.html` — Fixed. `href="/ui/characters/{{ character.id }}/play"` is now `href="/ui/game/{{ character.id }}"`.

2. `scene_id_int` in template context — Fixed. The bug report form (`scene.html` line 513) now reads `character.current_scene_id` directly from the ORM character object passed in template context. No `scene_id_int` variable needed.

3. Advance wizard sub-routes — Fixed. All advance wizard templates (`wizard_disciplines.html`, `wizard_inventory.html`, `wizard_advance_confirm.html`) POST to the unified `/ui/characters/{id}/wizard` endpoint using a hidden `step` field. The `wizard_post` handler in `app/routers/ui/characters.py` dispatches on `step` value and handles all four cases: `pick_equipment`, `confirm`, `pick_disciplines`, `inventory_adjust`. No sub-routes needed or present — the unified endpoint pattern is correct.

4. Missing advance route in gameplay router — Fixed. `POST /ui/game/{character_id}/advance` is implemented at line 373 of `app/routers/ui/gameplay.py`. On success it calls `init_book_advance_wizard()` and redirects to `/ui/characters/{character_id}/wizard`.

**Stories 8.4 and 8.5 implementation approach:**

Stories 8.4 (Combat & Random UI) and 8.5 (Items & Inventory UI) were implemented as sections within `templates/gameplay/scene.html` rather than as separate template files. The spec described `templates/gameplay/combat.html`, `templates/gameplay/random.html`, `templates/gameplay/items.html`, and `templates/gameplay/inventory.html` as separate files. The implementation merges all phases into one scene template using conditional blocks (`{% if scene.phase == "combat" %}`, `{% elif scene.pending_items %}`, etc.) and an always-visible inventory drawer `<details>` element.

This is a valid architecture divergence: the single-template approach avoids redirect chains between phase templates and keeps all game state visible. The acceptance criteria for both stories are satisfied within `scene.html`. No separate template files were created for these stories — this is a **code-ahead** pattern where implementation differs structurally from spec while meeting all behavioral requirements.

**Item management in scene.html**: The inventory drawer includes drop/equip/unequip buttons (Stories 8.5 AC) posting to `/ui/game/{id}/item/drop`, `/ui/game/{id}/item/equip`, `/ui/game/{id}/item/unequip`, and `/ui/game/{id}/item/use`. All routes are registered in `app/routers/ui/gameplay.py`. Pending item accept/decline posts to `/ui/game/{id}/item/accept` and `/ui/game/{id}/item/decline`. All item management AC is met.

**Combat UI in scene.html**: Enemy and hero endurance bars, Fight button, Psi-surge toggle (conditional on discipline), Evasion button (conditional on `combat.can_evade`), evasion-hint text (when not yet evadable), and round counter are all present. All combat AC is met.

**Random roll in scene.html**: Choice-triggered random, phase-based random, and combined states are handled. Roll button posts to `/ui/game/{id}/roll`. All roll AC is met.

**Terminology verification**: All templates use canonical glossary terms throughout. Confirmed:
- "Encyclopedia" used in nav (`layout/player.html`) and page heading (`game_objects/list.html`). Correct player-facing label; the internal "Game Object" spec term does not appear in player-facing UI.
- Filter label in encyclopedia is "Type" (`game_objects/list.html` line 11) — not "Kind". This is a deliberate player-friendly label. "Kind" appears only in the detail page `<dl>` under "Related Entities" as a technical display item (`game_objects/detail.html` line 24), which is acceptable.
- "Scene" used throughout (not "section"). "Choice" used (not "option"). "Discipline" used. "Combat Skill" / "CS" used. "Endurance" / "END" used. "Gold Crowns" / "Gold" used. "Meals" used. "Run" used in history filter. "Phase" used in stats display.
- "Special Items" label in inventory drawer is consistent with the glossary definition of "Special item".

**Template naming verification**: All templates specified in Stories 8.1–8.6 are present. Two code-ahead partial templates added: `characters/partials/stats_display.html`, `characters/history_rows.html`. One code-ahead template added: `game_objects/_results.html` (HTMX results partial). One code-ahead partial: `leaderboards/_content.html` (HTMX book-filter partial). All additions are sound design decisions.

**Route path verification**:
- `/ui/login`, `/ui/register`, `/ui/logout`, `/ui/change-password` — auth (Story 8.1)
- `/ui/characters`, `/ui/characters/roll`, `/ui/characters/create`, `/ui/characters/{id}/wizard`, `/ui/characters/{id}/sheet`, `/ui/characters/{id}/history` — character management
- `/ui/game/{id}`, `/ui/game/{id}/choose`, `/ui/game/{id}/restart`, `/ui/game/{id}/replay`, `/ui/game/{id}/advance`, `/ui/game/{id}/combat/round`, `/ui/game/{id}/combat/evasion`, `/ui/game/{id}/roll`, `/ui/game/{id}/item/accept`, `/ui/game/{id}/item/decline`, `/ui/game/{id}/item/drop`, `/ui/game/{id}/item/equip`, `/ui/game/{id}/item/unequip`, `/ui/game/{id}/item/use`, `/ui/game/{id}/report` — gameplay
- `/ui/books`, `/ui/books/{id}`, `/ui/game-objects`, `/ui/game-objects/{id}`, `/ui/leaderboards` — browse
No overlaps. All routes confirmed registered in the respective router modules.

**Docstring/comment accuracy**: All route docstrings accurately describe behavior. The `scene.html` comment on narrative `| safe` (line 55) correctly documents the trust boundary. The Psi-surge JS block (lines 249–260) is accurate. No misleading comments found.

**Minor note**: `game_objects/detail.html` line 25 displays `obj.kind` under "Kind" label in the `<dl>`, which exposes the internal `Kind` taxonomy term to players. This is a detail page only visible after a user selects a result. The exposure is minor and acceptable — it mirrors the filter label "Type" used on the list page. The inconsistency between "Type" (list page filter) and "Kind" (detail page data label) is noted for future consistency pass but does not block Epic completion.

**Spec deviation recorded**: Stories 8.4 and 8.5 template structure diverges from spec (merged into `scene.html` rather than separate files). All AC met; deviation is intentional and preferable.
