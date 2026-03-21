"""Integration tests for POST /characters — character creation."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Discipline, WeaponCategory
from app.services.auth_service import create_roll_token
from tests.factories import (
    make_book,
    make_character,
    make_user,
    make_wizard_step,
    make_wizard_template,
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

_KAI_DISCIPLINE_NAMES = [
    "Camouflage",
    "Hunting",
    "Sixth Sense",
    "Tracking",
    "Healing",
    "Weaponskill",
    "Mindblast",
    "Animal Kinship",
    "Mind Over Matter",
    "Mindshield",
]

_WEAPON_CATEGORIES = [
    ("Sword", "Sword"),
    ("Broadsword", "Sword"),
    ("Short Sword", "Sword"),
    ("Axe", "Axe"),
    ("Mace", "Mace"),
    ("Spear", "Spear"),
    ("Dagger", "Dagger"),
    ("Quarterstaff", "Quarterstaff"),
    ("Warhammer", "Warhammer"),
]


def _seed_kai_data(db: Session):
    """Seed disciplines, weapon categories, and wizard template for Kai era.

    Returns:
        Tuple of (book, disciplines, wizard_template).
    """
    book = make_book(db, number=1, era="kai")

    disciplines = []
    for name in _KAI_DISCIPLINE_NAMES:
        disc = Discipline(
            era="kai",
            name=name,
            html_id=name.lower().replace(" ", "-"),
            description=f"{name} discipline description.",
        )
        db.add(disc)
        disciplines.append(disc)
    db.flush()

    for weapon_name, category in _WEAPON_CATEGORIES:
        wc = WeaponCategory(weapon_name=weapon_name, category=category)
        db.add(wc)
    db.flush()

    template = make_wizard_template(db, name="character_creation")
    make_wizard_step(db, template, step_type="pick_equipment", ordinal=0)
    make_wizard_step(db, template, step_type="confirm", ordinal=1)

    return book, disciplines, template


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _register_and_login(client: TestClient, username: str) -> tuple[str, int]:
    """Register a user, log in, and return (access_token, user_id)."""
    reg = client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Pass1234!",
        },
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]
    resp = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    assert resp.status_code == 200
    return resp.json()["access_token"], user_id


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _roll(client: TestClient, token: str, book_id: int) -> str:
    """Call POST /characters/roll and return the roll_token."""
    resp = client.post(
        "/characters/roll",
        json={"book_id": book_id},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    return resp.json()["roll_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateCharacter:
    def test_valid_creation_returns_201(self, client: TestClient, db: Session) -> None:
        """Happy path: roll then create returns 201 with expected fields."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator1")
        roll_token = _roll(client, token, book.id)

        # Pick 5 non-Weaponskill disciplines
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

        resp = client.post(
            "/characters",
            json={
                "name": "Lone Wolf",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Lone Wolf"
        assert data["id"] > 0
        assert 10 <= data["combat_skill_base"] <= 19
        assert 20 <= data["endurance_base"] <= 29
        assert data["endurance_max"] == data["endurance_base"]
        assert data["endurance_current"] == data["endurance_base"]
        assert data["gold"] == 0
        assert data["meals"] == 0
        assert data["death_count"] == 0
        assert data["current_run"] == 1
        assert data["version"] == 1
        assert len(data["disciplines"]) == 5
        assert data["active_wizard"] is not None

    def test_expired_roll_token_returns_400_with_error_code(
        self, client: TestClient, db: Session
    ) -> None:
        """An expired roll token must return 400 with INVALID_ROLL_TOKEN error_code."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "creator2")

        # Build a token that expired 2 hours ago
        from app.services.auth_service import create_token

        expired_roll_token = create_token(
            data={"sub": str(user_id), "cs": 15, "end": 25, "book_id": book.id},
            token_type="roll",
            expires_delta=timedelta(hours=-2),
        )

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

        resp = client.post(
            "/characters",
            json={
                "name": "Ghost",
                "book_id": book.id,
                "roll_token": expired_roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "INVALID_ROLL_TOKEN"

    def test_max_characters_limit_enforced(self, client: TestClient, db: Session) -> None:
        """Creating a 4th character when max_characters=3 must return 400 MAX_CHARACTERS.

        Soft-deleted characters do not count toward the limit.
        """
        book, disciplines, _ = _seed_kai_data(db)

        # Register user via API so they get a DB record we can also use in factories
        token, user_id = _register_and_login(client, "creator3")

        # Find the user object from DB to use the factory
        from app.models.player import User

        user = db.query(User).filter(User.id == user_id).first()

        # Create 3 existing characters (up to max)
        for _ in range(3):
            make_character(db, user, book)

        # Also create 1 soft-deleted character — must NOT count
        make_character(db, user, book, is_deleted=True)

        roll_token = _roll(client, token, book.id)
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

        resp = client.post(
            "/characters",
            json={
                "name": "Overflow",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "MAX_CHARACTERS"

    def test_wrong_discipline_count_returns_400(self, client: TestClient, db: Session) -> None:
        """Sending 4 disciplines (or 6) must return 400."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator4")
        roll_token = _roll(client, token, book.id)

        chosen_4 = [d.id for d in disciplines if d.name != "Weaponskill"][:4]

        resp = client.post(
            "/characters",
            json={
                "name": "Short",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen_4,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 422  # Pydantic min_length=5 rejects at schema level

    def test_missing_weapon_skill_type_returns_400(self, client: TestClient, db: Session) -> None:
        """Choosing Weaponskill without providing weapon_skill_type must return 400."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator5")
        roll_token = _roll(client, token, book.id)

        # Include Weaponskill in the 5 chosen disciplines
        weaponskill = next(d for d in disciplines if d.name == "Weaponskill")
        others = [d.id for d in disciplines if d.name != "Weaponskill"][:4]
        chosen = [weaponskill.id] + others

        resp = client.post(
            "/characters",
            json={
                "name": "NoWeapon",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        assert "weapon_skill_type" in resp.json()["detail"].lower()

    def test_character_created_with_active_wizard(self, client: TestClient, db: Session) -> None:
        """The created character must have active_wizard set with correct metadata."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator6")
        roll_token = _roll(client, token, book.id)

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

        resp = client.post(
            "/characters",
            json={
                "name": "Wizard Hero",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["active_wizard"] is not None
        wizard = data["active_wizard"]
        assert wizard["type"] == "character_creation"
        assert wizard["step"] == "pick_equipment"
        assert wizard["step_index"] == 0
        assert wizard["total_steps"] == 2

    def test_roll_token_sub_mismatch_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """A roll token issued for a different user must return 400 INVALID_ROLL_TOKEN."""
        book, disciplines, _ = _seed_kai_data(db)

        # Register two users
        token_a, user_a_id = _register_and_login(client, "creator7a")
        token_b, user_b_id = _register_and_login(client, "creator7b")

        # Create a roll token belonging to user A
        roll_token_for_a = create_roll_token(
            user_id=user_a_id, cs=15, end=25, book_id=book.id
        )

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

        # User B tries to use user A's token
        resp = client.post(
            "/characters",
            json={
                "name": "Impostor",
                "book_id": book.id,
                "roll_token": roll_token_for_a,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token_b),
        )

        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "INVALID_ROLL_TOKEN"

    def test_invalid_discipline_ids_return_400(self, client: TestClient, db: Session) -> None:
        """Non-existent discipline IDs must return 400."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator8")
        roll_token = _roll(client, token, book.id)

        chosen = [99991, 99992, 99993, 99994, 99995]

        resp = client.post(
            "/characters",
            json={
                "name": "Ghost",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        assert "invalid" in resp.json()["detail"].lower()

    def test_unauthenticated_request_returns_401(self, client: TestClient, db: Session) -> None:
        """A request without a Bearer token must return 401."""
        book, disciplines, _ = _seed_kai_data(db)

        resp = client.post(
            "/characters",
            json={
                "name": "No Auth",
                "book_id": book.id,
                "roll_token": "fake",
                "discipline_ids": [1, 2, 3, 4, 5],
                "weapon_skill_type": None,
            },
        )

        assert resp.status_code == 401

    def test_weapon_skill_type_accepted_when_weaponskill_chosen(
        self, client: TestClient, db: Session
    ) -> None:
        """Choosing Weaponskill with a valid weapon_skill_type should succeed."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator9")
        roll_token = _roll(client, token, book.id)

        weaponskill = next(d for d in disciplines if d.name == "Weaponskill")
        others = [d.id for d in disciplines if d.name != "Weaponskill"][:4]
        chosen = [weaponskill.id] + others

        resp = client.post(
            "/characters",
            json={
                "name": "Blade Master",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": "Sword",
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert "Weaponskill" in data["disciplines"]

    def test_weapon_skill_type_without_weaponskill_is_ignored(
        self, client: TestClient, db: Session
    ) -> None:
        """Providing weapon_skill_type when Weaponskill is NOT selected is silently ignored."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator10")
        roll_token = _roll(client, token, book.id)

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

        resp = client.post(
            "/characters",
            json={
                "name": "Confused",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": "Sword",
            },
            headers=_auth_headers(token),
        )

        # Per spec: silently ignored, character created successfully
        assert resp.status_code == 201

    def test_roll_token_book_id_mismatch_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """A roll token whose book_id differs from the request must return 400."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "creator11")

        # Create a roll token for a different book_id (999)
        mismatched_token = create_roll_token(
            user_id=user_id, cs=15, end=25, book_id=999
        )

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

        resp = client.post(
            "/characters",
            json={
                "name": "Mismatch",
                "book_id": book.id,
                "roll_token": mismatched_token,
                "discipline_ids": chosen,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_ROLL_TOKEN"

    def test_invalid_weapon_skill_type_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """An invalid weapon category with Weaponskill chosen must return 400."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator12")
        roll_token = _roll(client, token, book.id)

        weaponskill = next(d for d in disciplines if d.name == "Weaponskill")
        others = [d.id for d in disciplines if d.name != "Weaponskill"][:4]
        chosen = [weaponskill.id] + others

        resp = client.post(
            "/characters",
            json={
                "name": "BadWeapon",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": "battleaxe",  # not a real category
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        assert "not a valid weapon category" in resp.json()["detail"]

    def test_duplicate_discipline_ids_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """Sending duplicate discipline IDs must return 400."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, "creator13")
        roll_token = _roll(client, token, book.id)

        first_disc = disciplines[0]
        duped = [first_disc.id] * 5

        resp = client.post(
            "/characters",
            json={
                "name": "Duper",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": duped,
            },
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        assert "duplicate" in resp.json()["detail"].lower()
