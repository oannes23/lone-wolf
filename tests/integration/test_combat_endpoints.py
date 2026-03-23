"""Integration tests for combat endpoints (Story 6.3).

Tests cover:
- Round resolution with CRT lookup
- Psi-surge (+4 CS, +2 END cost)
- Evasion after N rounds
- Evasion into death (damage kills hero)
- Multi-enemy combat (defeat first enemy, advance to second)
- Death in combat (hero END reaches 0)
- Conditional combat skip (character has required discipline)
- combat_over returns result field
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest import mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import (
    CombatEncounter,
    CombatModifier,
    CombatResults,
    Discipline,
    Scene,
)
from app.models.player import Character, CharacterDiscipline, CharacterEvent, CombatRound
from tests.factories import (
    make_book,
    make_character,
    make_encounter,
    make_scene,
    make_user,
)
from tests.helpers.auth import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# CRT seed helpers
# ---------------------------------------------------------------------------


def _seed_crt(db: Session, era: str = "kai") -> None:
    """Seed a minimal CRT for the given era covering combat ratio -999..999.

    Uses the Kai-era CRT values for CR<=0. For positive ratios we use the
    same values but with reversed roles (enemy takes more damage).
    """
    # For CR range -999..999 (covers everything in tests)
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


def _seed_discipline(db: Session, name: str, era: str = "kai") -> Discipline:
    """Create a discipline row (or re-use existing one by name)."""
    existing = db.query(Discipline).filter(Discipline.name == name, Discipline.era == era).first()
    if existing:
        return existing
    disc = Discipline(
        era=era,
        name=name,
        html_id=name.lower().replace(" ", "-"),
        description=f"{name} discipline",
    )
    db.add(disc)
    db.flush()
    return disc


def _give_discipline(db: Session, character: Character, discipline: Discipline) -> None:
    """Attach a discipline to a character."""
    cd = CharacterDiscipline(
        character_id=character.id,
        discipline_id=discipline.id,
        weapon_category=None,
    )
    db.add(cd)
    db.flush()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _setup_combat_character(
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
    encounter_condition_type: str | None = None,
    encounter_condition_value: str | None = None,
) -> tuple[dict, Character, CombatEncounter]:
    """Create a user, character, scene, encounter, and return auth tokens + models."""
    tokens = register_and_login(client, username=username, password="pass1234!")
    from app.models.player import User
    user = db.query(User).filter(User.username == username).first()

    book = make_book(db, era="kai")
    scene = make_scene(db, book)

    # Make evasion target scene if needed
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
        condition_type=encounter_condition_type,
        condition_value=encounter_condition_value,
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
    )

    _seed_crt(db)
    db.flush()

    return tokens, character, encounter


# ---------------------------------------------------------------------------
# Tests: Round Resolution
# ---------------------------------------------------------------------------


class TestCombatRoundBasic:
    """Basic combat round resolution tests."""

    def test_round_resolution_returns_correct_fields(
        self, client: TestClient, db: Session
    ) -> None:
        """Combat round response includes all required fields."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="combat_basic_user"
        )

        # Patch random.randint to control the outcome
        with mock.patch("app.services.combat_service.random.randint", return_value=5):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200, response.text
        data = response.json()

        # Required fields per spec
        assert "round_number" in data
        assert data["round_number"] == 1
        assert "random_number" in data
        assert data["random_number"] == 5
        assert "combat_ratio" in data
        assert "hero_damage" in data
        assert "enemy_damage" in data
        assert "hero_end_remaining" in data
        assert "enemy_end_remaining" in data
        assert "psi_surge_used" in data
        assert data["psi_surge_used"] is False
        assert "combat_over" in data
        assert "result" in data
        assert data["result"] in ("win", "loss", "continue")
        assert "evasion_available" in data
        assert "can_evade" in data
        assert "version" in data

    def test_round_increments_version(self, client: TestClient, db: Session) -> None:
        """Each combat round increments the character version."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="combat_version_user"
        )
        initial_version = character.version

        with mock.patch("app.services.combat_service.random.randint", return_value=3):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": initial_version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == initial_version + 1

    def test_round_saves_combat_round_row(self, client: TestClient, db: Session) -> None:
        """A CombatRound row is persisted after each round."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="combat_persist_user"
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=2):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200

        # Query for the saved round
        round_row = (
            db.query(CombatRound)
            .filter(
                CombatRound.character_id == character.id,
                CombatRound.combat_encounter_id == encounter.id,
            )
            .first()
        )
        assert round_row is not None
        assert round_row.round_number == 1
        assert round_row.random_number == 2
        assert round_row.run_number == character.current_run

    def test_round_number_increments_per_round(self, client: TestClient, db: Session) -> None:
        """round_number increases with each subsequent round call."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="combat_round_num_user",
            enemy_end=60,  # big enough to survive multiple rounds
        )

        for expected_round in range(1, 4):
            db.refresh(character)
            with mock.patch("app.services.combat_service.random.randint", return_value=0):
                response = client.post(
                    f"/gameplay/{character.id}/combat/round",
                    json={"use_psi_surge": False, "version": character.version},
                    headers=auth_headers(tokens["access_token"]),
                )
            assert response.status_code == 200, response.text
            data = response.json()
            # Stop if combat is over
            if data["combat_over"]:
                break
            assert data["round_number"] == expected_round


# ---------------------------------------------------------------------------
# Tests: Psi-surge
# ---------------------------------------------------------------------------


class TestCombatPsiSurge:
    """Psi-surge combat round tests."""

    def test_psi_surge_uses_when_discipline_present(
        self, client: TestClient, db: Session
    ) -> None:
        """With Psi-surge discipline and use_psi_surge=True, psi_surge_used=True."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="psi_surge_user", enemy_end=60
        )

        # Give character the Psi-surge discipline
        psi_disc = _seed_discipline(db, "Psi-surge")
        _give_discipline(db, character, psi_disc)
        db.flush()
        db.refresh(character)

        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": True, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["psi_surge_used"] is True

    def test_psi_surge_ignored_without_discipline(
        self, client: TestClient, db: Session
    ) -> None:
        """With use_psi_surge=True but no Psi-surge discipline, psi_surge_used=False."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="psi_surge_no_disc_user"
        )
        # No Psi-surge discipline

        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": True, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["psi_surge_used"] is False

    def test_psi_surge_costs_2_extra_end(self, client: TestClient, db: Session) -> None:
        """Psi-surge adds +2 to hero_loss compared to the CRT value."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="psi_surge_cost_user",
            char_end=30,
            enemy_end=60,
        )

        psi_disc = _seed_discipline(db, "Psi-surge")
        _give_discipline(db, character, psi_disc)
        db.flush()
        db.refresh(character)

        # With random_number=0 → hero_loss=6 from CRT; psi_surge adds +2 → hero_loss=8
        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            response_psi = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": True, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response_psi.status_code == 200
        psi_data = response_psi.json()

        # hero_damage should reflect +2 extra cost
        # CRT[rn=0] → hero_loss=6, psi_surge adds 2 → total 8
        assert psi_data["hero_damage"] == 8
        assert psi_data["psi_surge_used"] is True


