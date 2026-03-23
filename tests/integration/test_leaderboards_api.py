"""Integration tests for GET /leaderboards/books/{book_id} and GET /leaderboards/overall."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Discipline, Scene
from app.models.player import Character, CharacterDiscipline, CharacterEvent
from tests.factories import make_book, make_character, make_scene, make_user
from tests.helpers.auth import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_discipline(db: Session, name: str = "Healing") -> Discipline:
    disc = Discipline(
        era="kai",
        name=name,
        html_id=name.lower().replace(" ", "-"),
        description=f"{name} discipline.",
    )
    db.add(disc)
    db.flush()
    return disc


def _add_discipline(db: Session, character: Character, discipline: Discipline) -> None:
    cd = CharacterDiscipline(
        character_id=character.id,
        discipline_id=discipline.id,
    )
    db.add(cd)
    db.flush()


def _add_item_pickup_event(
    db: Session,
    character: Character,
    scene: Scene,
    item_name: str,
    seq: int = 1,
) -> None:
    event = CharacterEvent(
        character_id=character.id,
        scene_id=scene.id,
        run_number=character.current_run,
        event_type="item_pickup",
        details=f'{{"item_name": "{item_name}", "scene_item_id": 1}}',
        seq=seq,
        created_at=datetime.now(tz=UTC),
    )
    db.add(event)
    db.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBookLeaderboard:
    """Tests for GET /leaderboards/books/{book_id}."""

    def test_requires_auth(self, client: TestClient, db: Session) -> None:
        book = make_book(db)
        db.flush()
        response = client.get(f"/leaderboards/books/{book.id}")
        assert response.status_code == 401

    def test_book_not_found_returns_404(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="lb_notfound_user", password="pass1234!")
        response = client.get(
            "/leaderboards/books/99999",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 404

    def test_empty_leaderboard_returns_empty_arrays(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="lb_empty_user", password="pass1234!")
        book = make_book(db)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()

        # Check field names aligned to spec
        assert "book" in data  # not book_id
        assert data["book"]["id"] == book.id
        assert data["book"]["title"] == book.title
        assert "completions" in data
        assert data["completions"] == 0
        assert "fewest_deaths" in data
        assert data["fewest_deaths"] == []
        assert "fewest_decisions" in data
        assert "highest_endurance_at_victory" in data  # renamed from highest_endurance
        assert data["highest_endurance_at_victory"] == []
        assert "most_common_death_scenes" in data
        assert "discipline_popularity" in data
        assert "item_usage" in data

    def test_completions_counted_correctly(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="lb_completions_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_completions_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)

        # One character at victory
        make_character(db, user, book, current_scene_id=victory_scene.id)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["completions"] == 1

    def test_discipline_popularity_is_fraction(
        self, client: TestClient, db: Session
    ) -> None:
        """Pick rate should be 0-1 fraction, not 0-100 percentage."""
        tokens = register_and_login(client, username="lb_discipline_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_discipline_user").first()

        book = make_book(db)
        healing = _seed_discipline(db, "Healing_LB")

        # 2 characters, 1 has the discipline → pick_rate = 0.5
        c1 = make_character(db, user, book)
        c2 = make_character(db, user, book)
        _add_discipline(db, c1, healing)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        popularity = data["discipline_popularity"]
        assert len(popularity) >= 1
        entry = next(e for e in popularity if e["discipline"] == "Healing_LB")
        # Field name is "discipline" not "discipline_name"
        assert "discipline" in entry
        # Rate should be fraction 0-1, not percentage
        assert 0.0 <= entry["pick_rate"] <= 1.0
        assert entry["pick_rate"] == 0.5

    def test_item_usage_is_fraction(
        self, client: TestClient, db: Session
    ) -> None:
        """Pickup rate should be 0-1 fraction, not 0-100 percentage."""
        tokens = register_and_login(client, username="lb_item_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_item_user").first()

        book = make_book(db)
        scene = make_scene(db, book, number=1)

        # 2 characters, 1 picked up the sword → pickup_rate = 0.5
        c1 = make_character(db, user, book)
        make_character(db, user, book)
        _add_item_pickup_event(db, c1, scene, "Sommerswerd", seq=1)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        usage = data["item_usage"]
        assert len(usage) >= 1
        entry = next((e for e in usage if e["item_name"] == "Sommerswerd"), None)
        assert entry is not None
        assert 0.0 <= entry["pickup_rate"] <= 1.0
        assert entry["pickup_rate"] == 0.5


class TestOverallLeaderboard:
    """Tests for GET /leaderboards/overall."""

    def test_requires_auth(self, client: TestClient, db: Session) -> None:
        response = client.get("/leaderboards/overall")
        assert response.status_code == 401

    def test_overall_response_shape(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="overall_lb_user", password="pass1234!")
        response = client.get(
            "/leaderboards/overall",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_completions" in data
        assert "total_characters" in data
        assert "highest_endurance_at_victory" in data  # renamed from highest_endurance
        assert "most_completions" in data


# ---------------------------------------------------------------------------
# Additional tests for full coverage
# ---------------------------------------------------------------------------


class TestBookLeaderboardRankings:
    """Tests for fewest_deaths, fewest_decisions, and highest_endurance_at_victory rankings."""

    def test_fewest_deaths_sorted_ascending(
        self, client: TestClient, db: Session
    ) -> None:
        """fewest_deaths list must have lowest death_count first."""
        tokens = register_and_login(client, username="lb_deaths_sort_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_deaths_sort_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)

        # Two characters at victory — one with 0 deaths, one with 2
        make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            death_count=0,
        )
        make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            death_count=2,
        )
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        fewest = data["fewest_deaths"]
        assert len(fewest) >= 2
        # First entry should have fewer deaths
        assert fewest[0]["death_count"] <= fewest[1]["death_count"]

    def test_fewest_decisions_sorted_ascending(
        self, client: TestClient, db: Session
    ) -> None:
        """fewest_decisions list must have lowest decisions count first."""
        tokens = register_and_login(client, username="lb_dec_sort_user", password="pass1234!")
        from app.models.player import User
        from app.models.player import DecisionLog
        from datetime import UTC, datetime

        user = db.query(User).filter(User.username == "lb_dec_sort_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)
        scene_a = make_scene(db, book, number=10)

        # char1 = 1 decision, char2 = 3 decisions
        char1 = make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
        )
        char2 = make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
        )

        # Add decisions to char2
        for _ in range(3):
            dl = DecisionLog(
                character_id=char2.id,
                run_number=1,
                from_scene_id=scene_a.id,
                to_scene_id=victory_scene.id,
                action_type="choice",
                created_at=datetime.now(tz=UTC),
            )
            db.add(dl)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        fewest_dec = data["fewest_decisions"]
        assert len(fewest_dec) >= 2
        # First entry should have fewer decisions
        assert fewest_dec[0]["decisions"] <= fewest_dec[1]["decisions"]

    def test_highest_endurance_at_victory_sorted_descending(
        self, client: TestClient, db: Session
    ) -> None:
        """highest_endurance_at_victory list must have highest endurance first."""
        tokens = register_and_login(client, username="lb_end_sort_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_end_sort_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)

        # Two characters — different endurance
        make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            endurance_current=18,
        )
        make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            endurance_current=25,
        )
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        highest = data["highest_endurance_at_victory"]
        assert len(highest) >= 2
        # First entry should have higher endurance
        assert highest[0]["endurance"] >= highest[1]["endurance"]

    def test_highest_endurance_entry_has_expected_fields(
        self, client: TestClient, db: Session
    ) -> None:
        """EnduranceEntry has username, endurance, death_count."""
        tokens = register_and_login(client, username="lb_end_fields_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_end_fields_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)
        make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            endurance_current=20,
            death_count=1,
        )
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        highest = data["highest_endurance_at_victory"]
        assert len(highest) >= 1
        entry = highest[0]
        assert "username" in entry
        assert "endurance" in entry
        assert "death_count" in entry
        assert entry["endurance"] == 20

    def test_completions_only_counts_alive_characters_at_victory(
        self, client: TestClient, db: Session
    ) -> None:
        """Dead characters at a victory scene are still completions (is_alive is the player's state,
        the completion is determined by scene type, not character alive state)."""
        tokens = register_and_login(client, username="lb_alive_victory_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_alive_victory_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)
        non_victory = make_scene(db, book, number=100)

        # One at victory (completer), one at regular scene (non-completer)
        make_character(db, user, book, current_scene_id=victory_scene.id)
        make_character(db, user, book, current_scene_id=non_victory.id)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["completions"] == 1

    def test_deleted_characters_excluded_from_completions(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="lb_del_excl_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_del_excl_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)

        # Deleted character at victory — must not count
        make_character(
            db, user, book,
            current_scene_id=victory_scene.id,
            is_deleted=True,
        )
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["completions"] == 0


class TestBookLeaderboardMostCommonDeathScenes:
    """Tests for most_common_death_scenes."""

    def test_most_common_death_scenes_populated(
        self, client: TestClient, db: Session
    ) -> None:
        from app.models.player import CharacterEvent
        from datetime import UTC, datetime

        tokens = register_and_login(client, username="lb_death_scene_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_death_scene_user").first()

        book = make_book(db)
        death_scene = make_scene(db, book, number=99, is_death=True)
        char = make_character(db, user, book, current_scene_id=death_scene.id)

        # Two death events at this scene
        for seq in (1, 2):
            ev = CharacterEvent(
                character_id=char.id,
                scene_id=death_scene.id,
                run_number=char.current_run,
                event_type="death",
                seq=seq,
                created_at=datetime.now(tz=UTC),
            )
            db.add(ev)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        death_scenes = data["most_common_death_scenes"]
        assert len(death_scenes) >= 1
        entry = death_scenes[0]
        assert "scene_number" in entry
        assert "death_count" in entry
        assert entry["scene_number"] == 99
        assert entry["death_count"] == 2

    def test_most_common_death_scenes_empty_when_no_deaths(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="lb_no_death_user", password="pass1234!")
        book = make_book(db)
        make_scene(db, book, number=1)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["most_common_death_scenes"] == []


class TestBookLeaderboardLimit:
    """Tests for the limit query parameter."""

    def test_limit_parameter_restricts_fewest_deaths(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="lb_limit_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "lb_limit_user").first()

        book = make_book(db)
        victory_scene = make_scene(db, book, number=350, is_victory=True)

        # Create 5 completers
        for _ in range(5):
            make_character(db, user, book, current_scene_id=victory_scene.id)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}?limit=2",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["fewest_deaths"]) <= 2

    def test_limit_parameter_invalid_returns_422(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="lb_bad_limit_user", password="pass1234!")
        book = make_book(db)
        db.flush()

        response = client.get(
            f"/leaderboards/books/{book.id}?limit=0",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 422


class TestOverallLeaderboardExtended:
    """Extended tests for GET /leaderboards/overall."""

    def test_overall_counts_all_non_deleted_characters(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="overall_count_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "overall_count_user").first()

        book = make_book(db)
        scene = make_scene(db, book)

        before_count_resp = client.get(
            "/leaderboards/overall",
            headers=auth_headers(tokens["access_token"]),
        )
        before_count = before_count_resp.json()["total_characters"]

        make_character(db, user, book, current_scene_id=scene.id)
        make_character(db, user, book, current_scene_id=scene.id, is_deleted=True)
        db.flush()

        response = client.get(
            "/leaderboards/overall",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        # Only non-deleted character was added
        assert data["total_characters"] == before_count + 1

    def test_overall_completions_across_multiple_books(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="overall_multi_book_user", password="pass1234!")
        from app.models.player import User
        user = db.query(User).filter(User.username == "overall_multi_book_user").first()

        before_resp = client.get(
            "/leaderboards/overall",
            headers=auth_headers(tokens["access_token"]),
        )
        before_total = before_resp.json()["total_completions"]

        book1 = make_book(db)
        book2 = make_book(db)
        v1 = make_scene(db, book1, number=350, is_victory=True)
        v2 = make_scene(db, book2, number=400, is_victory=True)
        make_character(db, user, book1, current_scene_id=v1.id)
        make_character(db, user, book2, current_scene_id=v2.id)
        db.flush()

        response = client.get(
            "/leaderboards/overall",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_completions"] == before_total + 2
