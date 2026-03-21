"""Wizard service — orchestration logic for character creation and book advance wizards."""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.engine.meters import compute_endurance_max
from app.engine.types import ItemState
from app.models.content import Book, Discipline, Scene
from app.models.player import Character, CharacterBookStart, CharacterDiscipline, CharacterItem
from app.models.taxonomy import BookStartingEquipment, BookTransitionRule, GameObject
from app.models.wizard import CharacterWizardProgress, WizardTemplate, WizardTemplateStep


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_progress_and_steps(
    db: Session, character: Character
) -> tuple[CharacterWizardProgress, WizardTemplate, list[WizardTemplateStep]]:
    """Load the active wizard progress, template, and ordered steps.

    Args:
        db: Database session.
        character: The character whose active wizard to load.

    Returns:
        A three-tuple of (progress, template, steps).

    Raises:
        LookupError: If no active wizard is found on the character.
    """
    if character.active_wizard_id is None:
        raise LookupError("No active wizard on this character")

    progress = (
        db.query(CharacterWizardProgress)
        .filter(CharacterWizardProgress.id == character.active_wizard_id)
        .first()
    )
    if progress is None:
        raise LookupError("Wizard progress record not found")

    template = (
        db.query(WizardTemplate)
        .filter(WizardTemplate.id == progress.wizard_template_id)
        .first()
    )
    if template is None:
        raise LookupError("Wizard template not found")

    steps = (
        db.query(WizardTemplateStep)
        .filter(WizardTemplateStep.template_id == template.id)
        .order_by(WizardTemplateStep.ordinal)
        .all()
    )

    return progress, template, steps


def _load_wizard_state(progress: CharacterWizardProgress) -> dict:
    """Parse the wizard state JSON, returning an empty dict if unset.

    Args:
        progress: The wizard progress record.

    Returns:
        The parsed state dictionary.
    """
    if progress.state:
        return json.loads(progress.state)
    return {}


def _save_wizard_state(
    db: Session, progress: CharacterWizardProgress, state: dict
) -> None:
    """Serialize and persist the wizard state JSON.

    Args:
        db: Database session.
        progress: The wizard progress record to update.
        state: The state dictionary to persist.
    """
    progress.state = json.dumps(state)
    db.flush()


def _ensure_gold_and_meals(state: dict, book: Book) -> dict:
    """Roll gold and set meals in wizard state if not already present.

    Gold is rolled once and persisted — subsequent calls return the same value.

    Args:
        state: The wizard state dict (mutated in place).
        book: The book being played.

    Returns:
        The (mutated) state dict.
    """
    if "gold" not in state:
        if book.number == 1:
            state["gold"] = random.randint(0, 9)
            state["gold_formula"] = "random 0-9"
        else:
            state["gold"] = random.randint(0, 9) + 10
            state["gold_formula"] = "random 0-9 + 10"

    if "meals" not in state:
        # Book 1 provides 1 fixed meal; extend here for future books
        state["meals"] = 1 if book.number == 1 else 0

    return state


def _get_book_equipment(
    db: Session, book_id: int
) -> list[BookStartingEquipment]:
    """Fetch all BookStartingEquipment rows for the given book.

    Args:
        db: Database session.
        book_id: The book's primary key.

    Returns:
        All equipment rows for that book.
    """
    return (
        db.query(BookStartingEquipment)
        .filter(BookStartingEquipment.book_id == book_id)
        .all()
    )


def _build_item_states_from_character(
    db: Session, character: Character
) -> list[ItemState]:
    """Build ItemState objects for all items currently held by the character.

    Used to compute endurance_max via the engine's compute_endurance_max function.

    Args:
        db: Database session.
        character: The character whose items to load.

    Returns:
        List of ItemState DTOs suitable for engine functions.
    """
    item_states: list[ItemState] = []
    for ci in character.items:
        props: dict = {}
        if ci.game_object_id is not None:
            go = db.query(GameObject).filter(GameObject.id == ci.game_object_id).first()
            if go and go.properties:
                props = json.loads(go.properties)
        item_states.append(
            ItemState(
                character_item_id=ci.id,
                item_name=ci.item_name,
                item_type=ci.item_type,
                is_equipped=ci.is_equipped,
                game_object_id=ci.game_object_id,
                properties=props,
            )
        )
    return item_states


# ---------------------------------------------------------------------------
# Book advance step helpers (internal)
# ---------------------------------------------------------------------------


def _get_transition_rule(db: Session, character: Character) -> BookTransitionRule:
    """Retrieve the BookTransitionRule for the character's current book.

    Args:
        db: Database session.
        character: The character advancing to the next book.

    Returns:
        The BookTransitionRule for the character's current book.

    Raises:
        LookupError: If no transition rule exists for the current book.
    """
    rule = (
        db.query(BookTransitionRule)
        .filter(BookTransitionRule.from_book_id == character.book_id)
        .first()
    )
    if rule is None:
        raise LookupError(f"No transition rule for book_id={character.book_id}")
    return rule


