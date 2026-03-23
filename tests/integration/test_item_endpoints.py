"""Integration tests for item and inventory endpoints (Story 6.4).

POST /gameplay/{character_id}/item       — accept/decline scene items
POST /gameplay/{character_id}/inventory  — drop / equip / unequip
POST /gameplay/{character_id}/use-item   — consume a consumable item
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
from tests.helpers.auth import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_scene_item(
    db: Session,
    scene_id: int,
    *,
    item_name: str = "Sword",
    item_type: str = "weapon",
    is_mandatory: bool = False,
    game_object_id: int | None = None,
    phase_ordinal: int = 1,
) -> SceneItem:
    """Create a scene_items row for acceptance/decline tests."""
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


def _seed_character_item(
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


def _setup_base(db: Session, client: TestClient) -> tuple:
    """Create user, book, scene, character with an items-phase scene, and auth headers.

    Returns:
        (headers, character_id, scene)
    """
    tokens = register_and_login(client, username="itemtester", password="password123")
    headers = auth_headers(tokens["access_token"])

    book = make_book(db, number=1, era="kai")
    scene = make_scene(db, book)

    # Get the user id from the DB
    from app.models.player import User
    user = db.query(User).filter(User.username == "itemtester").first()

    character = make_character(
        db,
        user,
        book,
        current_scene_id=scene.id,
        scene_phase="items",
        scene_phase_index=0,
    )

    return headers, character.id, scene


# ---------------------------------------------------------------------------
# POST /gameplay/{id}/item — accept
# ---------------------------------------------------------------------------


def test_accept_item_adds_to_inventory(client: TestClient, db: Session) -> None:
    """Accepting a scene item creates a CharacterItem row and returns inventory."""
    headers, char_id, scene = _setup_base(db, client)
    go = make_game_object(db, kind="item", name="Short Sword", properties="{}")
    si = _seed_scene_item(db, scene.id, item_name="Short Sword", item_type="weapon", game_object_id=go.id)

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["action"] == "accept"
    assert data["item_name"] == "Short Sword"
    assert data["item_type"] == "weapon"
    assert data["character_item_id"] is not None
    assert data["version"] == 2

    # Verify the item is in the inventory list
    names = [i["item_name"] for i in data["inventory"]]
    assert "Short Sword" in names


def test_accept_item_increments_version(client: TestClient, db: Session) -> None:
    """Accepting an item increments the character version."""
    headers, char_id, scene = _setup_base(db, client)
    si = _seed_scene_item(db, scene.id, item_name="Axe", item_type="weapon")

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2


# ---------------------------------------------------------------------------
# POST /gameplay/{id}/item — decline
# ---------------------------------------------------------------------------


def test_decline_item_removes_from_pending(client: TestClient, db: Session) -> None:
    """Declining a non-mandatory item decrements pending_items_remaining."""
    headers, char_id, scene = _setup_base(db, client)
    si = _seed_scene_item(db, scene.id, item_name="Mace", item_type="weapon", is_mandatory=False)

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "decline", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["action"] == "decline"
    assert data["pending_items_remaining"] == 0
    assert data["phase_complete"] is True


def test_decline_mandatory_item_returns_400(client: TestClient, db: Session) -> None:
    """Declining a mandatory item returns 400 ITEM_MANDATORY."""
    headers, char_id, scene = _setup_base(db, client)
    si = _seed_scene_item(db, scene.id, item_name="Seal of Hammerdal", item_type="special", is_mandatory=True)

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "decline", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "ITEM_MANDATORY"


# ---------------------------------------------------------------------------
# POST /gameplay/{id}/item — slot limits
# ---------------------------------------------------------------------------


def test_accept_when_weapons_full_returns_400(client: TestClient, db: Session) -> None:
    """Accepting a weapon when 2 are already carried returns 400 INVENTORY_FULL."""
    headers, char_id, scene = _setup_base(db, client)

    # Pre-fill two weapons in inventory
    _seed_character_item(db, char_id, item_name="Sword", item_type="weapon")
    _seed_character_item(db, char_id, item_name="Dagger", item_type="weapon")

    si = _seed_scene_item(db, scene.id, item_name="Broadsword", item_type="weapon", is_mandatory=False)

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVENTORY_FULL"


def test_accept_mandatory_item_when_full_succeeds(client: TestClient, db: Session) -> None:
    """Mandatory items bypass slot limits and are always accepted."""
    headers, char_id, scene = _setup_base(db, client)

    # Pre-fill two weapons in inventory
    _seed_character_item(db, char_id, item_name="Sword", item_type="weapon")
    _seed_character_item(db, char_id, item_name="Dagger", item_type="weapon")

    si = _seed_scene_item(
        db, scene.id,
        item_name="Sommerswerd",
        item_type="weapon",
        is_mandatory=True,
    )

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["action"] == "accept"


def test_accept_when_backpack_full_returns_400(client: TestClient, db: Session) -> None:
    """Accepting a backpack item when 8 are already carried returns 400 INVENTORY_FULL."""
    headers, char_id, scene = _setup_base(db, client)

    for i in range(8):
        _seed_character_item(db, char_id, item_name=f"Potion {i}", item_type="backpack")

    si = _seed_scene_item(db, scene.id, item_name="Food", item_type="backpack", is_mandatory=False)

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVENTORY_FULL"


# ---------------------------------------------------------------------------
# Phase completion
# ---------------------------------------------------------------------------


def test_phase_complete_when_all_items_resolved(client: TestClient, db: Session) -> None:
    """phase_complete is True once the last pending item is resolved."""
    headers, char_id, scene = _setup_base(db, client)

    # Only one pending item
    si = _seed_scene_item(db, scene.id, item_name="Map", item_type="backpack")

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["phase_complete"] is True
    assert data["pending_items_remaining"] == 0


def test_phase_not_complete_with_multiple_pending_items(client: TestClient, db: Session) -> None:
    """phase_complete is False when more than one item remains pending."""
    headers, char_id, scene = _setup_base(db, client)

    si1 = _seed_scene_item(db, scene.id, item_name="Sword", item_type="weapon", phase_ordinal=1)
    _seed_scene_item(db, scene.id, item_name="Shield", item_type="special", phase_ordinal=2)

    # Accept only the first item
    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si1.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Shield is still pending
    assert data["pending_items_remaining"] == 1
    assert data["phase_complete"] is False


# ---------------------------------------------------------------------------
# POST /gameplay/{id}/inventory — drop
# ---------------------------------------------------------------------------


def test_drop_item_removes_from_inventory(client: TestClient, db: Session) -> None:
    """Dropping an item removes it from the character's inventory."""
    headers, char_id, scene = _setup_base(db, client)
    ci = _seed_character_item(db, char_id, item_name="Axe", item_type="weapon")

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "drop", "character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["action"] == "drop"
    names = [i["item_name"] for i in data["inventory"]]
    assert "Axe" not in names
    assert data["version"] == 2


