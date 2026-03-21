"""Integration tests for the wizard endpoints (Stories 4.3 + 4.5).

GET /characters/{id}/wizard  — returns current step state
POST /characters/{id}/wizard — advances the wizard
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Discipline, Scene, WeaponCategory
from app.models.player import CharacterBookStart
from app.models.taxonomy import BookStartingEquipment, GameObject
from app.services.auth_service import create_roll_token
from tests.factories import (
    make_book,
    make_game_object,
    make_scene,
    make_wizard_step,
    make_wizard_template,
)

# ---------------------------------------------------------------------------
# Seed data constants
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

# Book 1 equipment from spec/seed-data.md
_BOOK1_FIXED_EQUIPMENT = [
    # (item_name, item_type)
    ("Axe", "weapon"),
    ("Map of Sommerlund", "special"),
]

_BOOK1_CHOOSEABLE_EQUIPMENT = [
    # (item_name, item_type)
    ("Broadsword", "weapon"),
    ("Sword", "weapon"),
    ("Helmet", "special"),
    ("Meal", "meal"),
    ("Chainmail Waistcoat", "special"),
    ("Mace", "weapon"),
    ("Healing Potion", "backpack"),
    ("Quarterstaff", "weapon"),
    ("Spear", "weapon"),
    ("Gold Crowns", "gold"),
]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_kai_data(db: Session):
    """Seed disciplines, weapon categories, wizard template, and Book 1 starting equipment.

    Also creates a start scene for the book.

    Returns:
        Tuple of (book, disciplines, template, start_scene).
    """
    book = make_book(db, number=1, era="kai", max_total_picks=1, start_scene_number=1)

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

    # Seed game objects for items with stat bonuses
    chainmail_go = make_game_object(
        db,
        kind="item",
        name="Chainmail Waistcoat",
        properties=json.dumps({"endurance_bonus": 4, "item_type": "special", "is_special": True}),
        source="manual",
    )
    helmet_go = make_game_object(
        db,
        kind="item",
        name="Helmet",
        properties=json.dumps({"endurance_bonus": 2, "item_type": "special", "is_special": True}),
        source="manual",
    )

    go_by_name = {
        "Chainmail Waistcoat": chainmail_go,
        "Helmet": helmet_go,
    }

    # Seed fixed equipment
    for item_name, item_type in _BOOK1_FIXED_EQUIPMENT:
        go = go_by_name.get(item_name)
        eq = BookStartingEquipment(
            book_id=book.id,
            game_object_id=go.id if go else None,
            item_name=item_name,
            item_type=item_type,
            category="weapons" if item_type == "weapon" else item_type,
            is_default=True,
            source="manual",
        )
        db.add(eq)

    # Seed chooseable equipment
    for item_name, item_type in _BOOK1_CHOOSEABLE_EQUIPMENT:
        go = go_by_name.get(item_name)
        category = "weapons" if item_type == "weapon" else item_type
        eq = BookStartingEquipment(
            book_id=book.id,
            game_object_id=go.id if go else None,
            item_name=item_name,
            item_type=item_type,
            category=category,
            is_default=False,
            source="manual",
        )
        db.add(eq)

    db.flush()

    # Create a start scene (scene number 1)
    start_scene = make_scene(db, book, number=1)

    return book, disciplines, template, start_scene


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
    assert reg.status_code == 201, reg.json()
    user_id = reg.json()["id"]
    resp = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    assert resp.status_code == 200, resp.json()
    return resp.json()["access_token"], user_id


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_character(
    client: TestClient,
    token: str,
    user_id: int,
    book_id: int,
    discipline_ids: list[int],
) -> dict:
    """Roll and create a character, returning the character JSON."""
    roll_resp = client.post(
        "/characters/roll",
        json={"book_id": book_id},
        headers=_auth_headers(token),
    )
    assert roll_resp.status_code == 200, roll_resp.json()
    roll_token = roll_resp.json()["roll_token"]

    create_resp = client.post(
        "/characters",
        json={
            "name": "Test Hero",
            "book_id": book_id,
            "roll_token": roll_token,
            "discipline_ids": discipline_ids,
            "weapon_skill_type": None,
        },
        headers=_auth_headers(token),
    )
    assert create_resp.status_code == 201, create_resp.json()
    return create_resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWizardGet:
    def test_get_equipment_step_returns_correct_shape(
        self, client: TestClient, db: Session
    ) -> None:
        """GET wizard on equipment step returns pick_equipment shape."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_get1")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]

        resp = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        assert resp.status_code == 200, resp.json()
        data = resp.json()

        assert data["wizard_type"] == "character_creation"
        assert data["step"] == "pick_equipment"
        assert data["step_index"] == 0
        assert data["total_steps"] == 2
        assert data["pick_limit"] == 1

        # Check included_items (fixed)
        included_names = [i["item_name"] for i in data["included_items"]]
        assert "Axe" in included_names
        assert "Map of Sommerlund" in included_names
        for item in data["included_items"]:
            assert item["note"] == "fixed"

        # Check auto_applied
        auto = data["auto_applied"]
        assert 0 <= auto["gold"] <= 9
        assert auto["meals"] == 1
        assert "0-9" in auto["gold_formula"]

        # Check available_equipment (chooseable, not gold/meal)
        avail_names = [i["item_name"] for i in data["available_equipment"]]
        assert "Sword" in avail_names
        assert "Broadsword" in avail_names
        assert "Chainmail Waistcoat" in avail_names
        # Gold Crowns and Meal should NOT appear in available_equipment
        assert "Gold Crowns" not in avail_names
        assert "Meal" not in avail_names

    def test_get_wizard_returns_404_when_no_active_wizard(
        self, client: TestClient, db: Session
    ) -> None:
        """GET wizard returns 404 when character has no active wizard."""
        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_get2")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]

        # Complete the wizard first
        # POST equipment step
        client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": char["version"]},
            headers=_auth_headers(token),
        )
        # GET to get updated version
        get_resp = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        assert get_resp.status_code == 200
        confirm_version = get_resp.json()["character_preview"]["version"]
        # POST confirm
        client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": confirm_version},
            headers=_auth_headers(token),
        )

        # Now there's no active wizard
        resp = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        assert resp.status_code == 404

    def test_gold_rolled_once_and_persisted(
        self, client: TestClient, db: Session
    ) -> None:
        """Repeated GET wizard calls return the same gold value."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_get3")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]

        resp1 = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        resp2 = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["auto_applied"]["gold"] == resp2.json()["auto_applied"]["gold"]

    def test_get_confirm_step_returns_character_preview(
        self, client: TestClient, db: Session
    ) -> None:
        """GET wizard at confirm step returns character_preview with applied selections."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_get4")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        # Advance to confirm step
        post_resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        assert post_resp.status_code == 200, post_resp.json()

        # GET confirm step
        resp = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        assert resp.status_code == 200, resp.json()
        data = resp.json()

        assert data["wizard_type"] == "character_creation"
        assert data["step"] == "confirm"
        assert data["step_index"] == 1
        assert data["total_steps"] == 2
        assert "character_preview" in data
        preview = data["character_preview"]
        # Gold and meals should reflect auto_applied values
        assert preview["gold"] >= 0
        assert preview["meals"] == 1


