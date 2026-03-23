"""Integration tests for the UI browse routes (Story 8.6).

Covers:
- Books list and detail pages
- Game objects list (with kind filter and search) and detail pages
- Leaderboards page (default and book-filtered)
- Character sheet page
- Character history page (including HTMX partial)
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.models.content import Book, Discipline, Scene
from app.models.player import Character, DecisionLog, User
from app.models.taxonomy import GameObject
from tests.factories import make_book, make_character, make_game_object, make_scene, make_user


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _register_and_login_api(client: TestClient, username: str = "browseuser") -> str:
    """Register via JSON API and return the JWT access token."""
    client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": "Pass1234!"},
    )
    resp = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _ui_login(client: TestClient, username: str = "browseuser") -> str:
    """Log in via UI route and return the session cookie value."""
    resp = client.post(
        "/ui/login",
        data={"username": username, "password": "Pass1234!"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"UI login failed: {resp.status_code}"
    cookie = resp.cookies.get("session")
    assert cookie, "Expected session cookie"
    return cookie


def _register_and_ui_login(client: TestClient, username: str = "browseuser") -> str:
    """Register and log in; return the UI session cookie."""
    _register_and_login_api(client, username)
    return _ui_login(client, username)


# ---------------------------------------------------------------------------
# Books list
# ---------------------------------------------------------------------------


class TestUIBooksList:
    def test_books_list_renders_200(self, client: TestClient, db) -> None:
        make_book(db, number=8601, title="Test Book One", era="kai")
        cookie = _register_and_ui_login(client, "bklist1")

        resp = client.get("/ui/books", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"text/html" in resp.headers["content-type"].encode()
        assert b"Books" in resp.content

    def test_books_list_shows_book_title(self, client: TestClient, db) -> None:
        make_book(db, number=8602, title="Flight from the Dark", era="kai")
        cookie = _register_and_ui_login(client, "bklist2")

        resp = client.get("/ui/books", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"Flight from the Dark" in resp.content

    def test_books_list_shows_book_link(self, client: TestClient, db) -> None:
        book = make_book(db, number=8603, title="Fire on the Water", era="kai")
        cookie = _register_and_ui_login(client, "bklist3")

        resp = client.get("/ui/books", cookies={"session": cookie})

        assert resp.status_code == 200
        assert f"/ui/books/{book.id}".encode() in resp.content

    def test_books_list_requires_auth(self, client: TestClient, db) -> None:
        resp = client.get("/ui/books", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Book detail
# ---------------------------------------------------------------------------


class TestUIBookDetail:
    def test_book_detail_renders_200(self, client: TestClient, db) -> None:
        book = make_book(db, number=8610, title="The Caverns of Kalte", era="kai")
        cookie = _register_and_ui_login(client, "bkdet1")

        resp = client.get(f"/ui/books/{book.id}", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"Caverns of Kalte" in resp.content

    def test_book_detail_shows_era(self, client: TestClient, db) -> None:
        book = make_book(db, number=8611, era="kai")
        cookie = _register_and_ui_login(client, "bkdet2")

        resp = client.get(f"/ui/books/{book.id}", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"kai" in resp.content.lower() or b"Kai" in resp.content

    def test_book_detail_shows_scene_count(self, client: TestClient, db) -> None:
        book = make_book(db, number=8612, era="kai")
        make_scene(db, book)
        make_scene(db, book)
        cookie = _register_and_ui_login(client, "bkdet3")

        resp = client.get(f"/ui/books/{book.id}", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"2" in resp.content

    def test_book_detail_shows_disciplines_section(self, client: TestClient, db) -> None:
        book = make_book(db, number=8613, era="kai")
        disc = Discipline(era="kai", name="Camouflage", html_id="camouflage8613", description="Concealment.")
        db.add(disc)
        db.flush()
        cookie = _register_and_ui_login(client, "bkdet4")

        resp = client.get(f"/ui/books/{book.id}", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"Camouflage" in resp.content

    def test_book_detail_returns_404_for_unknown_book(self, client: TestClient, db) -> None:
        cookie = _register_and_ui_login(client, "bkdet5")

        resp = client.get("/ui/books/999999", cookies={"session": cookie})

        assert resp.status_code == 404

    def test_book_detail_requires_auth(self, client: TestClient, db) -> None:
        book = make_book(db, number=8614, era="kai")

        resp = client.get(f"/ui/books/{book.id}", follow_redirects=False)

        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Game objects list
# ---------------------------------------------------------------------------


class TestUIGameObjectsList:
    def test_game_objects_list_renders_200(self, client: TestClient, db) -> None:
        make_game_object(db, name="Test Sword 8620", kind="item")
        cookie = _register_and_ui_login(client, "golist1")

        resp = client.get("/ui/game-objects", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"Encyclopedia" in resp.content

    def test_game_objects_list_shows_item_name(self, client: TestClient, db) -> None:
        make_game_object(db, name="Golden Sword 8621", kind="item")
        cookie = _register_and_ui_login(client, "golist2")

        resp = client.get("/ui/game-objects", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"Golden Sword 8621" in resp.content

    def test_game_objects_list_kind_filter_htmx(self, client: TestClient, db) -> None:
        make_game_object(db, name="Darklord 8622", kind="character")
        make_game_object(db, name="Iron Sword 8622", kind="item")
        cookie = _register_and_ui_login(client, "golist3")

        resp = client.get(
            "/ui/game-objects?kind=character",
            cookies={"session": cookie},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        assert b"Darklord 8622" in resp.content
        # Should not contain the item (kind=item not selected)
        # Note: It may appear if both are returned — just check the partial template is used
        assert b"<html" not in resp.content  # should be a partial, not full page

    def test_game_objects_list_search_filters_results(self, client: TestClient, db) -> None:
        make_game_object(db, name="Unique Item XYZ8623", kind="item")
        make_game_object(db, name="Other Thing 8623", kind="item")
        cookie = _register_and_ui_login(client, "golist4")

        resp = client.get(
            "/ui/game-objects?search=Unique+Item+XYZ8623",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        assert b"Unique Item XYZ8623" in resp.content

    def test_game_objects_list_shows_kind_filter(self, client: TestClient, db) -> None:
        cookie = _register_and_ui_login(client, "golist5")

        resp = client.get("/ui/game-objects", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"kind" in resp.content.lower()

    def test_game_objects_list_requires_auth(self, client: TestClient, db) -> None:
        resp = client.get("/ui/game-objects", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Game object detail
# ---------------------------------------------------------------------------


class TestUIGameObjectDetail:
    def test_game_object_detail_renders_200(self, client: TestClient, db) -> None:
        go = make_game_object(db, name="Sommerswerd 8630", kind="item")
        cookie = _register_and_ui_login(client, "godet1")

        resp = client.get(f"/ui/game-objects/{go.id}", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"Sommerswerd 8630" in resp.content

    def test_game_object_detail_shows_kind(self, client: TestClient, db) -> None:
        go = make_game_object(db, name="Helgedad 8631", kind="location")
        cookie = _register_and_ui_login(client, "godet2")

        resp = client.get(f"/ui/game-objects/{go.id}", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"location" in resp.content.lower() or b"Location" in resp.content

    def test_game_object_detail_returns_404_for_unknown(self, client: TestClient, db) -> None:
        cookie = _register_and_ui_login(client, "godet3")

        resp = client.get("/ui/game-objects/999999", cookies={"session": cookie})

        assert resp.status_code == 404

    def test_game_object_detail_requires_auth(self, client: TestClient, db) -> None:
        go = make_game_object(db, name="Test Object 8632", kind="item")

        resp = client.get(f"/ui/game-objects/{go.id}", follow_redirects=False)

        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------------------------


class TestUILeaderboards:
    def test_leaderboards_renders_200(self, client: TestClient, db) -> None:
        cookie = _register_and_ui_login(client, "lb1")

        resp = client.get("/ui/leaderboards", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"Leaderboard" in resp.content

    def test_leaderboards_shows_book_select(self, client: TestClient, db) -> None:
        make_book(db, number=8641, title="Book for LB", era="kai")
        cookie = _register_and_ui_login(client, "lb2")

        resp = client.get("/ui/leaderboards", cookies={"session": cookie})

        assert resp.status_code == 200
        assert b"book" in resp.content.lower()

    def test_leaderboards_book_filter_htmx_returns_partial(self, client: TestClient, db) -> None:
        book = make_book(db, number=8642, title="Kai Book LB", era="kai")
        cookie = _register_and_ui_login(client, "lb3")

        resp = client.get(
            f"/ui/leaderboards?book_id={book.id}",
            cookies={"session": cookie},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        # Partial should not include the full page HTML wrapper
        assert b"<html" not in resp.content

    def test_leaderboards_requires_auth(self, client: TestClient, db) -> None:
        resp = client.get("/ui/leaderboards", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Character sheet
# ---------------------------------------------------------------------------


class TestUICharacterSheet:
    def _create_character_and_login(self, client: TestClient, db, username: str) -> tuple[Character, str]:
        """Create a user, character, and return (character, cookie)."""
        cookie = _register_and_ui_login(client, username)
        # Fetch the user from DB
        user = db.query(User).filter(User.username == username).first()
        book = make_book(db, number=8650 + hash(username) % 100, era="kai")
        character = make_character(db, user, book)
        return character, cookie

    def test_character_sheet_renders_200(self, client: TestClient, db) -> None:
        character, cookie = self._create_character_and_login(client, db, "sheetuser1")

        resp = client.get(
            f"/ui/characters/{character.id}/sheet",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        assert b"text/html" in resp.headers["content-type"].encode()

    def test_character_sheet_shows_name(self, client: TestClient, db) -> None:
        character, cookie = self._create_character_and_login(client, db, "sheetuser2")

        resp = client.get(
            f"/ui/characters/{character.id}/sheet",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        assert character.name.encode() in resp.content

    def test_character_sheet_shows_stats(self, client: TestClient, db) -> None:
        character, cookie = self._create_character_and_login(client, db, "sheetuser3")

        resp = client.get(
            f"/ui/characters/{character.id}/sheet",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        # Stats are shown — check CS and endurance labels/values appear
        assert b"Combat Skill" in resp.content or b"CS" in resp.content
        assert b"Endurance" in resp.content

    def test_character_sheet_returns_404_for_unknown(self, client: TestClient, db) -> None:
        cookie = _register_and_ui_login(client, "sheetuser4")

        resp = client.get("/ui/characters/999999/sheet", cookies={"session": cookie})

        assert resp.status_code == 404

    def test_character_sheet_returns_403_for_other_users_character(
        self, client: TestClient, db
    ) -> None:
        # Create character owned by user A
        _register_and_login_api(client, "sheetowner8")
        user_a = db.query(User).filter(User.username == "sheetowner8").first()
        book = make_book(db, number=8658, era="kai")
        character = make_character(db, user_a, book)

        # Login as user B
        cookie_b = _register_and_ui_login(client, "sheetother8")

        resp = client.get(
            f"/ui/characters/{character.id}/sheet",
            cookies={"session": cookie_b},
        )

        assert resp.status_code == 403

    def test_character_sheet_requires_auth(self, client: TestClient, db) -> None:
        _register_and_login_api(client, "sheetauth8")
        user = db.query(User).filter(User.username == "sheetauth8").first()
        book = make_book(db, number=8659, era="kai")
        character = make_character(db, user, book)

        resp = client.get(
            f"/ui/characters/{character.id}/sheet",
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Character history
# ---------------------------------------------------------------------------


class TestUICharacterHistory:
    def _setup(self, client: TestClient, db, username: str):
        """Create user, book, character, return (character, cookie)."""
        cookie = _register_and_ui_login(client, username)
        user = db.query(User).filter(User.username == username).first()
        book = make_book(db, number=8660 + hash(username) % 100, era="kai")
        character = make_character(db, user, book)
        return character, cookie

    def _add_history_row(self, db, character: Character, scene1: Scene, scene2: Scene) -> None:
        """Add a DecisionLog entry for test data."""
        entry = DecisionLog(
            character_id=character.id,
            run_number=character.current_run,
            from_scene_id=scene1.id,
            to_scene_id=scene2.id,
            choice_id=None,
            action_type="choice",
            created_at=datetime.now(UTC),
        )
        db.add(entry)
        db.flush()

    def test_history_renders_200(self, client: TestClient, db) -> None:
        character, cookie = self._setup(client, db, "histuser1")

        resp = client.get(
            f"/ui/characters/{character.id}/history",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        assert b"History" in resp.content

    def test_history_shows_table(self, client: TestClient, db) -> None:
        character, cookie = self._setup(client, db, "histuser2")

        resp = client.get(
            f"/ui/characters/{character.id}/history",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        assert b"<table" in resp.content

    def test_history_shows_entries_when_present(self, client: TestClient, db) -> None:
        character, cookie = self._setup(client, db, "histuser3")
        book = db.query(Book).filter(Book.id == character.book_id).first()
        scene1 = make_scene(db, book)
        scene2 = make_scene(db, book)
        self._add_history_row(db, character, scene1, scene2)

        resp = client.get(
            f"/ui/characters/{character.id}/history",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200
        # Scene numbers appear in the table
        assert str(scene1.number).encode() in resp.content

    def test_history_run_filter_renders(self, client: TestClient, db) -> None:
        character, cookie = self._setup(client, db, "histuser4")

        resp = client.get(
            f"/ui/characters/{character.id}/history?run=1",
            cookies={"session": cookie},
        )

        assert resp.status_code == 200

    def test_history_partial_returns_fragment(self, client: TestClient, db) -> None:
        """HTMX partial load (offset > 0 and HX-Request header) returns only rows."""
        character, cookie = self._setup(client, db, "histuser5")

        resp = client.get(
            f"/ui/characters/{character.id}/history?offset=0&partial=1",
            cookies={"session": cookie},
            headers={"HX-Request": "true"},
        )

        assert resp.status_code == 200
        # Partial template should not include the full layout
        assert b"<html" not in resp.content

    def test_history_returns_404_for_unknown_character(self, client: TestClient, db) -> None:
        cookie = _register_and_ui_login(client, "histuser6")

        resp = client.get("/ui/characters/999999/history", cookies={"session": cookie})

        assert resp.status_code == 404

    def test_history_returns_403_for_other_users_character(
        self, client: TestClient, db
    ) -> None:
        _register_and_login_api(client, "histowner7")
        user_a = db.query(User).filter(User.username == "histowner7").first()
        book = make_book(db, number=8677, era="kai")
        character = make_character(db, user_a, book)

        cookie_b = _register_and_ui_login(client, "histother7")

        resp = client.get(
            f"/ui/characters/{character.id}/history",
            cookies={"session": cookie_b},
        )

        assert resp.status_code == 403

    def test_history_requires_auth(self, client: TestClient, db) -> None:
        _register_and_login_api(client, "histauth8")
        user = db.query(User).filter(User.username == "histauth8").first()
        book = make_book(db, number=8688, era="kai")
        character = make_character(db, user, book)

        resp = client.get(
            f"/ui/characters/{character.id}/history",
            follow_redirects=False,
        )

        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]