def test_drop_item_recalculates_endurance_max(client: TestClient, db: Session) -> None:
    """Dropping a backpack item with an endurance_bonus recalculates endurance_max on character."""
    headers, char_id, scene = _setup_base(db, client)

    # Create a backpack game object with endurance_bonus (backpack items can be dropped)
    go = make_game_object(
        db,
        kind="item",
        name="Padded Waistcoat",
        properties=json.dumps({"endurance_bonus": 4}),
    )
    ci = _seed_character_item(
        db, char_id,
        item_name="Padded Waistcoat",
        item_type="backpack",
        game_object_id=go.id,
    )

    # Manually set endurance_max to reflect the bonus (simulate it was accepted)
    from app.models.player import Character
    char = db.query(Character).filter(Character.id == char_id).first()
    char.endurance_max = 29  # base 25 + 4 bonus
    char.endurance_current = 29
    db.flush()

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "drop", "character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2

    # Verify DB endurance_max was recalculated back to base (25)
    db.expire(char)
    assert char.endurance_max == 25
    assert char.endurance_current == 25  # clamped from 29 to 25


def test_drop_special_item_blocked(client: TestClient, db: Session) -> None:
    """Dropping a special item returns 400 (engine forbids it)."""
    headers, char_id, scene = _setup_base(db, client)
    ci = _seed_character_item(db, char_id, item_name="Gold Key", item_type="special")

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "drop", "character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /gameplay/{id}/inventory — equip / unequip
# ---------------------------------------------------------------------------


def test_equip_weapon(client: TestClient, db: Session) -> None:
    """Equipping a weapon sets is_equipped to True in the response."""
    headers, char_id, scene = _setup_base(db, client)
    ci = _seed_character_item(db, char_id, item_name="Sword", item_type="weapon", is_equipped=False)

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "equip", "character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    equipped = next(i for i in data["inventory"] if i["item_name"] == "Sword")
    assert equipped["is_equipped"] is True


