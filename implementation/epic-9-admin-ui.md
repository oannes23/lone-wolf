# Epic 9: Admin UI (HTMX + Jinja2 + Pico CSS)

**Phase**: 6
**Dependencies**: Epics 7, 8
**Status**: Not Started

Admin interface for content management, report triage, and user management. Shares UI patterns and Pico CSS setup from Epic 8. Separate admin layout with admin-specific navigation.

---

## Story 9.1: Admin Scaffolding & Auth

**Status**: Not Started

### Description

Admin layout, login page, and dashboard.

### Tasks

- [ ] Create `templates/layout/admin.html`:
  - Separate admin layout extending base.html
  - `<nav>` with admin-specific links: Dashboard, Content, Reports, Users
  - Visual distinction from player UI (e.g., different accent color via Pico theme vars)
- [ ] Create `templates/admin/login.html`:
  - Semantic `<form>` with username/password
  - Admin login calls `POST /admin/auth/login`
  - Session cookie for admin auth (separate from player cookies)
- [ ] Create `templates/admin/dashboard.html`:
  - Summary `<article>` cards in responsive grid:
    - Open reports count
    - Total users count
    - Total characters count
    - Books with content count
    - Recent report activity
  - Quick links to common admin tasks
- [ ] Create admin UI route layer (`app/routers/ui/admin.py`)

### Acceptance Criteria

- Admin can log in and see dashboard
- Dashboard responsive on mobile (cards stack vertically) and desktop (grid)
- Admin nav shows correct links
- Player session cookies do not grant admin access

---

## Story 9.2: Content Management Pages

**Status**: Not Started

### Description

Browse and edit all content types through the admin UI.

### Tasks

- [ ] Create `templates/admin/content/list.html` (generic list template):
  - `<table>` with columns appropriate to resource type
  - Pagination controls
  - Filter `<form>` at top (responsive — stacks vertically on mobile)
  - "New" button opens create form
  - Row click navigates to detail view
- [ ] Create `templates/admin/content/detail.html` (generic edit template):
  - `<form>` with all editable fields
  - Source badge: `<mark>` element styled for auto vs manual
  - Save button, Delete button (with confirmation)
- [ ] Create resource-specific templates where needed:
  - `templates/admin/content/scene_edit.html`:
    - Narrative `<textarea>` (large, monospace)
    - Phase override field
    - Checkboxes for is_death, is_victory, must_eat, loses_backpack
    - Linked content sections (choices, encounters, items) in `<details>` expandables
  - Other resources use the generic templates
- [ ] Route all content types through `/admin/content/{resource_type}` URL pattern

### Acceptance Criteria

- Admin can browse all content types (list view with pagination)
- Admin can edit content (detail view with form)
- Source badge displays correctly (auto=gray, manual=blue)
- Scene edit shows narrative textarea and linked content
- "New" creates new content with source='manual'
- Mobile and desktop both functional

---

## Story 9.3: Report Triage UI

**Status**: Not Started

### Description

Report queue for reviewing and triaging player bug reports.

### Tasks

- [ ] Create `templates/admin/reports/list.html`:
  - Filterable `<table>`: status filter, tag filter
  - Columns: ID, tags, status, user, scene, created_at
  - Inline expand via `<details>` or HTMX swap for quick preview
  - Color-coded status badges
- [ ] Create `templates/admin/reports/detail.html`:
  - Scene narrative snippet (linked from report's scene_id)
  - Tags displayed as badges
  - Admin notes `<textarea>`
  - Status `<select>` dropdown (open → triaging → resolved → wont_fix)
  - resolved_by auto-set to current admin on status change
  - Save button
- [ ] Create `templates/admin/reports/stats.html`:
  - Summary `<article>` cards:
    - Reports by status (open, triaging, resolved, wont_fix)
    - Reports by tag
    - Resolution rate
    - Average time to resolve

### Acceptance Criteria

- Admin can view report queue with filters
- Admin can triage reports (change status, add notes)
- Report detail shows linked scene content
- Report stats display correct aggregates
- Efficient workflow on desktop, functional on mobile

---

## Story 9.4: User & Character Management

**Status**: Not Started

### Description

Admin views for managing users and characters.

### Tasks

- [ ] Create `templates/admin/users/list.html`:
  - `<table>` with user list
  - Inline `<input type="number">` for max_characters (HTMX save on change)
  - Columns: ID, username, email, max_characters, character count, created_at
- [ ] Create `templates/admin/characters/list.html`:
  - Filterable `<table>`:
    - Filter by user, book, deleted status
  - Columns: ID, name, user, book, is_alive, is_deleted, version
  - "Restore" `<button>` on deleted character rows (HTMX)
- [ ] Create `templates/admin/events/list.html`:
  - Filterable `<table>` for character events (read-only):
    - Filter by character_id, event_type, scene_id
  - Columns: seq, event_type, phase, scene, details, created_at
  - Pagination

### Acceptance Criteria

- Admin can view and edit max_characters inline
- Admin can filter characters by user/book/deleted
- Admin can restore soft-deleted characters
- Character events viewable with filters
- All views work on mobile and desktop

---

## Implementation Notes

### Shared UI Patterns with Epic 8

- Base template and Pico CSS setup inherited from Epic 8
- HTMX patterns (swap, target, trigger) consistent
- Table pagination pattern reusable
- Form validation approach consistent

### Admin-Specific Styling

Minimal additions to `app.css`:
- Admin accent color (distinguish from player UI)
- Source badge styling (auto=gray, manual=blue)
- Status badge colors (open=yellow, triaging=blue, resolved=green, wont_fix=gray)
- Inline edit styling for max_characters input

### Content Management Architecture

The admin CRUD routes mirror the JSON API admin endpoints:
```
/admin/ui/content/books          → GET /admin/books
/admin/ui/content/books/{id}     → GET /admin/books/{id}
/admin/ui/content/books/{id}     → PUT /admin/books/{id} (form submit)
/admin/ui/content/books/new      → POST /admin/books (form submit)
```

This keeps the UI layer thin — just template rendering over the existing API.