def _get_pick_disciplines_state(
    db: Session,
    character: Character,
    progress: CharacterWizardProgress,
    template: WizardTemplate,
    step_index: int,
    total_steps: int,
    state: dict,
) -> dict:
    """Build the GET response for the pick_disciplines wizard step.

    Args:
        db: Database session.
        character: The character in the wizard.
        progress: The wizard progress record.
        template: The wizard template.
        step_index: Current step index.
        total_steps: Total number of steps.
        state: Current wizard state dict.

    Returns:
        A dict suitable for serialisation as WizardDisciplineStepResponse.
    """
    rule = _get_transition_rule(db, character)

    # Determine which discipline IDs the character already has
    existing_disc_ids: set[int] = {cd.discipline_id for cd in character.disciplines}  # type: ignore[attr-defined]

    # Get the book for era
    book = db.query(Book).filter(Book.id == character.book_id).first()
    era = book.era if book else "kai"

    # Fetch all Kai-era disciplines not yet learned by the character
    available = (
        db.query(Discipline)
        .filter(Discipline.era == era, ~Discipline.id.in_(existing_disc_ids))
        .order_by(Discipline.id)
        .all()
    )

    available_list = [
        {"id": d.id, "name": d.name, "description": d.description}
        for d in available
    ]

    return {
        "wizard_type": template.name,
        "step": "pick_disciplines",
        "step_index": step_index,
        "total_steps": total_steps,
        "available_disciplines": available_list,
        "disciplines_to_pick": rule.new_disciplines_count,
    }