def test_unequip_weapon(client: TestClient, db: Session) -> None:
    """Unequipping an equipped weapon sets is_equipped to False."""
    headers, char_id, scene = _setup_base(db, client)
    ci = _seed_character_item(db, char_id, item_name="Sword", item_type="weapon", is_equipped=True)

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "unequip", "character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    equipped = next(i for i in data["inventory"] if i["item_name"] == "Sword")
    assert equipped["is_equipped"] is False


def test_equip_non_weapon_returns_400(client: TestClient, db: Session) -> None:
    """Attempting to equip a backpack item returns 400."""
    headers, char_id, scene = _setup_base(db, client)
    ci = _seed_character_item(db, char_id, item_name="Healing Potion", item_type="backpack")

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "equip", "character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400


def test_inventory_action_wrong_version_returns_409(client: TestClient, db: Session) -> None:
    """Sending a wrong version returns 409 VERSION_MISMATCH."""
    headers, char_id, scene = _setup_base(db, client)
    ci = _seed_character_item(db, char_id, item_name="Sword", item_type="weapon")

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "drop", "character_item_id": ci.id, "version": 999},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "VERSION_MISMATCH"


def test_inventory_item_not_found_returns_404(client: TestClient, db: Session) -> None:
    """Referencing a non-existent character_item_id returns 404."""
    headers, char_id, scene = _setup_base(db, client)

    resp = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "drop", "character_item_id": 99999, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Inventory swap during items phase
# ---------------------------------------------------------------------------


def test_inventory_swap_during_items_phase(client: TestClient, db: Session) -> None:
    """Drop an existing weapon then accept a new one during items phase."""
    headers, char_id, scene = _setup_base(db, client)

    # Character already has 2 weapons (full)
    ci1 = _seed_character_item(db, char_id, item_name="Sword", item_type="weapon")
    _seed_character_item(db, char_id, item_name="Dagger", item_type="weapon")

    si = _seed_scene_item(db, scene.id, item_name="Broadsword", item_type="weapon")

    # 1. Verify accepting fails when full
    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVENTORY_FULL"

    # 2. Drop one weapon
    resp2 = client.post(
        f"/gameplay/{char_id}/inventory",
        json={"action": "drop", "character_item_id": ci1.id, "version": 1},
        headers=headers,
    )
    assert resp2.status_code == 200, resp2.text

    # 3. Now accept the new weapon (version is now 2)
    resp3 = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 2},
        headers=headers,
    )
    assert resp3.status_code == 200, resp3.text
    names = [i["item_name"] for i in resp3.json()["inventory"]]
    assert "Broadsword" in names
    assert "Sword" not in names


# ---------------------------------------------------------------------------
# POST /gameplay/{id}/use-item — consumable
# ---------------------------------------------------------------------------


