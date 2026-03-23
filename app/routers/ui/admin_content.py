"""Admin content UI router — browse and edit all content types via HTMX + Jinja2.

All routes are under /admin/ui/content and require admin authentication.
Data-driven approach: RESOURCE_CONFIG maps URL slugs to ORM models, columns,
filters, and field metadata. Generic list and detail templates receive the
config and render dynamically.

Wizard templates are read-only: POST/create/edit/delete routes return 405.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import AdminUser
from app.models.content import (
    Book,
    Choice,
    CombatEncounter,
    CombatModifier,
    Discipline,
    Scene,
    SceneItem,
    WeaponCategory,
)
from app.models.taxonomy import BookStartingEquipment, BookTransitionRule, GameObject, GameObjectRef
from app.models.wizard import WizardTemplate
from app.ui_dependencies import get_current_admin_ui, templates

router = APIRouter(prefix="/admin/ui", tags=["admin-ui-content"])

# ---------------------------------------------------------------------------
# Resource configuration
# ---------------------------------------------------------------------------

# Each entry maps a URL slug to metadata used by the generic route handlers
# and templates.  Keys:
#   model          — SQLAlchemy ORM class
#   display_name   — Human-readable label for headings
#   columns        — List of (field_name, column_heading) for the list table
#   filters        — List of (param_name, label) for the filter form
#   has_source     — Whether the resource has a source column (auto/manual)
#   editable_fields — Ordered list of field names to show in the edit form
#   read_only      — If True, create/edit/delete are disabled (405)
#   custom_template — Optional override template for the detail/edit view
#   filter_field   — Optional DB column name to apply the first filter to
#   filter_field2  — Optional DB column name for second filter (if needed)

RESOURCE_CONFIG: dict[str, dict[str, Any]] = {
    "books": {
        "model": Book,
        "display_name": "Books",
        "columns": [
            ("id", "ID"),
            ("number", "#"),
            ("title", "Title"),
            ("era", "Era"),
            ("series", "Series"),
        ],
        "filters": [("era", "Era"), ("series", "Series")],
        "filter_field": "era",
        "filter_field2": "series",
        "has_source": False,
        "editable_fields": [
            "slug", "number", "title", "era", "series",
            "start_scene_number", "max_total_picks",
        ],
        "read_only": False,
    },
    "scenes": {
        "model": Scene,
        "display_name": "Scenes",
        "columns": [
            ("id", "ID"),
            ("book_id", "Book"),
            ("number", "#"),
            ("is_death", "Death"),
            ("is_victory", "Victory"),
            ("source", "Source"),
        ],
        "filters": [("book_id", "Book ID")],
        "filter_field": "book_id",
        "has_source": True,
        "editable_fields": [
            "book_id", "number", "html_id", "narrative", "illustration_path",
            "is_death", "is_victory", "must_eat", "loses_backpack",
            "phase_sequence_override", "game_object_id",
        ],
        "read_only": False,
        "custom_template": "admin/content/scene_edit.html",
    },
    "choices": {
        "model": Choice,
        "display_name": "Choices",
        "columns": [
            ("id", "ID"),
            ("scene_id", "Scene"),
            ("target_scene_number", "Target #"),
            ("display_text", "Text"),
            ("source", "Source"),
        ],
        "filters": [("scene_id", "Scene ID")],
        "filter_field": "scene_id",
        "has_source": True,
        "editable_fields": [
            "scene_id", "target_scene_id", "target_scene_number",
            "raw_text", "display_text", "condition_type", "condition_value", "ordinal",
        ],
        "read_only": False,
    },
    "combat-encounters": {
        "model": CombatEncounter,
        "display_name": "Combat Encounters",
        "columns": [
            ("id", "ID"),
            ("scene_id", "Scene"),
            ("enemy_name", "Enemy"),
            ("enemy_cs", "CS"),
            ("enemy_end", "END"),
            ("source", "Source"),
        ],
        "filters": [("scene_id", "Scene ID")],
        "filter_field": "scene_id",
        "has_source": True,
        "editable_fields": [
            "scene_id", "foe_game_object_id", "enemy_name",
            "enemy_cs", "enemy_end", "ordinal", "mindblast_immune",
            "evasion_after_rounds", "evasion_target", "evasion_damage",
            "condition_type", "condition_value",
        ],
        "read_only": False,
    },
    "combat-modifiers": {
        "model": CombatModifier,
        "display_name": "Combat Modifiers",
        "columns": [
            ("id", "ID"),
            ("combat_encounter_id", "Encounter"),
            ("modifier_type", "Type"),
            ("modifier_value", "Value"),
            ("source", "Source"),
        ],
        "filters": [("combat_encounter_id", "Encounter ID")],
        "filter_field": "combat_encounter_id",
        "has_source": True,
        "editable_fields": [
            "combat_encounter_id", "modifier_type", "modifier_value", "condition",
        ],
        "read_only": False,
    },
    "scene-items": {
        "model": SceneItem,
        "display_name": "Scene Items",
        "columns": [
            ("id", "ID"),
            ("scene_id", "Scene"),
            ("item_name", "Item"),
            ("item_type", "Type"),
            ("action", "Action"),
            ("source", "Source"),
        ],
        "filters": [("scene_id", "Scene ID")],
        "filter_field": "scene_id",
        "has_source": True,
        "editable_fields": [
            "scene_id", "game_object_id", "item_name", "item_type",
            "quantity", "action", "is_mandatory", "phase_ordinal",
        ],
        "read_only": False,
    },
    "disciplines": {
        "model": Discipline,
        "display_name": "Disciplines",
        "columns": [
            ("id", "ID"),
            ("era", "Era"),
            ("name", "Name"),
            ("html_id", "HTML ID"),
        ],
        "filters": [("era", "Era")],
        "filter_field": "era",
        "has_source": False,
        "editable_fields": ["era", "name", "html_id", "description", "mechanical_effect"],
        "read_only": False,
    },
    "weapon-categories": {
        "model": WeaponCategory,
        "display_name": "Weapon Categories",
        "columns": [
            ("id", "ID"),
            ("weapon_name", "Weapon"),
            ("category", "Category"),
        ],
        "filters": [("category", "Category")],
        "filter_field": "category",
        "has_source": False,
        "editable_fields": ["weapon_name", "category"],
        "read_only": False,
    },
    "game-objects": {
        "model": GameObject,
        "display_name": "Game Objects",
        "columns": [
            ("id", "ID"),
            ("kind", "Kind"),
            ("name", "Name"),
            ("source", "Source"),
        ],
        "filters": [("kind", "Kind")],
        "filter_field": "kind",
        "has_source": True,
        "editable_fields": [
            "kind", "name", "description", "aliases", "properties", "first_book_id",
        ],
        "read_only": False,
    },
    "game-object-refs": {
        "model": GameObjectRef,
        "display_name": "Game Object Refs",
        "columns": [
            ("id", "ID"),
            ("source_id", "Source Obj"),
            ("target_id", "Target Obj"),
            ("tags", "Tags"),
            ("source", "Source"),
        ],
        "filters": [("source_id", "Source ID")],
        "filter_field": "source_id",
        "has_source": True,
        "editable_fields": ["source_id", "target_id", "tags", "metadata_"],
        "read_only": False,
    },
    "book-starting-equipment": {
        "model": BookStartingEquipment,
        "display_name": "Book Starting Equipment",
        "columns": [
            ("id", "ID"),
            ("book_id", "Book"),
            ("item_name", "Item"),
            ("item_type", "Type"),
            ("source", "Source"),
        ],
        "filters": [("book_id", "Book ID")],
        "filter_field": "book_id",
        "has_source": True,
        "editable_fields": [
            "book_id", "game_object_id", "item_name", "item_type", "category", "is_default",
        ],
        "read_only": False,
    },
    "book-transition-rules": {
        "model": BookTransitionRule,
        "display_name": "Book Transition Rules",
        "columns": [
            ("id", "ID"),
            ("from_book_id", "From Book"),
            ("to_book_id", "To Book"),
            ("max_weapons", "Max Wep"),
        ],
        "filters": [("from_book_id", "From Book ID")],
        "filter_field": "from_book_id",
        "has_source": False,
        "editable_fields": [
            "from_book_id", "to_book_id", "max_weapons", "max_backpack_items",
            "special_items_carry", "gold_carries", "new_disciplines_count",
            "base_cs_override", "base_end_override", "notes",
        ],
        "read_only": False,
    },
    "wizard-templates": {
        "model": WizardTemplate,
        "display_name": "Wizard Templates",
        "columns": [
            ("id", "ID"),
            ("name", "Name"),
            ("description", "Description"),
        ],
        "filters": [],
        "has_source": False,
        "editable_fields": ["name", "description"],
        "read_only": True,
    },
}

PAGE_SIZE = 25


# ---------------------------------------------------------------------------
# Helper — introspect ORM column type for form rendering
# ---------------------------------------------------------------------------


def _field_type(model: Any, field_name: str) -> str:
    """Return a string describing the HTML input type for a given ORM field.

    Returns one of: "text", "number", "textarea", "checkbox", "json".
    """
    try:
        mapper = sa_inspect(model)
        col = mapper.columns.get(field_name)
    except Exception:
        col = None

    if col is None:
        return "text"

    col_type = type(col.type).__name__
    if col_type in ("Boolean",):
        return "checkbox"
    if col_type in ("Integer",):
        return "number"
    if col_type in ("Text",):
        # Heuristic: long text fields named narrative or description → textarea
        if field_name in ("narrative", "description", "notes", "phase_sequence_override"):
            return "textarea"
        if field_name in ("aliases", "properties", "metadata_", "tags"):
            return "json"
        return "textarea"
    return "text"


def _field_info(model: Any, field_names: list[str]) -> list[dict[str, Any]]:
    """Build field metadata list for template rendering."""
    result = []
    for name in field_names:
        result.append({
            "name": name,
            "label": name.replace("_", " ").title(),
            "type": _field_type(model, name),
        })
    return result


# ---------------------------------------------------------------------------
# Helper — get config or raise 404
# ---------------------------------------------------------------------------


def _get_config(resource_type: str) -> dict[str, Any]:
    config = RESOURCE_CONFIG.get(resource_type)
    if not config:
        raise HTTPException(status_code=404, detail=f"Unknown resource type: {resource_type}")
    return config


# ---------------------------------------------------------------------------
# Helper — parse form data into a dict of field values for an ORM model
# ---------------------------------------------------------------------------


def _coerce_form_value(model: Any, field_name: str, raw: str | None) -> Any:
    """Convert a raw form string to the appropriate Python type for the field."""
    field_type = _field_type(model, field_name)
    if field_type == "checkbox":
        # Checkboxes only appear in form data when checked
        return raw is not None
    if raw is None or raw == "":
        return None
    if field_type == "number":
        try:
            return int(raw)
        except ValueError:
            return None
    return raw


def _parse_form_to_dict(model: Any, field_names: list[str], form_data: dict[str, str | None]) -> dict[str, Any]:
    """Turn raw form data into a dict suitable for setattr on an ORM instance."""
    result: dict[str, Any] = {}
    for field_name in field_names:
        field_type = _field_type(model, field_name)
        if field_type == "checkbox":
            # Checkbox: present in form = True, absent = False
            result[field_name] = field_name in form_data and form_data[field_name] is not None
        else:
            raw = form_data.get(field_name)
            result[field_name] = _coerce_form_value(model, field_name, raw)
    return result


# ---------------------------------------------------------------------------
# Content index — links to each resource type
# ---------------------------------------------------------------------------


@router.get("/content", response_class=HTMLResponse)
def content_index(
    request: Request,
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the content type index page with links to each resource type.

    Args:
        request: Incoming HTTP request.
        admin: Authenticated admin user.

    Returns:
        HTML page with a grid of cards linking to each resource type.
    """
    resource_types = [
        {"slug": slug, "display_name": cfg["display_name"], "read_only": cfg.get("read_only", False)}
        for slug, cfg in RESOURCE_CONFIG.items()
    ]
    return templates.TemplateResponse(
        request,
        "admin/content/index.html",
        {"admin": admin, "resource_types": resource_types},
    )


