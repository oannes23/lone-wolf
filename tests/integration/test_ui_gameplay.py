"""Integration tests for the UI gameplay routes (Story 8.3).

Covers:
- GET /ui/game/{character_id} — scene page renders
- POST /ui/game/{character_id}/choose — choice submission redirects
- POST /ui/game/{character_id}/restart — restart redirects
- POST /ui/game/{character_id}/replay — replay redirects
- POST /ui/game/{character_id}/report — bug report HTMX partial
- Auth redirect: unauthenticated requests redirect to /ui/login
- 403/404 on wrong-user or missing character
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Book, Choice, Discipline, Scene
from app.models.player import (
    Character,
    CharacterBookStart,
    CharacterDiscipline,
    CharacterItem,
    User,
)
from tests.factories import (
    make_book,
    make_character,
    make_scene,
    make_user,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_user(
    client: TestClient,
    username: str = "gameplayer",
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
    username: str = "gameplayer",
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


def _seed_minimal_disciplines(db: Session, count: int = 3) -> list[Discipline]:
    """Seed a few Kai disciplines needed for book-start snapshots."""
    names = ["Camouflage", "Hunting", "Sixth Sense"][:count]
    disciplines = []
    for name in names:
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


def _make_book_start_snapshot(
    db: Session,
    character: Character,
    disciplines: list[Discipline],
    book: Book,
) -> CharacterBookStart:
    """Create a CharacterBookStart snapshot required for restart/replay."""
    items_snapshot = [
        {"item_name": "Sword", "item_type": "weapon", "is_equipped": True, "game_object_id": None},
    ]
    disciplines_snapshot = [
        {"discipline_id": disc.id, "weapon_category": None} for disc in disciplines
    ]
    snapshot = CharacterBookStart(
        character_id=character.id,
        book_id=book.id,
        combat_skill_base=15,
        endurance_base=25,
        endurance_max=25,
        endurance_current=25,
        gold=10,
        meals=2,
        items_json=json.dumps(items_snapshot),
        disciplines_json=json.dumps(disciplines_snapshot),
        created_at=datetime.now(UTC),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


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


def _get_user_by_username(db: Session, username: str) -> User:
    return db.query(User).filter(User.username == username).first()


# ---------------------------------------------------------------------------
# Tests: GET /ui/game/{character_id}
# ---------------------------------------------------------------------------


class TestScenePage:
    def test_scene_page_redirects_unauthenticated(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated request redirects to login."""
        resp = client.get("/ui/game/999", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_scene_page_renders_for_character_at_choices_phase(
        self, client: TestClient, db: Session
    ) -> None:
        """Scene page renders HTML with scene number and narrative for a character at choices."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(
            db, book, number=1, narrative="<p>You stand at the crossroads.</p>"
        )
        target = make_scene(db, book, number=2, narrative="<p>You go north.</p>")
        choice = _make_choice(db, scene, target_scene=target, display_text="Go north")

        _register_user(client, "scene_player1")
        user = _get_user_by_username(db, "scene_player1")
        assert user is not None

        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        cookie = _login_cookie(client, "scene_player1")

        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        body = resp.text
        # Scene number visible
        assert "Scene 1" in body or "scene 1" in body.lower()
        # Narrative content rendered
        assert "crossroads" in body
        # Choice is present
        assert "Go north" in body

    def test_scene_page_shows_phase_results(
        self, client: TestClient, db: Session
    ) -> None:
        """Phase results from character events render in the scene page."""
        from app.models.player import CharacterEvent

        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A dark forest.</p>")
        _make_choice(db, scene, display_text="Continue")

        _register_user(client, "scene_phase_player")
        user = _get_user_by_username(db, "scene_phase_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        # Inject a phase result event (must use an event_type the service maps)
        from app.events import log_character_event

        log_character_event(
            db,
            character,
            event_type="meal_consumed",
            scene_id=scene.id,
            phase="eat",
            details={"meals_before": 2, "meals_after": 1},
        )
        db.flush()

        cookie = _login_cookie(client, "scene_phase_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        # Phase results section present
        assert "phase-result" in resp.text

    def test_scene_page_shows_death_panel(
        self, client: TestClient, db: Session
    ) -> None:
        """Death panel renders for a character on a death scene."""
        book = make_book(db, start_scene_number=1)
        start_scene = make_scene(db, book, number=1, narrative="<p>Start.</p>")
        death_scene = make_scene(
            db, book, number=99, is_death=True, narrative="<p>You have fallen.</p>"
        )

        _register_user(client, "death_scene_player")
        user = _get_user_by_username(db, "death_scene_player")
        disciplines = _seed_minimal_disciplines(db)
        character = make_character(
            db,
            user,
            book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            scene_phase="choices",
            scene_phase_index=0,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        cookie = _login_cookie(client, "death_scene_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "death-panel" in body
        assert "Restart" in body
        # Should NOT show regular choice buttons
        assert "What do you do" not in body

    def test_scene_page_shows_victory_panel(
        self, client: TestClient, db: Session
    ) -> None:
        """Victory panel renders for a character on a victory scene."""
        book = make_book(db, start_scene_number=1)
        start_scene = make_scene(db, book, number=1, narrative="<p>Start.</p>")
        victory_scene = make_scene(
            db, book, number=350, is_victory=True, narrative="<p>Victory!</p>"
        )

        _register_user(client, "victory_scene_player")
        user = _get_user_by_username(db, "victory_scene_player")
        disciplines = _seed_minimal_disciplines(db)
        character = make_character(
            db,
            user,
            book,
            current_scene_id=victory_scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        cookie = _login_cookie(client, "victory_scene_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "victory-panel" in body
        assert "Replay" in body or "replay" in body.lower()

    def test_scene_page_shows_unavailable_choice_as_disabled(
        self, client: TestClient, db: Session
    ) -> None:
        """Choices unavailable due to conditions render as disabled buttons."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A bridge.</p>")
        target = make_scene(db, book, number=2, narrative="<p>The other side.</p>")
        # Requires a discipline the character doesn't have
        _make_choice(
            db,
            scene,
            target_scene=target,
            display_text="Use your tracking skills",
            condition_type="discipline",
            condition_value="Tracking",
        )

        _register_user(client, "unavail_choice_player")
        user = _get_user_by_username(db, "unavail_choice_player")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
        )

        cookie = _login_cookie(client, "unavail_choice_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        # Disabled button should appear
        assert "disabled" in body
        assert "Use your tracking skills" in body

    def test_scene_page_404_for_missing_character(
        self, client: TestClient, db: Session
    ) -> None:
        """Returns 404 when character does not exist."""
        _register_user(client, "scene_404_player")
        cookie = _login_cookie(client, "scene_404_player")
        resp = client.get("/ui/game/999999", cookies={"session": cookie})
        assert resp.status_code == 404

    def test_scene_page_403_for_other_users_character(
        self, client: TestClient, db: Session
    ) -> None:
        """Returns 403 when the character belongs to a different user."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")

        _register_user(client, "owner_player_scene")
        owner = _get_user_by_username(db, "owner_player_scene")
        character = make_character(
            db, owner, book, current_scene_id=scene.id, scene_phase="choices", scene_phase_index=0
        )

        _register_user(client, "intruder_player_scene")
        cookie = _login_cookie(client, "intruder_player_scene")

        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 403

    def test_scene_page_contains_bug_report_form(
        self, client: TestClient, db: Session
    ) -> None:
        """Bug report collapsible is present on the scene page."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A room.</p>")
        _make_choice(db, scene, display_text="Enter")

        _register_user(client, "bugreport_page_player")
        user = _get_user_by_username(db, "bugreport_page_player")
        character = make_character(
            db, user, book, current_scene_id=scene.id, scene_phase="choices", scene_phase_index=0
        )

        cookie = _login_cookie(client, "bugreport_page_player")
        resp = client.get(f"/ui/game/{character.id}", cookies={"session": cookie})
        assert resp.status_code == 200
        body = resp.text
        assert "bug-report" in body
        assert "Report a problem" in body


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/choose
# ---------------------------------------------------------------------------