def test_use_consumable_restores_endurance(client: TestClient, db: Session) -> None:
    """Using a Healing Potion restores endurance via endurance_restore effect."""
    headers, char_id, scene = _setup_base(db, client)

    # Create game object with consumable + endurance_restore
    go = make_game_object(
        db,
        kind="item",
        name="Healing Potion",
        properties=json.dumps({"consumable": True, "endurance_restore": 4}),
    )
    ci = _seed_character_item(
        db, char_id,
        item_name="Healing Potion",
        item_type="backpack",
        game_object_id=go.id,
    )

    # Reduce character's endurance so healing has room
    from app.models.player import Character
    char = db.query(Character).filter(Character.id == char_id).first()
    char.endurance_current = 20
    db.flush()

    resp = client.post(
        f"/gameplay/{char_id}/use-item",
        json={"character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["effect_applied"] == {"endurance_restore": 4}
    assert data["endurance_current"] == 24  # 20 + 4
    assert data["version"] == 2

    # Item should be removed from inventory
    names = [i["item_name"] for i in data["inventory"]]
    assert "Healing Potion" not in names


def test_use_consumable_blocked_during_combat(client: TestClient, db: Session) -> None:
    """Using an item during combat phase returns 400 WRONG_PHASE."""
    headers, char_id, scene = _setup_base(db, client)

    go = make_game_object(
        db,
        kind="item",
        name="Healing Potion2",
        properties=json.dumps({"consumable": True, "endurance_restore": 4}),
    )
    ci = _seed_character_item(
        db, char_id,
        item_name="Healing Potion2",
        item_type="backpack",
        game_object_id=go.id,
    )

    # Set character to combat phase
    from app.models.player import Character
    char = db.query(Character).filter(Character.id == char_id).first()
    char.scene_phase = "combat"
    db.flush()

    resp = client.post(
        f"/gameplay/{char_id}/use-item",
        json={"character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "WRONG_PHASE"


def test_use_non_consumable_item_returns_400(client: TestClient, db: Session) -> None:
    """Using an item without consumable=True in properties returns 400 ITEM_NOT_CONSUMABLE."""
    headers, char_id, scene = _setup_base(db, client)

    go = make_game_object(
        db,
        kind="item",
        name="Torch",
        properties=json.dumps({}),
    )
    ci = _seed_character_item(
        db, char_id,
        item_name="Torch",
        item_type="backpack",
        game_object_id=go.id,
    )

    resp = client.post(
        f"/gameplay/{char_id}/use-item",
        json={"character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "ITEM_NOT_CONSUMABLE"


def test_use_item_without_game_object_not_consumable(client: TestClient, db: Session) -> None:
    """An item with no game_object_id has empty properties and is not consumable."""
    headers, char_id, scene = _setup_base(db, client)

    ci = _seed_character_item(
        db, char_id,
        item_name="Generic Item",
        item_type="backpack",
        game_object_id=None,
    )

    resp = client.post(
        f"/gameplay/{char_id}/use-item",
        json={"character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "ITEM_NOT_CONSUMABLE"


# ---------------------------------------------------------------------------
# endurance_max recalculation
# ---------------------------------------------------------------------------


def test_endurance_max_recalculated_on_item_accept(client: TestClient, db: Session) -> None:
    """Accepting an item with endurance_bonus updates endurance_max."""
    headers, char_id, scene = _setup_base(db, client)

    go = make_game_object(
        db,
        kind="item",
        name="Chainmail Vest",
        properties=json.dumps({"endurance_bonus": 4}),
    )
    si = _seed_scene_item(
        db, scene.id,
        item_name="Chainmail Vest",
        item_type="special",
        game_object_id=go.id,
    )

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # Verify the DB record has updated endurance_max
    from app.models.player import Character
    char = db.query(Character).filter(Character.id == char_id).first()
    assert char.endurance_max == 29  # base 25 + 4 bonus


def test_endurance_max_recalculated_on_use_item(client: TestClient, db: Session) -> None:
    """Using a consumable removes it and recalculates endurance_max."""
    headers, char_id, scene = _setup_base(db, client)

    # Item provides both an endurance_bonus AND is consumable (edge case)
    go = make_game_object(
        db,
        kind="item",
        name="Laumspur Potion",
        properties=json.dumps({"consumable": True, "endurance_restore": 4}),
    )
    ci = _seed_character_item(
        db, char_id,
        item_name="Laumspur Potion",
        item_type="backpack",
        game_object_id=go.id,
    )

    from app.models.player import Character
    char = db.query(Character).filter(Character.id == char_id).first()
    char.endurance_current = 20
    db.flush()

    resp = client.post(
        f"/gameplay/{char_id}/use-item",
        json={"character_item_id": ci.id, "version": 1},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Item was consumed — verify it's gone from inventory
    assert not any(i["item_name"] == "Laumspur Potion" for i in data["inventory"])


# ---------------------------------------------------------------------------
# Version mismatch
# ---------------------------------------------------------------------------


def test_item_action_wrong_version_returns_409(client: TestClient, db: Session) -> None:
    """Sending wrong version returns 409 VERSION_MISMATCH for /item endpoint."""
    headers, char_id, scene = _setup_base(db, client)
    si = _seed_scene_item(db, scene.id, item_name="Sword", item_type="weapon")

    resp = client.post(
        f"/gameplay/{char_id}/item",
        json={"scene_item_id": si.id, "action": "accept", "version": 999},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "VERSION_MISMATCH"


def test_use_item_wrong_version_returns_409(client: TestClient, db: Session) -> None:
    """Sending wrong version returns 409 VERSION_MISMATCH for /use-item endpoint."""
    headers, char_id, scene = _setup_base(db, client)

    go = make_game_object(
        db,
        kind="item",
        name="Healing Herb",
        properties=json.dumps({"consumable": True, "endurance_restore": 2}),
    )
    ci = _seed_character_item(db, char_id, item_name="Healing Herb", item_type="backpack", game_object_id=go.id)

    resp = client.post(
        f"/gameplay/{char_id}/use-item",
        json={"character_item_id": ci.id, "version": 999},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "VERSION_MISMATCH"