# ---------------------------------------------------------------------------
# Content list — paginated table view
# ---------------------------------------------------------------------------


@router.get("/content/{resource_type}", response_class=HTMLResponse)
def content_list(
    resource_type: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
    page: int = 1,
) -> HTMLResponse:
    """Render a paginated list of records for a given resource type.

    Supports optional filter query parameters defined in the resource config.
    Row click navigates to the detail/edit view.

    Args:
        resource_type: URL slug identifying the resource (e.g. "books").
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.
        page: Current page number (1-based).

    Returns:
        HTML page with a filtered, paginated table.
    """
    config = _get_config(resource_type)
    model = config["model"]

    query = db.query(model)

    # Apply filters from query params
    filter_field = config.get("filter_field")
    filter_field2 = config.get("filter_field2")
    filter_values: dict[str, str] = {}

    if filter_field:
        raw = request.query_params.get(filter_field)
        if raw:
            filter_values[filter_field] = raw
            query = query.filter(getattr(model, filter_field) == raw)

    if filter_field2:
        raw2 = request.query_params.get(filter_field2)
        if raw2:
            filter_values[filter_field2] = raw2
            query = query.filter(getattr(model, filter_field2) == raw2)

    total = query.count()
    offset = (page - 1) * PAGE_SIZE
    items = query.offset(offset).limit(PAGE_SIZE).all()

    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start_num = offset + 1 if total else 0
    end_num = min(offset + PAGE_SIZE, total)

    return templates.TemplateResponse(
        request,
        "admin/content/list.html",
        {
            "admin": admin,
            "resource_type": resource_type,
            "config": config,
            "items": items,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "start_num": start_num,
            "end_num": end_num,
            "filter_values": filter_values,
        },
    )


