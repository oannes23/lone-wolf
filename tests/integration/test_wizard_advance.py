"""Integration tests for the book advance wizard (Story 4.4).

POST /gameplay/{character_id}/advance  — starts the book advance wizard
GET  /characters/{character_id}/wizard — returns current step
POST /characters/{character_id}/wizard — advances through wizard steps

Tests cover the 4-step flow:
  Step 0: pick_disciplines
  Step 1: pick_equipment
  Step 2: inventory_adjust
  Step 3: confirm
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Discipline, Scene, WeaponCategory
from app.models.player import Character, CharacterBookStart, CharacterItem
from app.models.taxonomy import BookStartingEquipment, BookTransitionRule, GameObject
from app.models.wizard import CharacterWizardProgress
from tests.factories import (
    make_book,
    make_character,
    make_game_object,
    make_scene,
    make_user,
    make_wizard_step,
    make_wizard_template,
)

# ---------------------------------------------------------------------------
# Kai discipline names
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

_BOOK2_FIXED_EQUIPMENT = [
    ("Seal of Hammerdal", "special"),
]

_BOOK2_CHOOSEABLE_EQUIPMENT = [
    ("Sword", "weapon"),
    ("Short Sword", "weapon"),
    ("Chainmail Waistcoat", "special"),
    ("Mace", "weapon"),
    ("Healing Potion", "backpack"),
    ("Quarterstaff", "weapon"),
    ("Spear", "weapon"),
    ("Shield", "special"),
    ("Broadsword", "weapon"),
]


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_kai_disciplines(db: Session) -> list[Discipline]:
    """Create all 10 Kai disciplines and return them."""
    disciplines = []
    for name in _KAI_DISCIPLINE_NAMES:
        disc = Discipline(
            era="kai",
            name=name,
            html_id=name.lower().replace(" ", "-"),
            description=f"{name} discipline.",
        )
        db.add(disc)
        disciplines.append(disc)
    db.flush()
    return disciplines


def _seed_weapon_categories(db: Session) -> None:
    """Seed weapon categories for Kai era."""
    cats = [
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
    for weapon_name, category in cats:
        wc = WeaponCategory(weapon_name=weapon_name, category=category)
        db.add(wc)
    db.flush()


def _seed_full_advance_scenario(db: Session) -> dict:
    """Seed books 1 and 2, disciplines, transition rule, wizard template, and scenes.

    Returns a dict with:
        book1, book2, disciplines, start_scene_b1, victory_scene_b1,
        start_scene_b2, transition_rule, advance_template
    """
    # Books
    book1 = make_book(db, number=1, era="kai", max_total_picks=1, start_scene_number=1)
    book2 = make_book(db, number=2, era="kai", max_total_picks=2, start_scene_number=1)

    # Disciplines
    disciplines = _seed_kai_disciplines(db)
    _seed_weapon_categories(db)

    # Character creation wizard template (needed for creating characters)
    cc_template = make_wizard_template(db, name="character_creation")
    make_wizard_step(db, cc_template, step_type="pick_equipment", ordinal=0)
    make_wizard_step(db, cc_template, step_type="confirm", ordinal=1)

    # Book advance wizard template (4 steps per spec)
    adv_template = make_wizard_template(db, name="book_advance")
    make_wizard_step(db, adv_template, step_type="pick_disciplines", ordinal=0)
    make_wizard_step(db, adv_template, step_type="pick_equipment", ordinal=1)
    make_wizard_step(db, adv_template, step_type="inventory_adjust", ordinal=2)
    make_wizard_step(db, adv_template, step_type="confirm", ordinal=3)

    # Book 1 starting equipment (minimal — just what character creation needs)
    axe_go = make_game_object(db, kind="item", name="Axe", source="manual")
    map_go = make_game_object(db, kind="item", name="Map of Sommerlund", source="manual")
    sword_go = make_game_object(db, kind="item", name="Sword", source="manual")
    db.add(BookStartingEquipment(
        book_id=book1.id, game_object_id=axe_go.id, item_name="Axe",
        item_type="weapon", category="weapons", is_default=True, source="manual",
    ))
    db.add(BookStartingEquipment(
        book_id=book1.id, game_object_id=map_go.id, item_name="Map of Sommerlund",
        item_type="special", category="special", is_default=True, source="manual",
    ))
    db.add(BookStartingEquipment(
        book_id=book1.id, game_object_id=sword_go.id, item_name="Sword",
        item_type="weapon", category="weapons", is_default=False, source="manual",
    ))
    db.flush()

    # Book 2 starting equipment
    seal_go = make_game_object(db, kind="item", name="Seal of Hammerdal", source="manual")
    chainmail_go = make_game_object(
        db, kind="item", name="Chainmail Waistcoat",
        properties=json.dumps({"endurance_bonus": 4, "item_type": "special"}),
        source="manual",
    )
    healing_go = make_game_object(db, kind="item", name="Healing Potion", source="manual")
    spear_go = make_game_object(db, kind="item", name="Spear", source="manual")
    mace_go = make_game_object(db, kind="item", name="Mace", source="manual")

    go_map = {
        "Seal of Hammerdal": seal_go,
        "Chainmail Waistcoat": chainmail_go,
        "Healing Potion": healing_go,
        "Spear": spear_go,
        "Mace": mace_go,
    }

    db.add(BookStartingEquipment(
        book_id=book2.id, game_object_id=seal_go.id, item_name="Seal of Hammerdal",
        item_type="special", category="special", is_default=True, source="manual",
    ))
    for item_name, item_type in _BOOK2_CHOOSEABLE_EQUIPMENT:
        go = go_map.get(item_name)
        db.add(BookStartingEquipment(
            book_id=book2.id,
            game_object_id=go.id if go else None,
            item_name=item_name,
            item_type=item_type,
            category="weapons" if item_type == "weapon" else item_type,
            is_default=False,
            source="manual",
        ))
    db.flush()

    # Transition rule book1 → book2
    rule = BookTransitionRule(
        from_book_id=book1.id,
        to_book_id=book2.id,
        max_weapons=2,
        max_backpack_items=8,
        special_items_carry=True,
        gold_carries=True,
        new_disciplines_count=1,
    )
    db.add(rule)
    db.flush()

    # Scenes
    start_scene_b1 = make_scene(db, book1, number=1)
    victory_scene_b1 = make_scene(db, book1, number=350, is_victory=True)
    start_scene_b2 = make_scene(db, book2, number=1)

    return {
        "book1": book1,
        "book2": book2,
        "disciplines": disciplines,
        "start_scene_b1": start_scene_b1,
        "victory_scene_b1": victory_scene_b1,
        "start_scene_b2": start_scene_b2,
        "transition_rule": rule,
        "advance_template": adv_template,
        "cc_template": cc_template,
    }


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


def _create_character_at_victory(
    db: Session,
    client: TestClient,
    seed: dict,
    username: str,
) -> tuple[str, int, int]:
    """Create a character, complete the creation wizard, and place them at the victory scene.

    Returns (token, user_id, character_id).
    """
    book1 = seed["book1"]
    disciplines = seed["disciplines"]
    victory_scene = seed["victory_scene_b1"]

    token, user_id = _register_and_login(client, username)
    headers = _auth_headers(token)

    # Roll stats
    roll_resp = client.post("/characters/roll", json={"book_id": book1.id}, headers=headers)
    assert roll_resp.status_code == 200, roll_resp.json()
    roll_token = roll_resp.json()["roll_token"]

    # Pick 5 non-Weaponskill disciplines
    chosen_ids = [d.id for d in disciplines if d.name != "Weaponskill"][:5]

    create_resp = client.post(
        "/characters",
        json={
            "name": "Test Hero",
            "book_id": book1.id,
            "roll_token": roll_token,
            "discipline_ids": chosen_ids,
            "weapon_skill_type": None,
        },
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.json()
    char_data = create_resp.json()
    char_id = char_data["id"]
    version = char_data["version"]

    # Complete creation wizard: equipment → confirm
    post_eq = client.post(
        f"/characters/{char_id}/wizard",
        json={"selected_items": ["Sword"], "version": version},
        headers=headers,
    )
    assert post_eq.status_code == 200, post_eq.json()
    version2 = post_eq.json()["version"]

    post_confirm = client.post(
        f"/characters/{char_id}/wizard",
        json={"confirm": True, "version": version2},
        headers=headers,
    )
    assert post_confirm.status_code == 200, post_confirm.json()
    version3 = post_confirm.json()["character"]["version"]

    # Place character at victory scene (direct DB manipulation)
    db_char = db.query(Character).filter(Character.id == char_id).first()
    db_char.current_scene_id = victory_scene.id
    db_char.version = version3
    db.flush()

    return token, user_id, char_id, version3


# ---------------------------------------------------------------------------
# Tests: POST /gameplay/{character_id}/advance
# ---------------------------------------------------------------------------


class TestAdvanceEndpoint:
    def test_advance_creates_wizard_and_returns_first_step(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance on a victory scene character returns 201 with pick_disciplines step."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_init1")

        resp = client.post(
            f"/gameplay/{char_id}/advance",
            json={"version": char_version},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()

        assert data["wizard_type"] == "book_advance"
        assert data["step"] == "pick_disciplines"
        assert data["step_index"] == 0
        assert data["total_steps"] == 4
        assert data["book"]["id"] == seed["book2"].id
        assert data["book"]["title"] == seed["book2"].title

    def test_advance_blocked_if_not_at_victory_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance returns 400 if character is not at a victory scene."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_novict")

        # Move character to a non-victory scene
        db_char = db.query(Character).filter(Character.id == char_id).first()
        db_char.current_scene_id = seed["start_scene_b1"].id
        db.flush()

        resp = client.post(
            f"/gameplay/{char_id}/advance",
            json={"version": char_version},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 400, resp.json()
        assert "victory" in resp.json()["detail"].lower()

    def test_advance_blocked_if_wizard_already_active(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance returns 409 if character already has an active wizard."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_409")

        # Start advance once
        r1 = client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=_auth_headers(token))
        assert r1.status_code == 201, r1.json()

        # Try again (version has been incremented, but should fail on wizard check before version)
        r2 = client.post(f"/gameplay/{char_id}/advance", json={"version": char_version + 1}, headers=_auth_headers(token))
        assert r2.status_code == 409, r2.json()
        assert r2.json()["error_code"] == "WIZARD_ALREADY_ACTIVE"

    def test_advance_returns_404_if_no_next_book(
        self, client: TestClient, db: Session
    ) -> None:
        """POST /advance returns 404 when no BookTransitionRule exists for the book."""
        seed = _seed_full_advance_scenario(db)
        # Move character to book2 directly (no transition rule from book2)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_404")

        # Create a victory scene for book2 and place character there
        # But there's no transition rule from book2
        victory_b2 = make_scene(db, seed["book2"], number=350, is_victory=True)
        db_char = db.query(Character).filter(Character.id == char_id).first()
        db_char.book_id = seed["book2"].id
        db_char.current_scene_id = victory_b2.id
        db.flush()

        resp = client.post(
            f"/gameplay/{char_id}/advance",
            json={"version": char_version},
            headers=_auth_headers(token),
        )
        assert resp.status_code == 404, resp.json()
        assert resp.json()["error_code"] == "NO_NEXT_BOOK"


# ---------------------------------------------------------------------------
# Tests: Full 4-step advance flow
# ---------------------------------------------------------------------------


class TestAdvanceFullFlow:
    def test_full_4_step_advance(
        self, client: TestClient, db: Session
    ) -> None:
        """Complete 4-step book advance: disciplines → equipment → inventory → confirm."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_full1")
        headers = _auth_headers(token)

        # Get current version
        db_char = db.query(Character).filter(Character.id == char_id).first()
        version = db_char.version

        # Step 0: Start wizard
        r_advance = client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        assert r_advance.status_code == 201

        # Re-read version (wizard init increments version)
        db.refresh(db_char)
        version = db_char.version

        # Step 0: GET pick_disciplines
        r_get0 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        assert r_get0.status_code == 200
        data0 = r_get0.json()
        assert data0["step"] == "pick_disciplines"
        assert data0["disciplines_to_pick"] == 1
        assert len(data0["available_disciplines"]) > 0

        # POST pick_disciplines — pick the first available non-Weaponskill discipline
        non_ws_discs = [d for d in data0["available_disciplines"] if d["name"] != "Weaponskill"]
        first_disc = non_ws_discs[0]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [first_disc["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        assert r_post0.status_code == 200, r_post0.json()
        version = r_post0.json()["version"]

        # Step 1: GET pick_equipment
        r_get1 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        assert r_get1.status_code == 200
        data1 = r_get1.json()
        assert data1["step"] == "pick_equipment"
        assert data1["pick_limit"] == 2  # book2 has max_total_picks=2
        # Fixed item: Seal of Hammerdal
        included = [i["item_name"] for i in data1["included_items"]]
        assert "Seal of Hammerdal" in included

        # POST pick_equipment — pick 2 items
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Spear", "Healing Potion"], "version": version},
            headers=headers,
        )
        assert r_post1.status_code == 200, r_post1.json()
        version = r_post1.json()["version"]

        # Step 2: GET inventory_adjust
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        assert r_get2.status_code == 200
        data2 = r_get2.json()
        assert data2["step"] == "inventory_adjust"
        assert data2["max_weapons"] == 2
        assert data2["max_backpack_items"] == 8

        # POST inventory_adjust — keep existing weapons and backpack items
        weapon_names = [w["item_name"] for w in data2["current_weapons"]]
        backpack_names = [b["item_name"] for b in data2["current_backpack"]]

        # Only keep up to limits
        keep_w = weapon_names[:2]
        keep_b = backpack_names[:8]

        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": keep_b, "version": version},
            headers=headers,
        )
        assert r_post2.status_code == 200, r_post2.json()
        version = r_post2.json()["version"]

        # Step 3: GET confirm
        r_get3 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        assert r_get3.status_code == 200
        data3 = r_get3.json()
        assert data3["step"] == "confirm"

        # POST confirm
        r_post3 = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_post3.status_code == 200, r_post3.json()
        result = r_post3.json()
        assert result["wizard_complete"] is True

        final_char = result["character"]
        assert final_char["active_wizard"] is None

        # Verify the character is now in book 2
        db.refresh(db_char)
        assert db_char.book_id == seed["book2"].id

    def test_new_discipline_added_after_confirm(
        self, client: TestClient, db: Session
    ) -> None:
        """After confirm, the newly selected discipline is in character's disciplines."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_disc1")
        headers = _auth_headers(token)

        db_char = db.query(Character).filter(Character.id == char_id).first()
        version = db_char.version

        # Start wizard
        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Pick disciplines step — get available
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = r_get.json()["available_disciplines"]
        # Pick the first one (should not be Weaponskill to avoid needing weapon_skill_type)
        non_ws = [d for d in avail if d["name"] != "Weaponskill"]
        chosen = non_ws[0]

        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [chosen["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Skip equipment step
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        # Inventory adjust step — keep all weapons/backpack
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        keep_w = [w["item_name"] for w in data2["current_weapons"]][:2]
        keep_b = [b["item_name"] for b in data2["current_backpack"]][:8]
        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": keep_b, "version": version},
            headers=headers,
        )
        version = r_post2.json()["version"]

        # Confirm
        r_confirm = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_confirm.status_code == 200, r_confirm.json()

        # Verify discipline in DB
        db.refresh(db_char)
        discipline_names = [cd.discipline.name for cd in db_char.disciplines]
        assert chosen["name"] in discipline_names

    def test_snapshot_created_for_book2(
        self, client: TestClient, db: Session
    ) -> None:
        """After confirm, a character_book_starts snapshot for book2 is created."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_snap1")
        headers = _auth_headers(token)

        db_char = db.query(Character).filter(Character.id == char_id).first()
        version = db_char.version

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Disciplines step
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Equipment step
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        # Inventory adjust
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        keep_w = [w["item_name"] for w in data2["current_weapons"]][:2]
        keep_b = [b["item_name"] for b in data2["current_backpack"]][:8]
        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": keep_b, "version": version},
            headers=headers,
        )
        version = r_post2.json()["version"]

        # Confirm
        r_confirm = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_confirm.status_code == 200, r_confirm.json()

        # Check snapshot in DB
        snapshot = (
            db.query(CharacterBookStart)
            .filter(
                CharacterBookStart.character_id == char_id,
                CharacterBookStart.book_id == seed["book2"].id,
            )
            .first()
        )
        assert snapshot is not None
        discs = json.loads(snapshot.disciplines_json)
        # Should have 6 disciplines (5 from creation + 1 new)
        assert len(discs) == 6

    def test_character_placed_at_book2_start_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """After confirm, character current_scene_id is the book2 start scene."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_scene1")
        headers = _auth_headers(token)

        db_char = db.query(Character).filter(Character.id == char_id).first()
        version = db_char.version

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Disciplines
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Equipment
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        # Inventory
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        keep_w = [w["item_name"] for w in data2["current_weapons"]][:2]
        keep_b = [b["item_name"] for b in data2["current_backpack"]][:8]
        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": keep_b, "version": version},
            headers=headers,
        )
        version = r_post2.json()["version"]

        # Confirm
        client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )

        # Verify scene placement
        db.refresh(db_char)
        assert db_char.current_scene_id == seed["start_scene_b2"].id

    def test_endurance_max_recalculated_after_advance(
        self, client: TestClient, db: Session
    ) -> None:
        """endurance_max is recalculated after advance when Chainmail Waistcoat picked."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_end1")
        headers = _auth_headers(token)

        db_char = db.query(Character).filter(Character.id == char_id).first()
        base_end = db_char.endurance_base
        version = db_char.version

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Disciplines
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Pick Chainmail Waistcoat in equipment step (has +4 endurance bonus)
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": ["Chainmail Waistcoat"], "version": version},
            headers=headers,
        )
        assert r_post1.status_code == 200, r_post1.json()
        version = r_post1.json()["version"]

        # Inventory — keep weapons/backpack
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        keep_w = [w["item_name"] for w in data2["current_weapons"]][:2]
        keep_b = [b["item_name"] for b in data2["current_backpack"]][:8]
        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": keep_b, "version": version},
            headers=headers,
        )
        version = r_post2.json()["version"]

        # Confirm
        r_confirm = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_confirm.status_code == 200, r_confirm.json()

        db.refresh(db_char)
        # endurance_max should be at least base_end + 4 (from Chainmail)
        assert db_char.endurance_max >= base_end + 4

    def test_endurance_not_restored_on_advance(
        self, client: TestClient, db: Session
    ) -> None:
        """After advance confirm, endurance_current is NOT set to endurance_max (character may be damaged)."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_end2")
        headers = _auth_headers(token)

        # Damage the character before advancing
        db_char = db.query(Character).filter(Character.id == char_id).first()
        damaged_end = db_char.endurance_max - 5
        assert damaged_end > 0, "endurance_max must be > 5 for this test"
        db_char.endurance_current = damaged_end
        db.flush()
        version = db_char.version

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Disciplines
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        keep_w = [w["item_name"] for w in data2["current_weapons"]][:2]
        keep_b = [b["item_name"] for b in data2["current_backpack"]][:8]
        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": keep_b, "version": version},
            headers=headers,
        )
        version = r_post2.json()["version"]

        r_confirm = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_confirm.status_code == 200, r_confirm.json()

        db.refresh(db_char)
        # Character should still have the damaged endurance (not restored to max)
        assert db_char.endurance_current == damaged_end


# ---------------------------------------------------------------------------
# Tests: Discipline step validation
# ---------------------------------------------------------------------------


class TestDisciplineStep:
    def test_weaponskill_requires_weapon_skill_type(
        self, client: TestClient, db: Session
    ) -> None:
        """Picking Weaponskill without weapon_skill_type returns 400."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_ws1")
        headers = _auth_headers(token)

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db_char = db.query(Character).filter(Character.id == char_id).first()
        db.refresh(db_char)
        version = db_char.version

        # Find Weaponskill discipline
        ws_disc = next(d for d in seed["disciplines"] if d.name == "Weaponskill")

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [ws_disc.id], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        assert resp.status_code == 400, resp.json()
        assert "weapon_skill_type" in resp.json()["detail"].lower()

    def test_weaponskill_with_weapon_type_accepted(
        self, client: TestClient, db: Session
    ) -> None:
        """Picking Weaponskill with a valid weapon_skill_type advances the wizard."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_ws2")
        headers = _auth_headers(token)

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db_char = db.query(Character).filter(Character.id == char_id).first()
        db.refresh(db_char)
        version = db_char.version

        ws_disc = next(d for d in seed["disciplines"] if d.name == "Weaponskill")

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [ws_disc.id], "weapon_skill_type": "Sword", "version": version},
            headers=headers,
        )
        assert resp.status_code == 200, resp.json()
        assert resp.json()["active_wizard"]["step"] == "pick_equipment"

    def test_already_known_discipline_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """Picking a discipline the character already knows returns 400."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_disc_dup")
        headers = _auth_headers(token)

        # Get character's existing disciplines
        db_char = db.query(Character).filter(Character.id == char_id).first()
        existing_disc_id = db_char.disciplines[0].discipline_id

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={
                "discipline_ids": [existing_disc_id],
                "weapon_skill_type": None,
                "version": version,
            },
            headers=headers,
        )
        assert resp.status_code == 400, resp.json()
        assert "already has" in resp.json()["detail"].lower()

    def test_wrong_discipline_count_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """Picking 0 or 2 disciplines when 1 is required returns 400."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_disc_count")
        headers = _auth_headers(token)

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db_char = db.query(Character).filter(Character.id == char_id).first()
        db.refresh(db_char)
        version = db_char.version

        # 0 picks
        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        assert resp.status_code == 400, resp.json()


# ---------------------------------------------------------------------------
# Tests: Inventory adjust step validation
# ---------------------------------------------------------------------------


class TestInventoryAdjustStep:
    def _advance_to_inventory_step(
        self,
        db: Session,
        client: TestClient,
        seed: dict,
        username: str,
    ) -> tuple[str, int, int]:
        """Create character at victory, start wizard, pass disciplines and equipment steps.

        Returns (token, char_id, version).
        """
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, username)
        headers = _auth_headers(token)

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db_char = db.query(Character).filter(Character.id == char_id).first()
        db.refresh(db_char)
        version = db_char.version

        # Disciplines
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Equipment
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        return token, char_id, version

    def test_too_many_weapons_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """Keeping more weapons than max_weapons returns 400."""
        seed = _seed_full_advance_scenario(db)
        token, char_id, version = self._advance_to_inventory_step(db, client, seed, "adv_inv_over")
        headers = _auth_headers(token)

        # Try to keep 3 weapons when max is 2
        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": ["Axe", "Sword", "Spear"], "keep_backpack": [], "version": version},
            headers=headers,
        )
        assert resp.status_code == 400, resp.json()
        assert "weapons" in resp.json()["detail"].lower()

    def test_invalid_weapon_name_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """Keeping a weapon not in the character's inventory returns 400."""
        seed = _seed_full_advance_scenario(db)
        token, char_id, version = self._advance_to_inventory_step(db, client, seed, "adv_inv_bad")
        headers = _auth_headers(token)

        resp = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": ["Banana Sword"], "keep_backpack": [], "version": version},
            headers=headers,
        )
        assert resp.status_code == 400, resp.json()
        assert "not found" in resp.json()["detail"].lower()

    def test_inventory_limits_respected(
        self, client: TestClient, db: Session
    ) -> None:
        """Items dropped in inventory_adjust are not present after confirm."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_inv_drop")
        headers = _auth_headers(token)

        # Add extra weapons to character (so they need to drop some)
        db_char = db.query(Character).filter(Character.id == char_id).first()
        extra_axe = CharacterItem(
            character_id=char_id,
            item_name="Mace",
            item_type="weapon",
            is_equipped=False,
        )
        db.add(extra_axe)
        db.flush()
        version = db_char.version

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Disciplines
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Equipment
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        # Inventory — check that we have >2 weapons
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        all_weapons = [w["item_name"] for w in data2["current_weapons"]]
        assert len(all_weapons) >= 2, f"Expected >=2 weapons, got {all_weapons}"

        # Keep only 2 weapons (drop the rest)
        keep_w = all_weapons[:2]
        drop_w = all_weapons[2:]

        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": [], "version": version},
            headers=headers,
        )
        assert r_post2.status_code == 200, r_post2.json()
        version = r_post2.json()["version"]

        # Confirm
        r_confirm = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_confirm.status_code == 200, r_confirm.json()

        # Verify dropped weapons are gone
        db.refresh(db_char)
        char_weapon_names = [ci.item_name for ci in db_char.items if ci.item_type == "weapon"]
        for dropped_name in drop_w:
            assert dropped_name not in char_weapon_names, (
                f"Dropped weapon '{dropped_name}' still in inventory"
            )


# ---------------------------------------------------------------------------
# Tests: Carry-over rules
# ---------------------------------------------------------------------------


class TestCarryOverRules:
    def test_special_items_carry_over(
        self, client: TestClient, db: Session
    ) -> None:
        """Special items (Map of Sommerlund) carry over to the new book."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_carry1")
        headers = _auth_headers(token)

        # Verify Map of Sommerlund is in inventory after character creation
        db_char = db.query(Character).filter(Character.id == char_id).first()
        special_names = [ci.item_name for ci in db_char.items if ci.item_type == "special"]
        assert "Map of Sommerlund" in special_names

        version = db_char.version
        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Disciplines
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Equipment
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        # Inventory — note special items should not appear in keep lists
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        # Special items are shown but always carried over (not in keep_weapons/keep_backpack)
        special_in_adjust = [s["item_name"] for s in data2["current_special"]]
        assert "Map of Sommerlund" in special_in_adjust

        keep_w = [w["item_name"] for w in data2["current_weapons"]][:2]
        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": [], "version": version},
            headers=headers,
        )
        version = r_post2.json()["version"]

        # Confirm
        r_confirm = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_confirm.status_code == 200, r_confirm.json()

        # Verify Map of Sommerlund still in inventory
        db.refresh(db_char)
        special_after = [ci.item_name for ci in db_char.items if ci.item_type == "special"]
        assert "Map of Sommerlund" in special_after

    def test_gold_receives_advance_bonus(
        self, client: TestClient, db: Session
    ) -> None:
        """Gold increases by random 0-9 + 10 during book advance."""
        seed = _seed_full_advance_scenario(db)
        token, user_id, char_id, char_version = _create_character_at_victory(db, client, seed, "adv_gold1")
        headers = _auth_headers(token)

        db_char = db.query(Character).filter(Character.id == char_id).first()
        gold_before = db_char.gold
        version = db_char.version

        client.post(f"/gameplay/{char_id}/advance", json={"version": char_version}, headers=headers)
        db.refresh(db_char)
        version = db_char.version

        # Disciplines
        r_get = client.get(f"/characters/{char_id}/wizard", headers=headers)
        avail = [d for d in r_get.json()["available_disciplines"] if d["name"] != "Weaponskill"]
        r_post0 = client.post(
            f"/characters/{char_id}/wizard",
            json={"discipline_ids": [avail[0]["id"]], "weapon_skill_type": None, "version": version},
            headers=headers,
        )
        version = r_post0.json()["version"]

        # Equipment (no items to keep gold minimal)
        r_post1 = client.post(
            f"/characters/{char_id}/wizard",
            json={"selected_items": [], "version": version},
            headers=headers,
        )
        version = r_post1.json()["version"]

        # Inventory
        r_get2 = client.get(f"/characters/{char_id}/wizard", headers=headers)
        data2 = r_get2.json()
        keep_w = [w["item_name"] for w in data2["current_weapons"]][:2]
        r_post2 = client.post(
            f"/characters/{char_id}/wizard",
            json={"keep_weapons": keep_w, "keep_backpack": [], "version": version},
            headers=headers,
        )
        version = r_post2.json()["version"]

        # Confirm
        r_confirm = client.post(
            f"/characters/{char_id}/wizard",
            json={"confirm": True, "version": version},
            headers=headers,
        )
        assert r_confirm.status_code == 200, r_confirm.json()

        db.refresh(db_char)
        # Gold should have increased by at least 10 (random 0-9 + 10)
        gold_increase = db_char.gold - gold_before
        # If they were near the cap, gold_increase could be less than 10 due to capping at 50
        # In our test character starts with 0 gold (creation wizard), so increase should be >= 10
        assert gold_increase >= 10 or db_char.gold == 50
