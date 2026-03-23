"""Integration tests for UI item and inventory routes (Story 8.5).

Covers:
- POST /ui/game/{character_id}/item/accept  — accept a pending scene item
- POST /ui/game/{character_id}/item/decline — decline a pending scene item
- POST /ui/game/{character_id}/item/drop    — drop an inventory item
- POST /ui/game/{character_id}/item/equip   — equip a weapon
- POST /ui/game/{character_id}/item/unequip — unequip a weapon
- POST /ui/game/{character_id}/item/use     — use a consumable item
- Template rendering: pending items panel, mandatory items, inventory drawer
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import SceneItem
from app.models.player import CharacterItem
from tests.factories import (
    make_book,
    make_character,
    make_game_object,
    make_scene,
    make_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_user(
    client: TestClient,
    username: str,
    password: str = "Pass1234!",
) -> None:
    """Register a user via the JSON API."""
    resp = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": password},
    )
    assert resp.status_code == 201, resp.text


def _login_cookie(
    client: TestClient,
    username: str,
    password: str = "Pass1234!",
) -> str:
    """Log in via the UI and return the session cookie value."""
    resp = client.post(
        "/ui/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"Expected 303, got {resp.status_code}: {resp.text}"
    cookie = resp.cookies.get("session")
    assert cookie, "Expected session cookie"
    return cookie


def _get_user_by_username(db: Session, username: str):
    from app.models.player import User
    return db.query(User).filter(User.username == username).first()


def _make_scene_item(
    db: Session,
    scene_id: int,
    *,
    item_name: str = "Sword",
    item_type: str = "weapon",
    is_mandatory: bool = False,
    game_object_id: int | None = None,
    phase_ordinal: int = 1,
) -> SceneItem:
    """Create a scene_items gain row for accept/decline tests."""
    si = SceneItem(
        scene_id=scene_id,
        game_object_id=game_object_id,
        item_name=item_name,
        item_type=item_type,
        quantity=1,
        action="gain",
        is_mandatory=is_mandatory,
        phase_ordinal=phase_ordinal,
        source="manual",
    )
    db.add(si)
    db.flush()
    return si


def _make_character_item(
    db: Session,
    character_id: int,
    *,
    item_name: str = "Dagger",
    item_type: str = "weapon",
    is_equipped: bool = False,
    game_object_id: int | None = None,
) -> CharacterItem:
    """Add an item directly to a character's inventory."""
    ci = CharacterItem(
        character_id=character_id,
        game_object_id=game_object_id,
        item_name=item_name,
        item_type=item_type,
        is_equipped=is_equipped,
    )
    db.add(ci)
    db.flush()
    return ci


def _setup_items_phase_character(
    db: Session,
    client: TestClient,
    username: str,
) -> tuple:
    """Set up a user, book, scene in items phase, and character.

    Returns:
        (cookie, character, scene, user)
    """
    book = make_book(db, start_scene_number=1)
    scene = make_scene(db, book, number=1, narrative="<p>You find an item.</p>")

    _register_user(client, username)
    user = _get_user_by_username(db, username)
    assert user is not None

    character = make_character(
        db,
        user,
        book,
        current_scene_id=scene.id,
        scene_phase="items",
        scene_phase_index=0,
        version=1,
    )
    cookie = _login_cookie(client, username)
    return cookie, character, scene, user


# ---------------------------------------------------------------------------
# Tests: pending items panel template rendering
# ---------------------------------------------------------------------------


