"""Integration tests for UI character creation flow.

Tests for:
- GET /ui/characters        — character list page
- GET /ui/characters/roll   — stat roll page
- POST /ui/characters/roll  — HTMX re-roll partial
- GET /ui/characters/create — create form
- POST /ui/characters/create — character creation
- GET /ui/characters/{id}/wizard — wizard step rendering
- POST /ui/characters/{id}/wizard — wizard step submission
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Discipline, WeaponCategory
from app.models.taxonomy import BookStartingEquipment, GameObject
from app.services.auth_service import create_access_token, create_roll_token
from tests.factories import (
    make_book,
    make_character,
    make_scene,
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
    ("Axe", "Axe"),
    ("Mace", "Mace"),
]


def _seed_kai_data(db: Session):
    """Seed Book 1, Kai disciplines, weapon categories, and wizard template.

    Returns:
        Tuple of (book, disciplines, template).
    """
    book = make_book(db, number=1, era="kai")

    # Create start scene required by confirm step
    scene = make_scene(db, book, number=1)
    book.start_scene_number = 1
    db.flush()

    disciplines = []
    for name in _KAI_DISCIPLINE_NAMES:
        disc = Discipline(
            era="kai",
            name=name,
            html_id=name.lower().replace(" ", "-"),
            description=f"{name} description.",
        )
        db.add(disc)
        disciplines.append(disc)
    db.flush()

    for weapon_name, category in _WEAPON_CATEGORIES:
        db.add(WeaponCategory(weapon_name=weapon_name, category=category))
    db.flush()

    template = make_wizard_template(db, name="character_creation")
    make_wizard_step(db, template, step_type="pick_equipment", ordinal=0)
    make_wizard_step(db, template, step_type="confirm", ordinal=1)

    return book, disciplines, template


def _register_and_login(client: TestClient, db: Session, username: str):
    """Register a user via API and return (access_token, user_id)."""
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
    login = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    return token, user_id


def _session_cookie(token: str) -> dict:
    """Return a cookie dict for UI requests."""
    return {"session": token}


# ---------------------------------------------------------------------------
# Character list
# ---------------------------------------------------------------------------


class TestCharacterList:
    def test_list_page_requires_auth(self, client: TestClient, db: Session) -> None:
        """Unauthenticated request to /ui/characters redirects to login."""
        resp = client.get("/ui/characters", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_list_page_renders_for_authenticated_user(
        self, client: TestClient, db: Session
    ) -> None:
        """Authenticated user sees the character list page."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "listuser1")
        resp = client.get("/ui/characters", cookies=_session_cookie(token))
        assert resp.status_code == 200
        assert "My Characters" in resp.text

    def test_list_shows_create_button(self, client: TestClient, db: Session) -> None:
        """Character list page has a 'Create New Character' link."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "listuser2")
        resp = client.get("/ui/characters", cookies=_session_cookie(token))
        assert resp.status_code == 200
        assert "Create New Character" in resp.text

    def test_list_shows_existing_characters(self, client: TestClient, db: Session) -> None:
        """Character list page shows the user's characters by name."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "listuser3")

        from app.models.player import User
        user = db.query(User).filter(User.id == user_id).first()
        make_character(db, user, book, name="Lone Wolf")
        db.flush()

        resp = client.get("/ui/characters", cookies=_session_cookie(token))
        assert resp.status_code == 200
        assert "Lone Wolf" in resp.text

    def test_list_does_not_show_deleted_characters(
        self, client: TestClient, db: Session
    ) -> None:
        """Soft-deleted characters must not appear in the list."""
        book, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "listuser4")

        from app.models.player import User
        user = db.query(User).filter(User.id == user_id).first()
        make_character(db, user, book, name="Ghost Character", is_deleted=True)
        db.flush()

        resp = client.get("/ui/characters", cookies=_session_cookie(token))
        assert resp.status_code == 200
        assert "Ghost Character" not in resp.text


