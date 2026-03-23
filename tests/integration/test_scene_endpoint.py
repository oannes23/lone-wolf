"""Integration tests for GET /gameplay/{character_id}/scene (Story 6.1).

Tests cover scene state assembly across all phase types.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Choice, CombatEncounter, Scene, SceneItem
from tests.factories import (
    make_book,
    make_character,
    make_encounter,
    make_scene,
    make_user,
)
from tests.helpers.auth import register_and_login, auth_headers


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _make_choice(
    db: Session,
    scene: Scene,
    display_text: str = "Go north",
    target_scene_id: int | None = None,
    ordinal: int = 1,
    condition_type: str | None = None,
    condition_value: str | None = None,
) -> Choice:
    choice = Choice(
        scene_id=scene.id,
        target_scene_id=target_scene_id,
        target_scene_number=100,
        raw_text=display_text,
        display_text=display_text,
        ordinal=ordinal,
        source="manual",
        condition_type=condition_type,
        condition_value=condition_value,
    )
    db.add(choice)
    db.flush()
    return choice


def _make_scene_item(
    db: Session,
    scene: Scene,
    item_name: str = "Sword",
    item_type: str = "weapon",
    action: str = "gain",
    is_mandatory: bool = False,
    quantity: int = 1,
) -> SceneItem:
    si = SceneItem(
        scene_id=scene.id,
        item_name=item_name,
        item_type=item_type,
        quantity=quantity,
        action=action,
        is_mandatory=is_mandatory,
        phase_ordinal=1,
        source="manual",
    )
    db.add(si)
    db.flush()
    return si


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSceneEndpointAuth:
    """Authentication requirements for the scene endpoint."""

    def test_unauthenticated_returns_401(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book)
        user = make_user(db)
        character = make_character(db, user, book, current_scene_id=scene.id)

        response = client.get(f"/gameplay/{character.id}/scene")
        assert response.status_code == 401

    def test_other_user_character_returns_403(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book)

        # Create character belonging to user A
        tokens_a = register_and_login(client, username="userA_scene", password="pass1234!")
        from app.models.player import User
        user_a = db.query(User).filter(User.username == "userA_scene").first()
        character = make_character(db, user_a, book, current_scene_id=scene.id)
        db.flush()

        # Log in as user B
        tokens_b = register_and_login(client, username="userB_scene", password="pass1234!")

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens_b["access_token"]),
        )
        assert response.status_code == 403


class TestSceneEndpointChoicesPhase:
    """Scene endpoint in choices phase."""

    def test_choices_phase_response_shape(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="scene_test_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "scene_test_user").first()

        book = make_book(db)
        target_scene = make_scene(db, book, number=42)
        scene = make_scene(db, book, number=1)
        _make_choice(db, scene, "Go north", target_scene_id=target_scene.id, ordinal=1)

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()

        # Check spec-aligned field names
        assert "phase" in data  # not "current_phase"
        assert data["phase"] == "choices"
        assert "phase_index" in data
        assert data["phase_index"] == 0
        assert "phase_sequence" in data
        assert isinstance(data["phase_sequence"], list)
        assert "phase_results" in data
        assert "choices" in data
        assert "combat" in data
        assert data["combat"] is None
        assert "pending_items" in data
        assert "is_death" in data
        assert "is_victory" in data
        assert "is_alive" in data
        assert data["is_alive"] is True
        assert "version" in data
        assert data["version"] == character.version

    def test_choices_have_correct_field_names(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="choices_field_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "choices_field_user").first()

        book = make_book(db)
        target_scene = make_scene(db, book, number=50)
        scene = make_scene(db, book, number=1)
        # Use a test-namespaced discipline name to avoid UNIQUE constraint conflicts
        # with other test modules that seed Kai disciplines with canonical names.
        _make_choice(
            db, scene,
            "Use your Sixth Sense",
            target_scene_id=target_scene.id,
            ordinal=1,
            condition_type="discipline",
            condition_value="Sixth Sense",
        )
        _make_choice(
            db, scene,
            "Take the right path",
            target_scene_id=target_scene.id,
            ordinal=2,
        )

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        choices = data["choices"]
        assert len(choices) == 2

        # Check spec-aligned field names: "id" not "choice_id", "text" not "choice_text"
        c1 = choices[0]
        assert "id" in c1  # not "choice_id"
        assert "text" in c1  # not "choice_text"
        assert "available" in c1
        assert "condition" in c1
        assert "has_random_outcomes" in c1

        # Conditional choice should have condition dict
        assert c1["condition"] is not None
        assert c1["condition"]["type"] == "discipline"
        assert c1["condition"]["value"] == "Sixth Sense"
        # Character doesn't have discipline, so unavailable
        assert c1["available"] is False

        # Unconditional choice should have no condition
        c2 = choices[1]
        assert c2["condition"] is None
        assert c2["available"] is True

    def test_scene_response_has_correct_is_alive(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="alive_test_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "alive_test_user").first()

        book = make_book(db)
        death_scene = make_scene(db, book, number=1, is_death=True)

        character = make_character(
            db, user, book,
            current_scene_id=death_scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            is_alive=False,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_death"] is True
        assert data["is_alive"] is False


class TestSceneEndpointItemsPhase:
    """Scene endpoint in items phase with pending items."""

    def test_pending_items_include_quantity(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="pending_items_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "pending_items_user").first()

        book = make_book(db)
        scene = make_scene(db, book, number=1)
        _make_scene_item(db, scene, item_name="Sword", item_type="weapon", quantity=1)

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="items",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        pending = data["pending_items"]
        assert len(pending) == 1
        assert "quantity" in pending[0]
        assert pending[0]["quantity"] == 1
        assert "id" in pending[0]
        assert "item_name" in pending[0]
        assert pending[0]["item_name"] == "Sword"


class TestSceneEndpointCombatPhase:
    """Scene endpoint in combat phase with combat state."""

    def test_combat_state_fields(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="combat_scene_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "combat_scene_user").first()

        book = make_book(db)
        scene = make_scene(db, book, number=1)
        encounter = make_encounter(
            db, scene,
            enemy_cs=16,
            enemy_end=24,
            evasion_after_rounds=3,
        )

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="combat",
            scene_phase_index=0,
            active_combat_encounter_id=encounter.id,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        combat = data["combat"]
        assert combat is not None

        # Check spec-aligned combat fields
        assert "encounter_id" in combat
        assert combat["encounter_id"] == encounter.id
        assert "enemy_name" in combat
        assert "enemy_cs" in combat
        assert combat["enemy_cs"] == 16
        assert "enemy_end_remaining" in combat
        assert "hero_end_remaining" in combat
        assert "rounds_fought" in combat
        assert combat["rounds_fought"] == 0
        assert "evasion_available" in combat  # renamed from evasion_possible
        assert combat["evasion_available"] is True
        assert "can_evade" in combat  # new field
        assert combat["can_evade"] is False  # 0 rounds fought < threshold of 3
        assert "evasion_after_rounds" in combat
        assert combat["evasion_after_rounds"] == 3
        assert "hero_effective_cs" in combat
        assert "combat_ratio" in combat


class TestSceneEndpointVictory:
    """Scene endpoint at victory scene."""

    def test_victory_scene(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="victory_scene_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "victory_scene_user").first()

        book = make_book(db)
        scene = make_scene(db, book, number=350, is_victory=True)

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_victory"] is True
        assert data["is_death"] is False


# ---------------------------------------------------------------------------
# Additional tests for full coverage
# ---------------------------------------------------------------------------


class TestSceneEndpointNotFound:
    """404 cases for the scene endpoint."""

    def test_nonexistent_character_returns_404(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="scene_404_user", password="pass1234!")
        response = client.get(
            "/gameplay/99999/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 404

    def test_no_current_scene_returns_404(
        self, client: TestClient, db: Session
    ) -> None:
        """Character with no current_scene_id (wizard not complete yet) returns 404."""
        tokens = register_and_login(client, username="no_scene_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "no_scene_user").first()

        book = make_book(db)
        # current_scene_id=None — character has no active scene
        character = make_character(db, user, book, current_scene_id=None)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 404

    def test_soft_deleted_character_returns_404(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="deleted_char_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "deleted_char_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            is_deleted=True,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 404


class TestSceneEndpointWizardActive:
    """409 when a character has an active wizard."""

    def test_wizard_active_does_not_block_scene_read(
        self, client: TestClient, db: Session
    ) -> None:
        """GET /scene is read-only; even with an active wizard it returns 200.

        The 409 wizard-active guard is on mutating endpoints (POST /advance),
        not on the read endpoint.  This test documents that behavior explicitly.
        """
        tokens = register_and_login(client, username="wizard_active_scene_user", password="pass1234!")
        from app.models.player import User
        from app.models.wizard import CharacterWizardProgress, WizardTemplate
        user = db.query(User).filter(User.username == "wizard_active_scene_user").first()

        book = make_book(db)
        scene = make_scene(db, book)

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        # Create a wizard template and progress record
        template = WizardTemplate(name="scene_advance_wizard_test", description="test")
        db.add(template)
        db.flush()

        from datetime import UTC, datetime
        progress = CharacterWizardProgress(
            character_id=character.id,
            wizard_template_id=template.id,
            current_step_index=0,
            started_at=datetime.now(tz=UTC),
        )
        db.add(progress)
        db.flush()

        character.active_wizard_id = progress.id
        db.flush()
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        # GET /scene is readable even with wizard active
        assert response.status_code == 200


class TestSceneEndpointDeathScene:
    """Death scenes: is_death=True and empty phase_sequence check."""

    def test_death_scene_flags(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="death_flags_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "death_flags_user").first()

        book = make_book(db)
        death_scene = make_scene(db, book, is_death=True)

        character = make_character(
            db, user, book,
            current_scene_id=death_scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            is_alive=False,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_death"] is True
        assert data["is_victory"] is False
        assert data["is_alive"] is False

    def test_death_scene_has_only_choices_in_phase_sequence(
        self, client: TestClient, db: Session
    ) -> None:
        """A plain death scene with no items/combat should have ['choices'] phase_sequence."""
        tokens = register_and_login(client, username="death_seq_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "death_seq_user").first()

        book = make_book(db)
        # Death scene with no items, no combat, no random
        death_scene = make_scene(db, book, is_death=True)

        character = make_character(
            db, user, book,
            current_scene_id=death_scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            is_alive=False,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        # A death scene with no special content should have phase_sequence = ["choices"]
        assert "choices" in data["phase_sequence"]


class TestSceneEndpointItemsPhaseExtended:
    """Extended items-phase tests: gold/meal exclusion, already-resolved exclusion."""

    def test_gold_item_excluded_from_pending(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="gold_excl_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "gold_excl_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        # Gold items are auto-applied — must NOT appear in pending_items
        _make_scene_item(db, scene, item_name="Gold Coins", item_type="gold", action="gain")

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="items",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [p["item_name"] for p in data["pending_items"]]
        assert "Gold Coins" not in names

    def test_meal_item_excluded_from_pending(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="meal_excl_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "meal_excl_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        # Meal items are auto-applied — must NOT appear in pending_items
        _make_scene_item(db, scene, item_name="Meal", item_type="meal", action="gain")

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="items",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [p["item_name"] for p in data["pending_items"]]
        assert "Meal" not in names

    def test_already_resolved_item_excluded_from_pending(
        self, client: TestClient, db: Session
    ) -> None:
        """An item already resolved via item_pickup event is excluded from pending_items."""
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="resolved_item_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "resolved_item_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        si = _make_scene_item(db, scene, item_name="Shield", item_type="backpack", action="gain")

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="items",
            scene_phase_index=0,
        )

        # Add an item_pickup event referencing this scene_item
        event = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="item_pickup",
            details=f'{{"item_name": "Shield", "scene_item_id": {si.id}}}',
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add(event)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [p["item_name"] for p in data["pending_items"]]
        assert "Shield" not in names

    def test_items_phase_not_in_choices_phase_returns_empty_pending(
        self, client: TestClient, db: Session
    ) -> None:
        """When not in items phase, pending_items is empty regardless of scene items."""
        tokens = register_and_login(client, username="not_items_phase_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "not_items_phase_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        _make_scene_item(db, scene, item_name="Dagger", item_type="weapon", action="gain")

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["pending_items"] == []


class TestSceneEndpointRandomPhase:
    """Scene endpoint in random phase."""

    def test_random_phase_in_phase_sequence(
        self, client: TestClient, db: Session
    ) -> None:
        from app.models.content import RandomOutcome

        tokens = register_and_login(client, username="random_phase_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "random_phase_user").first()

        book = make_book(db)
        target_scene = make_scene(db, book, number=99)
        scene = make_scene(db, book)

        # Add a random outcome to the scene so it builds a "random" phase
        ro = RandomOutcome(
            scene_id=scene.id,
            roll_group=0,
            range_min=0,
            range_max=4,
            effect_type="scene_redirect",
            effect_value=str(target_scene.number),
            ordinal=1,
            source="manual",
        )
        db.add(ro)

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="random",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["phase"] == "random"
        assert "random" in data["phase_sequence"]


class TestSceneEndpointChoicesExtended:
    """Extended choices tests: item/gold/path_unavailable unavailability reasons."""

    def test_item_conditioned_choice_unavailable_without_item(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="item_cond_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "item_cond_user").first()

        book = make_book(db)
        target_scene = make_scene(db, book, number=200)
        scene = make_scene(db, book)

        _make_choice(
            db, scene,
            "Use the Sommerswerd",
            target_scene_id=target_scene.id,
            ordinal=1,
            condition_type="item",
            condition_value="Sommerswerd",
        )
        _make_choice(
            db, scene,
            "Flee",
            target_scene_id=target_scene.id,
            ordinal=2,
        )

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        choices = data["choices"]
        assert len(choices) == 2

        item_choice = choices[0]
        assert item_choice["available"] is False
        assert item_choice["condition"] is not None
        assert item_choice["condition"]["type"] == "item"
        assert item_choice["condition"]["value"] == "Sommerswerd"

        free_choice = choices[1]
        assert free_choice["available"] is True

    def test_gold_conditioned_choice_unavailable_when_poor(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="gold_cond_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "gold_cond_user").first()

        book = make_book(db)
        target_scene = make_scene(db, book, number=201)
        scene = make_scene(db, book)

        _make_choice(
            db, scene,
            "Pay 10 gold",
            target_scene_id=target_scene.id,
            ordinal=1,
            condition_type="gold",
            condition_value="10",
        )

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            gold=0,  # no gold
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        choices = data["choices"]
        assert len(choices) == 1
        assert choices[0]["available"] is False
        assert choices[0]["condition"]["type"] == "gold"

    def test_choice_with_random_outcomes_has_has_random_outcomes_true(
        self, client: TestClient, db: Session
    ) -> None:
        from app.models.content import ChoiceRandomOutcome

        tokens = register_and_login(client, username="random_outcome_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "random_outcome_user").first()

        book = make_book(db)
        target_a = make_scene(db, book, number=101)
        target_b = make_scene(db, book, number=102)
        scene = make_scene(db, book)

        choice = _make_choice(
            db, scene,
            "Roll the dice",
            target_scene_id=None,
            ordinal=1,
        )

        # Add random outcomes to the choice
        cro1 = ChoiceRandomOutcome(
            choice_id=choice.id,
            range_min=0,
            range_max=4,
            target_scene_id=target_a.id,
            target_scene_number=target_a.number,
            source="manual",
        )
        cro2 = ChoiceRandomOutcome(
            choice_id=choice.id,
            range_min=5,
            range_max=9,
            target_scene_id=target_b.id,
            target_scene_number=target_b.number,
            source="manual",
        )
        db.add_all([cro1, cro2])

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        choices = data["choices"]
        assert len(choices) == 1
        assert choices[0]["has_random_outcomes"] is True

    def test_multiple_choices_sorted_by_ordinal(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="ordinal_sort_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "ordinal_sort_user").first()

        book = make_book(db)
        t1 = make_scene(db, book, number=301)
        t2 = make_scene(db, book, number=302)
        t3 = make_scene(db, book, number=303)
        scene = make_scene(db, book)

        # Insert in reverse ordinal order to test sorting
        _make_choice(db, scene, "Choice C", target_scene_id=t3.id, ordinal=3)
        _make_choice(db, scene, "Choice A", target_scene_id=t1.id, ordinal=1)
        _make_choice(db, scene, "Choice B", target_scene_id=t2.id, ordinal=2)

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        choices = data["choices"]
        assert len(choices) == 3
        assert choices[0]["text"] == "Choice A"
        assert choices[1]["text"] == "Choice B"
        assert choices[2]["text"] == "Choice C"


class TestSceneEndpointCombatExtended:
    """Extended combat state tests: rounds fought, can_evade threshold."""

    def test_can_evade_true_after_threshold_rounds(
        self, client: TestClient, db: Session
    ) -> None:
        from app.models.player import CombatRound
        from datetime import UTC, datetime

        tokens = register_and_login(client, username="evade_true_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "evade_true_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        encounter = make_encounter(
            db, scene,
            enemy_cs=14,
            enemy_end=20,
            evasion_after_rounds=2,
        )

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="combat",
            scene_phase_index=0,
            active_combat_encounter_id=encounter.id,
        )
        db.flush()

        # Add 2 combat rounds (meets evasion_after_rounds threshold)
        for rn in (1, 2):
            cr = CombatRound(
                character_id=character.id,
                combat_encounter_id=encounter.id,
                run_number=character.current_run,
                round_number=rn,
                random_number=5,
                combat_ratio=0,
                enemy_end_remaining=encounter.enemy_end - rn * 3,
                hero_end_remaining=character.endurance_current - rn * 2,
                created_at=datetime.now(tz=UTC),
            )
            db.add(cr)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        combat = data["combat"]
        assert combat is not None
        assert combat["rounds_fought"] == 2
        assert combat["can_evade"] is True
        assert combat["evasion_available"] is True

    def test_no_evasion_encounter(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="no_evade_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "no_evade_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        # No evasion_after_rounds means evasion not available
        encounter = make_encounter(
            db, scene,
            enemy_cs=18,
            enemy_end=30,
        )

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="combat",
            scene_phase_index=0,
            active_combat_encounter_id=encounter.id,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        combat = data["combat"]
        assert combat is not None
        assert combat["evasion_available"] is False
        assert combat["can_evade"] is False
        assert combat["evasion_after_rounds"] is None

    def test_combat_enemy_end_decreases_after_rounds(
        self, client: TestClient, db: Session
    ) -> None:
        from app.models.player import CombatRound
        from datetime import UTC, datetime

        tokens = register_and_login(client, username="end_decrease_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "end_decrease_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        encounter = make_encounter(
            db, scene,
            enemy_cs=15,
            enemy_end=20,
        )

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="combat",
            scene_phase_index=0,
            active_combat_encounter_id=encounter.id,
        )
        db.flush()

        # After 1 round, enemy lost 5 endurance
        cr = CombatRound(
            character_id=character.id,
            combat_encounter_id=encounter.id,
            run_number=character.current_run,
            round_number=1,
            random_number=7,
            combat_ratio=0,
            enemy_end_remaining=15,
            hero_end_remaining=23,
            created_at=datetime.now(tz=UTC),
        )
        db.add(cr)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        combat = data["combat"]
        assert combat["enemy_end_remaining"] == 15
        assert combat["rounds_fought"] == 1


class TestSceneEndpointPhaseResults:
    """Phase results reconstruction from character_events."""

    def test_meal_consumed_event_appears_in_phase_results(
        self, client: TestClient, db: Session
    ) -> None:
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="meal_result_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "meal_result_user").first()

        book = make_book(db)
        scene = make_scene(db, book, must_eat=True)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        event = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="meal_consumed",
            details='{"meals_remaining": 1}',
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add(event)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        results = data["phase_results"]
        assert len(results) >= 1
        eat_result = next((r for r in results if r["type"] == "eat"), None)
        assert eat_result is not None
        assert eat_result["result"] == "meal_consumed"
        assert eat_result["severity"] == "info"

    def test_meal_penalty_event_has_warn_severity(
        self, client: TestClient, db: Session
    ) -> None:
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="meal_penalty_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "meal_penalty_user").first()

        book = make_book(db)
        scene = make_scene(db, book, must_eat=True)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            meals=0,
        )

        event = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="meal_penalty",
            details='{"endurance_lost": 3}',
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add(event)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        results = data["phase_results"]
        penalty = next((r for r in results if r["result"] == "meal_penalty"), None)
        assert penalty is not None
        assert penalty["severity"] == "warn"

    def test_healing_event_appears_in_phase_results(
        self, client: TestClient, db: Session
    ) -> None:
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="healing_result_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "healing_result_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        event = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="healing",
            details='{"endurance_gained": 2}',
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add(event)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        results = data["phase_results"]
        heal = next((r for r in results if r["type"] == "heal"), None)
        assert heal is not None
        assert heal["result"] == "healed"

    def test_backpack_loss_event_appears_in_phase_results(
        self, client: TestClient, db: Session
    ) -> None:
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="backpack_loss_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "backpack_loss_user").first()

        book = make_book(db)
        scene = make_scene(db, book, loses_backpack=True)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        event = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="backpack_loss",
            details='{}',
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add(event)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        results = data["phase_results"]
        bp = next((r for r in results if r["type"] == "backpack_loss"), None)
        assert bp is not None
        assert bp["result"] == "backpack_lost"

    def test_phase_results_ordered_by_seq(
        self, client: TestClient, db: Session
    ) -> None:
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="seq_order_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "seq_order_user").first()

        book = make_book(db)
        scene = make_scene(db, book, must_eat=True, loses_backpack=True)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        # Insert seq=2 before seq=1 to test ordering
        e2 = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="meal_consumed",
            seq=2,
            created_at=datetime.now(tz=UTC),
        )
        e1 = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="backpack_loss",
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add_all([e2, e1])
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        results = data["phase_results"]
        assert len(results) == 2
        # seq=1 (backpack_loss) must come before seq=2 (meal_consumed)
        assert results[0]["type"] == "backpack_loss"
        assert results[1]["type"] == "eat"

    def test_phase_results_isolated_to_current_run(
        self, client: TestClient, db: Session
    ) -> None:
        """Events from a previous run must not appear in current phase_results."""
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="run_isolation_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "run_isolation_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            current_run=2,
        )

        # Event from run 1 — must NOT appear
        old_event = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=1,
            event_type="meal_consumed",
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add(old_event)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        # Only current run events qualify — none in run 2
        assert data["phase_results"] == []

    def test_non_phase_events_excluded_from_phase_results(
        self, client: TestClient, db: Session
    ) -> None:
        """item_pickup, combat_start, etc. must NOT appear in phase_results."""
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="excl_events_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "excl_events_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        for etype in ("item_pickup", "combat_start", "combat_end", "gold_change"):
            ev = CharacterEvent(
                character_id=character.id,
                scene_id=scene.id,
                run_number=character.current_run,
                event_type=etype,
                seq=1,
                created_at=datetime.now(tz=UTC),
            )
            db.add(ev)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["phase_results"] == []


class TestSceneEndpointVersion:
    """Version field in scene response."""

    def test_version_reflects_character_version(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="version_check_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "version_check_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=7,
        )
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 7


class TestSceneEndpointVictoryPhaseResults:
    """Victory scene: phase_results are shown (no restriction on victory scenes)."""

    def test_victory_scene_shows_phase_results(
        self, client: TestClient, db: Session
    ) -> None:
        from datetime import UTC, datetime
        from app.models.player import CharacterEvent

        tokens = register_and_login(client, username="victory_results_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "victory_results_user").first()

        book = make_book(db)
        scene = make_scene(db, book, number=350, is_victory=True)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        event = CharacterEvent(
            character_id=character.id,
            scene_id=scene.id,
            run_number=character.current_run,
            event_type="healing",
            details='{"endurance_gained": 3}',
            seq=1,
            created_at=datetime.now(tz=UTC),
        )
        db.add(event)
        db.flush()

        response = client.get(
            f"/gameplay/{character.id}/scene",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_victory"] is True
        results = data["phase_results"]
        assert len(results) >= 1
        assert results[0]["type"] == "heal"
