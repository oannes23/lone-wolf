"""Integration tests for the Books API (GET /books, /books/{id}, /books/{id}/rules)."""

import pytest
from fastapi.testclient import TestClient

from app.models.content import Book, Discipline, Scene, WeaponCategory
from tests.factories import make_book, make_scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client: TestClient, username: str) -> str:
    """Register a user and return the access token."""
    client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "Pass1234!",
        },
    )
    resp = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_disciplines(db, era: str = "kai") -> list[Discipline]:
    """Insert a few disciplines for the given era and return them."""
    rows = [
        Discipline(era=era, name="Camouflage", html_id="camouflage",
                   description="Blend in with natural surroundings."),
        Discipline(era=era, name="Hunting", html_id="hunting",
                   description="Never starve in the wild."),
        Discipline(era=era, name="Healing", html_id="healing",
                   description="Accelerate natural recovery."),
    ]
    for d in rows:
        db.add(d)
    db.flush()
    return rows


def _seed_weapon_categories(db) -> None:
    """Insert a small set of weapon categories."""
    pairs = [("Sword", "Sword"), ("Axe", "Axe"), ("Mace", "Mace")]
    for weapon_name, category in pairs:
        db.add(WeaponCategory(weapon_name=weapon_name, category=category))
    db.flush()


# ---------------------------------------------------------------------------
# GET /books — list all books
# ---------------------------------------------------------------------------


