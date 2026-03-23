"""Admin content CRUD router — full CRUD for all content resources.

All endpoints require admin auth. The ``source`` column is always set to
``'manual'`` on create and update operations to distinguish admin edits from
parser-generated content.

Wizard templates are read-only: POST, PUT, DELETE return 405.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.admin import AdminUser
from app.models.content import (
    Book,
    Choice,
    CombatEncounter,
    CombatModifier,
    Discipline,
    SceneItem,
    WeaponCategory,
)
from app.models.content import Scene
from app.models.taxonomy import BookStartingEquipment, BookTransitionRule, GameObject, GameObjectRef
from app.models.wizard import WizardTemplate
from app.schemas.admin import (
    BookAdminResponse,
    BookCreateRequest,
    BookStartingEquipmentAdminResponse,
    BookStartingEquipmentCreateRequest,
    BookStartingEquipmentUpdateRequest,
    BookTransitionRuleAdminResponse,
    BookTransitionRuleCreateRequest,
    BookTransitionRuleUpdateRequest,
    BookUpdateRequest,
    ChoiceAdminResponse,
    ChoiceCreateRequest,
    ChoiceUpdateRequest,
    CombatEncounterAdminResponse,
    CombatEncounterCreateRequest,
    CombatEncounterUpdateRequest,
    CombatModifierAdminResponse,
    CombatModifierCreateRequest,
    CombatModifierUpdateRequest,
    DisciplineAdminResponse,
    DisciplineCreateRequest,
    DisciplineUpdateRequest,
    GameObjectAdminResponse,
    GameObjectCreateRequest,
    GameObjectRefAdminResponse,
    GameObjectRefCreateRequest,
    GameObjectRefUpdateRequest,
    GameObjectUpdateRequest,
    SceneAdminResponse,
    SceneCreateRequest,
    SceneItemAdminResponse,
    SceneItemCreateRequest,
    SceneItemUpdateRequest,
    SceneUpdateRequest,
    WeaponCategoryAdminResponse,
    WeaponCategoryCreateRequest,
    WeaponCategoryUpdateRequest,
    WizardTemplateAdminResponse,
)

router = APIRouter(prefix="/admin", tags=["admin-content"])


# ---------------------------------------------------------------------------
# Helper — apply non-None fields from an update schema to an ORM model
# ---------------------------------------------------------------------------


def _apply_update(model: Any, update_data: dict[str, Any]) -> None:
    """Apply non-None fields from *update_data* to *model* in-place.

    Fields whose value is ``None`` in the update dict are skipped so that a
    partial update (PATCH-style via PUT) works correctly — only explicitly
    supplied fields are changed.

    Args:
        model: The SQLAlchemy ORM instance to mutate.
        update_data: A dict of field name → new value.
    """
    for field, value in update_data.items():
        if value is not None:
            setattr(model, field, value)


# ---------------------------------------------------------------------------
# Books CRUD
# ---------------------------------------------------------------------------


@router.post("/books", response_model=BookAdminResponse, status_code=201)
def create_book(
    body: BookCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookAdminResponse:
    """Create a new book record with source='manual'.

    Args:
        body: Book fields to create.
        db: Database session.
        _admin: Authenticated admin (enforces admin-only access).

    Returns:
        The newly created book.
    """
    book = Book(**body.model_dump())
    db.add(book)
    db.flush()
    return BookAdminResponse.model_validate(book)


@router.get("/books", response_model=list[BookAdminResponse])
def list_books(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[BookAdminResponse]:
    """List all books.

    Args:
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        All book records.
    """
    books = db.query(Book).all()
    return [BookAdminResponse.model_validate(b) for b in books]


@router.get("/books/{id}", response_model=BookAdminResponse)
def get_book(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookAdminResponse:
    """Retrieve a single book by ID.

    Args:
        id: Book primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The book record.

    Raises:
        HTTPException 404: If no book with the given ID exists.
    """
    book = db.query(Book).filter(Book.id == id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return BookAdminResponse.model_validate(book)


@router.put("/books/{id}", response_model=BookAdminResponse)
def update_book(
    id: int,
    body: BookUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookAdminResponse:
    """Update a book's fields (partial update — only supplied fields change).

    Args:
        id: Book primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated book.

    Raises:
        HTTPException 404: If no book with the given ID exists.
    """
    book = db.query(Book).filter(Book.id == id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    _apply_update(book, body.model_dump(exclude_unset=True))
    db.flush()
    return BookAdminResponse.model_validate(book)


@router.delete("/books/{id}", status_code=204)
def delete_book(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a book.

    Args:
        id: Book primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If no book with the given ID exists.
    """
    book = db.query(Book).filter(Book.id == id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    db.delete(book)
    db.flush()


# ---------------------------------------------------------------------------
# Scenes CRUD
# ---------------------------------------------------------------------------


@router.post("/scenes", response_model=SceneAdminResponse, status_code=201)
def create_scene(
    body: SceneCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> SceneAdminResponse:
    """Create a new scene with source='manual'.

    Args:
        body: Scene fields to create.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created scene.
    """
    scene = Scene(**body.model_dump(), source="manual")
    db.add(scene)
    db.flush()
    return SceneAdminResponse.model_validate(scene)


@router.get("/scenes", response_model=list[SceneAdminResponse])
def list_scenes(
    book_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[SceneAdminResponse]:
    """List scenes, optionally filtered by book.

    Args:
        book_id: Optional filter — only return scenes for this book.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching scene records.
    """
    q = db.query(Scene)
    if book_id is not None:
        q = q.filter(Scene.book_id == book_id)
    return [SceneAdminResponse.model_validate(s) for s in q.all()]


@router.get("/scenes/{id}", response_model=SceneAdminResponse)
def get_scene(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> SceneAdminResponse:
    """Retrieve a single scene by ID.

    Args:
        id: Scene primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The scene record.

    Raises:
        HTTPException 404: If no scene with the given ID exists.
    """
    scene = db.query(Scene).filter(Scene.id == id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return SceneAdminResponse.model_validate(scene)


@router.put("/scenes/{id}", response_model=SceneAdminResponse)
def update_scene(
    id: int,
    body: SceneUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> SceneAdminResponse:
    """Update a scene's fields and set source='manual'.

    Args:
        id: Scene primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated scene.

    Raises:
        HTTPException 404: If no scene with the given ID exists.
    """
    scene = db.query(Scene).filter(Scene.id == id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    _apply_update(scene, body.model_dump(exclude_unset=True))
    scene.source = "manual"
    db.flush()
    return SceneAdminResponse.model_validate(scene)


@router.delete("/scenes/{id}", status_code=204)
def delete_scene(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a scene.

    Args:
        id: Scene primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If no scene with the given ID exists.
    """
    scene = db.query(Scene).filter(Scene.id == id).first()
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    db.delete(scene)
    db.flush()


# ---------------------------------------------------------------------------
# Choices CRUD
# ---------------------------------------------------------------------------


@router.post("/choices", response_model=ChoiceAdminResponse, status_code=201)
def create_choice(
    body: ChoiceCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> ChoiceAdminResponse:
    """Create a new choice with source='manual'.

    Args:
        body: Choice fields to create.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created choice.
    """
    choice = Choice(**body.model_dump(), source="manual")
    db.add(choice)
    db.flush()
    return ChoiceAdminResponse.model_validate(choice)


@router.get("/choices", response_model=list[ChoiceAdminResponse])
def list_choices(
    scene_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[ChoiceAdminResponse]:
    """List choices, optionally filtered by scene.

    Args:
        scene_id: Optional filter — only return choices for this scene.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching choice records.
    """
    q = db.query(Choice)
    if scene_id is not None:
        q = q.filter(Choice.scene_id == scene_id)
    return [ChoiceAdminResponse.model_validate(c) for c in q.all()]


@router.get("/choices/{id}", response_model=ChoiceAdminResponse)
def get_choice(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> ChoiceAdminResponse:
    """Retrieve a single choice by ID.

    Args:
        id: Choice primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The choice record.

    Raises:
        HTTPException 404: If no choice with the given ID exists.
    """
    choice = db.query(Choice).filter(Choice.id == id).first()
    if not choice:
        raise HTTPException(status_code=404, detail="Choice not found")
    return ChoiceAdminResponse.model_validate(choice)


@router.put("/choices/{id}", response_model=ChoiceAdminResponse)
def update_choice(
    id: int,
    body: ChoiceUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> ChoiceAdminResponse:
    """Update a choice's fields and set source='manual'.

    Args:
        id: Choice primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated choice.

    Raises:
        HTTPException 404: If no choice with the given ID exists.
    """
    choice = db.query(Choice).filter(Choice.id == id).first()
    if not choice:
        raise HTTPException(status_code=404, detail="Choice not found")
    _apply_update(choice, body.model_dump(exclude_unset=True))
    choice.source = "manual"
    db.flush()
    return ChoiceAdminResponse.model_validate(choice)


@router.delete("/choices/{id}", status_code=204)
def delete_choice(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a choice.

    Args:
        id: Choice primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If no choice with the given ID exists.
    """
    choice = db.query(Choice).filter(Choice.id == id).first()
    if not choice:
        raise HTTPException(status_code=404, detail="Choice not found")
    db.delete(choice)
    db.flush()


# ---------------------------------------------------------------------------
# Combat Encounters CRUD
# ---------------------------------------------------------------------------


@router.post("/combat-encounters", response_model=CombatEncounterAdminResponse, status_code=201)
def create_combat_encounter(
    body: CombatEncounterCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> CombatEncounterAdminResponse:
    """Create a new combat encounter with source='manual'.

    Args:
        body: Encounter fields to create.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created combat encounter.
    """
    encounter = CombatEncounter(**body.model_dump(), source="manual")
    db.add(encounter)
    db.flush()
    return CombatEncounterAdminResponse.model_validate(encounter)


@router.get("/combat-encounters", response_model=list[CombatEncounterAdminResponse])
def list_combat_encounters(
    scene_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[CombatEncounterAdminResponse]:
    """List combat encounters, optionally filtered by scene.

    Args:
        scene_id: Optional filter.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching encounter records.
    """
    q = db.query(CombatEncounter)
    if scene_id is not None:
        q = q.filter(CombatEncounter.scene_id == scene_id)
    return [CombatEncounterAdminResponse.model_validate(e) for e in q.all()]


@router.get("/combat-encounters/{id}", response_model=CombatEncounterAdminResponse)
def get_combat_encounter(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> CombatEncounterAdminResponse:
    """Retrieve a single combat encounter by ID.

    Args:
        id: Encounter primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The combat encounter record.

    Raises:
        HTTPException 404: If not found.
    """
    encounter = db.query(CombatEncounter).filter(CombatEncounter.id == id).first()
    if not encounter:
        raise HTTPException(status_code=404, detail="Combat encounter not found")
    return CombatEncounterAdminResponse.model_validate(encounter)


@router.put("/combat-encounters/{id}", response_model=CombatEncounterAdminResponse)
def update_combat_encounter(
    id: int,
    body: CombatEncounterUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> CombatEncounterAdminResponse:
    """Update a combat encounter and set source='manual'.

    Args:
        id: Encounter primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated combat encounter.

    Raises:
        HTTPException 404: If not found.
    """
    encounter = db.query(CombatEncounter).filter(CombatEncounter.id == id).first()
    if not encounter:
        raise HTTPException(status_code=404, detail="Combat encounter not found")
    _apply_update(encounter, body.model_dump(exclude_unset=True))
    encounter.source = "manual"
    db.flush()
    return CombatEncounterAdminResponse.model_validate(encounter)


@router.delete("/combat-encounters/{id}", status_code=204)
def delete_combat_encounter(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a combat encounter.

    Args:
        id: Encounter primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    encounter = db.query(CombatEncounter).filter(CombatEncounter.id == id).first()
    if not encounter:
        raise HTTPException(status_code=404, detail="Combat encounter not found")
    db.delete(encounter)
    db.flush()


# ---------------------------------------------------------------------------
# Combat Modifiers CRUD
# ---------------------------------------------------------------------------


@router.post("/combat-modifiers", response_model=CombatModifierAdminResponse, status_code=201)
def create_combat_modifier(
    body: CombatModifierCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> CombatModifierAdminResponse:
    """Create a combat modifier with source='manual'.

    Args:
        body: Modifier fields to create.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created modifier.
    """
    modifier = CombatModifier(**body.model_dump(), source="manual")
    db.add(modifier)
    db.flush()
    return CombatModifierAdminResponse.model_validate(modifier)


@router.get("/combat-modifiers", response_model=list[CombatModifierAdminResponse])
def list_combat_modifiers(
    combat_encounter_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[CombatModifierAdminResponse]:
    """List combat modifiers, optionally filtered by encounter.

    Args:
        combat_encounter_id: Optional filter.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching modifier records.
    """
    q = db.query(CombatModifier)
    if combat_encounter_id is not None:
        q = q.filter(CombatModifier.combat_encounter_id == combat_encounter_id)
    return [CombatModifierAdminResponse.model_validate(m) for m in q.all()]


@router.get("/combat-modifiers/{id}", response_model=CombatModifierAdminResponse)
def get_combat_modifier(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> CombatModifierAdminResponse:
    """Retrieve a single combat modifier by ID.

    Args:
        id: Modifier primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The modifier record.

    Raises:
        HTTPException 404: If not found.
    """
    modifier = db.query(CombatModifier).filter(CombatModifier.id == id).first()
    if not modifier:
        raise HTTPException(status_code=404, detail="Combat modifier not found")
    return CombatModifierAdminResponse.model_validate(modifier)


@router.put("/combat-modifiers/{id}", response_model=CombatModifierAdminResponse)
def update_combat_modifier(
    id: int,
    body: CombatModifierUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> CombatModifierAdminResponse:
    """Update a combat modifier and set source='manual'.

    Args:
        id: Modifier primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated modifier.

    Raises:
        HTTPException 404: If not found.
    """
    modifier = db.query(CombatModifier).filter(CombatModifier.id == id).first()
    if not modifier:
        raise HTTPException(status_code=404, detail="Combat modifier not found")
    _apply_update(modifier, body.model_dump(exclude_unset=True))
    modifier.source = "manual"
    db.flush()
    return CombatModifierAdminResponse.model_validate(modifier)


@router.delete("/combat-modifiers/{id}", status_code=204)
def delete_combat_modifier(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a combat modifier.

    Args:
        id: Modifier primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    modifier = db.query(CombatModifier).filter(CombatModifier.id == id).first()
    if not modifier:
        raise HTTPException(status_code=404, detail="Combat modifier not found")
    db.delete(modifier)
    db.flush()


# ---------------------------------------------------------------------------
# Scene Items CRUD
# ---------------------------------------------------------------------------


@router.post("/scene-items", response_model=SceneItemAdminResponse, status_code=201)
def create_scene_item(
    body: SceneItemCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> SceneItemAdminResponse:
    """Create a scene item with source='manual'.

    Args:
        body: Scene item fields to create.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created scene item.
    """
    item = SceneItem(**body.model_dump(), source="manual")
    db.add(item)
    db.flush()
    return SceneItemAdminResponse.model_validate(item)


@router.get("/scene-items", response_model=list[SceneItemAdminResponse])
def list_scene_items(
    scene_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[SceneItemAdminResponse]:
    """List scene items, optionally filtered by scene.

    Args:
        scene_id: Optional filter.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching scene item records.
    """
    q = db.query(SceneItem)
    if scene_id is not None:
        q = q.filter(SceneItem.scene_id == scene_id)
    return [SceneItemAdminResponse.model_validate(i) for i in q.all()]


@router.get("/scene-items/{id}", response_model=SceneItemAdminResponse)
def get_scene_item(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> SceneItemAdminResponse:
    """Retrieve a single scene item by ID.

    Args:
        id: Scene item primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The scene item record.

    Raises:
        HTTPException 404: If not found.
    """
    item = db.query(SceneItem).filter(SceneItem.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scene item not found")
    return SceneItemAdminResponse.model_validate(item)


@router.put("/scene-items/{id}", response_model=SceneItemAdminResponse)
def update_scene_item(
    id: int,
    body: SceneItemUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> SceneItemAdminResponse:
    """Update a scene item and set source='manual'.

    Args:
        id: Scene item primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated scene item.

    Raises:
        HTTPException 404: If not found.
    """
    item = db.query(SceneItem).filter(SceneItem.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scene item not found")
    _apply_update(item, body.model_dump(exclude_unset=True))
    item.source = "manual"
    db.flush()
    return SceneItemAdminResponse.model_validate(item)


@router.delete("/scene-items/{id}", status_code=204)
def delete_scene_item(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a scene item.

    Args:
        id: Scene item primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    item = db.query(SceneItem).filter(SceneItem.id == id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scene item not found")
    db.delete(item)
    db.flush()


# ---------------------------------------------------------------------------
# Disciplines CRUD
# ---------------------------------------------------------------------------


@router.post("/disciplines", response_model=DisciplineAdminResponse, status_code=201)
def create_discipline(
    body: DisciplineCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> DisciplineAdminResponse:
    """Create a discipline record.

    Args:
        body: Discipline fields.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created discipline.
    """
    discipline = Discipline(**body.model_dump())
    db.add(discipline)
    db.flush()
    return DisciplineAdminResponse.model_validate(discipline)


@router.get("/disciplines", response_model=list[DisciplineAdminResponse])
def list_disciplines(
    era: str | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[DisciplineAdminResponse]:
    """List disciplines, optionally filtered by era.

    Args:
        era: Optional filter.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching discipline records.
    """
    q = db.query(Discipline)
    if era is not None:
        q = q.filter(Discipline.era == era)
    return [DisciplineAdminResponse.model_validate(d) for d in q.all()]


@router.get("/disciplines/{id}", response_model=DisciplineAdminResponse)
def get_discipline(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> DisciplineAdminResponse:
    """Retrieve a single discipline by ID.

    Args:
        id: Discipline primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The discipline record.

    Raises:
        HTTPException 404: If not found.
    """
    discipline = db.query(Discipline).filter(Discipline.id == id).first()
    if not discipline:
        raise HTTPException(status_code=404, detail="Discipline not found")
    return DisciplineAdminResponse.model_validate(discipline)


@router.put("/disciplines/{id}", response_model=DisciplineAdminResponse)
def update_discipline(
    id: int,
    body: DisciplineUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> DisciplineAdminResponse:
    """Update a discipline's fields.

    Args:
        id: Discipline primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated discipline.

    Raises:
        HTTPException 404: If not found.
    """
    discipline = db.query(Discipline).filter(Discipline.id == id).first()
    if not discipline:
        raise HTTPException(status_code=404, detail="Discipline not found")
    _apply_update(discipline, body.model_dump(exclude_unset=True))
    db.flush()
    return DisciplineAdminResponse.model_validate(discipline)


@router.delete("/disciplines/{id}", status_code=204)
def delete_discipline(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a discipline.

    Args:
        id: Discipline primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    discipline = db.query(Discipline).filter(Discipline.id == id).first()
    if not discipline:
        raise HTTPException(status_code=404, detail="Discipline not found")
    db.delete(discipline)
    db.flush()


# ---------------------------------------------------------------------------
# Book Transition Rules CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/book-transition-rules", response_model=BookTransitionRuleAdminResponse, status_code=201
)
def create_book_transition_rule(
    body: BookTransitionRuleCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookTransitionRuleAdminResponse:
    """Create a book transition rule.

    Args:
        body: Transition rule fields.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created transition rule.
    """
    rule = BookTransitionRule(**body.model_dump())
    db.add(rule)
    db.flush()
    return BookTransitionRuleAdminResponse.model_validate(rule)


@router.get("/book-transition-rules", response_model=list[BookTransitionRuleAdminResponse])
def list_book_transition_rules(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[BookTransitionRuleAdminResponse]:
    """List all book transition rules.

    Args:
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        All transition rule records.
    """
    rules = db.query(BookTransitionRule).all()
    return [BookTransitionRuleAdminResponse.model_validate(r) for r in rules]


@router.get("/book-transition-rules/{id}", response_model=BookTransitionRuleAdminResponse)
def get_book_transition_rule(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookTransitionRuleAdminResponse:
    """Retrieve a single book transition rule by ID.

    Args:
        id: Rule primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The transition rule record.

    Raises:
        HTTPException 404: If not found.
    """
    rule = db.query(BookTransitionRule).filter(BookTransitionRule.id == id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Book transition rule not found")
    return BookTransitionRuleAdminResponse.model_validate(rule)


@router.put("/book-transition-rules/{id}", response_model=BookTransitionRuleAdminResponse)
def update_book_transition_rule(
    id: int,
    body: BookTransitionRuleUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookTransitionRuleAdminResponse:
    """Update a book transition rule.

    Args:
        id: Rule primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated rule.

    Raises:
        HTTPException 404: If not found.
    """
    rule = db.query(BookTransitionRule).filter(BookTransitionRule.id == id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Book transition rule not found")
    _apply_update(rule, body.model_dump(exclude_unset=True))
    db.flush()
    return BookTransitionRuleAdminResponse.model_validate(rule)


@router.delete("/book-transition-rules/{id}", status_code=204)
def delete_book_transition_rule(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a book transition rule.

    Args:
        id: Rule primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    rule = db.query(BookTransitionRule).filter(BookTransitionRule.id == id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Book transition rule not found")
    db.delete(rule)
    db.flush()


# ---------------------------------------------------------------------------
# Weapon Categories CRUD
# ---------------------------------------------------------------------------


@router.post("/weapon-categories", response_model=WeaponCategoryAdminResponse, status_code=201)
def create_weapon_category(
    body: WeaponCategoryCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> WeaponCategoryAdminResponse:
    """Create a weapon category.

    Args:
        body: Weapon category fields.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created weapon category.
    """
    wc = WeaponCategory(**body.model_dump())
    db.add(wc)
    db.flush()
    return WeaponCategoryAdminResponse.model_validate(wc)


@router.get("/weapon-categories", response_model=list[WeaponCategoryAdminResponse])
def list_weapon_categories(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[WeaponCategoryAdminResponse]:
    """List all weapon categories.

    Args:
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        All weapon category records.
    """
    categories = db.query(WeaponCategory).all()
    return [WeaponCategoryAdminResponse.model_validate(c) for c in categories]


@router.get("/weapon-categories/{id}", response_model=WeaponCategoryAdminResponse)
def get_weapon_category(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> WeaponCategoryAdminResponse:
    """Retrieve a single weapon category by ID.

    Args:
        id: Weapon category primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The weapon category record.

    Raises:
        HTTPException 404: If not found.
    """
    wc = db.query(WeaponCategory).filter(WeaponCategory.id == id).first()
    if not wc:
        raise HTTPException(status_code=404, detail="Weapon category not found")
    return WeaponCategoryAdminResponse.model_validate(wc)


@router.put("/weapon-categories/{id}", response_model=WeaponCategoryAdminResponse)
def update_weapon_category(
    id: int,
    body: WeaponCategoryUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> WeaponCategoryAdminResponse:
    """Update a weapon category.

    Args:
        id: Weapon category primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated weapon category.

    Raises:
        HTTPException 404: If not found.
    """
    wc = db.query(WeaponCategory).filter(WeaponCategory.id == id).first()
    if not wc:
        raise HTTPException(status_code=404, detail="Weapon category not found")
    _apply_update(wc, body.model_dump(exclude_unset=True))
    db.flush()
    return WeaponCategoryAdminResponse.model_validate(wc)


@router.delete("/weapon-categories/{id}", status_code=204)
def delete_weapon_category(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a weapon category.

    Args:
        id: Weapon category primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    wc = db.query(WeaponCategory).filter(WeaponCategory.id == id).first()
    if not wc:
        raise HTTPException(status_code=404, detail="Weapon category not found")
    db.delete(wc)
    db.flush()


# ---------------------------------------------------------------------------
# Game Objects CRUD
# ---------------------------------------------------------------------------


@router.post("/game-objects", response_model=GameObjectAdminResponse, status_code=201)
def create_game_object(
    body: GameObjectCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GameObjectAdminResponse:
    """Create a game object with source='manual'.

    Args:
        body: Game object fields.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created game object.
    """
    obj = GameObject(**body.model_dump(), source="manual")
    db.add(obj)
    db.flush()
    return GameObjectAdminResponse.model_validate(obj)


@router.get("/game-objects", response_model=list[GameObjectAdminResponse])
def list_game_objects(
    kind: str | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[GameObjectAdminResponse]:
    """List game objects, optionally filtered by kind.

    Args:
        kind: Optional filter (e.g. 'item', 'character').
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching game object records.
    """
    q = db.query(GameObject)
    if kind is not None:
        q = q.filter(GameObject.kind == kind)
    return [GameObjectAdminResponse.model_validate(o) for o in q.all()]


@router.get("/game-objects/{id}", response_model=GameObjectAdminResponse)
def get_game_object(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GameObjectAdminResponse:
    """Retrieve a single game object by ID.

    Args:
        id: Game object primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The game object record.

    Raises:
        HTTPException 404: If not found.
    """
    obj = db.query(GameObject).filter(GameObject.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Game object not found")
    return GameObjectAdminResponse.model_validate(obj)


@router.put("/game-objects/{id}", response_model=GameObjectAdminResponse)
def update_game_object(
    id: int,
    body: GameObjectUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GameObjectAdminResponse:
    """Update a game object and set source='manual'.

    Args:
        id: Game object primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated game object.

    Raises:
        HTTPException 404: If not found.
    """
    obj = db.query(GameObject).filter(GameObject.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Game object not found")
    _apply_update(obj, body.model_dump(exclude_unset=True))
    obj.source = "manual"
    db.flush()
    return GameObjectAdminResponse.model_validate(obj)


@router.delete("/game-objects/{id}", status_code=204)
def delete_game_object(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a game object.

    Args:
        id: Game object primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    obj = db.query(GameObject).filter(GameObject.id == id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="Game object not found")
    db.delete(obj)
    db.flush()


# ---------------------------------------------------------------------------
# Game Object Refs CRUD
# ---------------------------------------------------------------------------


@router.post("/game-object-refs", response_model=GameObjectRefAdminResponse, status_code=201)
def create_game_object_ref(
    body: GameObjectRefCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GameObjectRefAdminResponse:
    """Create a game object ref with source='manual'.

    The ``metadata`` request field maps to the ``metadata_`` column alias on the model.

    Args:
        body: Ref fields.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created ref.
    """
    data = body.model_dump()
    # Map 'metadata' request field to 'metadata_' column alias
    metadata_val = data.pop("metadata", None)
    ref = GameObjectRef(**data, metadata_=metadata_val, source="manual")
    db.add(ref)
    db.flush()
    return GameObjectRefAdminResponse.model_validate(ref)


@router.get("/game-object-refs", response_model=list[GameObjectRefAdminResponse])
def list_game_object_refs(
    source_id: int | None = None,
    target_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[GameObjectRefAdminResponse]:
    """List game object refs with optional filters.

    Args:
        source_id: Optional filter by source game object.
        target_id: Optional filter by target game object.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching ref records.
    """
    q = db.query(GameObjectRef)
    if source_id is not None:
        q = q.filter(GameObjectRef.source_id == source_id)
    if target_id is not None:
        q = q.filter(GameObjectRef.target_id == target_id)
    return [GameObjectRefAdminResponse.model_validate(r) for r in q.all()]


@router.get("/game-object-refs/{id}", response_model=GameObjectRefAdminResponse)
def get_game_object_ref(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GameObjectRefAdminResponse:
    """Retrieve a single game object ref by ID.

    Args:
        id: Ref primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The ref record.

    Raises:
        HTTPException 404: If not found.
    """
    ref = db.query(GameObjectRef).filter(GameObjectRef.id == id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Game object ref not found")
    return GameObjectRefAdminResponse.model_validate(ref)


@router.put("/game-object-refs/{id}", response_model=GameObjectRefAdminResponse)
def update_game_object_ref(
    id: int,
    body: GameObjectRefUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> GameObjectRefAdminResponse:
    """Update a game object ref and set source='manual'.

    Args:
        id: Ref primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated ref.

    Raises:
        HTTPException 404: If not found.
    """
    ref = db.query(GameObjectRef).filter(GameObjectRef.id == id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Game object ref not found")
    update_data = body.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")
    _apply_update(ref, update_data)
    ref.source = "manual"
    db.flush()
    return GameObjectRefAdminResponse.model_validate(ref)


@router.delete("/game-object-refs/{id}", status_code=204)
def delete_game_object_ref(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a game object ref.

    Args:
        id: Ref primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    ref = db.query(GameObjectRef).filter(GameObjectRef.id == id).first()
    if not ref:
        raise HTTPException(status_code=404, detail="Game object ref not found")
    db.delete(ref)
    db.flush()


# ---------------------------------------------------------------------------
# Book Starting Equipment CRUD
# ---------------------------------------------------------------------------


@router.post(
    "/book-starting-equipment", response_model=BookStartingEquipmentAdminResponse, status_code=201
)
def create_book_starting_equipment(
    body: BookStartingEquipmentCreateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookStartingEquipmentAdminResponse:
    """Create a book starting equipment record with source='manual'.

    Args:
        body: Equipment fields.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The newly created equipment record.
    """
    equip = BookStartingEquipment(**body.model_dump(), source="manual")
    db.add(equip)
    db.flush()
    return BookStartingEquipmentAdminResponse.model_validate(equip)


@router.get("/book-starting-equipment", response_model=list[BookStartingEquipmentAdminResponse])
def list_book_starting_equipment(
    book_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[BookStartingEquipmentAdminResponse]:
    """List book starting equipment, optionally filtered by book.

    Args:
        book_id: Optional filter.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        Matching equipment records.
    """
    q = db.query(BookStartingEquipment)
    if book_id is not None:
        q = q.filter(BookStartingEquipment.book_id == book_id)
    return [BookStartingEquipmentAdminResponse.model_validate(e) for e in q.all()]


@router.get("/book-starting-equipment/{id}", response_model=BookStartingEquipmentAdminResponse)
def get_book_starting_equipment(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookStartingEquipmentAdminResponse:
    """Retrieve a single book starting equipment record by ID.

    Args:
        id: Equipment primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The equipment record.

    Raises:
        HTTPException 404: If not found.
    """
    equip = db.query(BookStartingEquipment).filter(BookStartingEquipment.id == id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Book starting equipment not found")
    return BookStartingEquipmentAdminResponse.model_validate(equip)


@router.put(
    "/book-starting-equipment/{id}", response_model=BookStartingEquipmentAdminResponse
)
def update_book_starting_equipment(
    id: int,
    body: BookStartingEquipmentUpdateRequest,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> BookStartingEquipmentAdminResponse:
    """Update a book starting equipment record and set source='manual'.

    Args:
        id: Equipment primary key.
        body: Fields to update.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The updated equipment record.

    Raises:
        HTTPException 404: If not found.
    """
    equip = db.query(BookStartingEquipment).filter(BookStartingEquipment.id == id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Book starting equipment not found")
    _apply_update(equip, body.model_dump(exclude_unset=True))
    equip.source = "manual"
    db.flush()
    return BookStartingEquipmentAdminResponse.model_validate(equip)


@router.delete("/book-starting-equipment/{id}", status_code=204)
def delete_book_starting_equipment(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> None:
    """Delete a book starting equipment record.

    Args:
        id: Equipment primary key.
        db: Database session.
        _admin: Authenticated admin.

    Raises:
        HTTPException 404: If not found.
    """
    equip = db.query(BookStartingEquipment).filter(BookStartingEquipment.id == id).first()
    if not equip:
        raise HTTPException(status_code=404, detail="Book starting equipment not found")
    db.delete(equip)
    db.flush()


# ---------------------------------------------------------------------------
# Wizard Templates — READ ONLY (POST/PUT/DELETE return 405)
# ---------------------------------------------------------------------------


@router.post("/wizard-templates", status_code=405)
def create_wizard_template_not_allowed() -> dict:
    """Wizard templates are read-only — POST is not allowed.

    Returns:
        405 Method Not Allowed.
    """
    raise HTTPException(status_code=405, detail="Wizard templates are read-only")


@router.get("/wizard-templates", response_model=list[WizardTemplateAdminResponse])
def list_wizard_templates(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> list[WizardTemplateAdminResponse]:
    """List all wizard templates (read-only).

    Args:
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        All wizard template records.
    """
    templates = db.query(WizardTemplate).all()
    return [WizardTemplateAdminResponse.model_validate(t) for t in templates]


@router.get("/wizard-templates/{id}", response_model=WizardTemplateAdminResponse)
def get_wizard_template(
    id: int,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(get_current_admin),
) -> WizardTemplateAdminResponse:
    """Retrieve a single wizard template by ID (read-only).

    Args:
        id: Template primary key.
        db: Database session.
        _admin: Authenticated admin.

    Returns:
        The wizard template record.

    Raises:
        HTTPException 404: If not found.
    """
    template = db.query(WizardTemplate).filter(WizardTemplate.id == id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Wizard template not found")
    return WizardTemplateAdminResponse.model_validate(template)


@router.put("/wizard-templates/{id}", status_code=405)
def update_wizard_template_not_allowed(id: int) -> dict:
    """Wizard templates are read-only — PUT is not allowed.

    Args:
        id: Template primary key (unused).

    Returns:
        405 Method Not Allowed.
    """
    raise HTTPException(status_code=405, detail="Wizard templates are read-only")


@router.delete("/wizard-templates/{id}", status_code=405)
def delete_wizard_template_not_allowed(id: int) -> dict:
    """Wizard templates are read-only — DELETE is not allowed.

    Args:
        id: Template primary key (unused).

    Returns:
        405 Method Not Allowed.
    """
    raise HTTPException(status_code=405, detail="Wizard templates are read-only")