# ---------------------------------------------------------------------------
# Roll page
# ---------------------------------------------------------------------------


class TestRollPage:
    def test_roll_page_requires_auth(self, client: TestClient, db: Session) -> None:
        """Unauthenticated request to /ui/characters/roll redirects to login."""
        resp = client.get("/ui/characters/roll", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_roll_page_renders_stats(self, client: TestClient, db: Session) -> None:
        """Roll page shows Combat Skill and Endurance values."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "rolluser1")
        resp = client.get("/ui/characters/roll", cookies=_session_cookie(token))
        assert resp.status_code == 200
        assert "Combat Skill" in resp.text
        assert "Endurance" in resp.text

    def test_roll_page_has_roll_again_button(self, client: TestClient, db: Session) -> None:
        """Roll page has a 'Roll Again' button with HTMX attributes."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "rolluser2")
        resp = client.get("/ui/characters/roll", cookies=_session_cookie(token))
        assert resp.status_code == 200
        assert "Roll Again" in resp.text
        assert "hx-post" in resp.text

    def test_roll_page_has_accept_button(self, client: TestClient, db: Session) -> None:
        """Roll page has an 'Accept' button that links to the create form."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "rolluser3")
        resp = client.get("/ui/characters/roll", cookies=_session_cookie(token))
        assert resp.status_code == 200
        assert "Accept" in resp.text
        assert "/ui/characters/create" in resp.text


class TestRollReroll:
    def test_post_roll_returns_htmx_fragment(self, client: TestClient, db: Session) -> None:
        """POST /ui/characters/roll returns the stats fragment partial."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "rerolluser1")
        resp = client.post(
            "/ui/characters/roll",
            cookies=_session_cookie(token),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "stats-display" in resp.text
        assert "Combat Skill" in resp.text
        assert "Endurance" in resp.text

    def test_post_roll_requires_auth(self, client: TestClient, db: Session) -> None:
        """Unauthenticated POST to /ui/characters/roll redirects to login."""
        resp = client.post("/ui/characters/roll", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Create form
# ---------------------------------------------------------------------------


class TestCreatePage:
    def test_create_page_requires_auth(self, client: TestClient, db: Session) -> None:
        """Unauthenticated request to /ui/characters/create redirects to login."""
        resp = client.get("/ui/characters/create", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_create_page_shows_discipline_checkboxes(
        self, client: TestClient, db: Session
    ) -> None:
        """Create page lists all Kai disciplines as checkboxes."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "createpageuser1")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        resp = client.get(
            "/ui/characters/create",
            params={"roll_token": roll_token, "book_id": book.id},
            cookies=_session_cookie(token),
        )
        assert resp.status_code == 200
        assert "Kai Disciplines" in resp.text
        # Check a few discipline names appear
        assert "Camouflage" in resp.text
        assert "Hunting" in resp.text
        assert "Weaponskill" in resp.text

    def test_create_page_has_name_input(self, client: TestClient, db: Session) -> None:
        """Create page has a character name input."""
        book, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "createpageuser2")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        resp = client.get(
            "/ui/characters/create",
            params={"roll_token": roll_token, "book_id": book.id},
            cookies=_session_cookie(token),
        )
        assert resp.status_code == 200
        assert 'name="name"' in resp.text


# ---------------------------------------------------------------------------
# Create submit
# ---------------------------------------------------------------------------


class TestCreateSubmit:
    def _post_create(
        self, client: TestClient, token: str, book_id: int, roll_token: str, disciplines: list, name: str = "Lone Wolf"
    ):
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        return client.post(
            "/ui/characters/create",
            data={
                "name": name,
                "book_id": str(book_id),
                "roll_token": roll_token,
                "discipline_ids": [str(d) for d in chosen],
            },
            cookies=_session_cookie(token),
            follow_redirects=False,
        )

    def test_valid_create_redirects_to_wizard(
        self, client: TestClient, db: Session
    ) -> None:
        """Creating a valid character redirects to the wizard page."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "createsubmit1")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        resp = self._post_create(client, token, book.id, roll_token, disciplines)
        assert resp.status_code == 303
        assert "/wizard" in resp.headers["location"]

    def test_create_requires_auth(self, client: TestClient, db: Session) -> None:
        """Unauthenticated POST to /ui/characters/create redirects to login."""
        resp = client.post(
            "/ui/characters/create",
            data={"name": "Test"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_too_few_disciplines_returns_400(self, client: TestClient, db: Session) -> None:
        """Submitting fewer than 5 disciplines returns a 400 with error message."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "createsubmit2")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:3]
        resp = client.post(
            "/ui/characters/create",
            data={
                "name": "Short",
                "book_id": str(book.id),
                "roll_token": roll_token,
                "discipline_ids": [str(d) for d in chosen],
            },
            cookies=_session_cookie(token),
        )
        assert resp.status_code == 400
        assert "5 disciplines" in resp.text

    def test_missing_name_returns_400(self, client: TestClient, db: Session) -> None:
        """Submitting without a name returns 400."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "createsubmit3")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        resp = client.post(
            "/ui/characters/create",
            data={
                "name": "",
                "book_id": str(book.id),
                "roll_token": roll_token,
                "discipline_ids": [str(d) for d in chosen],
            },
            cookies=_session_cookie(token),
        )
        assert resp.status_code == 400
        assert "name" in resp.text.lower()

    def test_invalid_roll_token_redirects_to_roll_page(
        self, client: TestClient, db: Session
    ) -> None:
        """An expired/invalid roll token redirects back to the roll page."""
        book, disciplines, _ = _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "createsubmit4")

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        resp = client.post(
            "/ui/characters/create",
            data={
                "name": "Lone Wolf",
                "book_id": str(book.id),
                "roll_token": "invalid.token.value",
                "discipline_ids": [str(d) for d in chosen],
            },
            cookies=_session_cookie(token),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/characters/roll" in resp.headers["location"]

    def test_created_character_appears_in_list(
        self, client: TestClient, db: Session
    ) -> None:
        """After creating a character, it appears on the character list page."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "createsubmit5")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        self._post_create(client, token, book.id, roll_token, disciplines, name="Epic Hero")
        # Now follow redirects to wizard, then navigate to list
        list_resp = client.get("/ui/characters", cookies=_session_cookie(token))
        assert list_resp.status_code == 200
        assert "Epic Hero" in list_resp.text


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------


class TestWizardGet:
    def test_wizard_requires_auth(self, client: TestClient, db: Session) -> None:
        """Unauthenticated request to wizard redirects to login."""
        resp = client.get("/ui/characters/999/wizard", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_wizard_unknown_character_redirects_to_list(
        self, client: TestClient, db: Session
    ) -> None:
        """Wizard for non-existent character redirects to character list."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "wizgetuser1")
        resp = client.get(
            "/ui/characters/99999/wizard",
            cookies=_session_cookie(token),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/characters" in resp.headers["location"]

    def test_equipment_step_renders(self, client: TestClient, db: Session) -> None:
        """Wizard equipment step renders the equipment selection form."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "wizgetuser2")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        # Create character via API to get into wizard
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        create_resp = client.post(
            "/characters",
            json={
                "name": "Wizard Test",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        char_id = create_resp.json()["id"]

        resp = client.get(
            f"/ui/characters/{char_id}/wizard",
            cookies=_session_cookie(token),
        )
        assert resp.status_code == 200
        assert "Equipment" in resp.text

    def test_equipment_step_shows_accept_button(self, client: TestClient, db: Session) -> None:
        """Equipment step has a submit button."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "wizgetuser3")
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        create_resp = client.post(
            "/characters",
            json={
                "name": "Equipment Test",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert create_resp.status_code == 201
        char_id = create_resp.json()["id"]

        resp = client.get(
            f"/ui/characters/{char_id}/wizard",
            cookies=_session_cookie(token),
        )
        assert resp.status_code == 200
        assert "<button" in resp.text
        assert 'type="submit"' in resp.text


class TestWizardPost:
    def _create_character_in_wizard(
        self, client: TestClient, db: Session, token: str, user_id: int, book, disciplines
    ) -> int:
        """Helper: create a character via API and return its ID."""
        roll_token = create_roll_token(user_id=user_id, cs=15, end=25, book_id=book.id)
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        resp = client.post(
            "/characters",
            json={
                "name": "Wizard Submit Test",
                "book_id": book.id,
                "roll_token": roll_token,
                "discipline_ids": chosen,
                "weapon_skill_type": None,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        return resp.json()["id"]

    def test_equipment_step_redirects_to_wizard(
        self, client: TestClient, db: Session
    ) -> None:
        """Submitting the equipment step redirects back to wizard (now confirm step)."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "wizpostuser1")
        char_id = self._create_character_in_wizard(client, db, token, user_id, book, disciplines)

        # Get character version
        detail_resp = client.get(
            f"/characters/{char_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        version = detail_resp.json()["version"]

        resp = client.post(
            f"/ui/characters/{char_id}/wizard",
            data={
                "step": "pick_equipment",
                "version": str(version),
                "selected_items": [],
            },
            cookies=_session_cookie(token),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert f"/ui/characters/{char_id}/wizard" in resp.headers["location"]

    def test_confirm_step_redirects_to_character_list(
        self, client: TestClient, db: Session
    ) -> None:
        """Submitting the confirm step redirects to character list after completion."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "wizpostuser2")
        char_id = self._create_character_in_wizard(client, db, token, user_id, book, disciplines)

        # Step 1: Submit equipment
        detail_resp = client.get(
            f"/characters/{char_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        version = detail_resp.json()["version"]
        client.post(
            f"/ui/characters/{char_id}/wizard",
            data={"step": "pick_equipment", "version": str(version)},
            cookies=_session_cookie(token),
            follow_redirects=False,
        )

        # Step 2: Submit confirm
        detail_resp2 = client.get(
            f"/characters/{char_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        version2 = detail_resp2.json()["version"]
        resp = client.post(
            f"/ui/characters/{char_id}/wizard",
            data={"step": "confirm", "version": str(version2)},
            cookies=_session_cookie(token),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/characters" in resp.headers["location"]

    def test_wizard_post_requires_auth(self, client: TestClient, db: Session) -> None:
        """Unauthenticated wizard POST redirects to login."""
        resp = client.post(
            "/ui/characters/999/wizard",
            data={"step": "confirm", "version": "1"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_wizard_unknown_character_redirects_to_list(
        self, client: TestClient, db: Session
    ) -> None:
        """Wizard POST for non-existent character redirects to list."""
        _seed_kai_data(db)
        token, _ = _register_and_login(client, db, "wizpostuser3")
        resp = client.post(
            "/ui/characters/99999/wizard",
            data={"step": "confirm", "version": "1"},
            cookies=_session_cookie(token),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/characters" in resp.headers["location"]

    def test_confirm_step_renders_after_equipment(
        self, client: TestClient, db: Session
    ) -> None:
        """After submitting equipment, wizard shows the confirm step."""
        book, disciplines, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, db, "wizpostuser4")
        char_id = self._create_character_in_wizard(client, db, token, user_id, book, disciplines)

        # Submit equipment
        detail_resp = client.get(
            f"/characters/{char_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        version = detail_resp.json()["version"]
        client.post(
            f"/ui/characters/{char_id}/wizard",
            data={"step": "pick_equipment", "version": str(version)},
            cookies=_session_cookie(token),
            follow_redirects=False,
        )

        # Now the confirm step should render
        resp = client.get(
            f"/ui/characters/{char_id}/wizard",
            cookies=_session_cookie(token),
        )
        assert resp.status_code == 200
        assert "Confirm" in resp.text
