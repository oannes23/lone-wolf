"""Character service — business logic for character creation."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.content import Book, Discipline, WeaponCategory
from app.models.player import Character, CharacterDiscipline, User
from app.models.wizard import CharacterWizardProgress, WizardTemplate
from app.services.auth_service import decode_token


def create_character(
    db: Session,
    user: User,
    name: str,
    book_id: int,
    roll_token: str,
    discipline_ids: list[int],
    weapon_skill_type: str | None,
) -> Character:
    """Create a new character for the given user by consuming a roll token.

    Validates the roll token, book, discipline selection, and weapon skill
    choice, then writes the Character, CharacterDiscipline rows, and the
    initial CharacterWizardProgress record in a single transaction.

    Args:
        db: Database session (caller owns the transaction).
        user: The authenticated player creating the character.
        name: Desired character name (1–100 characters).
        book_id: ID of the book the character will play.
        roll_token: Signed JWT returned by ``POST /characters/roll``.
        discipline_ids: Exactly 5 discipline primary keys for the Kai era.
        weapon_skill_type: Required weapon category if Weaponskill is chosen;
            must be ``None`` otherwise.

    Returns:
        The newly created ``Character`` ORM instance (not yet committed —
        caller should commit or the session-level transaction will commit).

    Raises:
        ValueError: For any validation failure.  The caller maps these to
            HTTP 400 responses.
        LookupError: If the book is not found (caller maps to HTTP 404).
    """
    # ------------------------------------------------------------------
    # 1. Decode and validate the roll token
    # ------------------------------------------------------------------
    try:
        payload = decode_token(roll_token, expected_type="roll")
    except ValueError as exc:
        raise ValueError(f"INVALID_ROLL_TOKEN: {exc}") from exc

    token_sub = payload.get("sub")
    if str(token_sub) != str(user.id):
        raise ValueError("INVALID_ROLL_TOKEN: token was issued for a different user")

    token_book_id = payload.get("book_id")
    if token_book_id != book_id:
        raise ValueError("INVALID_ROLL_TOKEN: token book_id does not match request")

    cs: int = payload["cs"]
    end: int = payload["end"]

    # ------------------------------------------------------------------
    # 2. Validate the book
    # ------------------------------------------------------------------
    book = db.query(Book).filter(Book.id == book_id).first()
    if book is None:
        raise LookupError("Book not found")

    if book.number != 1:
        raise ValueError("Only Book 1 is supported in this version")

    # ------------------------------------------------------------------
    # 3. Check the user's character limit
    # ------------------------------------------------------------------
    existing_count = (
        db.query(Character)
        .filter(Character.user_id == user.id, Character.is_deleted == False)  # noqa: E712
        .count()
    )
    if existing_count >= user.max_characters:
        raise ValueError("MAX_CHARACTERS: maximum number of characters reached")

    # ------------------------------------------------------------------
    # 4. Validate disciplines
    # ------------------------------------------------------------------
    if len(discipline_ids) != 5:
        raise ValueError(
            f"Exactly 5 disciplines are required for the Kai era, got {len(discipline_ids)}"
        )

    if len(set(discipline_ids)) != len(discipline_ids):
        raise ValueError("Duplicate discipline IDs are not allowed")

    disciplines = (
        db.query(Discipline).filter(Discipline.id.in_(discipline_ids)).all()
    )
    if len(disciplines) != 5:
        raise ValueError("One or more discipline IDs are invalid")

    for disc in disciplines:
        if disc.era != "kai":
            raise ValueError(
                f"Discipline '{disc.name}' (id={disc.id}) is not a Kai era discipline"
            )

    # ------------------------------------------------------------------
    # 5. Validate weapon skill type
    # ------------------------------------------------------------------
    weaponskill_discipline = next(
        (d for d in disciplines if d.name == "Weaponskill"), None
    )

    if weaponskill_discipline is not None:
        if not weapon_skill_type:
            raise ValueError(
                "weapon_skill_type is required when the Weaponskill discipline is chosen"
            )
        # Verify it's a valid category
        valid_category = (
            db.query(WeaponCategory)
            .filter(WeaponCategory.category == weapon_skill_type)
            .first()
        )
        if valid_category is None:
            raise ValueError(
                f"'{weapon_skill_type}' is not a valid weapon category"
            )
    else:
        # Spec: "If weapon_skill_type is provided but no Weaponskill discipline
        # was selected, it is ignored."  Silently discard.
        weapon_skill_type = None

    # ------------------------------------------------------------------
    # 6. Create the Character record
    # ------------------------------------------------------------------
    now = datetime.now(UTC)
    character = Character(
        user_id=user.id,
        book_id=book.id,
        name=name,
        combat_skill_base=cs,
        endurance_base=end,
        endurance_max=end,
        endurance_current=end,
        gold=0,
        meals=0,
        is_alive=True,
        is_deleted=False,
        death_count=0,
        current_run=1,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(character)
    db.flush()  # assigns character.id

    # ------------------------------------------------------------------
    # 7. Create CharacterDiscipline rows
    # ------------------------------------------------------------------
    for disc in disciplines:
        wc = weapon_skill_type if disc.name == "Weaponskill" else None
        cd = CharacterDiscipline(
            character_id=character.id,
            discipline_id=disc.id,
            weapon_category=wc,
        )
        db.add(cd)

    # ------------------------------------------------------------------
    # 8. Auto-start the equipment wizard
    # ------------------------------------------------------------------
    template = (
        db.query(WizardTemplate)
        .filter(WizardTemplate.name == "character_creation")
        .first()
    )
    if template is None:
        raise ValueError(
            "character_creation wizard template is not configured in the database"
        )

    wizard_progress = CharacterWizardProgress(
        character_id=character.id,
        wizard_template_id=template.id,
        current_step_index=0,
        state=None,
        started_at=now,
    )
    db.add(wizard_progress)
    db.flush()  # assigns wizard_progress.id

    character.active_wizard_id = wizard_progress.id
    db.flush()

    return character