# ---------------------------------------------------------------------------
# Content create — GET form
# ---------------------------------------------------------------------------


@router.get("/content/{resource_type}/new", response_class=HTMLResponse)
def content_new_form(
    resource_type: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the create form for a resource type.

    Returns 405 for wizard-templates (read-only).

    Args:
        resource_type: URL slug identifying the resource.
        request: Incoming HTTP request.
        admin: Authenticated admin user.

    Returns:
        HTML form for creating a new record.
    """
    config = _get_config(resource_type)
    if config.get("read_only"):
        raise HTTPException(status_code=405, detail="Wizard templates are read-only")

    fields = _field_info(config["model"], config["editable_fields"])
    return templates.TemplateResponse(
        request,
        "admin/content/detail.html",
        {
            "admin": admin,
            "resource_type": resource_type,
            "config": config,
            "item": None,
            "fields": fields,
            "is_new": True,
            "error": None,
        },
    )


# ---------------------------------------------------------------------------
# Content create — POST form submission
# ---------------------------------------------------------------------------


@router.post("/content/{resource_type}/new", response_class=HTMLResponse)
async def content_create(
    resource_type: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Handle create form submission for a resource type.

    Sets source='manual' on resources that have a source field.
    Redirects to the detail view on success, re-renders the form on error.

    Returns 405 for wizard-templates (read-only).

    Args:
        resource_type: URL slug identifying the resource.
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        303 redirect on success, or re-rendered form with error on failure.
    """
    config = _get_config(resource_type)
    if config.get("read_only"):
        raise HTTPException(status_code=405, detail="Wizard templates are read-only")

    model = config["model"]
    form_data = await request.form()
    form_dict = dict(form_data)

    field_names = config["editable_fields"]
    values = _parse_form_to_dict(model, field_names, form_dict)

    # Always set source to 'manual' on create for resources that have it
    if config.get("has_source"):
        values["source"] = "manual"

    try:
        instance = model(**{k: v for k, v in values.items() if v is not None or _field_type(model, k) == "checkbox"})
        db.add(instance)
        db.flush()
    except Exception as exc:
        fields = _field_info(model, field_names)
        return templates.TemplateResponse(
            request,
            "admin/content/detail.html",
            {
                "admin": admin,
                "resource_type": resource_type,
                "config": config,
                "item": None,
                "fields": fields,
                "is_new": True,
                "error": str(exc),
            },
            status_code=400,
        )

    return RedirectResponse(
        url=f"/admin/ui/content/{resource_type}/{instance.id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Content detail / edit — GET form
# ---------------------------------------------------------------------------


@router.get("/content/{resource_type}/{item_id}", response_class=HTMLResponse)
def content_detail(
    resource_type: str,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Render the detail/edit view for a single resource record.

    Scene detail loads linked choices, combat encounters, and scene items.
    Wizard template detail is read-only (no Save/Delete buttons).

    Args:
        resource_type: URL slug identifying the resource.
        item_id: Primary key of the record.
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        HTML detail/edit form.
    """
    config = _get_config(resource_type)
    model = config["model"]
    item = db.query(model).filter(model.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{config['display_name']} not found")

    fields = _field_info(model, config["editable_fields"])
    template_name = config.get("custom_template", "admin/content/detail.html")

    ctx: dict[str, Any] = {
        "admin": admin,
        "resource_type": resource_type,
        "config": config,
        "item": item,
        "fields": fields,
        "is_new": False,
        "error": None,
    }

    # For scenes, attach linked content for the expandable sections
    if resource_type == "scenes":
        ctx["scene_choices"] = item.choices
        ctx["scene_encounters"] = item.combat_encounters
        ctx["scene_items"] = item.scene_items

    return templates.TemplateResponse(request, template_name, ctx)


# ---------------------------------------------------------------------------
# Content edit — POST form submission
# ---------------------------------------------------------------------------


@router.post("/content/{resource_type}/{item_id}", response_class=HTMLResponse)
async def content_update(
    resource_type: str,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Handle edit form submission for a single resource record.

    Always sets source='manual' on save (admin touched it).
    Redirects back to the detail view on success.

    Returns 405 for wizard-templates (read-only).

    Args:
        resource_type: URL slug identifying the resource.
        item_id: Primary key of the record.
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        303 redirect on success, or re-rendered form with error on failure.
    """
    config = _get_config(resource_type)
    if config.get("read_only"):
        raise HTTPException(status_code=405, detail="Wizard templates are read-only")

    model = config["model"]
    item = db.query(model).filter(model.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{config['display_name']} not found")

    form_data = await request.form()
    form_dict = dict(form_data)

    field_names = config["editable_fields"]
    values = _parse_form_to_dict(model, field_names, form_dict)

    # Always set source to 'manual' on edit for resources that have it
    if config.get("has_source"):
        values["source"] = "manual"

    try:
        for field_name, value in values.items():
            setattr(item, field_name, value)
        db.flush()
    except Exception as exc:
        fields = _field_info(model, field_names)
        template_name = config.get("custom_template", "admin/content/detail.html")
        ctx: dict[str, Any] = {
            "admin": admin,
            "resource_type": resource_type,
            "config": config,
            "item": item,
            "fields": fields,
            "is_new": False,
            "error": str(exc),
        }
        if resource_type == "scenes":
            ctx["scene_choices"] = item.choices
            ctx["scene_encounters"] = item.combat_encounters
            ctx["scene_items"] = item.scene_items
        return templates.TemplateResponse(
            request,
            template_name,
            ctx,
            status_code=400,
        )

    return RedirectResponse(
        url=f"/admin/ui/content/{resource_type}/{item_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Content delete — POST with confirmation
# ---------------------------------------------------------------------------


@router.post("/content/{resource_type}/{item_id}/delete", response_class=HTMLResponse)
def content_delete(
    resource_type: str,
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(get_current_admin_ui),
) -> HTMLResponse:
    """Handle delete form submission for a single resource record.

    Uses POST (not DELETE) since HTML forms only support GET/POST.
    Returns 405 for wizard-templates (read-only).

    Args:
        resource_type: URL slug identifying the resource.
        item_id: Primary key of the record.
        request: Incoming HTTP request.
        db: Database session.
        admin: Authenticated admin user.

    Returns:
        303 redirect to the list view on success.
    """
    config = _get_config(resource_type)
    if config.get("read_only"):
        raise HTTPException(status_code=405, detail="Wizard templates are read-only")

    model = config["model"]
    item = db.query(model).filter(model.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"{config['display_name']} not found")

    db.delete(item)
    db.flush()

    return RedirectResponse(
        url=f"/admin/ui/content/{resource_type}",
        status_code=303,
    )