class TestPendingItemsDisplay:
    def test_pending_items_panel_renders(
        self, client: TestClient, db: Session
    ) -> None:
        """Scene page renders the pending items panel when items are pending."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "items_display_player"
        )
        _make_scene_item(db, scene.id, item_name="Short Sword", item_type="weapon")

        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "Short Sword" in body
        assert "items-section" in body
        # Accept button present
        assert "Accept" in body

    def test_mandatory_item_has_no_decline_button(
        self, client: TestClient, db: Session
    ) -> None:
        """Mandatory items render with accept only — no decline button."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "mandatory_item_player"
        )
        _make_scene_item(
            db, scene.id, item_name="Special Map", item_type="special", is_mandatory=True
        )

        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "Special Map" in body
        # Required badge should appear
        assert "Required" in body
        # Accept present
        assert "Accept" in body
        # Decline should NOT appear for mandatory item
        assert "Decline" not in body

    def test_optional_item_has_both_accept_and_decline(
        self, client: TestClient, db: Session
    ) -> None:
        """Optional items render with both accept and decline buttons."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "optional_item_player"
        )
        _make_scene_item(
            db, scene.id, item_name="Dagger", item_type="weapon", is_mandatory=False
        )

        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "Dagger" in body
        assert "Accept" in body
        assert "Decline" in body

    def test_inventory_drawer_renders(
        self, client: TestClient, db: Session
    ) -> None:
        """Inventory drawer section is present on the scene page."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "inv_drawer_player")
        user = _get_user_by_username(db, "inv_drawer_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        _make_character_item(db, character.id, item_name="Sword", item_type="weapon")

        cookie = _login_cookie(client, "inv_drawer_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "inventory-drawer" in body
        assert "Sword" in body

    def test_inventory_drawer_shows_slot_counters(
        self, client: TestClient, db: Session
    ) -> None:
        """Inventory drawer shows weapon and backpack slot counters."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "slot_counter_player")
        user = _get_user_by_username(db, "slot_counter_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        _make_character_item(db, character.id, item_name="Sword", item_type="weapon")
        _make_character_item(db, character.id, item_name="Bread", item_type="backpack")

        cookie = _login_cookie(client, "slot_counter_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        # Weapon slots (1/2)
        assert "1/2" in body
        # Backpack slots (1/8)
        assert "1/8" in body

    def test_equipped_item_shows_equipped_badge(
        self, client: TestClient, db: Session
    ) -> None:
        """Equipped weapons show the Equipped badge in the inventory drawer."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "equipped_badge_player")
        user = _get_user_by_username(db, "equipped_badge_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        _make_character_item(
            db, character.id, item_name="Broadsword", item_type="weapon", is_equipped=True
        )

        cookie = _login_cookie(client, "equipped_badge_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "Equipped" in body
        assert "inventory-item-equipped" in body


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/item/accept
# ---------------------------------------------------------------------------


class TestItemAccept:
    def test_accept_item_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Accepting a pending item redirects back to the scene page."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "accept_item_player"
        )
        si = _make_scene_item(db, scene.id, item_name="Sword", item_type="weapon")

        resp = client.post(
            f"/ui/game/{character.id}/item/accept",
            data={"scene_item_id": si.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_accept_item_adds_to_inventory(
        self, client: TestClient, db: Session
    ) -> None:
        """Accepting a pending item adds it to the character's inventory."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "accept_adds_inventory"
        )
        si = _make_scene_item(db, scene.id, item_name="Broadsword", item_type="weapon")

        client.post(
            f"/ui/game/{character.id}/item/accept",
            data={"scene_item_id": si.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        db.expire_all()
        items = db.query(CharacterItem).filter(
            CharacterItem.character_id == character.id
        ).all()
        assert any(i.item_name == "Broadsword" for i in items)

    def test_accept_unauthenticated_redirects_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated accept request redirects to login."""
        resp = client.post(
            "/ui/game/1/item/accept",
            data={"scene_item_id": 1, "version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_accept_version_mismatch_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Version mismatch silently redirects back without crashing."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "accept_version_mismatch"
        )
        si = _make_scene_item(db, scene.id, item_name="Sword", item_type="weapon")

        resp = client.post(
            f"/ui/game/{character.id}/item/accept",
            data={"scene_item_id": si.id, "version": 999},  # wrong version
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/item/decline
# ---------------------------------------------------------------------------


class TestItemDecline:
    def test_decline_item_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Declining an optional item redirects back to the scene page."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "decline_item_player"
        )
        si = _make_scene_item(
            db, scene.id, item_name="Shield", item_type="backpack", is_mandatory=False
        )

        resp = client.post(
            f"/ui/game/{character.id}/item/decline",
            data={"scene_item_id": si.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_decline_does_not_add_to_inventory(
        self, client: TestClient, db: Session
    ) -> None:
        """Declining an item does not add it to the character's inventory."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "decline_no_inventory"
        )
        si = _make_scene_item(
            db, scene.id, item_name="Rope", item_type="backpack", is_mandatory=False
        )

        client.post(
            f"/ui/game/{character.id}/item/decline",
            data={"scene_item_id": si.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        db.expire_all()
        items = db.query(CharacterItem).filter(
            CharacterItem.character_id == character.id
        ).all()
        assert not any(i.item_name == "Rope" for i in items)

    def test_decline_mandatory_item_redirects_back_silently(
        self, client: TestClient, db: Session
    ) -> None:
        """Declining a mandatory item redirects back without error — no item added."""
        cookie, character, scene, user = _setup_items_phase_character(
            db, client, "decline_mandatory_player"
        )
        si = _make_scene_item(
            db, scene.id, item_name="Required Map", item_type="special", is_mandatory=True
        )

        resp = client.post(
            f"/ui/game/{character.id}/item/decline",
            data={"scene_item_id": si.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        # Silently redirects back — no 400 or 500
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_decline_unauthenticated_redirects_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated decline request redirects to login."""
        resp = client.post(
            "/ui/game/1/item/decline",
            data={"scene_item_id": 1, "version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/item/drop
# ---------------------------------------------------------------------------


class TestItemDrop:
    def test_drop_item_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Dropping an inventory item redirects back to the scene page."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "drop_item_player")
        user = _get_user_by_username(db, "drop_item_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        ci = _make_character_item(db, character.id, item_name="Sword", item_type="weapon")
        cookie = _login_cookie(client, "drop_item_player")

        resp = client.post(
            f"/ui/game/{character.id}/item/drop",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_drop_item_removes_from_inventory(
        self, client: TestClient, db: Session
    ) -> None:
        """Dropping an item removes it from the character's inventory."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "drop_removes_player")
        user = _get_user_by_username(db, "drop_removes_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        ci = _make_character_item(db, character.id, item_name="Torch", item_type="backpack")
        cookie = _login_cookie(client, "drop_removes_player")

        client.post(
            f"/ui/game/{character.id}/item/drop",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        db.expire_all()
        remaining = db.query(CharacterItem).filter(
            CharacterItem.character_id == character.id,
            CharacterItem.id == ci.id,
        ).first()
        assert remaining is None

    def test_drop_unauthenticated_redirects_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated drop request redirects to login."""
        resp = client.post(
            "/ui/game/1/item/drop",
            data={"character_item_id": 1, "version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/item/equip and /unequip
# ---------------------------------------------------------------------------


class TestItemEquipUnequip:
    def test_equip_weapon_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Equipping a weapon redirects back to the scene page."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "equip_player")
        user = _get_user_by_username(db, "equip_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        ci = _make_character_item(
            db, character.id, item_name="Sword", item_type="weapon", is_equipped=False
        )
        cookie = _login_cookie(client, "equip_player")

        resp = client.post(
            f"/ui/game/{character.id}/item/equip",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_equip_sets_is_equipped(
        self, client: TestClient, db: Session
    ) -> None:
        """Equipping a weapon sets is_equipped to True."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "equip_sets_player")
        user = _get_user_by_username(db, "equip_sets_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        ci = _make_character_item(
            db, character.id, item_name="Axe", item_type="weapon", is_equipped=False
        )
        cookie = _login_cookie(client, "equip_sets_player")

        client.post(
            f"/ui/game/{character.id}/item/equip",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        db.expire_all()
        updated = db.query(CharacterItem).filter(CharacterItem.id == ci.id).first()
        assert updated is not None
        assert updated.is_equipped is True

    def test_unequip_weapon_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Unequipping a weapon redirects back to the scene page."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "unequip_player")
        user = _get_user_by_username(db, "unequip_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        ci = _make_character_item(
            db, character.id, item_name="Sword", item_type="weapon", is_equipped=True
        )
        cookie = _login_cookie(client, "unequip_player")

        resp = client.post(
            f"/ui/game/{character.id}/item/unequip",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_unequip_clears_is_equipped(
        self, client: TestClient, db: Session
    ) -> None:
        """Unequipping a weapon sets is_equipped to False."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "unequip_clears_player")
        user = _get_user_by_username(db, "unequip_clears_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        ci = _make_character_item(
            db, character.id, item_name="Mace", item_type="weapon", is_equipped=True
        )
        cookie = _login_cookie(client, "unequip_clears_player")

        client.post(
            f"/ui/game/{character.id}/item/unequip",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        db.expire_all()
        updated = db.query(CharacterItem).filter(CharacterItem.id == ci.id).first()
        assert updated is not None
        assert updated.is_equipped is False

    def test_equip_unauthenticated_redirects_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated equip request redirects to login."""
        resp = client.post(
            "/ui/game/1/item/equip",
            data={"character_item_id": 1, "version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_unequip_unauthenticated_redirects_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated unequip request redirects to login."""
        resp = client.post(
            "/ui/game/1/item/unequip",
            data={"character_item_id": 1, "version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/item/use
# ---------------------------------------------------------------------------


class TestItemUse:
    def test_use_consumable_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Using a consumable item redirects back to the scene page."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        # Create a game_object with consumable property
        go = make_game_object(
            db,
            name="Healing Potion",
            kind="item",
            properties=json.dumps({"consumable": True, "effect": {"endurance_restore": 4}}),
        )

        _register_user(client, "use_item_player")
        user = _get_user_by_username(db, "use_item_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            endurance_current=15,
            endurance_max=25,
            version=1,
        )
        ci = _make_character_item(
            db,
            character.id,
            item_name="Healing Potion",
            item_type="backpack",
            game_object_id=go.id,
        )
        cookie = _login_cookie(client, "use_item_player")

        resp = client.post(
            f"/ui/game/{character.id}/item/use",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_use_consumable_removes_item(
        self, client: TestClient, db: Session
    ) -> None:
        """Using a consumable removes it from the character's inventory."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        go = make_game_object(
            db,
            name="Laumspur Potion",
            kind="item",
            properties=json.dumps({"consumable": True, "effect": {"endurance_restore": 4}}),
        )

        _register_user(client, "use_removes_player")
        user = _get_user_by_username(db, "use_removes_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            endurance_current=15,
            endurance_max=25,
            version=1,
        )
        ci = _make_character_item(
            db,
            character.id,
            item_name="Laumspur Potion",
            item_type="backpack",
            game_object_id=go.id,
        )
        cookie = _login_cookie(client, "use_removes_player")

        client.post(
            f"/ui/game/{character.id}/item/use",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        db.expire_all()
        remaining = db.query(CharacterItem).filter(CharacterItem.id == ci.id).first()
        assert remaining is None

    def test_use_non_consumable_redirects_back_silently(
        self, client: TestClient, db: Session
    ) -> None:
        """Using a non-consumable item redirects back without error."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        go = make_game_object(
            db,
            name="Crystal Star",
            kind="item",
            properties=json.dumps({"consumable": False}),
        )

        _register_user(client, "use_nonconsumable_player")
        user = _get_user_by_username(db, "use_nonconsumable_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        ci = _make_character_item(
            db,
            character.id,
            item_name="Crystal Star",
            item_type="special",
            game_object_id=go.id,
        )
        cookie = _login_cookie(client, "use_nonconsumable_player")

        resp = client.post(
            f"/ui/game/{character.id}/item/use",
            data={"character_item_id": ci.id, "version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_use_item_unauthenticated_redirects_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated use item request redirects to login."""
        resp = client.post(
            "/ui/game/1/item/use",
            data={"character_item_id": 1, "version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_use_item_version_mismatch_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Version mismatch on use item redirects back silently."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        go = make_game_object(
            db,
            name="Potion X",
            kind="item",
            properties=json.dumps({"consumable": True, "effect": {"endurance_restore": 2}}),
        )

        _register_user(client, "use_version_mismatch_player")
        user = _get_user_by_username(db, "use_version_mismatch_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=3,
        )
        ci = _make_character_item(
            db, character.id, item_name="Potion X", item_type="backpack", game_object_id=go.id
        )
        cookie = _login_cookie(client, "use_version_mismatch_player")

        resp = client.post(
            f"/ui/game/{character.id}/item/use",
            data={"character_item_id": ci.id, "version": 1},  # wrong version
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"