class TestWizardPostEquipmentStep:
    def test_valid_equipment_selection_advances_to_confirm(
        self, client: TestClient, db: Session
    ) -> None:
        """POST valid equipment advances wizard to confirm step."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_post1")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()
        data = resp.json()
        assert data["active_wizard"]["step"] == "confirm"
        assert data["active_wizard"]["step_index"] == 1
        # Version incremented
        assert data["version"] == version + 1

    def test_repick_replaces_previous_selection(
        self, client: TestClient, db: Session
    ) -> None:
        """Re-submitting equipment replaces previous selection.

        After posting equipment, the wizard advances to confirm. We reset
        step_index to 0 (simulating a go-back) and verify the second
        selection replaces the first in the final character.
        """
        from app.models.player import Character as CharModel
        from app.models.wizard import CharacterWizardProgress

        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_post2")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        # First pick: Sword
        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        assert resp1.status_code == 200
        version2 = resp1.json()["version"]

        # Reset wizard step to 0 to allow re-pick
        db_char = db.query(CharModel).filter(CharModel.id == char_id).first()
        progress = (
            db.query(CharacterWizardProgress)
            .filter(CharacterWizardProgress.id == db_char.active_wizard_id)
            .first()
        )
        progress.current_step_index = 0
        db.flush()

        # Re-pick: Broadsword instead of Sword
        resp2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Broadsword"], "version": version2},
            headers=_auth_headers(token),
        )
        assert resp2.status_code == 200
        version3 = resp2.json()["version"]

        # Confirm and verify Broadsword replaced Sword
        resp3 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version3},
            headers=_auth_headers(token),
        )
        assert resp3.status_code == 200

        db.refresh(db_char)
        item_names = [ci.item_name for ci in db_char.items]
        assert "Broadsword" in item_names
        assert "Sword" not in item_names

    def test_too_many_items_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """Selecting more items than pick_limit returns 400."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_post3")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        # Book 1 has pick_limit=1, try to pick 2
        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword", "Broadsword"], "version": version},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400, resp.json()
        assert "pick limit" in resp.json()["detail"].lower() or "too many" in resp.json()["detail"].lower()

    def test_invalid_item_name_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """Selecting an item not in available_equipment returns 400."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_post4")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Banana Sword"], "version": version},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400, resp.json()
        assert "valid equipment" in resp.json()["detail"].lower() or "not a valid" in resp.json()["detail"].lower()

    def test_version_required_returns_422(
        self, client: TestClient, db: Session
    ) -> None:
        """Missing version field in POST body returns 422."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_post5")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"]},  # no version
            headers=_auth_headers(token),
        )
        assert resp.status_code == 422, resp.json()

    def test_version_mismatch_returns_409(
        self, client: TestClient, db: Session
    ) -> None:
        """Wrong version in POST body returns 409."""
        book, disciplines, _, _ = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_post6")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": 9999},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 409, resp.json()


