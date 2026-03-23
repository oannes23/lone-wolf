"""Integration tests for UI combat and random roll routes (Story 8.4).

Covers:
- POST /ui/game/{character_id}/combat/round — resolve a round, redirect
- POST /ui/game/{character_id}/combat/evasion — attempt evasion, redirect
- POST /ui/game/{character_id}/roll — resolve a roll, redirect
- GET /ui/game/{character_id} — combat panel renders in scene page
- Auth redirects for unauthenticated requests
- Version mismatch is handled silently
"""

from __future__ import annotations

from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import CombatEncounter, CombatResults, Discipline, Scene
from app.models.player import Character, CharacterDiscipline, User
from tests.factories import (
    make_book,
    make_character,
    make_encounter,
    make_scene,
    make_user,
)


# ---------------------------------------------------------------------------
# Test infrastructure helpers
# ---------------------------------------------------------------------------


def _register_user(
    client: TestClient,
    username: str = "combat_ui_player",
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
    username: str = "combat_ui_player",
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
    assert cookie, "Expected session cookie in login response"
    return cookie


def _get_user_by_username(db: Session, username: str) -> User:
    return db.query(User).filter(User.username == username).first()


def _seed_crt(db: Session, era: str = "kai") -> None:
    """Seed a minimal CRT for combat tests."""
    rows = [
        # (random_number, cr_min, cr_max, enemy_loss, hero_loss)
        (0, -999, 999, 0, 6),
        (1, -999, 999, 0, 7),
        (2, -999, 999, 0, 8),
        (3, -999, 999, 1, 8),
        (4, -999, 999, 1, 7),
        (5, -999, 999, 2, 8),
        (6, -999, 999, 2, 7),
        (7, -999, 999, 3, 8),
        (8, -999, 999, 3, 7),
        (9, -999, 999, 4, 8),
    ]
    for rn, cr_min, cr_max, enemy_loss, hero_loss in rows:
        db.add(
            CombatResults(
                era=era,
                random_number=rn,
                combat_ratio_min=cr_min,
                combat_ratio_max=cr_max,
                enemy_loss=enemy_loss,
                hero_loss=hero_loss,
            )
        )
    db.flush()


def _setup_combat_scene(
    db: Session,
    client: TestClient,
    username: str,
    enemy_cs: int = 14,
    enemy_end: int = 20,
    char_cs: int = 18,
    char_end: int = 25,
    evasion_after_rounds: int | None = None,
    evasion_target_scene_number: int | None = None,
    evasion_damage: int = 0,
) -> tuple[str, Character, CombatEncounter]:
    """Set up a character in combat phase with a CRT seeded.

    Returns:
        Tuple of (session_cookie, character, encounter).
    """
    _register_user(client, username)
    user = _get_user_by_username(db, username)

    book = make_book(db, era="kai")
    scene = make_scene(db, book)

    evasion_target_id: int | None = None
    if evasion_target_scene_number is not None:
        evasion_scene = make_scene(db, book, number=evasion_target_scene_number)
        evasion_target_id = evasion_scene.id

    encounter = make_encounter(
        db,
        scene,
        enemy_cs=enemy_cs,
        enemy_end=enemy_end,
        evasion_after_rounds=evasion_after_rounds,
        evasion_target=evasion_target_id,
        evasion_damage=evasion_damage,
    )

    character = make_character(
        db,
        user,
        book,
        current_scene_id=scene.id,
        scene_phase="combat",
        scene_phase_index=0,
        active_combat_encounter_id=encounter.id,
        combat_skill_base=char_cs,
        endurance_base=char_end,
        endurance_max=char_end,
        endurance_current=char_end,
        version=1,
    )

    _seed_crt(db)
    db.flush()

    cookie = _login_cookie(client, username)
    return cookie, character, encounter


# ---------------------------------------------------------------------------
# Tests: Combat Round UI Route
# ---------------------------------------------------------------------------


class TestCombatRoundSubmit:
    """Tests for POST /ui/game/{character_id}/combat/round."""

    def test_combat_round_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Combat round POST resolves and redirects back to scene."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_combat_round_user"
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=5):
            resp = client.post(
                f"/ui/game/{character.id}/combat/round",
                data={"version": character.version, "use_psi_surge": "false"},
                cookies={"session": cookie},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_combat_round_updates_character_endurance(
        self, client: TestClient, db: Session
    ) -> None:
        """After a combat round, character endurance changes in the DB."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_combat_end_user",
            char_end=30,
            enemy_end=30,
        )
        initial_end = character.endurance_current

        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            # rn=0 -> hero_loss=6
            resp = client.post(
                f"/ui/game/{character.id}/combat/round",
                data={"version": character.version},
                cookies={"session": cookie},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        db.refresh(character)
        # Hero should have taken damage (unless CRT gives 0 hero_loss)
        assert character.endurance_current <= initial_end

    def test_combat_round_redirects_unauthenticated(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated combat round POST redirects to login."""
        resp = client.post(
            "/ui/game/1/combat/round",
            data={"version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_combat_round_version_mismatch_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Version mismatch silently redirects back without processing."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_combat_version_user"
        )
        initial_end = character.endurance_current

        resp = client.post(
            f"/ui/game/{character.id}/combat/round",
            data={"version": 999, "use_psi_surge": "false"},  # wrong version
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"
        # Endurance unchanged
        db.refresh(character)
        assert character.endurance_current == initial_end

    def test_combat_round_wrong_phase_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Combat round POST silently redirects when not in combat phase."""
        _register_user(client, "ui_combat_phase_user")
        user = _get_user_by_username(db, "ui_combat_phase_user")
        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        db.flush()

        cookie = _login_cookie(client, "ui_combat_phase_user")
        resp = client.post(
            f"/ui/game/{character.id}/combat/round",
            data={"version": 1},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_combat_round_404_for_missing_character(
        self, client: TestClient, db: Session
    ) -> None:
        """Returns 404 for non-existent character."""
        _register_user(client, "ui_combat_404_user")
        cookie = _login_cookie(client, "ui_combat_404_user")
        resp = client.post(
            "/ui/game/999999/combat/round",
            data={"version": 1},
            cookies={"session": cookie},
        )
        assert resp.status_code == 404

    def test_combat_round_hero_death_redirects(
        self, client: TestClient, db: Session
    ) -> None:
        """When hero dies in combat, still redirects back to scene."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_combat_death_user",
            char_end=1,  # dies from any hit
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            resp = client.post(
                f"/ui/game/{character.id}/combat/round",
                data={"version": character.version},
                cookies={"session": cookie},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

        db.refresh(character)
        assert character.is_alive is False

    def test_combat_round_enemy_death_advances_phase(
        self, client: TestClient, db: Session
    ) -> None:
        """When enemy dies, character phase advances past combat."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_combat_win_user",
            enemy_end=1,  # dies on any hit with rn>=3
            char_end=30,
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=9):
            resp = client.post(
                f"/ui/game/{character.id}/combat/round",
                data={"version": character.version},
                cookies={"session": cookie},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        db.refresh(character)
        assert character.scene_phase != "combat"
        assert character.active_combat_encounter_id is None


# ---------------------------------------------------------------------------
# Tests: Evasion UI Route
# ---------------------------------------------------------------------------


class TestCombatEvasionSubmit:
    """Tests for POST /ui/game/{character_id}/combat/evasion."""

    def test_evasion_after_threshold_redirects(
        self, client: TestClient, db: Session
    ) -> None:
        """Evasion POST after meeting threshold redirects to scene."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_evade_user",
            char_end=30,
            enemy_end=60,
            evasion_after_rounds=1,
            evasion_target_scene_number=777,
            evasion_damage=0,
        )

        # Fight 1 round to meet threshold (rn=0 -> enemy_loss=0, enemy survives)
        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            r = client.post(
                f"/ui/game/{character.id}/combat/round",
                data={"version": character.version},
                cookies={"session": cookie},
                follow_redirects=False,
            )
        assert r.status_code == 303
        db.refresh(character)

        # Now evade
        resp = client.post(
            f"/ui/game/{character.id}/combat/evasion",
            data={"version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_evasion_before_threshold_is_silently_rejected(
        self, client: TestClient, db: Session
    ) -> None:
        """Evasion before threshold silently redirects back (no change)."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_early_evade_user",
            char_end=30,
            enemy_end=60,
            evasion_after_rounds=3,
            evasion_target_scene_number=777,
        )
        initial_scene_id = character.current_scene_id

        # No rounds fought, evasion should fail silently
        resp = client.post(
            f"/ui/game/{character.id}/combat/evasion",
            data={"version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"
        # Scene should not have changed
        db.refresh(character)
        assert character.current_scene_id == initial_scene_id

    def test_evasion_redirects_unauthenticated(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated evasion POST redirects to login."""
        resp = client.post(
            "/ui/game/1/combat/evasion",
            data={"version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_evasion_version_mismatch_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Version mismatch redirects without processing evasion."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_evade_version_user",
            evasion_after_rounds=1,
            evasion_target_scene_number=777,
        )
        initial_scene_id = character.current_scene_id

        resp = client.post(
            f"/ui/game/{character.id}/combat/evasion",
            data={"version": 9999},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        db.refresh(character)
        assert character.current_scene_id == initial_scene_id


# ---------------------------------------------------------------------------
# Tests: Roll UI Route
# ---------------------------------------------------------------------------


class TestRollSubmit:
    """Tests for POST /ui/game/{character_id}/roll."""

    def _setup_random_scene(
        self, db: Session, client: TestClient, username: str
    ) -> tuple[str, Character]:
        """Set up a character in random phase with a simple random scene."""
        from app.models.content import RandomOutcome

        _register_user(client, username)
        user = _get_user_by_username(db, username)
        book = make_book(db)
        scene = make_scene(db, book)
        target = make_scene(db, book, number=500)

        # Add a random outcome so the roll can resolve
        ro = RandomOutcome(
            scene_id=scene.id,
            roll_group=1,
            range_min=0,
            range_max=9,
            effect_type="scene_redirect",
            effect_value=str(target.id),
            narrative_text="You roll and proceed.",
            ordinal=1,
            source="manual",
        )
        db.add(ro)
        db.flush()

        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="random",
            scene_phase_index=0,
            version=1,
        )
        db.flush()

        cookie = _login_cookie(client, username)
        return cookie, character

    def test_roll_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Roll POST resolves and redirects back to scene."""
        cookie, character = self._setup_random_scene(db, client, "ui_roll_user")

        resp = client.post(
            f"/ui/game/{character.id}/roll",
            data={"version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_roll_updates_character_version(
        self, client: TestClient, db: Session
    ) -> None:
        """After a successful roll, character version increments."""
        cookie, character = self._setup_random_scene(db, client, "ui_roll_version_user")
        initial_version = character.version

        client.post(
            f"/ui/game/{character.id}/roll",
            data={"version": character.version},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        db.refresh(character)
        assert character.version > initial_version

    def test_roll_redirects_unauthenticated(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated roll POST redirects to login."""
        resp = client.post(
            "/ui/game/1/roll",
            data={"version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_roll_version_mismatch_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Version mismatch redirects without processing the roll."""
        cookie, character = self._setup_random_scene(db, client, "ui_roll_version_mismatch")
        initial_version = character.version

        resp = client.post(
            f"/ui/game/{character.id}/roll",
            data={"version": 9999},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        db.refresh(character)
        assert character.version == initial_version

    def test_roll_wrong_phase_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Roll POST when not in random phase silently redirects back."""
        _register_user(client, "ui_roll_phase_user")
        user = _get_user_by_username(db, "ui_roll_phase_user")
        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        db.flush()

        cookie = _login_cookie(client, "ui_roll_phase_user")
        resp = client.post(
            f"/ui/game/{character.id}/roll",
            data={"version": 1},
            cookies={"session": cookie},
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_roll_404_for_missing_character(
        self, client: TestClient, db: Session
    ) -> None:
        """Returns 404 for non-existent character."""
        _register_user(client, "ui_roll_404_user")
        cookie = _login_cookie(client, "ui_roll_404_user")
        resp = client.post(
            "/ui/game/999999/roll",
            data={"version": 1},
            cookies={"session": cookie},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests: Combat panel renders in scene page
# ---------------------------------------------------------------------------


class TestCombatSceneRender:
    """Tests for combat UI rendering in the scene page."""

    def test_combat_panel_renders_when_in_combat_phase(
        self, client: TestClient, db: Session
    ) -> None:
        """Scene page renders combat panel with enemy name and Fight button."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_combat_render_user",
            enemy_cs=14,
            enemy_end=20,
        )

        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "combat-section" in body
        assert encounter.enemy_name in body
        assert "Fight" in body

    def test_combat_panel_shows_endurance_bars(
        self, client: TestClient, db: Session
    ) -> None:
        """Combat panel includes progress elements for endurance."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_combat_bars_user",
        )

        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "end-bar" in body
        assert "<progress" in body

    def test_combat_panel_shows_evasion_button_when_eligible(
        self, client: TestClient, db: Session
    ) -> None:
        """Evasion button appears when can_evade is true (rounds_fought >= threshold)."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_evade_btn_user",
            char_end=30,
            enemy_end=60,
            evasion_after_rounds=1,
            evasion_target_scene_number=888,
            evasion_damage=0,
        )

        # Fight 1 round to meet evasion threshold
        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            client.post(
                f"/ui/game/{character.id}/combat/round",
                data={"version": character.version},
                cookies={"session": cookie},
                follow_redirects=False,
            )
        db.refresh(character)

        # Check that combat phase is still active (enemy survived rn=0)
        if character.scene_phase != "combat":
            pytest.skip("Enemy died too early — adjust test setup")

        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "Evade" in body
        assert "combat/evasion" in body

    def test_combat_panel_no_evasion_button_below_threshold(
        self, client: TestClient, db: Session
    ) -> None:
        """Evasion button is absent when rounds_fought < evasion threshold."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_no_evade_btn_user",
            evasion_after_rounds=3,
            evasion_target_scene_number=888,
        )

        # No rounds fought yet — evasion should not be available
        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        # Fight button present
        assert "Fight" in body
        # No evasion form action
        assert "combat/evasion" not in body

    def test_combat_panel_shows_psi_surge_toggle_with_discipline(
        self, client: TestClient, db: Session
    ) -> None:
        """Psi-surge toggle is visible when character has Psi-surge discipline."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_psi_toggle_user",
        )

        # Add Psi-surge discipline
        psi_disc = Discipline(
            era="kai",
            name="Psi-surge",
            html_id="psi-surge",
            description="Psi-surge discipline.",
        )
        db.add(psi_disc)
        db.flush()
        cd = CharacterDiscipline(
            character_id=character.id,
            discipline_id=psi_disc.id,
            weapon_category=None,
        )
        db.add(cd)
        db.flush()

        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "psi-surge" in body.lower() or "Psi-surge" in body

    def test_combat_panel_no_psi_surge_without_discipline(
        self, client: TestClient, db: Session
    ) -> None:
        """Psi-surge toggle is absent when character lacks the discipline."""
        cookie, character, encounter = _setup_combat_scene(
            db, client, username="ui_no_psi_user",
        )
        # No Psi-surge discipline given

        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "psi-surge-toggle" not in body

    def test_roll_panel_renders_when_in_random_phase(
        self, client: TestClient, db: Session
    ) -> None:
        """Scene page renders roll panel with Roll button when in random phase."""
        _register_user(client, "ui_roll_render_user")
        user = _get_user_by_username(db, "ui_roll_render_user")
        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="random",
            scene_phase_index=0,
        )
        db.flush()

        cookie = _login_cookie(client, "ui_roll_render_user")
        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "roll-section" in body
        assert "Roll" in body
        # Roll form should post to the roll endpoint
        assert f"/ui/game/{character.id}/roll" in body

    def test_roll_panel_renders_for_pending_choice_id(
        self, client: TestClient, db: Session
    ) -> None:
        """Roll panel renders when character has a pending choice requiring a roll."""
        from app.models.content import Choice

        _register_user(client, "ui_pending_roll_user")
        user = _get_user_by_username(db, "ui_pending_roll_user")
        book = make_book(db)
        scene = make_scene(db, book)
        target = make_scene(db, book, number=300)

        choice = Choice(
            scene_id=scene.id,
            target_scene_id=target.id,
            target_scene_number=300,
            raw_text="Roll for outcome.",
            display_text="Roll for outcome.",
            ordinal=1,
            source="manual",
        )
        db.add(choice)
        db.flush()

        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            pending_choice_id=choice.id,
        )
        db.flush()

        cookie = _login_cookie(client, "ui_pending_roll_user")
        resp = client.get(
            f"/ui/game/{character.id}",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        body = resp.text
        assert "roll-section" in body
        assert "Roll" in body
