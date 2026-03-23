"""Integration tests for POST /gameplay/{character_id}/roll (Story 6.5).

Tests cover all three dispatch paths:
 1. Choice-triggered random (pending_choice_id set)
 2. Phase-based random with in-scene effects (gold_change, scene_redirect)
 3. Scene-level random exit (all choices are random-gated)

Plus error and edge-case tests:
 - 409 when not in random phase and no pending choice
 - Multi-roll scene (two roll groups)
 - Redirect depth limit enforcement (409 at depth > 5)
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import (
    Choice,
    ChoiceRandomOutcome,
    RandomOutcome,
    Scene,
)
from app.models.player import CharacterEvent
from tests.factories import make_book, make_character, make_scene, make_user
from tests.helpers.auth import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _make_choice(
    db: Session,
    scene: Scene,
    target_scene: Scene | None = None,
    display_text: str = "Go forward",
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


def _make_random_outcome(
    db: Session,
    scene: Scene,
    roll_group: int = 0,
    range_min: int = 0,
    range_max: int = 9,
    effect_type: str = "gold_change",
    effect_value: str = "5",
    narrative_text: str | None = "You find some gold.",
    ordinal: int = 1,
) -> RandomOutcome:
    """Create a RandomOutcome row for the given scene."""
    ro = RandomOutcome(
        scene_id=scene.id,
        roll_group=roll_group,
        range_min=range_min,
        range_max=range_max,
        effect_type=effect_type,
        effect_value=effect_value,
        narrative_text=narrative_text,
        ordinal=ordinal,
        source="manual",
    )
    db.add(ro)
    db.flush()
    return ro


def _setup_character_at_random(
    client: TestClient,
    db: Session,
    username: str,
    scene: Scene,
    book,
    gold: int = 10,
    meals: int = 2,
    endurance_current: int = 25,
) -> tuple[dict, object]:
    """Register user, log in, and place character in 'random' phase at the given scene."""
    tokens = register_and_login(client, username=username, password="pass1234!")
    from app.models.player import User

    user = db.query(User).filter(User.username == username).first()
    character = make_character(
        db,
        user,
        book,
        current_scene_id=scene.id,
        scene_phase="random",
        scene_phase_index=0,
        gold=gold,
        meals=meals,
        endurance_current=endurance_current,
    )
    db.flush()
    return auth_headers(tokens["access_token"]), character


def _setup_character_at_choices(
    client: TestClient,
    db: Session,
    username: str,
    scene: Scene,
    book,
    gold: int = 10,
    meals: int = 2,
) -> tuple[dict, object]:
    """Register user, log in, and place character in 'choices' phase at the given scene."""
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
    )
    db.flush()
    return auth_headers(tokens["access_token"]), character


# ---------------------------------------------------------------------------
# Tests: 409 when not in roll state
# ---------------------------------------------------------------------------


class TestNotInRollState:
    """Roll returns 409 when character is not in a rollable state."""

    def test_409_when_in_choices_phase_no_pending_choice(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        _make_choice(db, scene, make_scene(db, book, number=2), "Go north")

        headers, character = _setup_character_at_choices(
            client, db, "roll_not_random_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/roll",
            json={"version": character.version},
            headers=headers,
        )
        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "NOT_IN_RANDOM_PHASE"

    def test_409_includes_error_code(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=10)
        _make_choice(db, scene, make_scene(db, book, number=11), "Continue")

        headers, character = _setup_character_at_choices(
            client, db, "roll_error_code_user", scene, book
        )

        response = client.post(
            f"/gameplay/{character.id}/roll",
            json={"version": character.version},
            headers=headers,
        )
        assert response.status_code == 409
        assert "NOT_IN_RANDOM_PHASE" in response.json()["error_code"]


# ---------------------------------------------------------------------------
# Tests: choice-triggered random resolution
# ---------------------------------------------------------------------------


class TestChoiceTriggeredRandom:
    """Roll resolves choice-triggered random outcomes when pending_choice_id is set."""

    def test_choice_outcome_transitions_to_correct_scene(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target_a = make_scene(db, book, number=50)
        target_b = make_scene(db, book, number=75)

        # Target scenes need choices so phase can reach 'choices'
        _make_choice(db, target_a, make_scene(db, book, number=51), "Continue A")
        _make_choice(db, target_b, make_scene(db, book, number=76), "Continue B")

        choice = _make_choice(db, scene, target_scene=None, display_text="Attempt escape")
        _make_choice_random_outcome(db, choice, target_a, range_min=0, range_max=4)
        _make_choice_random_outcome(db, choice, target_b, range_min=5, range_max=9)

        tokens = register_and_login(
            client, username="roll_choice_outcome_user", password="pass1234!"
        )
        from app.models.player import User

        user = db.query(User).filter(User.username == "roll_choice_outcome_user").first()
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        character.pending_choice_id = choice.id
        db.flush()

        headers = auth_headers(tokens["access_token"])

        # Force roll of 3 → target_a (scene 50)
        with patch("random.randint", return_value=3):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["random_type"] == "choice_outcome"
        assert data["random_number"] == 3
        assert data["scene_number"] == 50

    def test_choice_outcome_returns_narrative_and_version(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=80)
        _make_choice(db, target, make_scene(db, book, number=81), "Onward")

        choice = _make_choice(db, scene, target_scene=None, display_text="Try your luck")
        _make_choice_random_outcome(
            db, choice, target, range_min=0, range_max=9, narrative_text="You escape safely."
        )

        tokens = register_and_login(
            client, username="roll_narrative_user", password="pass1234!"
        )
        from app.models.player import User

        user = db.query(User).filter(User.username == "roll_narrative_user").first()
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        character.pending_choice_id = choice.id
        db.flush()

        headers = auth_headers(tokens["access_token"])
        initial_version = character.version

        with patch("random.randint", return_value=5):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": initial_version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["outcome_text"] == "You escape safely."
        assert data["version"] > initial_version

    def test_choice_outcome_clears_pending_choice_id(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target = make_scene(db, book, number=100)
        _make_choice(db, target, make_scene(db, book, number=101), "Continue")

        choice = _make_choice(db, scene, target_scene=None, display_text="Gamble")
        _make_choice_random_outcome(db, choice, target, range_min=0, range_max=9)

        tokens = register_and_login(
            client, username="roll_clear_pending_user", password="pass1234!"
        )
        from app.models.player import User

        user = db.query(User).filter(User.username == "roll_clear_pending_user").first()
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        character.pending_choice_id = choice.id
        db.flush()

        headers = auth_headers(tokens["access_token"])

        with patch("random.randint", return_value=7):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        db.refresh(character)
        assert character.pending_choice_id is None

    def test_choice_outcome_different_roll_different_target(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        target_low = make_scene(db, book, number=20)
        target_high = make_scene(db, book, number=30)
        _make_choice(db, target_low, make_scene(db, book, number=21), "Continue")
        _make_choice(db, target_high, make_scene(db, book, number=31), "Continue")

        choice = _make_choice(db, scene, target_scene=None, display_text="Take the chance")
        _make_choice_random_outcome(db, choice, target_low, range_min=0, range_max=4)
        _make_choice_random_outcome(db, choice, target_high, range_min=5, range_max=9)

        tokens = register_and_login(
            client, username="roll_high_user", password="pass1234!"
        )
        from app.models.player import User

        user = db.query(User).filter(User.username == "roll_high_user").first()
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        character.pending_choice_id = choice.id
        db.flush()

        headers = auth_headers(tokens["access_token"])

        # Roll 8 → target_high (scene 30)
        with patch("random.randint", return_value=8):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        assert response.json()["scene_number"] == 30


# ---------------------------------------------------------------------------
# Tests: phase-based random with in-scene effect
# ---------------------------------------------------------------------------


class TestPhaseBasedRandom:
    """Phase-based random resolves effect from random_outcomes table."""

    def test_gold_change_effect_applied(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=1)
        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="12",
            narrative_text="You find 12 Gold Crowns."
        )
        # Need a choices phase after random
        _make_choice(db, scene, make_scene(db, book, number=2), "Continue")

        headers, character = _setup_character_at_random(
            client, db, "roll_gold_change_user", scene, book, gold=5
        )
        initial_version = character.version

        with patch("random.randint", return_value=4):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": initial_version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["random_type"] == "phase_effect"
        assert data["random_number"] == 4
        assert data["effect_type"] == "gold_change"
        assert data["version"] > initial_version

        # Verify gold was updated in DB
        db.refresh(character)
        # gold capped at 50, 5 + 12 = 17
        assert character.gold == 17

    def test_phase_effect_returns_outcome_text(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=5)
        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="3",
            narrative_text="You discover a small purse of coins."
        )
        _make_choice(db, scene, make_scene(db, book, number=6), "Proceed")

        headers, character = _setup_character_at_random(
            client, db, "roll_outcome_text_user", scene, book
        )

        with patch("random.randint", return_value=2):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["outcome_text"] == "You discover a small purse of coins."

    def test_phase_effect_phase_complete_when_single_group(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=7)
        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="1"
        )
        _make_choice(db, scene, make_scene(db, book, number=8), "Go on")

        headers, character = _setup_character_at_random(
            client, db, "roll_phase_complete_user", scene, book
        )

        with patch("random.randint", return_value=0):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["phase_complete"] is True
        assert data["rolls_remaining"] == 0
        assert data["current_roll_group"] == 0

    def test_phase_complete_advances_to_choices(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=9)
        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="2"
        )
        _make_choice(db, scene, make_scene(db, book, number=10), "Move on")

        headers, character = _setup_character_at_random(
            client, db, "roll_advance_choices_user", scene, book
        )

        with patch("random.randint", return_value=5):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        db.refresh(character)
        assert character.scene_phase == "choices"

    def test_random_roll_event_logged(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=11)
        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="endurance_change", effect_value="-2"
        )
        _make_choice(db, scene, make_scene(db, book, number=12), "Continue")

        headers, character = _setup_character_at_random(
            client, db, "roll_event_logged_user", scene, book
        )

        with patch("random.randint", return_value=6):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        event = (
            db.query(CharacterEvent)
            .filter(
                CharacterEvent.character_id == character.id,
                CharacterEvent.event_type == "random_roll",
            )
            .first()
        )
        assert event is not None
        details = json.loads(event.details)
        assert details["random_number"] == 6
        assert details["roll_group"] == 0


# ---------------------------------------------------------------------------
# Tests: multi-roll scene (two roll groups)
# ---------------------------------------------------------------------------


class TestMultiRollScene:
    """Scene with two roll groups requires two /roll calls."""

    def test_first_roll_returns_rolls_remaining_1(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=20)

        # Group 0: gold_change
        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="3", ordinal=1
        )
        # Group 1: endurance_change
        _make_random_outcome(
            db, scene, roll_group=1, range_min=0, range_max=9,
            effect_type="endurance_change", effect_value="-1", ordinal=2
        )
        _make_choice(db, scene, make_scene(db, book, number=21), "Continue")

        headers, character = _setup_character_at_random(
            client, db, "roll_multi_first_user", scene, book, gold=5
        )

        with patch("random.randint", return_value=3):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["random_type"] == "phase_effect"
        assert data["rolls_remaining"] == 1
        assert data["phase_complete"] is False
        assert data["current_roll_group"] == 0

    def test_second_roll_completes_phase(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=22)

        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="2", ordinal=1
        )
        _make_random_outcome(
            db, scene, roll_group=1, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="1", ordinal=2
        )
        _make_choice(db, scene, make_scene(db, book, number=23), "Continue")

        headers, character = _setup_character_at_random(
            client, db, "roll_multi_second_user", scene, book, gold=5
        )

        # First roll
        with patch("random.randint", return_value=1):
            r1 = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )
        assert r1.status_code == 200
        assert r1.json()["rolls_remaining"] == 1

        db.refresh(character)

        # Second roll
        with patch("random.randint", return_value=5):
            r2 = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )
        assert r2.status_code == 200
        data = r2.json()
        assert data["rolls_remaining"] == 0
        assert data["phase_complete"] is True
        assert data["current_roll_group"] == 1

    def test_second_roll_resolves_group_1(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=24)

        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="gold_change", effect_value="2", ordinal=1
        )
        _make_random_outcome(
            db, scene, roll_group=1, range_min=0, range_max=9,
            effect_type="endurance_change", effect_value="-3", ordinal=2
        )
        _make_choice(db, scene, make_scene(db, book, number=25), "Continue")

        headers, character = _setup_character_at_random(
            client, db, "roll_multi_group1_user", scene, book, endurance_current=20
        )

        # First roll (group 0)
        with patch("random.randint", return_value=4):
            r1 = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )
        assert r1.status_code == 200

        db.refresh(character)

        # Second roll (group 1)
        with patch("random.randint", return_value=7):
            r2 = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )
        assert r2.status_code == 200
        data = r2.json()
        assert data["current_roll_group"] == 1
        # Endurance should have been reduced by 3
        db.refresh(character)
        assert character.endurance_current == 17


# ---------------------------------------------------------------------------
# Tests: scene_redirect (heal completes before redirect)
# ---------------------------------------------------------------------------


class TestSceneRedirect:
    """scene_redirect effect transitions character after completing heal phase."""

    def test_redirect_transitions_to_target_scene(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=30)
        redirect_target = make_scene(db, book, number=150)
        _make_choice(db, redirect_target, make_scene(db, book, number=151), "Continue")

        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="scene_redirect", effect_value=str(redirect_target.id),
            narrative_text="You fall through a trapdoor."
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_redirect_user", scene, book
        )

        with patch("random.randint", return_value=2):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["random_type"] == "phase_effect"
        assert data["effect_type"] == "scene_redirect"
        assert data["scene_number"] == 150
        assert data["narrative"] is not None

    def test_redirect_returns_phase_complete(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=31)
        redirect_target = make_scene(db, book, number=160)
        _make_choice(db, redirect_target, make_scene(db, book, number=161), "Continue")

        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="scene_redirect", effect_value=str(redirect_target.id)
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_redirect_complete_user", scene, book
        )

        with patch("random.randint", return_value=0):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["phase_complete"] is True
        assert data["rolls_remaining"] == 0

    def test_redirect_character_moves_to_new_scene(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=32)
        redirect_target = make_scene(db, book, number=170)
        _make_choice(db, redirect_target, make_scene(db, book, number=171), "Continue")

        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="scene_redirect", effect_value=str(redirect_target.id)
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_redirect_scene_move_user", scene, book
        )

        with patch("random.randint", return_value=4):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        db.refresh(character)
        assert character.current_scene_id == redirect_target.id


# ---------------------------------------------------------------------------
# Tests: scene-level random exit
# ---------------------------------------------------------------------------


class TestSceneExitRandom:
    """All choices are random-gated: roll determines which scene to navigate to."""

    def test_low_roll_goes_to_low_target(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=40)
        target_low = make_scene(db, book, number=200)
        target_high = make_scene(db, book, number=210)
        _make_choice(db, target_low, make_scene(db, book, number=201), "Continue")
        _make_choice(db, target_high, make_scene(db, book, number=211), "Continue")

        # All choices are random-gated
        _make_choice(
            db, scene, target_low, "Take the left path.",
            ordinal=1, condition_type="random", condition_value="0-4"
        )
        _make_choice(
            db, scene, target_high, "Take the right path.",
            ordinal=2, condition_type="random", condition_value="5-9"
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_scene_exit_low_user", scene, book
        )

        with patch("random.randint", return_value=2):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["random_type"] == "scene_exit"
        assert data["scene_number"] == 200

    def test_high_roll_goes_to_high_target(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=41)
        target_low = make_scene(db, book, number=220)
        target_high = make_scene(db, book, number=230)
        _make_choice(db, target_low, make_scene(db, book, number=221), "Continue")
        _make_choice(db, target_high, make_scene(db, book, number=231), "Continue")

        _make_choice(
            db, scene, target_low, "Go left.",
            ordinal=1, condition_type="random", condition_value="0-4"
        )
        _make_choice(
            db, scene, target_high, "Go right.",
            ordinal=2, condition_type="random", condition_value="5-9"
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_scene_exit_high_user", scene, book
        )

        with patch("random.randint", return_value=7):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["random_type"] == "scene_exit"
        assert data["scene_number"] == 230

    def test_scene_exit_includes_narrative_and_phase_results(
        self, client: TestClient, db: Session
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, number=42)
        target = make_scene(db, book, number=240)
        _make_choice(db, target, make_scene(db, book, number=241), "Go on")

        _make_choice(
            db, scene, target, "Follow the path.",
            ordinal=1, condition_type="random", condition_value="0-9"
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_scene_exit_narrative_user", scene, book
        )
        initial_version = character.version

        with patch("random.randint", return_value=3):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": initial_version},
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "narrative" in data
        assert "phase_results" in data
        assert data["version"] > initial_version

    def test_scene_exit_creates_decision_log_entry(
        self, client: TestClient, db: Session
    ) -> None:
        from app.models.player import DecisionLog

        book = make_book(db)
        scene = make_scene(db, book, number=43)
        target = make_scene(db, book, number=250)
        _make_choice(db, target, make_scene(db, book, number=251), "Continue")

        _make_choice(
            db, scene, target, "Roll to escape.",
            ordinal=1, condition_type="random", condition_value="0-9"
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_scene_exit_log_user", scene, book
        )

        with patch("random.randint", return_value=5):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 200
        log = (
            db.query(DecisionLog)
            .filter(
                DecisionLog.character_id == character.id,
                DecisionLog.action_type == "random",
            )
            .first()
        )
        assert log is not None
        assert log.to_scene_id == target.id


# ---------------------------------------------------------------------------
# Tests: redirect depth limit
# ---------------------------------------------------------------------------


class TestRedirectDepthLimit:
    """Roll returns 409 when redirect depth exceeds MAX_REDIRECT_DEPTH."""

    def test_redirect_depth_exceeded_returns_409(
        self, client: TestClient, db: Session
    ) -> None:
        from app.models.player import CharacterEvent as CE
        from datetime import UTC, datetime

        book = make_book(db)
        scene = make_scene(db, book, number=50)
        redirect_target = make_scene(db, book, number=300)
        _make_choice(db, redirect_target, make_scene(db, book, number=301), "Continue")

        _make_random_outcome(
            db, scene, roll_group=0, range_min=0, range_max=9,
            effect_type="scene_redirect", effect_value=str(redirect_target.id)
        )

        headers, character = _setup_character_at_random(
            client, db, "roll_depth_limit_user", scene, book
        )

        # Pre-populate 5 random_roll events at this scene to simulate prior redirects
        from app.events import log_character_event

        for i in range(5):
            log_character_event(
                db,
                character,
                "random_roll",
                scene_id=scene.id,
                phase="random",
                details={
                    "random_type": "phase_effect",
                    "random_number": i,
                    "roll_group": 0,
                    "effects_applied": [{"type": "scene_redirect"}],
                    "narrative_text": "redirect",
                    "scene_redirect": redirect_target.id,
                },
            )
        db.flush()

        with patch("random.randint", return_value=3):
            response = client.post(
                f"/gameplay/{character.id}/roll",
                json={"version": character.version},
                headers=headers,
            )

        assert response.status_code == 409
        data = response.json()
        assert data["error_code"] == "REDIRECT_DEPTH_EXCEEDED"