class TestWizardFullFlow:
    def test_full_wizard_flow_character_ready(
        self, client: TestClient, db: Session
    ) -> None:
        """Full flow: GET equipment → POST equipment → GET confirm → POST confirm → character ready."""
        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_full1")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        # Step 1: GET equipment step
        get1 = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        assert get1.status_code == 200
        assert get1.json()["step"] == "pick_equipment"

        # Step 2: POST equipment selection
        post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        assert post1.status_code == 200, post1.json()
        version2 = post1.json()["version"]

        # Step 3: GET confirm step
        get2 = client.get(f"/characters/{char_id}/wizard", headers=_auth_headers(token))
        assert get2.status_code == 200
        assert get2.json()["step"] == "confirm"
        preview = get2.json()["character_preview"]
        assert preview["meals"] == 1

        # Step 4: POST confirm
        post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version2},
            headers=_auth_headers(token),
        )
        assert post2.status_code == 200, post2.json()
        data = post2.json()
        assert data["wizard_complete"] is True
        assert data["message"] == "Character creation complete"

        final_char = data["character"]
        assert final_char["active_wizard"] is None
        assert final_char["gold"] >= 0  # auto-applied gold
        assert final_char["meals"] == 1

    def test_character_placed_at_start_scene_after_confirm(
        self, client: TestClient, db: Session
    ) -> None:
        """Character has current_scene_id set to start scene after wizard confirm."""
        from app.models.player import Character

        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_full2")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        # Equipment step
        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        assert resp1.status_code == 200
        version2 = resp1.json()["version"]

        # Confirm step
        resp2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version2},
            headers=_auth_headers(token),
        )
        assert resp2.status_code == 200

        # Verify in DB
        db_char = db.query(Character).filter(Character.id == char_id).first()
        assert db_char is not None
        assert db_char.current_scene_id == start_scene.id

    def test_active_wizard_id_cleared_after_confirm(
        self, client: TestClient, db: Session
    ) -> None:
        """active_wizard_id is None after wizard confirm."""
        from app.models.player import Character

        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_full3")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        # Pre-condition: active_wizard_id is set
        db_char_before = db.query(Character).filter(Character.id == char_id).first()
        assert db_char_before.active_wizard_id is not None

        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        version2 = resp1.json()["version"]

        resp2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version2},
            headers=_auth_headers(token),
        )
        assert resp2.status_code == 200

        db.expire(db_char_before)
        db.refresh(db_char_before)
        assert db_char_before.active_wizard_id is None

    def test_character_book_starts_snapshot_created_on_confirm(
        self, client: TestClient, db: Session
    ) -> None:
        """character_book_starts snapshot is created after wizard confirm."""
        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_full4")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        version2 = resp1.json()["version"]

        resp2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version2},
            headers=_auth_headers(token),
        )
        assert resp2.status_code == 200

        # Check DB for snapshot
        snapshot = (
            db.query(CharacterBookStart)
            .filter(
                CharacterBookStart.character_id == char_id,
                CharacterBookStart.book_id == book.id,
            )
            .first()
        )
        assert snapshot is not None
        # items_json should include Sword (selected) and Axe (fixed)
        items = json.loads(snapshot.items_json)
        item_names = [i["item_name"] for i in items]
        assert "Sword" in item_names
        assert "Axe" in item_names
        # disciplines_json should have 5 entries
        discs = json.loads(snapshot.disciplines_json)
        assert len(discs) == 5