class TestChooseSubmit:
    def test_choose_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Choosing a valid choice redirects to the scene page."""
        book = make_book(db, start_scene_number=1)
        scene1 = make_scene(db, book, number=1, narrative="<p>Scene 1.</p>")
        scene2 = make_scene(db, book, number=2, narrative="<p>Scene 2.</p>")
        choice = _make_choice(db, scene1, target_scene=scene2, display_text="Go north")

        _register_user(client, "choose_player1")
        user = _get_user_by_username(db, "choose_player1")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene1.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )

        cookie = _login_cookie(client, "choose_player1")
        resp = client.post(
            f"/ui/game/{character.id}/choose",
            data={"choice_id": choice.id, "version": 1},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_choose_redirects_unauthenticated_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated POST /choose redirects to login."""
        resp = client.post(
            "/ui/game/1/choose",
            data={"choice_id": 1, "version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_choose_wrong_phase_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Submitting a choice when not in choices phase silently redirects back."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>Scene.</p>")
        target = make_scene(db, book, number=2, narrative="<p>Scene 2.</p>")
        choice = _make_choice(db, scene, target_scene=target)

        _register_user(client, "choose_wrong_phase")
        user = _get_user_by_username(db, "choose_wrong_phase")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="combat",  # Wrong phase
            scene_phase_index=0,
            version=1,
        )

        cookie = _login_cookie(client, "choose_wrong_phase")
        resp = client.post(
            f"/ui/game/{character.id}/choose",
            data={"choice_id": choice.id, "version": 1},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_choose_version_mismatch_redirects_back(
        self, client: TestClient, db: Session
    ) -> None:
        """Version mismatch silently redirects back to scene without crashing."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>Scene.</p>")
        target = make_scene(db, book, number=2, narrative="<p>Scene 2.</p>")
        choice = _make_choice(db, scene, target_scene=target)

        _register_user(client, "choose_version_mismatch")
        user = _get_user_by_username(db, "choose_version_mismatch")
        character = make_character(
            db,
            user,
            book,
            current_scene_id=scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=5,
        )

        cookie = _login_cookie(client, "choose_version_mismatch")
        resp = client.post(
            f"/ui/game/{character.id}/choose",
            data={"choice_id": choice.id, "version": 1},  # wrong version
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/restart
# ---------------------------------------------------------------------------


class TestRestartSubmit:
    def test_restart_dead_character_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Restart a dead character and verify redirect to scene page."""
        book = make_book(db, start_scene_number=1)
        start_scene = make_scene(db, book, number=1, narrative="<p>Start.</p>")
        death_scene = make_scene(
            db, book, number=99, is_death=True, narrative="<p>Death.</p>"
        )

        _register_user(client, "restart_player1")
        user = _get_user_by_username(db, "restart_player1")
        disciplines = _seed_minimal_disciplines(db)
        character = make_character(
            db,
            user,
            book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        cookie = _login_cookie(client, "restart_player1")
        resp = client.post(
            f"/ui/game/{character.id}/restart",
            data={"version": 1},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_restart_redirects_unauthenticated_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated POST /restart redirects to login."""
        resp = client.post(
            "/ui/game/1/restart",
            data={"version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_restart_404_for_missing_character(
        self, client: TestClient, db: Session
    ) -> None:
        """Returns 404 for a non-existent character."""
        _register_user(client, "restart_404_player")
        cookie = _login_cookie(client, "restart_404_player")
        resp = client.post(
            "/ui/game/999999/restart",
            data={"version": 1},
            cookies={"session": cookie},
        )
        assert resp.status_code == 404

    def test_restart_death_scene_shows_updated_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """After restart, following the redirect renders the start scene page."""
        book = make_book(db, start_scene_number=1)
        start_scene = make_scene(db, book, number=1, narrative="<p>The journey begins.</p>")
        death_scene = make_scene(
            db, book, number=99, is_death=True, narrative="<p>Death scene.</p>"
        )

        _register_user(client, "restart_follow_player")
        user = _get_user_by_username(db, "restart_follow_player")
        disciplines = _seed_minimal_disciplines(db)
        character = make_character(
            db,
            user,
            book,
            current_scene_id=death_scene.id,
            is_alive=False,
            endurance_current=0,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        cookie = _login_cookie(client, "restart_follow_player")

        # POST restart then follow the redirect
        resp = client.post(
            f"/ui/game/{character.id}/restart",
            data={"version": 1},
            cookies={"session": cookie},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        # After restart the character is at the start scene
        assert "The journey begins" in resp.text


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/replay
# ---------------------------------------------------------------------------


class TestReplaySubmit:
    def test_replay_victory_scene_redirects_to_scene(
        self, client: TestClient, db: Session
    ) -> None:
        """Replay at victory scene redirects to scene page."""
        book = make_book(db, start_scene_number=1)
        start_scene = make_scene(db, book, number=1, narrative="<p>Start again.</p>")
        victory_scene = make_scene(
            db, book, number=350, is_victory=True, narrative="<p>Victory!</p>"
        )

        _register_user(client, "replay_player1")
        user = _get_user_by_username(db, "replay_player1")
        disciplines = _seed_minimal_disciplines(db)
        character = make_character(
            db,
            user,
            book,
            current_scene_id=victory_scene.id,
            scene_phase="choices",
            scene_phase_index=0,
            version=1,
        )
        _make_book_start_snapshot(db, character, disciplines, book)

        cookie = _login_cookie(client, "replay_player1")
        resp = client.post(
            f"/ui/game/{character.id}/replay",
            data={"version": 1},
            cookies={"session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/ui/game/{character.id}"

    def test_replay_redirects_unauthenticated_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated POST /replay redirects to login."""
        resp = client.post(
            "/ui/game/1/replay",
            data={"version": 1},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Tests: POST /ui/game/{character_id}/report
# ---------------------------------------------------------------------------


class TestBugReportSubmit:
    def test_report_returns_success_partial(
        self, client: TestClient, db: Session
    ) -> None:
        """Bug report returns HTML success message (HTMX partial)."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")
        _make_choice(db, scene, display_text="Enter")

        _register_user(client, "report_player1")
        user = _get_user_by_username(db, "report_player1")
        character = make_character(
            db, user, book, current_scene_id=scene.id, scene_phase="choices", scene_phase_index=0
        )

        cookie = _login_cookie(client, "report_player1")
        resp = client.post(
            f"/ui/game/{character.id}/report",
            data={
                "tags": ["narrative_error"],
                "free_text": "The story says I go north but I should go south.",
                "scene_id": scene.id,
            },
            cookies={"session": cookie},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Report submitted" in resp.text
        assert "alert-success" in resp.text

    def test_report_with_no_tags_succeeds(
        self, client: TestClient, db: Session
    ) -> None:
        """Bug report with no tags is accepted (tags are optional)."""
        book = make_book(db, start_scene_number=1)
        scene = make_scene(db, book, number=1, narrative="<p>A scene.</p>")
        _make_choice(db, scene, display_text="Enter")

        _register_user(client, "report_player_notags")
        user = _get_user_by_username(db, "report_player_notags")
        character = make_character(
            db, user, book, current_scene_id=scene.id, scene_phase="choices", scene_phase_index=0
        )

        cookie = _login_cookie(client, "report_player_notags")
        resp = client.post(
            f"/ui/game/{character.id}/report",
            data={"free_text": "Something is wrong.", "scene_id": 0},
            cookies={"session": cookie},
        )
        assert resp.status_code == 200
        assert "Report submitted" in resp.text

    def test_report_redirects_unauthenticated_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated bug report redirects to login."""
        resp = client.post(
            "/ui/game/1/report",
            data={"free_text": "Bug.", "scene_id": 0},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]