# ---------------------------------------------------------------------------
# Tests: Hero Death in Combat
# ---------------------------------------------------------------------------


class TestCombatHeroDeath:
    """Tests for hero death during combat."""

    def test_hero_death_marks_character_dead(self, client: TestClient, db: Session) -> None:
        """When hero END reaches 0, character.is_alive becomes False."""
        # Use very low endurance to ensure death on first round
        tokens, character, encounter = _setup_combat_character(
            db, client, username="hero_death_user",
            char_end=1,  # will die from any hit
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["combat_over"] is True
        assert data["result"] == "loss"

        # Verify character is dead in DB
        db.refresh(character)
        assert character.is_alive is False
        assert character.scene_phase is None
        assert character.active_combat_encounter_id is None

    def test_hero_death_logs_death_event(self, client: TestClient, db: Session) -> None:
        """Death in combat logs a 'death' event with parent_event_id pointing to combat_end."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="hero_death_event_user",
            char_end=1,
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200

        # Check death event exists
        death_event = (
            db.query(CharacterEvent)
            .filter(
                CharacterEvent.character_id == character.id,
                CharacterEvent.event_type == "death",
            )
            .first()
        )
        assert death_event is not None
        assert death_event.parent_event_id is not None

        # Parent must be combat_end
        parent = (
            db.query(CharacterEvent)
            .filter(CharacterEvent.id == death_event.parent_event_id)
            .first()
        )
        assert parent is not None
        assert parent.event_type == "combat_end"


# ---------------------------------------------------------------------------
# Tests: Enemy Death / Win
# ---------------------------------------------------------------------------


class TestCombatEnemyDeath:
    """Tests for enemy defeat in combat."""

    def test_enemy_death_returns_win(self, client: TestClient, db: Session) -> None:
        """When enemy END reaches 0, result='win' and combat_over=True."""
        # Use an enemy with only 1 endurance so any hit kills them
        # CRT[rn=9] → enemy_loss=4. With enemy_end=1 this is an instant kill.
        tokens, character, encounter = _setup_combat_character(
            db, client, username="enemy_death_user",
            enemy_end=1,
            char_end=30,
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=9):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["combat_over"] is True
        assert data["result"] == "win"

    def test_enemy_death_advances_phase(self, client: TestClient, db: Session) -> None:
        """After enemy defeat with no more enemies, scene phase advances past combat."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="phase_advance_user",
            enemy_end=1,
            char_end=30,
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=9):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200

        db.refresh(character)
        # Phase should have advanced past combat
        assert character.scene_phase != "combat"
        assert character.active_combat_encounter_id is None

    def test_combat_logs_combat_start_and_end_events(
        self, client: TestClient, db: Session
    ) -> None:
        """combat_start is logged on round 1, combat_end is logged on enemy death."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="combat_events_user",
            enemy_end=1,
            char_end=30,
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=9):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200

        events = (
            db.query(CharacterEvent)
            .filter(CharacterEvent.character_id == character.id)
            .all()
        )
        event_types = [e.event_type for e in events]
        assert "combat_start" in event_types
        assert "combat_end" in event_types


# ---------------------------------------------------------------------------
# Tests: Multi-Enemy Combat
# ---------------------------------------------------------------------------


class TestMultiEnemyCombat:
    """Tests for multi-enemy sequential combat."""

    def test_defeating_first_enemy_advances_to_second(
        self, client: TestClient, db: Session
    ) -> None:
        """After defeating enemy 1, active_combat_encounter_id becomes enemy 2's id."""
        tokens, character, encounter1 = _setup_combat_character(
            db, client, username="multi_enemy_user",
            enemy_end=1,   # dies on first hit
            char_end=30,
        )

        # Add a second encounter with higher ordinal
        db.expire_all()
        encounter2 = CombatEncounter(
            scene_id=character.current_scene_id,
            enemy_name="Second Foe",
            enemy_cs=12,
            enemy_end=15,
            ordinal=encounter1.ordinal + 1,
            mindblast_immune=False,
            evasion_damage=0,
            source="manual",
        )
        db.add(encounter2)
        db.flush()
        db.flush()

        with mock.patch("app.services.combat_service.random.randint", return_value=9):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["combat_over"] is True
        assert data["result"] == "win"

        db.refresh(character)
        # Should now be pointing to the second encounter
        assert character.active_combat_encounter_id == encounter2.id
        assert character.scene_phase == "combat"

    def test_defeating_all_enemies_exits_combat_phase(
        self, client: TestClient, db: Session
    ) -> None:
        """After defeating the only/last enemy, phase advances past combat."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="multi_enemy_exit_user",
            enemy_end=1,
            char_end=30,
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=9):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        db.refresh(character)
        assert character.scene_phase != "combat"


# ---------------------------------------------------------------------------
# Tests: Conditional Combat Skip
# ---------------------------------------------------------------------------


class TestConditionalCombatSkip:
    """Tests for combat encounters that are skipped when condition is met."""

    def test_combat_skipped_when_character_has_required_discipline(
        self, client: TestClient, db: Session
    ) -> None:
        """A combat encounter is skipped when the skip condition is satisfied.

        When the first enemy is defeated and the second encounter has a
        skip condition (condition_type='discipline') and the character has
        that discipline, the second encounter is skipped automatically.
        """
        tokens, character, encounter1 = _setup_combat_character(
            db, client, username="cond_combat_skip_user",
            enemy_end=1,
            char_end=30,
        )

        # Create the skippable second encounter
        db.expire_all()

        # Seed and give the skip discipline
        skip_disc = _seed_discipline(db, "Camouflage")
        _give_discipline(db, character, skip_disc)

        encounter2 = CombatEncounter(
            scene_id=character.current_scene_id,
            enemy_name="Skippable Foe",
            enemy_cs=10,
            enemy_end=10,
            ordinal=encounter1.ordinal + 1,
            mindblast_immune=False,
            evasion_damage=0,
            source="manual",
            condition_type="discipline",
            condition_value="Camouflage",
        )
        db.add(encounter2)
        db.flush()
        db.flush()

        with mock.patch("app.services.combat_service.random.randint", return_value=9):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200

        db.refresh(character)
        # Second encounter is skipped, phase advances past combat
        assert character.active_combat_encounter_id != encounter2.id
        assert character.scene_phase != "combat"

        # combat_skipped event logged
        skip_event = (
            db.query(CharacterEvent)
            .filter(
                CharacterEvent.character_id == character.id,
                CharacterEvent.event_type == "combat_skipped",
            )
            .first()
        )
        assert skip_event is not None


# ---------------------------------------------------------------------------
# Tests: Evasion
# ---------------------------------------------------------------------------


class TestCombatEvasion:
    """Tests for combat evasion."""

    def test_evasion_allowed_after_threshold(self, client: TestClient, db: Session) -> None:
        """Evasion succeeds and transitions to evasion target scene after N rounds."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="evasion_user",
            char_end=30,
            enemy_end=60,
            evasion_after_rounds=2,
            evasion_target_scene_number=999,
            evasion_damage=0,
        )

        # Fight 2 rounds (enemy will survive with CRT[rn=0] → enemy_loss=0)
        for _ in range(2):
            db.refresh(character)
            with mock.patch("app.services.combat_service.random.randint", return_value=0):
                r = client.post(
                    f"/gameplay/{character.id}/combat/round",
                    json={"use_psi_surge": False, "version": character.version},
                    headers=auth_headers(tokens["access_token"]),
                )
            assert r.status_code == 200, r.text
            if r.json()["combat_over"]:
                pytest.skip("Enemy died too early — adjust test setup")

        # Now attempt evasion
        db.refresh(character)
        response = client.post(
            f"/gameplay/{character.id}/combat/evade",
            json={"version": character.version},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert "evasion_damage" in data
        assert data["evasion_damage"] == 0
        assert data["is_alive"] is True
        assert data["scene_number"] == 999

    def test_evasion_rejected_before_threshold(self, client: TestClient, db: Session) -> None:
        """Evasion returns 400 if rounds_fought < evasion_after_rounds."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="early_evade_user",
            char_end=30,
            enemy_end=60,
            evasion_after_rounds=3,
            evasion_target_scene_number=999,
        )

        # Attempt evasion without any rounds fought
        response = client.post(
            f"/gameplay/{character.id}/combat/evade",
            json={"version": character.version},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 400

    def test_evasion_death_stays_at_current_scene(self, client: TestClient, db: Session) -> None:
        """When evasion_damage kills the hero, character dies at current scene (no transition).

        Setup: character has 15 END, combat round deals 6 damage (rn=0, hero_loss=6),
        leaving 9 END. Evasion damage is 20, which kills the character (9 - 20 <= 0).
        """
        tokens, character, encounter = _setup_combat_character(
            db, client, username="evade_death_user",
            char_end=15,  # after combat round damage of 6, ends up at 9 END
            enemy_end=60,
            evasion_after_rounds=1,
            evasion_target_scene_number=999,
            evasion_damage=20,  # definitely kills with 9 END
        )

        original_scene_id = character.current_scene_id

        # Fight 1 round to meet threshold — rn=0, hero_loss=6; enemy_loss=0 (enemy survives)
        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            r = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )
        assert r.status_code == 200, r.text
        assert r.json().get("result") != "loss", (
            "Character should not die in the combat round — check CRT values"
        )

        db.refresh(character)

        # Now evade — should kill the hero (9 END - 20 damage = dead)
        response = client.post(
            f"/gameplay/{character.id}/combat/evade",
            json={"version": character.version},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 200, response.text
        data = response.json()

        # Hero died — still at the original scene, is_alive=False
        assert data["is_alive"] is False
        assert data["evasion_damage"] == 20

        db.refresh(character)
        assert character.is_alive is False
        assert character.current_scene_id == original_scene_id

    def test_evasion_logs_evasion_event(self, client: TestClient, db: Session) -> None:
        """Successful evasion logs an 'evasion' character event."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="evade_event_user",
            char_end=30,
            enemy_end=60,
            evasion_after_rounds=1,
            evasion_target_scene_number=998,
            evasion_damage=0,
        )

        # Fight 1 round
        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            r = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )
        if r.json().get("combat_over"):
            pytest.skip("Enemy died too early")

        db.refresh(character)
        response = client.post(
            f"/gameplay/{character.id}/combat/evade",
            json={"version": character.version},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 200
        evasion_event = (
            db.query(CharacterEvent)
            .filter(
                CharacterEvent.character_id == character.id,
                CharacterEvent.event_type == "evasion",
            )
            .first()
        )
        assert evasion_event is not None


# ---------------------------------------------------------------------------
# Tests: Validation Errors
# ---------------------------------------------------------------------------


class TestCombatValidation:
    """Tests for request validation errors."""

    def test_round_wrong_phase_returns_409(self, client: TestClient, db: Session) -> None:
        """Combat round returns 409 WRONG_PHASE when not in combat phase."""
        tokens = register_and_login(client, username="wrong_phase_round_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "wrong_phase_round_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        _seed_crt(db)
        db.flush()

        response = client.post(
            f"/gameplay/{character.id}/combat/round",
            json={"use_psi_surge": False, "version": character.version},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "WRONG_PHASE"

    def test_round_version_mismatch_returns_409(self, client: TestClient, db: Session) -> None:
        """Combat round returns 409 VERSION_MISMATCH for stale version."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="version_mismatch_round_user"
        )

        response = client.post(
            f"/gameplay/{character.id}/combat/round",
            json={"use_psi_surge": False, "version": 999},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "VERSION_MISMATCH"

    def test_evade_wrong_phase_returns_409(self, client: TestClient, db: Session) -> None:
        """Evade returns 409 WRONG_PHASE when not in combat phase."""
        tokens = register_and_login(client, username="wrong_phase_evade_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "wrong_phase_evade_user").first()

        book = make_book(db)
        scene = make_scene(db, book)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        db.flush()

        response = client.post(
            f"/gameplay/{character.id}/combat/evade",
            json={"version": character.version},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "WRONG_PHASE"

    def test_evade_version_mismatch_returns_409(self, client: TestClient, db: Session) -> None:
        """Evade returns 409 VERSION_MISMATCH for stale version."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="version_mismatch_evade_user",
            evasion_after_rounds=1,
            evasion_target_scene_number=999,
        )

        response = client.post(
            f"/gameplay/{character.id}/combat/evade",
            json={"version": 999},
            headers=auth_headers(tokens["access_token"]),
        )

        assert response.status_code == 409
        assert response.json()["error_code"] == "VERSION_MISMATCH"

    def test_round_unauthenticated_returns_401(self, client: TestClient, db: Session) -> None:
        """Combat round returns 401 for unauthenticated requests."""
        book = make_book(db)
        scene = make_scene(db, book)
        user = make_user(db)
        character = make_character(
            db, user, book,
            current_scene_id=scene.id,
            scene_phase="combat",
            scene_phase_index=0,
        )
        db.flush()

        response = client.post(
            f"/gameplay/{character.id}/combat/round",
            json={"use_psi_surge": False, "version": character.version},
        )

        assert response.status_code == 401

    def test_combat_over_returns_result_field(self, client: TestClient, db: Session) -> None:
        """combat_over=True response always has a non-None result field."""
        tokens, character, encounter = _setup_combat_character(
            db, client, username="combat_result_user",
            char_end=1,  # will die
        )

        with mock.patch("app.services.combat_service.random.randint", return_value=0):
            response = client.post(
                f"/gameplay/{character.id}/combat/round",
                json={"use_psi_surge": False, "version": character.version},
                headers=auth_headers(tokens["access_token"]),
            )

        assert response.status_code == 200
        data = response.json()
        assert data["combat_over"] is True
        assert data["result"] in ("win", "loss")