class TestWizardStatRecalculation:
    def test_chainmail_waistcoat_increases_endurance_max(
        self, client: TestClient, db: Session
    ) -> None:
        """Picking Chainmail Waistcoat (+4 endurance_max) recalculates endurance."""
        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_stat1")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]
        base_end = char["endurance_base"]

        # Pick Chainmail Waistcoat
        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Chainmail Waistcoat"], "version": version},
            headers=_auth_headers(token),
        )
        assert resp1.status_code == 200, resp1.json()
        version2 = resp1.json()["version"]

        # Confirm
        resp2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version2},
            headers=_auth_headers(token),
        )
        assert resp2.status_code == 200, resp2.json()

        final = resp2.json()["character"]
        # endurance_max should be base + 4 (Chainmail) + (Axe fixed, no bonus)
        # Note: Axe is a fixed weapon with no endurance bonus
        expected_end_max = base_end + 4
        assert final["endurance_max"] == expected_end_max

    def test_confirm_step_preview_shows_chainmail_bonus(
        self, client: TestClient, db: Session
    ) -> None:
        """GET confirm step preview shows correct endurance_max with Chainmail Waistcoat."""
        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_stat2")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]
        base_end = char["endurance_base"]

        # Pick Chainmail Waistcoat
        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Chainmail Waistcoat"], "version": version},
            headers=_auth_headers(token),
        )
        assert resp1.status_code == 200

        get_confirm = client.get(
            f"/characters/{char_id}/wizard", headers=_auth_headers(token)
        )
        assert get_confirm.status_code == 200
        preview = get_confirm.json()["character_preview"]
        # Preview should show base + 4
        assert preview["endurance_max"] == base_end + 4


class TestWizardEdgeCases:
    def test_pick_zero_items_is_valid(
        self, client: TestClient, db: Session
    ) -> None:
        """Picking 0 items (within pick_limit=1) is valid."""
        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_edge1")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["active_wizard"]["step"] == "confirm"

    def test_fixed_items_in_character_after_confirm(
        self, client: TestClient, db: Session
    ) -> None:
        """Fixed items (Axe, Map of Sommerlund) are present in character after confirm."""
        from app.models.player import Character, CharacterItem

        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_edge2")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        version2 = resp1.json()["version"]

        resp2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version2},
            headers=_auth_headers(token),
        )
        assert resp2.status_code == 200

        # Check items in DB
        items = db.query(CharacterItem).filter(CharacterItem.character_id == char_id).all()
        item_names = [i.item_name for i in items]
        assert "Axe" in item_names
        assert "Map of Sommerlund" in item_names
        assert "Sword" in item_names

    def test_first_weapon_auto_equipped(
        self, client: TestClient, db: Session
    ) -> None:
        """After confirm, the first weapon (Axe from fixed) is equipped."""
        from app.models.player import Character, CharacterItem

        book, disciplines, _, start_scene = _seed_kai_data(db)
        token, user_id = _register_and_login(client, "wiz_edge3")
        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char = _create_character(client, token, user_id, book.id, chosen)
        char_id = char["id"]
        version = char["version"]

        resp1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Sword"], "version": version},
            headers=_auth_headers(token),
        )
        version2 = resp1.json()["version"]

        resp2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version2},
            headers=_auth_headers(token),
        )
        assert resp2.status_code == 200

        # Exactly one weapon should be equipped
        items = db.query(CharacterItem).filter(CharacterItem.character_id == char_id).all()
        equipped_weapons = [i for i in items if i.item_type == "weapon" and i.is_equipped]
        assert len(equipped_weapons) == 1

    def test_unauthenticated_get_wizard_returns_401(
        self, client: TestClient, db: Session
    ) -> None:
        """GET wizard without auth returns 401."""
        resp = client.get("/characters/999/wizard")
        assert resp.status_code == 401

    def test_unauthenticated_post_wizard_returns_401(
        self, client: TestClient, db: Session
    ) -> None:
        """POST wizard without auth returns 401."""
        resp = client.post(
            "/characters/999/wizard",
            json={"selected_items": ["Sword"], "version": 1},
        )
        assert resp.status_code == 401

    def test_wrong_character_owner_returns_403(
        self, client: TestClient, db: Session
    ) -> None:
        """GET wizard for another user's character returns 403."""
        book, disciplines, _, _ = _seed_kai_data(db)

        token_a, user_a_id = _register_and_login(client, "wiz_owner1a")
        token_b, user_b_id = _register_and_login(client, "wiz_owner1b")

        chosen = [d.id for d in disciplines if d.name != "Weaponskill"][:5]
        char_a = _create_character(client, token_a, user_a_id, book.id, chosen)
        char_a_id = char_a["id"]

        resp = client.get(
            f"/characters/{char_a_id}/wizard", headers=_auth_headers(token_b)
        )
        assert resp.status_code == 403