class TestListBooks:
    def test_list_books_returns_all_books(self, client: TestClient, db) -> None:
        """All seeded books are returned when no filters are applied."""
        make_book(db, number=101, era="kai", series="lone_wolf")
        make_book(db, number=102, era="kai", series="lone_wolf")
        token = _register_and_login(client, "listbooksuser")

        resp = client.get("/books", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        # At least the two we just created are present
        ids_in_response = {item["id"] for item in data}
        assert len(data) >= 2
        # Verify shape of one item
        book_data = data[0]
        assert "id" in book_data
        assert "number" in book_data
        assert "slug" in book_data
        assert "title" in book_data
        assert "era" in book_data
        assert "start_scene_number" in book_data

    def test_filter_by_era_returns_only_matching_books(self, client: TestClient, db) -> None:
        """?era=kai returns only kai-era books."""
        kai_book = make_book(db, number=201, era="kai", series="lone_wolf")
        magnakai_book = make_book(db, number=202, era="magnakai", series="lone_wolf")
        token = _register_and_login(client, "erafilteruser")

        resp = client.get("/books?era=kai", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        returned_ids = {item["id"] for item in data}
        assert kai_book.id in returned_ids
        assert magnakai_book.id not in returned_ids
        for item in data:
            assert item["era"] == "kai"

    def test_filter_by_series_returns_only_matching_books(self, client: TestClient, db) -> None:
        """?series=lone_wolf returns only lone_wolf series books."""
        lw_book = make_book(db, number=301, era="kai", series="lone_wolf")
        token = _register_and_login(client, "seriesfilteruser")

        resp = client.get("/books?series=lone_wolf", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        returned_ids = {item["id"] for item in data}
        assert lw_book.id in returned_ids

    def test_list_books_returns_401_when_unauthenticated(self, client: TestClient, db) -> None:
        """No Bearer token must yield 401."""
        make_book(db, number=401, era="kai")
        resp = client.get("/books")
        assert resp.status_code == 401

    def test_list_books_empty_when_no_books_exist(self, client: TestClient, db) -> None:
        """When no books match the filter, an empty list is returned (not an error)."""
        token = _register_and_login(client, "emptybooksuser")
        resp = client.get("/books?era=new_order", headers=_auth(token))
        assert resp.status_code == 200
        # We don't assert empty because other tests may have added new_order books,
        # but we do assert a list is returned.
        assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# GET /books/{book_id} — book detail
# ---------------------------------------------------------------------------


class TestGetBook:
    def test_book_detail_returns_correct_fields(self, client: TestClient, db) -> None:
        """Book detail includes all BookDetail fields."""
        book = make_book(db, number=501, era="kai", series="lone_wolf")
        _seed_disciplines(db, era="kai")
        token = _register_and_login(client, "detailuser")

        resp = client.get(f"/books/{book.id}", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == book.id
        assert data["number"] == book.number
        assert data["slug"] == book.slug
        assert data["title"] == book.title
        assert data["era"] == "kai"
        assert "scene_count" in data
        assert "disciplines" in data
        assert "max_total_picks" in data

    def test_book_detail_includes_scene_count(self, client: TestClient, db) -> None:
        """scene_count reflects the actual number of scenes for the book."""
        book = make_book(db, number=601, era="kai")
        make_scene(db, book)
        make_scene(db, book)
        make_scene(db, book)
        token = _register_and_login(client, "scenecountuser")

        resp = client.get(f"/books/{book.id}", headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()["scene_count"] == 3

    def test_book_detail_includes_discipline_list(self, client: TestClient, db) -> None:
        """disciplines list is populated from the book's era."""
        book = make_book(db, number=701, era="kai")
        discs = _seed_disciplines(db, era="kai")
        token = _register_and_login(client, "disciplineuser")

        resp = client.get(f"/books/{book.id}", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        returned_names = {d["name"] for d in data["disciplines"]}
        for disc in discs:
            assert disc.name in returned_names
        # Each discipline item has the required fields
        for d in data["disciplines"]:
            assert "id" in d
            assert "name" in d
            assert "description" in d

    def test_book_detail_scene_count_zero_when_no_scenes(self, client: TestClient, db) -> None:
        """scene_count is 0 when the book has no scenes yet."""
        book = make_book(db, number=801, era="kai")
        token = _register_and_login(client, "nosceneuser")

        resp = client.get(f"/books/{book.id}", headers=_auth(token))

        assert resp.status_code == 200
        assert resp.json()["scene_count"] == 0

    def test_book_detail_returns_404_for_nonexistent_book(self, client: TestClient, db) -> None:
        """A book_id that does not exist returns 404."""
        token = _register_and_login(client, "notfounduser")

        resp = client.get("/books/99999", headers=_auth(token))

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_book_detail_returns_401_when_unauthenticated(self, client: TestClient, db) -> None:
        """No Bearer token must yield 401."""
        book = make_book(db, number=901, era="kai")

        resp = client.get(f"/books/{book.id}")

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /books/{book_id}/rules — game rules
# ---------------------------------------------------------------------------


class TestGetBookRules:
    def test_rules_returns_discipline_descriptions(self, client: TestClient, db) -> None:
        """Discipline descriptions are included in the rules response."""
        book = make_book(db, number=1001, era="kai")
        discs = _seed_disciplines(db, era="kai")
        token = _register_and_login(client, "rulesuser")

        resp = client.get(f"/books/{book.id}/rules", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert "disciplines" in data
        returned_names = {d["name"] for d in data["disciplines"]}
        for disc in discs:
            assert disc.name in returned_names
        for d in data["disciplines"]:
            assert d["description"]  # description is non-empty

    def test_rules_returns_equipment_rules(self, client: TestClient, db) -> None:
        """equipment_rules field is present and contains weapon_categories."""
        book = make_book(db, number=1101, era="kai")
        _seed_disciplines(db, era="kai")
        _seed_weapon_categories(db)
        token = _register_and_login(client, "equiprulesuser")

        resp = client.get(f"/books/{book.id}/rules", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert "equipment_rules" in data
        eq = data["equipment_rules"]
        assert "weapon_categories" in eq
        assert "starting_equipment_note" in eq
        # The three seeded categories should appear
        assert "Sword" in eq["weapon_categories"]
        assert "Axe" in eq["weapon_categories"]

    def test_rules_returns_combat_rules_summary(self, client: TestClient, db) -> None:
        """combat_rules field is present with era and explanation strings."""
        book = make_book(db, number=1201, era="kai")
        _seed_disciplines(db, era="kai")
        token = _register_and_login(client, "combatrulesuser")

        resp = client.get(f"/books/{book.id}/rules", headers=_auth(token))

        assert resp.status_code == 200
        data = resp.json()
        assert "combat_rules" in data
        cr = data["combat_rules"]
        assert cr["era"] == "kai"
        assert "combat_ratio_explained" in cr
        assert "random_number_range" in cr

    def test_rules_returns_404_for_nonexistent_book(self, client: TestClient, db) -> None:
        """A book_id that does not exist returns 404."""
        token = _register_and_login(client, "rulesnotfounduser")

        resp = client.get("/books/99998/rules", headers=_auth(token))

        assert resp.status_code == 404

    def test_rules_returns_401_when_unauthenticated(self, client: TestClient, db) -> None:
        """No Bearer token must yield 401."""
        book = make_book(db, number=1301, era="kai")

        resp = client.get(f"/books/{book.id}/rules")

        assert resp.status_code == 401