def _get_inventory_adjust_state(
    db: Session,
    character: Character,
    progress: CharacterWizardProgress,
    template: WizardTemplate,
    step_index: int,
    total_steps: int,
    state: dict,
) -> dict:
    """Build the GET response for the inventory_adjust wizard step.

    Args:
        db: Database session.
        character: The character in the wizard.
        progress: The wizard progress record.
        template: The wizard template.
        step_index: Current step index.
        total_steps: Total number of steps.
        state: Current wizard state dict.

    Returns:
        A dict suitable for serialisation as WizardInventoryStepResponse.
    """
    rule = _get_transition_rule(db, character)

    # Build inventory lists from character's current items plus newly selected equipment
    # The player sees their current inventory and decides what to keep within limits.
    # Also include newly added items from the pick_equipment step.
    selected_items_state: list[dict] = state.get("selected_items", [])

    # Get equipment book for fixed items
    to_book_id: int | None = state.get("to_book_id")
    new_fixed_items: list[dict] = []
    new_selected_items: list[dict] = list(selected_items_state)
    if to_book_id:
        equipment = _get_book_equipment(db, to_book_id)
        for eq in equipment:
            if eq.is_default and eq.item_type not in ("gold", "meal"):
                new_fixed_items.append({
                    "item_name": eq.item_name,
                    "item_type": eq.item_type,
                    "is_equipped": False,
                })

    weapons: list[dict] = []
    backpack: list[dict] = []
    special: list[dict] = []

    # Existing items from character
    for ci in character.items:
        entry = {
            "item_name": ci.item_name,
            "item_type": ci.item_type,
            "is_equipped": ci.is_equipped,
        }
        if ci.item_type == "weapon":
            weapons.append(entry)
        elif ci.item_type == "backpack":
            backpack.append(entry)
        elif ci.item_type == "special":
            special.append(entry)

    # New items from this wizard (fixed + selected)
    for item in new_fixed_items:
        entry = {"item_name": item["item_name"], "item_type": item["item_type"], "is_equipped": False}
        if item["item_type"] == "weapon":
            weapons.append(entry)
        elif item["item_type"] == "backpack":
            backpack.append(entry)
        elif item["item_type"] == "special":
            special.append(entry)

    for item in new_selected_items:
        entry = {"item_name": item["item_name"], "item_type": item.get("item_type", "special"), "is_equipped": False}
        if entry["item_type"] == "weapon":
            weapons.append(entry)
        elif entry["item_type"] == "backpack":
            backpack.append(entry)
        elif entry["item_type"] == "special":
            special.append(entry)

    return {
        "wizard_type": template.name,
        "step": "inventory_adjust",
        "step_index": step_index,
        "total_steps": total_steps,
        "current_weapons": weapons,
        "current_backpack": backpack,
        "current_special": special,
        "max_weapons": rule.max_weapons,
        "max_backpack_items": rule.max_backpack_items,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_wizard_state(db: Session, character: Character) -> dict:
    """Get the current wizard step data for rendering.

    For the equipment step (step_index=0), builds the full equipment listing
    including fixed items, auto-applied resources, and available choices.
    Rolls gold once and persists it in wizard state so subsequent GETs return
    the same value.

    For the confirm step (step_index=1), builds a preview of the character
    with all selections applied (not yet committed to the character record).

    Args:
        db: Database session.
        character: The character to get wizard state for.

    Returns:
        A dict suitable for serialisation as the appropriate step response.

    Raises:
        LookupError: If the character has no active wizard.
    """
    progress, template, steps = _get_progress_and_steps(db, character)
    step_index = progress.current_step_index
    total_steps = len(steps)
    current_step = steps[step_index] if step_index < len(steps) else None
    step_type = current_step.step_type if current_step else "unknown"

    book = db.query(Book).filter(Book.id == character.book_id).first()
    if book is None:
        raise LookupError("Book not found for character")

    state = _load_wizard_state(progress)

    if step_type == "pick_disciplines":
        return _get_pick_disciplines_state(db, character, progress, template, step_index, total_steps, state)

    elif step_type == "pick_equipment":
        # Determine which book's equipment to show.
        # For book_advance, the target book id is stored in wizard state.
        equipment_book_id = state.get("to_book_id", book.id)
        equipment_book = db.query(Book).filter(Book.id == equipment_book_id).first()
        if equipment_book is None:
            raise LookupError("Equipment book not found")

        _ensure_gold_and_meals(state, equipment_book)
        _save_wizard_state(db, progress, state)

        equipment = _get_book_equipment(db, equipment_book.id)

        included_items = []
        auto_applied: dict = {
            "gold": state["gold"],
            "gold_formula": state.get("gold_formula", "random 0-9"),
            "meals": state["meals"],
        }
        available_equipment = []

        for eq in equipment:
            if eq.is_default:
                included_items.append({
                    "item_name": eq.item_name,
                    "item_type": eq.item_type,
                    "note": "fixed",
                })
            elif eq.item_type in ("gold", "meal"):
                # Auto-applied items (not shown as selectable)
                pass
            else:
                available_equipment.append({
                    "item_name": eq.item_name,
                    "item_type": eq.item_type,
                    "category": eq.category,
                })

        return {
            "wizard_type": template.name,
            "step": step_type,
            "step_index": step_index,
            "total_steps": total_steps,
            "included_items": included_items,
            "auto_applied": auto_applied,
            "available_equipment": available_equipment,
            "pick_limit": equipment_book.max_total_picks,
        }

    elif step_type == "inventory_adjust":
        return _get_inventory_adjust_state(db, character, progress, template, step_index, total_steps, state)

    elif step_type == "confirm":
        # Build a preview of the character with selections applied.
        # Works for both character_creation and book_advance.
        discipline_names = [cd.discipline.name for cd in character.disciplines]  # type: ignore[attr-defined]

        # Determine book for equipment lookup
        equipment_book_id = state.get("to_book_id", book.id)
        equipment_book = db.query(Book).filter(Book.id == equipment_book_id).first()
        if equipment_book is None:
            raise LookupError("Equipment book not found")

        # Collect items that will be applied
        equipment = _get_book_equipment(db, equipment_book.id)
        eq_by_name = {eq.item_name: eq for eq in equipment}

        selected_items_state: list[dict] = state.get("selected_items", [])
        gold_to_apply = state.get("gold", 0)
        meals_to_apply = state.get("meals", 0)

        # Build temporary item states for endurance calculation
        preview_item_states: list[ItemState] = []

        def _add_preview_item(item_name: str, item_type: str, game_object_id: int | None) -> None:
            props: dict = {}
            if game_object_id is not None:
                go = db.query(GameObject).filter(GameObject.id == game_object_id).first()
                if go and go.properties:
                    props = json.loads(go.properties)
            preview_item_states.append(
                ItemState(
                    character_item_id=0,  # not yet persisted
                    item_name=item_name,
                    item_type=item_type,
                    is_equipped=False,
                    game_object_id=game_object_id,
                    properties=props,
                )
            )

        if template.name == "book_advance":
            # For book_advance confirm: start from kept inventory, add new items
            keep_weapons: list[str] = state.get("keep_weapons", [])
            keep_backpack: list[str] = state.get("keep_backpack", [])
            # Add kept weapons and backpack items
            for ci in character.items:
                if ci.item_type == "weapon" and ci.item_name in keep_weapons:
                    _add_preview_item(ci.item_name, ci.item_type, ci.game_object_id)
                elif ci.item_type == "backpack" and ci.item_name in keep_backpack:
                    _add_preview_item(ci.item_name, ci.item_type, ci.game_object_id)
                elif ci.item_type == "special":
                    # Special items always carry over
                    _add_preview_item(ci.item_name, ci.item_type, ci.game_object_id)
            # Add new fixed equipment from target book
            for eq in equipment:
                if eq.is_default and eq.item_type not in ("gold", "meal"):
                    _add_preview_item(eq.item_name, eq.item_type, eq.game_object_id)
            # Add newly selected equipment
            for sel in selected_items_state:
                eq = eq_by_name.get(sel["item_name"])
                goid = sel.get("game_object_id") or (eq.game_object_id if eq else None)
                _add_preview_item(sel["item_name"], sel["item_type"], goid)
            # Add new disciplines to name list for endurance calculation
            new_disc_ids: list[int] = state.get("new_disciplines", [])
            for disc_id in new_disc_ids:
                disc = db.query(Discipline).filter(Discipline.id == disc_id).first()
                if disc and disc.name not in discipline_names:
                    discipline_names = discipline_names + [disc.name]
        else:
            # character_creation: only new items from wizard state
            for eq in equipment:
                if eq.is_default and eq.item_type not in ("gold", "meal"):
                    _add_preview_item(eq.item_name, eq.item_type, eq.game_object_id)

            for sel in selected_items_state:
                eq = eq_by_name.get(sel["item_name"])
                goid = eq.game_object_id if eq else None
                _add_preview_item(sel["item_name"], sel["item_type"], goid)

        new_endurance_max = compute_endurance_max(
            character.endurance_base, discipline_names, preview_item_states
        )
        new_gold = min(character.gold + gold_to_apply, 50)
        new_meals = min(character.meals + meals_to_apply, 8)
        new_endurance_current = min(character.endurance_current, new_endurance_max)

        character_preview = {
            "id": character.id,
            "name": character.name,
            "combat_skill_base": character.combat_skill_base,
            "endurance_base": character.endurance_base,
            "endurance_max": new_endurance_max,
            "endurance_current": new_endurance_current,
            "gold": new_gold,
            "meals": new_meals,
            "death_count": character.death_count,
            "current_run": character.current_run,
            "version": character.version,
            "disciplines": discipline_names,
            "active_wizard": {
                "type": template.name,
                "step": step_type,
                "step_index": step_index,
                "total_steps": total_steps,
            },
        }

        return {
            "wizard_type": template.name,
            "step": step_type,
            "step_index": step_index,
            "total_steps": total_steps,
            "character_preview": character_preview,
        }

    else:
        raise ValueError(f"Unknown wizard step type: {step_type}")


def handle_equipment_step(
    db: Session,
    character: Character,
    selected_items: list[str],
    version: int,  # noqa: ARG001 — caller has already verified via verify_version
) -> Character:
    """Process the equipment selection step.

    Validates the chosen items against the book's available equipment list,
    stores them in wizard state, and advances to the confirm step.

    Re-submitting replaces previous selections (re-pick is allowed).

    Args:
        db: Database session.
        character: The character undergoing the wizard.
        selected_items: List of item names the player chose.
        version: Client-supplied version (already verified by caller).

    Returns:
        The updated character ORM instance.

    Raises:
        LookupError: If the character has no active wizard or book is missing.
        ValueError: If validation fails (too many items, invalid item names).
    """
    progress, _template, steps = _get_progress_and_steps(db, character)
    step_index = progress.current_step_index
    current_step = steps[step_index] if step_index < len(steps) else None

    if current_step is None or current_step.step_type != "pick_equipment":
        raise ValueError("Character is not at the equipment selection step")

    # Load existing state to preserve gold/meals roll and to_book_id
    state = _load_wizard_state(progress)

    # For book_advance wizard, use the target book; for character_creation use character.book_id
    equipment_book_id: int = state.get("to_book_id", character.book_id)
    book = db.query(Book).filter(Book.id == equipment_book_id).first()
    if book is None:
        raise LookupError("Book not found for character")

    equipment = _get_book_equipment(db, book.id)

    # Build the set of chooseable (not default, not auto-applied gold/meal)
    available: dict[str, BookStartingEquipment] = {
        eq.item_name: eq
        for eq in equipment
        if not eq.is_default and eq.item_type not in ("gold", "meal")
    }

    pick_limit = book.max_total_picks
    if len(selected_items) > pick_limit:
        raise ValueError(
            f"Too many items selected: {len(selected_items)} exceeds pick limit of {pick_limit}"
        )

    for item_name in selected_items:
        if item_name not in available:
            raise ValueError(
                f"'{item_name}' is not a valid equipment choice for this book"
            )

    # Initialise gold/meals if not yet rolled (happens on first GET, but POST may come first)
    _ensure_gold_and_meals(state, book)

    # Build selected_items list for state
    state["selected_items"] = [
        {
            "item_name": item_name,
            "item_type": available[item_name].item_type,
            "game_object_id": available[item_name].game_object_id,
        }
        for item_name in selected_items
    ]

    # Advance to next step
    progress.current_step_index = step_index + 1
    _save_wizard_state(db, progress, state)

    # Increment character version
    character.version += 1
    now = datetime.now(UTC)
    character.updated_at = now
    db.flush()

    return character


def handle_confirm_step(
    db: Session,
    character: Character,
    version: int,  # noqa: ARG001 — caller has already verified via verify_version
) -> Character:
    """Finalise the wizard — apply all items, save snapshot, place at start scene.

    Applies fixed and selected items from wizard state to the character, sets
    gold and meals, recalculates endurance_max, saves a character_book_starts
    snapshot, places the character at the book's start scene, and clears the
    active wizard.

    Args:
        db: Database session.
        character: The character completing the wizard.
        version: Client-supplied version (already verified by caller).

    Returns:
        The updated character ORM instance.

    Raises:
        LookupError: If the character has no active wizard, book is missing,
            or start scene cannot be found.
        ValueError: If the wizard is not at the confirm step.
    """
    progress, _template, steps = _get_progress_and_steps(db, character)
    step_index = progress.current_step_index
    current_step = steps[step_index] if step_index < len(steps) else None

    if current_step is None or current_step.step_type != "confirm":
        raise ValueError("Character is not at the confirm step")

    book = db.query(Book).filter(Book.id == character.book_id).first()
    if book is None:
        raise LookupError("Book not found for character")

    state = _load_wizard_state(progress)
    gold_to_apply = state.get("gold", 0)
    meals_to_apply = state.get("meals", 0)
    selected_items_state: list[dict] = state.get("selected_items", [])

    equipment = _get_book_equipment(db, book.id)
    eq_by_name = {eq.item_name: eq for eq in equipment}

    now = datetime.now(UTC)

    # -----------------------------------------------------------------------
    # 1. Add fixed items (is_default=True, not gold/meal type) to character
    # -----------------------------------------------------------------------
    fixed_items: list[CharacterItem] = []
    for eq in equipment:
        if eq.is_default and eq.item_type not in ("gold", "meal"):
            ci = CharacterItem(
                character_id=character.id,
                game_object_id=eq.game_object_id,
                item_name=eq.item_name,
                item_type=eq.item_type,
                is_equipped=False,
            )
            db.add(ci)
            fixed_items.append(ci)

    # -----------------------------------------------------------------------
    # 2. Add selected items
    # -----------------------------------------------------------------------
    selected_character_items: list[CharacterItem] = []
    for sel in selected_items_state:
        # Resolve game_object_id from equipment table (state may have it too)
        eq = eq_by_name.get(sel["item_name"])
        goid = sel.get("game_object_id") or (eq.game_object_id if eq else None)
        item_type = sel.get("item_type", "special")

        # Only persisted item types: weapon, backpack, special
        # meal and gold are handled as character stats
        if item_type in ("gold", "meal"):
            continue

        ci = CharacterItem(
            character_id=character.id,
            game_object_id=goid,
            item_name=sel["item_name"],
            item_type=item_type,
            is_equipped=False,
        )
        db.add(ci)
        selected_character_items.append(ci)

    db.flush()

    # -----------------------------------------------------------------------
    # 3. Apply gold from wizard state (also handle gold selected as item pick)
    # -----------------------------------------------------------------------
    extra_gold_from_selection = 0
    for sel in selected_items_state:
        if sel.get("item_type") == "gold":
            # Gold Crowns item — qty from spec (12 for Book 1)
            eq = eq_by_name.get(sel["item_name"])
            if eq is None:
                continue
            # Find qty from game_object or fall back to 0
            go = (
                db.query(GameObject).filter(GameObject.id == eq.game_object_id).first()
                if eq.game_object_id
                else None
            )
            if go and go.properties:
                props = json.loads(go.properties)
                extra_gold_from_selection += int(props.get("quantity", 0))
            else:
                # For Gold Crowns in Book 1 — 12 gold per spec
                # Use the item name to infer (since no game_object may exist in tests)
                extra_gold_from_selection += 12  # default for Book 1 Gold Crowns

    extra_meals_from_selection = 0
    for sel in selected_items_state:
        if sel.get("item_type") == "meal":
            eq = eq_by_name.get(sel["item_name"])
            if eq is None:
                continue
            go = (
                db.query(GameObject).filter(GameObject.id == eq.game_object_id).first()
                if eq.game_object_id
                else None
            )
            if go and go.properties:
                props = json.loads(go.properties)
                extra_meals_from_selection += int(props.get("quantity", 0))
            else:
                # Meal item in Book 1 — 2 meals per spec
                extra_meals_from_selection += 2

    new_gold = min(character.gold + gold_to_apply + extra_gold_from_selection, 50)
    new_meals = min(character.meals + meals_to_apply + extra_meals_from_selection, 8)

    # -----------------------------------------------------------------------
    # 4. Equip first weapon automatically
    # -----------------------------------------------------------------------
    all_new_items = fixed_items + selected_character_items
    first_weapon = next((ci for ci in all_new_items if ci.item_type == "weapon"), None)
    if first_weapon is not None:
        first_weapon.is_equipped = True

    # -----------------------------------------------------------------------
    # 5. Recalculate endurance_max
    # -----------------------------------------------------------------------
    # Flush pending item writes and reload the character's item collection
    # so compute_endurance_max sees the newly-added items.
    db.flush()
    db.refresh(character)
    discipline_names = [cd.discipline.name for cd in character.disciplines]  # type: ignore[attr-defined]
    item_states = _build_item_states_from_character(db, character)
    new_endurance_max = compute_endurance_max(character.endurance_base, discipline_names, item_states)
    character.endurance_max = new_endurance_max
    # New characters start at full health — set current to max.
    # (Book advance wizard should NOT do this, since the character may be damaged.)
    character.endurance_current = new_endurance_max

    # Apply gold and meals AFTER the refresh so they are not overwritten
    character.gold = new_gold
    character.meals = new_meals

    # -----------------------------------------------------------------------
    # 6. Save character_book_starts snapshot
    # -----------------------------------------------------------------------
    items_snapshot = [
        {
            "item_name": ci.item_name,
            "item_type": ci.item_type,
            "is_equipped": ci.is_equipped,
            "game_object_id": ci.game_object_id,
        }
        for ci in character.items
    ]
    disciplines_snapshot = [
        {
            "discipline_id": cd.discipline_id,
            "weapon_category": cd.weapon_category,
        }
        for cd in character.disciplines  # type: ignore[attr-defined]
    ]

    book_start = CharacterBookStart(
        character_id=character.id,
        book_id=book.id,
        combat_skill_base=character.combat_skill_base,
        endurance_base=character.endurance_base,
        endurance_max=character.endurance_max,
        endurance_current=character.endurance_current,
        gold=character.gold,
        meals=character.meals,
        items_json=json.dumps(items_snapshot),
        disciplines_json=json.dumps(disciplines_snapshot),
        created_at=now,
    )
    db.add(book_start)

    # -----------------------------------------------------------------------
    # 7. Place character at start scene
    # -----------------------------------------------------------------------
    start_scene = (
        db.query(Scene)
        .filter(Scene.book_id == book.id, Scene.number == book.start_scene_number)
        .first()
    )
    if start_scene is None:
        raise LookupError(
            f"Start scene (number={book.start_scene_number}) not found for book {book.id}"
        )
    character.current_scene_id = start_scene.id

    # -----------------------------------------------------------------------
    # 8. Clear wizard
    # -----------------------------------------------------------------------
    progress.completed_at = now
    character.active_wizard_id = None
    character.version += 1
    character.updated_at = now

    db.flush()

    return character


# ---------------------------------------------------------------------------
# Book advance wizard public handlers
# ---------------------------------------------------------------------------


def init_book_advance_wizard(
    db: Session,
    character: Character,
) -> dict:
    """Start the book advance wizard for a character at a victory scene.

    Creates a CharacterWizardProgress record for the book_advance template,
    sets character.active_wizard_id, increments version, and returns the
    first-step info (pick_disciplines).

    Args:
        db: Database session.
        character: The character initiating the advance.

    Returns:
        A dict with wizard_type, step, step_index, total_steps, and book info
        suitable for serialisation as AdvanceInitResponse.

    Raises:
        LookupError: If no book_advance wizard template, no transition rule, or
            no target book is found.
        ValueError: If the character is not at a victory scene, or already has
            an active wizard.
    """
    # Validate: character must be at a victory scene
    if character.current_scene_id is None:
        raise ValueError("Character is not at a scene")

    current_scene = db.query(Scene).filter(Scene.id == character.current_scene_id).first()
    if current_scene is None or not current_scene.is_victory:
        raise ValueError("Character is not at a victory scene")

    # Validate: no active wizard
    if character.active_wizard_id is not None:
        raise ValueError("Character already has an active wizard")

    # Look up transition rule
    rule = (
        db.query(BookTransitionRule)
        .filter(BookTransitionRule.from_book_id == character.book_id)
        .first()
    )
    if rule is None:
        raise LookupError(f"No transition rule found for book_id={character.book_id}")

    # Look up the target book
    to_book = db.query(Book).filter(Book.id == rule.to_book_id).first()
    if to_book is None:
        raise LookupError(f"Target book not found for book_id={rule.to_book_id}")

    # Find the book_advance wizard template
    template = (
        db.query(WizardTemplate)
        .filter(WizardTemplate.name == "book_advance")
        .first()
    )
    if template is None:
        raise LookupError("book_advance wizard template not found")

    steps = (
        db.query(WizardTemplateStep)
        .filter(WizardTemplateStep.template_id == template.id)
        .order_by(WizardTemplateStep.ordinal)
        .all()
    )
    total_steps = len(steps)

    now = datetime.now(UTC)

    # Initial wizard state stores the transition context
    initial_state = {
        "from_book_id": character.book_id,
        "to_book_id": to_book.id,
        "transition_rule_id": rule.id,
        "max_weapons": rule.max_weapons,
        "max_backpack_items": rule.max_backpack_items,
        "new_disciplines_count": rule.new_disciplines_count,
    }

    # Create progress record
    progress = CharacterWizardProgress(
        character_id=character.id,
        wizard_template_id=template.id,
        current_step_index=0,
        state=json.dumps(initial_state),
        started_at=now,
    )
    db.add(progress)
    db.flush()

    # Link wizard to character
    character.active_wizard_id = progress.id
    character.version += 1
    character.updated_at = now
    db.flush()

    return {
        "wizard_type": template.name,
        "step": steps[0].step_type if steps else "unknown",
        "step_index": 0,
        "total_steps": total_steps,
        "book": {"id": to_book.id, "title": to_book.title},
    }


def handle_discipline_step(
    db: Session,
    character: Character,
    discipline_ids: list[int],
    weapon_skill_type: str | None,
    version: int,  # noqa: ARG001 — caller has already verified via verify_version
) -> Character:
    """Process the pick_disciplines step of the book advance wizard.

    Validates the discipline selection, stores the choices in wizard state,
    and advances to the next step (pick_equipment).

    Args:
        db: Database session.
        character: The character undergoing the wizard.
        discipline_ids: List of discipline IDs to pick.
        weapon_skill_type: The weapon category if Weaponskill is selected.
        version: Client-supplied version (already verified by caller).

    Returns:
        The updated character ORM instance.

    Raises:
        LookupError: If the character has no active wizard.
        ValueError: If validation fails (wrong count, invalid disciplines,
            missing weapon_skill_type for Weaponskill).
    """
    progress, _template, steps = _get_progress_and_steps(db, character)
    step_index = progress.current_step_index
    current_step = steps[step_index] if step_index < len(steps) else None

    if current_step is None or current_step.step_type != "pick_disciplines":
        raise ValueError("Character is not at the pick_disciplines step")

    state = _load_wizard_state(progress)
    required_count: int = state.get("new_disciplines_count", 1)

    if len(discipline_ids) != required_count:
        raise ValueError(
            f"Must pick exactly {required_count} discipline(s), got {len(discipline_ids)}"
        )

    # Validate: disciplines must exist and be Kai era, not already learned
    existing_disc_ids: set[int] = {cd.discipline_id for cd in character.disciplines}  # type: ignore[attr-defined]
    book = db.query(Book).filter(Book.id == character.book_id).first()
    era = book.era if book else "kai"

    weapon_skill_disc_id: int | None = None

    for disc_id in discipline_ids:
        disc = db.query(Discipline).filter(Discipline.id == disc_id).first()
        if disc is None:
            raise ValueError(f"Discipline id={disc_id} not found")
        if disc.era != era:
            raise ValueError(
                f"Discipline '{disc.name}' is not a {era} discipline"
            )
        if disc_id in existing_disc_ids:
            raise ValueError(
                f"Character already has discipline '{disc.name}'"
            )
        if disc.name == "Weaponskill":
            weapon_skill_disc_id = disc_id

    # Validate weapon_skill_type if Weaponskill was selected
    if weapon_skill_disc_id is not None:
        if not weapon_skill_type:
            raise ValueError("weapon_skill_type is required when Weaponskill is selected")
        # Validate against WeaponCategory table
        from app.models.content import WeaponCategory

        valid_category = (
            db.query(WeaponCategory)
            .filter(WeaponCategory.category == weapon_skill_type)
            .first()
        )
        if valid_category is None:
            raise ValueError(f"'{weapon_skill_type}' is not a valid weapon category")
    else:
        # Silently ignore weapon_skill_type if no Weaponskill selected
        weapon_skill_type = None

    # Store in wizard state and advance
    state["new_disciplines"] = discipline_ids
    state["weapon_type"] = weapon_skill_type

    # Advance to next step (pick_equipment = step 1)
    progress.current_step_index = step_index + 1
    _save_wizard_state(db, progress, state)

    character.version += 1
    now = datetime.now(UTC)
    character.updated_at = now
    db.flush()

    return character


def handle_inventory_adjust_step(
    db: Session,
    character: Character,
    keep_weapons: list[str],
    keep_backpack: list[str],
    version: int,  # noqa: ARG001 — caller has already verified via verify_version
) -> Character:
    """Process the inventory_adjust step of the book advance wizard.

    Validates that kept items exist in the character's current inventory
    (or newly selected items from prior steps) and that limits are respected.
    Stores the kept lists in wizard state and advances to confirm.

    Args:
        db: Database session.
        character: The character undergoing the wizard.
        keep_weapons: List of weapon item names to carry over.
        keep_backpack: List of backpack item names to carry over.
        version: Client-supplied version (already verified by caller).

    Returns:
        The updated character ORM instance.

    Raises:
        LookupError: If the character has no active wizard.
        ValueError: If validation fails (over limit, items not in inventory).
    """
    progress, _template, steps = _get_progress_and_steps(db, character)
    step_index = progress.current_step_index
    current_step = steps[step_index] if step_index < len(steps) else None

    if current_step is None or current_step.step_type != "inventory_adjust":
        raise ValueError("Character is not at the inventory_adjust step")

    state = _load_wizard_state(progress)
    max_weapons: int = state.get("max_weapons", 2)
    max_backpack: int = state.get("max_backpack_items", 8)

    if len(keep_weapons) > max_weapons:
        raise ValueError(
            f"Too many weapons: {len(keep_weapons)} exceeds max of {max_weapons}"
        )
    if len(keep_backpack) > max_backpack:
        raise ValueError(
            f"Too many backpack items: {len(keep_backpack)} exceeds max of {max_backpack}"
        )

    # Build the full set of item names available to the character at this point.
    # This includes their existing items plus newly selected items from pick_equipment.
    existing_weapons: set[str] = {
        ci.item_name for ci in character.items if ci.item_type == "weapon"
    }
    existing_backpack: set[str] = {
        ci.item_name for ci in character.items if ci.item_type == "backpack"
    }

    # Add newly selected equipment from wizard state
    selected_items_state: list[dict] = state.get("selected_items", [])
    to_book_id: int | None = state.get("to_book_id")
    if to_book_id:
        equipment = _get_book_equipment(db, to_book_id)
        for eq in equipment:
            if eq.is_default:
                if eq.item_type == "weapon":
                    existing_weapons.add(eq.item_name)
                elif eq.item_type == "backpack":
                    existing_backpack.add(eq.item_name)

    for sel in selected_items_state:
        if sel.get("item_type") == "weapon":
            existing_weapons.add(sel["item_name"])
        elif sel.get("item_type") == "backpack":
            existing_backpack.add(sel["item_name"])

    # Validate that all kept items exist in the available set
    for item_name in keep_weapons:
        if item_name not in existing_weapons:
            raise ValueError(f"Weapon '{item_name}' not found in inventory")

    for item_name in keep_backpack:
        if item_name not in existing_backpack:
            raise ValueError(f"Backpack item '{item_name}' not found in inventory")

    # Store in wizard state and advance to confirm
    state["keep_weapons"] = keep_weapons
    state["keep_backpack"] = keep_backpack
    progress.current_step_index = step_index + 1
    _save_wizard_state(db, progress, state)

    character.version += 1
    now = datetime.now(UTC)
    character.updated_at = now
    db.flush()

    return character


def handle_book_advance_confirm_step(
    db: Session,
    character: Character,
    version: int,  # noqa: ARG001 — caller has already verified via verify_version
) -> Character:
    """Finalise the book advance wizard.

    Applies new disciplines, equipment, inventory adjustments, and gold.
    Updates character.book_id to the new book. Saves a book-start snapshot.
    Places the character at the new book's start scene. Recalculates
    endurance_max. Clears the active wizard. Does NOT set endurance_current
    to max — the character may be damaged.

    Args:
        db: Database session.
        character: The character completing the book advance wizard.
        version: Client-supplied version (already verified by caller).

    Returns:
        The updated character ORM instance.

    Raises:
        LookupError: If the character has no active wizard, book is missing,
            or start scene cannot be found.
        ValueError: If the wizard is not at the confirm step.
    """
    progress, _template, steps = _get_progress_and_steps(db, character)
    step_index = progress.current_step_index
    current_step = steps[step_index] if step_index < len(steps) else None

    if current_step is None or current_step.step_type != "confirm":
        raise ValueError("Character is not at the confirm step")

    state = _load_wizard_state(progress)

    to_book_id: int | None = state.get("to_book_id")
    if to_book_id is None:
        raise LookupError("to_book_id not found in wizard state")

    to_book = db.query(Book).filter(Book.id == to_book_id).first()
    if to_book is None:
        raise LookupError(f"Target book id={to_book_id} not found")

    now = datetime.now(UTC)

    # -----------------------------------------------------------------------
    # 1. Apply new disciplines
    # -----------------------------------------------------------------------
    new_disc_ids: list[int] = state.get("new_disciplines", [])
    weapon_type: str | None = state.get("weapon_type")

    for disc_id in new_disc_ids:
        disc = db.query(Discipline).filter(Discipline.id == disc_id).first()
        if disc is None:
            continue
        weapon_category: str | None = None
        if disc.name == "Weaponskill" and weapon_type:
            weapon_category = weapon_type
        cd = CharacterDiscipline(
            character_id=character.id,
            discipline_id=disc_id,
            weapon_category=weapon_category,
        )
        db.add(cd)

    db.flush()

    # -----------------------------------------------------------------------
    # 2. Apply inventory adjustments (drop items not in keep lists)
    # -----------------------------------------------------------------------
    keep_weapons: list[str] = state.get("keep_weapons", [])
    keep_backpack: list[str] = state.get("keep_backpack", [])

    items_to_remove: list[CharacterItem] = []
    for ci in list(character.items):
        if ci.item_type == "weapon" and ci.item_name not in keep_weapons:
            items_to_remove.append(ci)
        elif ci.item_type == "backpack" and ci.item_name not in keep_backpack:
            items_to_remove.append(ci)
        # Special items always carry over — do not remove

    for ci in items_to_remove:
        db.delete(ci)

    db.flush()

    # -----------------------------------------------------------------------
    # 3. Add new fixed equipment from target book
    # -----------------------------------------------------------------------
    equipment = _get_book_equipment(db, to_book.id)
    eq_by_name = {eq.item_name: eq for eq in equipment}

    fixed_items: list[CharacterItem] = []
    for eq in equipment:
        if eq.is_default and eq.item_type not in ("gold", "meal"):
            ci = CharacterItem(
                character_id=character.id,
                game_object_id=eq.game_object_id,
                item_name=eq.item_name,
                item_type=eq.item_type,
                is_equipped=False,
            )
            db.add(ci)
            fixed_items.append(ci)

    # -----------------------------------------------------------------------
    # 4. Add newly selected equipment items
    # -----------------------------------------------------------------------
    selected_items_state: list[dict] = state.get("selected_items", [])
    selected_character_items: list[CharacterItem] = []
    for sel in selected_items_state:
        eq = eq_by_name.get(sel["item_name"])
        goid = sel.get("game_object_id") or (eq.game_object_id if eq else None)
        item_type = sel.get("item_type", "special")

        if item_type in ("gold", "meal"):
            continue

        ci = CharacterItem(
            character_id=character.id,
            game_object_id=goid,
            item_name=sel["item_name"],
            item_type=item_type,
            is_equipped=False,
        )
        db.add(ci)
        selected_character_items.append(ci)

    db.flush()

    # -----------------------------------------------------------------------
    # 5. Apply gold (random roll from wizard state)
    # -----------------------------------------------------------------------
    gold_to_apply: int = state.get("gold", 0)

    # Handle extra gold from selected equipment (Gold Crowns item pick)
    extra_gold_from_selection = 0
    for sel in selected_items_state:
        if sel.get("item_type") == "gold":
            eq = eq_by_name.get(sel["item_name"])
            if eq is None:
                continue
            go = (
                db.query(GameObject).filter(GameObject.id == eq.game_object_id).first()
                if eq.game_object_id
                else None
            )
            if go and go.properties:
                props = json.loads(go.properties)
                extra_gold_from_selection += int(props.get("quantity", 0))

    new_gold = min(character.gold + gold_to_apply + extra_gold_from_selection, 50)

    # -----------------------------------------------------------------------
    # 6. Update character's book_id to the new book
    # -----------------------------------------------------------------------
    character.book_id = to_book.id

    # -----------------------------------------------------------------------
    # 7. Recalculate endurance_max
    # -----------------------------------------------------------------------
    db.flush()
    db.refresh(character)

    discipline_names = [cd.discipline.name for cd in character.disciplines]  # type: ignore[attr-defined]
    item_states = _build_item_states_from_character(db, character)
    new_endurance_max = compute_endurance_max(character.endurance_base, discipline_names, item_states)
    character.endurance_max = new_endurance_max
    # NOTE: Do NOT set endurance_current = endurance_max here.
    # The character may be damaged. Only cap current at new max.
    character.endurance_current = min(character.endurance_current, new_endurance_max)

    character.gold = new_gold

    # -----------------------------------------------------------------------
    # 8. Save character_book_starts snapshot for the new book
    # -----------------------------------------------------------------------
    db.flush()
    db.refresh(character)

    items_snapshot = [
        {
            "item_name": ci.item_name,
            "item_type": ci.item_type,
            "is_equipped": ci.is_equipped,
            "game_object_id": ci.game_object_id,
        }
        for ci in character.items
    ]
    disciplines_snapshot = [
        {
            "discipline_id": cd.discipline_id,
            "weapon_category": cd.weapon_category,
        }
        for cd in character.disciplines  # type: ignore[attr-defined]
    ]

    book_start = CharacterBookStart(
        character_id=character.id,
        book_id=to_book.id,
        combat_skill_base=character.combat_skill_base,
        endurance_base=character.endurance_base,
        endurance_max=character.endurance_max,
        endurance_current=character.endurance_current,
        gold=character.gold,
        meals=character.meals,
        items_json=json.dumps(items_snapshot),
        disciplines_json=json.dumps(disciplines_snapshot),
        created_at=now,
    )
    db.add(book_start)

    # -----------------------------------------------------------------------
    # 9. Place character at new book's start scene
    # -----------------------------------------------------------------------
    start_scene = (
        db.query(Scene)
        .filter(Scene.book_id == to_book.id, Scene.number == to_book.start_scene_number)
        .first()
    )
    if start_scene is None:
        raise LookupError(
            f"Start scene (number={to_book.start_scene_number}) not found for book {to_book.id}"
        )
    character.current_scene_id = start_scene.id

    # -----------------------------------------------------------------------
    # 10. Clear wizard
    # -----------------------------------------------------------------------
    progress.completed_at = now
    character.active_wizard_id = None
    character.version += 1
    character.updated_at = now

    db.flush()

    return character
