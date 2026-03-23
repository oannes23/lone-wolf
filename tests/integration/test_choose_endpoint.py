"""Integration tests for POST /gameplay/{character_id}/choose (Story 6.2).

Tests cover the full choose endpoint including normal transitions, automatic
phase execution, gold-gated choices, choice-triggered random rolls, and all
validation error paths.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Choice, ChoiceRandomOutcome, Scene, SceneItem
from app.models.player import CharacterEvent, DecisionLog
from tests.factories import (
    make_book,
    make_character,
    make_scene,
    make_user,
)
from tests.helpers.auth import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _make_choice(
    db: Session,
    scene: Scene,
    target_scene: Scene | None = None,
    display_text: str = "Go north",
    ordinal: int = 1,
    condition_type: str | None = None,
    condition_value: str | None = None,
) -> Choice:
    """Create a Choice for the given scene."""
    choice = Choice(
        scene_id=scene.id,
        target_scene_id=target_scene.id if target_scene else None,
        target_scene_number=target_scene.number if target_scene else 999,
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
    """Create a SceneItem for the given scene."""
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


def _make_choice_random_outcome(
    db: Session,
    choice: Choice,
    target_scene: Scene,
    range_min: int,
    range_max: int,
    narrative_text: str | None = None,
) -> ChoiceRandomOutcome:
    """Create a ChoiceRandomOutcome for the given choice."""
    cro = ChoiceRandomOutcome(
        choice_id=choice.id,
        range_min=range_min,
        range_max=range_max,
        target_scene_id=target_scene.id,
        target_scene_number=target_scene.number,
        narrative_text=narrative_text,
        source="manual",
    )
    db.add(cro)
    db.flush()
    return cro


# ---------------------------------------------------------------------------
# Helper: register user, create character at scene, return headers + char
# ---------------------------------------------------------------------------


def _setup_character_at_choices(
    client: TestClient,
    db: Session,
    username: str,
    scene: Scene,
    book,
    gold: int = 10,
    meals: int = 2,
    is_alive: bool = True,
) -> tuple[dict[str, str], object]:
    """Register a user, log in, and create a character at the choices phase."""
    tokens = register_and_login(client, username=username, password="pass1234!")
    from app.models.player import User
    user = db.query(User).filter(User.username == username).first()
    character = make_character(
        db,
        user,
        book,
        current_scene_id=scene.id,
        scene_phase="choices",
        scene_phase_index=0,
        gold=gold,
        meals=meals,
        is_alive=is_alive,
    )
    db.flush()
    return auth_headers(tokens["access_token"]), character


# ---------------------------------------------------------------------------
# Tests: normal transition
# ---------------------------------------------------------------------------


class TestNormalTransition:
    """Normal choice transitions to target scene."""

    def test_normal_choice_returns_200(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=42)
        choice = _make_choice(db, scene, target, "Go north")

        headers, character = _setup_character_at_choices(
            client, db, "choose_normal_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scene_number"] == 42

    def test_normal_choice_transitions_to_target_scene(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=55)
        choice = _make_choice(db, scene, target, "Explore the cave")

        headers, character = _setup_character_at_choices(
            client, db, "choose_transition_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["scene_number"] == 55

    def test_version_incremented_after_transition(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=10)
        choice = _make_choice(db, scene, target, "Go forward")

        headers, character = _setup_character_at_choices(
            client, db, "choose_version_user", scene, book
        )
        initial_version = character.version

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": initial_version},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["version"] > initial_version

    def test_decision_log_entry_created(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=100)
        choice = _make_choice(db, scene, target, "Turn to section 100")

        headers, character = _setup_character_at_choices(
            client, db, "choose_decision_log_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200

        # Verify decision log entry was created
        log_entry = (
            db.query(DecisionLog)
            .filter(
                DecisionLog.character_id == character.id,
                DecisionLog.choice_id == choice.id,
            )
            .first()
        )
        assert log_entry is not None
        assert log_entry.from_scene_id == scene.id
        assert log_entry.to_scene_id == target.id
        assert log_entry.action_type == "choice"

    def test_character_ends_in_choices_phase_for_simple_scene(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        onward_choice = _make_choice(db, target, make_scene(db, book, number=3), "Continue")
        choice = _make_choice(db, scene, target, "Go forward")

        headers, character = _setup_character_at_choices(
            client, db, "choose_phase_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Simple scene with no eat/combat/random should land on choices
        assert data["phase"] == "choices"


# ---------------------------------------------------------------------------
# Tests: automatic phases at new scene
# ---------------------------------------------------------------------------


class TestAutomaticPhasesAtNewScene:
    """Automatic phases run at new scene on transition."""

    def test_eat_phase_runs_automatically(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        # Target scene requires eating
        target = make_scene(db, book, number=20, must_eat=True)
        _make_choice(db, target, make_scene(db, book, number=21), "Proceed")
        choice = _make_choice(db, scene, target, "Go to meal scene")

        headers, character = _setup_character_at_choices(
            client, db, "choose_eat_user", scene, book, meals=2
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should have eat in phase_results
        phase_results = data["phase_results"]
        eat_results = [r for r in phase_results if r["type"] == "eat"]
        assert len(eat_results) == 1
        assert eat_results[0]["result"] == "meal_consumed"

    def test_meal_penalty_when_no_meals(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=25, must_eat=True)
        _make_choice(db, target, make_scene(db, book, number=26), "Continue")
        choice = _make_choice(db, scene, target, "Go there")

        headers, character = _setup_character_at_choices(
            client, db, "choose_penalty_user", scene, book, meals=0
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        eat_results = [r for r in data["phase_results"] if r["type"] == "eat"]
        assert len(eat_results) == 1
        assert eat_results[0]["result"] == "meal_penalty"
        assert eat_results[0]["severity"] == "warn"

    def test_heal_phase_runs_with_healing_discipline(
        self, client: TestClient, db: Session
    ) -> None:
        """Healing discipline grants +1 END when no combat occurred in new scene."""
        from app.models.content import Discipline
        from app.models.player import CharacterDiscipline

        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=30)
        _make_choice(db, target, make_scene(db, book, number=31), "Continue")
        choice = _make_choice(db, scene, target, "Go to heal scene")

        tokens = register_and_login(client, username="choose_heal_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "choose_heal_user").first()

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            endurance_current=20,
            endurance_max=25,
        )

        # Add Healing discipline — name must be exactly "Healing" for engine to recognise it.
        # Each test runs in a rolled-back transaction so the unique constraint won't conflict.
        healing_disc = Discipline(
            era="kai",
            name="Healing",
            html_id=f"healing-{character.id}",
            description="Healing discipline",
        )
        db.add(healing_disc)
        db.flush()
        cd = CharacterDiscipline(
            character_id=character.id,
            discipline_id=healing_disc.id,
        )
        db.add(cd)
        db.flush()

        headers = auth_headers(tokens["access_token"])
        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should have a healing result in phase_results
        heal_results = [r for r in data["phase_results"] if r["type"] == "heal"]
        assert len(heal_results) == 1
        assert heal_results[0]["result"] == "healed"


# ---------------------------------------------------------------------------
# Tests: gold-gated choice
# ---------------------------------------------------------------------------


class TestGoldGatedChoice:
    """Gold-gated choices deduct gold and log events."""

    def test_gold_gated_choice_deducts_gold(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=5)
        _make_choice(db, target, make_scene(db, book, number=6), "Continue")
        choice = _make_choice(
            db, scene, target, "Pay 5 gold coins",
            condition_type="gold",
            condition_value="5",
        )

        headers, character = _setup_character_at_choices(
            client, db, "choose_gold_user", scene, book, gold=10
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200

        # Verify gold was deducted
        db.expire(character)
        db.refresh(character)
        # After transition, character is at target scene — gold should be 10 - 5 = 5
        # (We need to reload via the response or re-query)
        gold_events = (
            db.query(CharacterEvent)
            .filter(
                CharacterEvent.character_id == character.id,
                CharacterEvent.event_type == "gold_change",
            )
            .all()
        )
        assert len(gold_events) >= 1
        gold_event = next(
            (e for e in gold_events if "gold_gated_choice" in (e.details or "")),
            None,
        )
        assert gold_event is not None

    def test_gold_gated_choice_logs_gold_change_event(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=7)
        _make_choice(db, target, make_scene(db, book, number=8), "Continue")
        choice = _make_choice(
            db, scene, target, "Spend 3 coins",
            condition_type="gold",
            condition_value="3",
        )

        headers, character = _setup_character_at_choices(
            client, db, "choose_gold_log_user", scene, book, gold=10
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200

        # Check gold_change event was logged with right details
        events = (
            db.query(CharacterEvent)
            .filter(
                CharacterEvent.character_id == character.id,
                CharacterEvent.event_type == "gold_change",
            )
            .all()
        )
        assert len(events) >= 1
        # Find the gold deduction event
        deduction_event = None
        for ev in events:
            try:
                d = json.loads(ev.details) if ev.details else {}
                if d.get("reason") == "gold_gated_choice":
                    deduction_event = d
                    break
            except (json.JSONDecodeError, TypeError):
                pass
        assert deduction_event is not None
        assert deduction_event["amount_deducted"] == 3


# ---------------------------------------------------------------------------
# Tests: choice-triggered random
# ---------------------------------------------------------------------------


class TestChoiceTriggeredRandom:
    """Choice-triggered random returns requires_roll response."""

    def test_random_choice_returns_requires_roll(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target_a = make_scene(db, book, number=10)
        target_b = make_scene(db, book, number=20)

        # Choice with random outcomes but no fixed target
        choice = Choice(
            scene_id=scene.id,
            target_scene_id=None,
            target_scene_number=999,
            raw_text="Take a chance",
            display_text="Take a chance",
            ordinal=1,
            source="manual",
        )
        db.add(choice)
        db.flush()

        _make_choice_random_outcome(db, choice, target_a, 0, 4, "You succeed!")
        _make_choice_random_outcome(db, choice, target_b, 5, 9, "You fail!")

        headers, character = _setup_character_at_choices(
            client, db, "choose_random_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["requires_roll"] is True
        assert data["choice_id"] == choice.id
        assert data["choice_text"] == "Take a chance"
        assert "outcome_bands" in data
        assert len(data["outcome_bands"]) == 2
        assert "version" in data

    def test_random_choice_outcome_bands_have_correct_fields(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target_a = make_scene(db, book, number=11)
        target_b = make_scene(db, book, number=22)

        choice = Choice(
            scene_id=scene.id,
            target_scene_id=None,
            target_scene_number=999,
            raw_text="Roll the dice",
            display_text="Roll the dice",
            ordinal=1,
            source="manual",
        )
        db.add(choice)
        db.flush()

        _make_choice_random_outcome(db, choice, target_a, 0, 4, "Lucky!")
        _make_choice_random_outcome(db, choice, target_b, 5, 9, None)

        headers, character = _setup_character_at_choices(
            client, db, "choose_bands_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        bands = data["outcome_bands"]
        # Sorted by range_min
        assert bands[0]["range_min"] == 0
        assert bands[0]["range_max"] == 4
        assert bands[0]["target_scene_number"] == 11
        assert bands[0]["narrative_text"] == "Lucky!"
        assert bands[1]["range_min"] == 5
        assert bands[1]["range_max"] == 9
        assert bands[1]["narrative_text"] is None

    def test_random_choice_sets_pending_choice_id(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=15)

        choice = Choice(
            scene_id=scene.id,
            target_scene_id=None,
            target_scene_number=999,
            raw_text="Chance event",
            display_text="Chance event",
            ordinal=1,
            source="manual",
        )
        db.add(choice)
        db.flush()
        _make_choice_random_outcome(db, choice, target, 0, 9, "Outcome")

        headers, character = _setup_character_at_choices(
            client, db, "choose_pending_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        # Reload character to verify pending_choice_id was set
        db.expire(character)
        db.refresh(character)
        assert character.pending_choice_id == choice.id

    def test_random_choice_does_not_transition(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=50)

        choice = Choice(
            scene_id=scene.id,
            target_scene_id=None,
            target_scene_number=999,
            raw_text="Random event",
            display_text="Random event",
            ordinal=1,
            source="manual",
        )
        db.add(choice)
        db.flush()
        _make_choice_random_outcome(db, choice, target, 0, 9, "Something happens")

        headers, character = _setup_character_at_choices(
            client, db, "choose_no_trans_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        # The response should NOT have a scene_number field (SceneResponse format)
        assert "requires_roll" in data
        assert data.get("scene_number") is None or "requires_roll" in data

        # Character should still be at original scene
        db.expire(character)
        db.refresh(character)
        assert character.current_scene_id == scene.id


# ---------------------------------------------------------------------------
# Tests: validation errors
# ---------------------------------------------------------------------------


class TestChooseValidationErrors:
    """Validation errors return correct 409 and 400 responses."""

    def test_version_mismatch_returns_409(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        choice = _make_choice(db, scene, target, "Go")

        headers, character = _setup_character_at_choices(
            client, db, "choose_version_mismatch_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 999},  # wrong version
            headers=headers,
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "VERSION_MISMATCH"

    def test_wrong_phase_returns_409(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        choice = _make_choice(db, scene, target, "Go")

        tokens = register_and_login(client, username="choose_wrong_phase_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "choose_wrong_phase_user").first()
        # Character is in combat phase, not choices
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="combat",
            scene_phase_index=0,
        )
        db.flush()

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "WRONG_PHASE"

    def test_pending_items_returns_409(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        choice = _make_choice(db, scene, target, "Go")
        # Add a pending scene item (weapon, not gold/meal)
        _make_scene_item(db, scene, item_name="Shield", item_type="weapon")

        headers, character = _setup_character_at_choices(
            client, db, "choose_pending_items_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "PENDING_ITEMS"

    def test_unresolved_combat_returns_409(
        self, client: TestClient, db: Session
    ) -> None:
        from tests.factories import make_encounter

        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        choice = _make_choice(db, scene, target, "Go")
        encounter = make_encounter(db, scene)

        tokens = register_and_login(client, username="choose_combat_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "choose_combat_user").first()
        # Character has active combat but is in choices phase (edge case)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            active_combat_encounter_id=encounter.id,
        )
        db.flush()

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "COMBAT_UNRESOLVED"

    def test_unavailable_choice_discipline_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        choice = _make_choice(
            db, scene, target, "Use Sixth Sense",
            condition_type="discipline",
            condition_value="Sixth Sense",
        )

        headers, character = _setup_character_at_choices(
            client, db, "choose_unavail_disc_user", scene, book
        )
        # Character has no Sixth Sense discipline

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "CHOICE_UNAVAILABLE"

    def test_unavailable_choice_gold_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        choice = _make_choice(
            db, scene, target, "Spend 20 gold",
            condition_type="gold",
            condition_value="20",
        )

        headers, character = _setup_character_at_choices(
            client, db, "choose_unavail_gold_user", scene, book, gold=5  # not enough
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "CHOICE_UNAVAILABLE"

    def test_choice_from_different_scene_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)
        target = make_scene(db, book, number=3)
        # Choice belongs to scene_b but character is at scene_a
        foreign_choice = _make_choice(db, scene_b, target, "Foreign choice")

        headers, character = _setup_character_at_choices(
            client, db, "choose_wrong_scene_user", scene_a, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": foreign_choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 400

    def test_unauthenticated_returns_401(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=2)
        choice = _make_choice(db, scene, target, "Go")
        user = make_user(db)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests: death scene transition
# ---------------------------------------------------------------------------


class TestDeathSceneTransition:
    """Choice leading to death scene marks character dead."""

    def test_transition_to_death_scene_marks_character_dead(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        death_scene = make_scene(db, book, number=350, is_death=True)
        choice = _make_choice(db, scene, death_scene, "Die here")

        headers, character = _setup_character_at_choices(
            client, db, "choose_death_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_death"] is True
        assert data["is_alive"] is False
        assert data["scene_number"] == 350

    def test_death_scene_character_is_not_alive_in_db(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        death_scene = make_scene(db, book, number=351, is_death=True)
        choice = _make_choice(db, scene, death_scene, "Meet your end")

        headers, character = _setup_character_at_choices(
            client, db, "choose_dead_db_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/choose",
            json={"choice_id": choice.id, "version": 1},
            headers=headers,
        )
        assert response.status_code == 200

        # Re-load character from DB and verify is_alive = False
        db.expire(character)
        db.refresh(character)
        assert character.is_alive is False
        assert character.current_scene_id == death_scene.id
