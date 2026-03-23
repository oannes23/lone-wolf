"""Integration tests for GET /game-objects and GET /game-objects/{id}."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.content import Book
from app.models.taxonomy import GameObject, GameObjectRef
from tests.factories import make_book, make_game_object, make_user
from tests.helpers.auth import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _seed_game_object(
    db: Session,
    name: str = "Lone Wolf",
    kind: str = "character",
    first_book: Book | None = None,
    aliases: list[str] | None = None,
    properties: dict | None = None,
) -> GameObject:
    go = GameObject(
        name=name,
        kind=kind,
        description=f"Description for {name}.",
        aliases=json.dumps(aliases or []),
        properties=json.dumps(properties or {}),
        first_book_id=first_book.id if first_book else None,
        source="manual",
    )
    db.add(go)
    db.flush()
    return go


def _seed_ref(
    db: Session,
    source: GameObject,
    target: GameObject,
    tags: list[str],
) -> GameObjectRef:
    ref = GameObjectRef(
        source_id=source.id,
        target_id=target.id,
        tags=json.dumps(tags),
        source="manual",
    )
    db.add(ref)
    db.flush()
    return ref


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGameObjectsList:
    """Tests for GET /game-objects."""

    def test_requires_auth(self, client: TestClient, db: Session) -> None:
        response = client.get("/game-objects")
        assert response.status_code == 401

    def test_list_all_returns_results(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_list_user", password="pass1234!")
        _seed_game_object(db, name="Test Character List")
        db.flush()

        response = client.get(
            "/game-objects",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_filter_by_kind(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_kind_user", password="pass1234!")
        _seed_game_object(db, name="A Character", kind="character")
        _seed_game_object(db, name="An Item", kind="item")
        db.flush()

        response = client.get(
            "/game-objects?kind=character",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert all(obj["kind"] == "character" for obj in data)

    def test_filter_by_book_id(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_bookid_user", password="pass1234!")
        book = make_book(db)
        _seed_game_object(db, name="Book Char", kind="character", first_book=book)
        _seed_game_object(db, name="No Book Char", kind="character")
        db.flush()

        response = client.get(
            f"/game-objects?book_id={book.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert all(
            obj["first_appearance"] is not None and obj["first_appearance"]["book_id"] == book.id
            for obj in data
        )

    def test_first_appearance_is_structured_object(
        self, client: TestClient, db: Session
    ) -> None:
        """first_appearance must be {book_id, book_title} not just an int."""
        tokens = register_and_login(client, username="go_fa_user", password="pass1234!")
        book = make_book(db, title="Flight from the Dark")
        _seed_game_object(db, name="FA Test Char", kind="character", first_book=book)
        db.flush()

        response = client.get(
            "/game-objects",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        fa_obj = next((o for o in data if o["name"] == "FA Test Char"), None)
        assert fa_obj is not None
        assert fa_obj["first_appearance"] is not None

        # Must be structured object with book_id and book_title
        fa = fa_obj["first_appearance"]
        assert "book_id" in fa
        assert "book_title" in fa
        assert fa["book_id"] == book.id
        assert fa["book_title"] == "Flight from the Dark"
        # Must NOT be a plain int
        assert not isinstance(fa, int)

    def test_no_first_appearance_returns_null(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_nofa_user", password="pass1234!")
        _seed_game_object(db, name="No FA Char", kind="character", first_book=None)
        db.flush()

        response = client.get(
            "/game-objects",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        nofa_obj = next((o for o in data if o["name"] == "No FA Char"), None)
        assert nofa_obj is not None
        assert nofa_obj["first_appearance"] is None

    def test_search_by_name(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_search_user", password="pass1234!")
        _seed_game_object(db, name="Lone Wolf Searchable", kind="character")
        _seed_game_object(db, name="Other Entity", kind="character")
        db.flush()

        response = client.get(
            "/game-objects?search=Lone Wolf Searchable",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [obj["name"] for obj in data]
        assert "Lone Wolf Searchable" in names


class TestGameObjectDetail:
    """Tests for GET /game-objects/{id}."""

    def test_detail_404_for_missing(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_detail404_user", password="pass1234!")
        response = client.get(
            "/game-objects/99999",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 404

    def test_detail_includes_first_appearance(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_detail_fa_user", password="pass1234!")
        book = make_book(db, title="Fire on the Water")
        go = _seed_game_object(
            db, name="Detail FA Char", kind="character", first_book=book
        )
        db.flush()

        response = client.get(
            f"/game-objects/{go.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()

        fa = data["first_appearance"]
        assert fa is not None
        assert "book_id" in fa
        assert "book_title" in fa
        assert fa["book_id"] == book.id
        assert fa["book_title"] == "Fire on the Water"

    def test_detail_includes_properties_and_refs(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_refs_user", password="pass1234!")
        go_source = _seed_game_object(
            db, name="Source Obj", kind="character",
            properties={"title": "Grand Master"}
        )
        go_target = _seed_game_object(db, name="Kai Order", kind="organization")
        _seed_ref(db, go_source, go_target, tags=["factional", "member_of"])
        db.flush()

        response = client.get(
            f"/game-objects/{go_source.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()

        assert "properties" in data
        assert data["properties"].get("title") == "Grand Master"
        assert "refs" in data
        assert len(data["refs"]) >= 1
        ref = data["refs"][0]
        assert ref["target"]["name"] == "Kai Order"
        assert "factional" in ref["tags"]


class TestGameObjectRefs:
    """Tests for GET /game-objects/{id}/refs."""

    def test_refs_pagination(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_refs_page_user", password="pass1234!")
        go_source = _seed_game_object(db, name="Paged Source", kind="character")
        for i in range(3):
            go_target = _seed_game_object(db, name=f"Target {i}", kind="item")
            _seed_ref(db, go_source, go_target, tags=["related"])
        db.flush()

        response = client.get(
            f"/game-objects/{go_source.id}/refs?limit=2&offset=0",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_refs_direction_incoming(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_refs_inc_user", password="pass1234!")
        go_source = _seed_game_object(db, name="Incoming Source", kind="character")
        go_target = _seed_game_object(db, name="Incoming Target", kind="item")
        _seed_ref(db, go_source, go_target, tags=["related"])
        db.flush()

        # Outgoing refs for source → should have 1
        response = client.get(
            f"/game-objects/{go_source.id}/refs?direction=outgoing",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1

        # Incoming refs for target → should have 1
        response = client.get(
            f"/game-objects/{go_target.id}/refs?direction=incoming",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1


# ---------------------------------------------------------------------------
# Additional tests for full coverage
# ---------------------------------------------------------------------------


class TestGameObjectsListExtended:
    """Extended list endpoint tests: search, pagination, case-insensitive."""

    def test_search_by_alias_case_insensitive(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_alias_search_user", password="pass1234!")
        _seed_game_object(
            db,
            name="The Darklord",
            kind="foe",
            aliases=["Darkmaster", "The Dark One"],
        )
        db.flush()

        response = client.get(
            "/game-objects?search=darkmaster",  # lowercase
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [obj["name"] for obj in data]
        assert "The Darklord" in names

    def test_search_by_description_case_insensitive(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_desc_search_user", password="pass1234!")
        go = _seed_game_object(
            db,
            name="Unique Desc Item",
            kind="item",
        )
        # Overwrite description with something searchable
        go.description = "A legendary ARTIFACT from ancient times"
        db.flush()
        db.flush()

        response = client.get(
            "/game-objects?search=legendary artifact",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [obj["name"] for obj in data]
        assert "Unique Desc Item" in names

    def test_search_by_name_case_insensitive(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_name_case_user", password="pass1234!")
        _seed_game_object(db, name="Kalte Glacier", kind="location")
        db.flush()

        response = client.get(
            "/game-objects?search=kalte",  # lowercase
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [obj["name"] for obj in data]
        assert "Kalte Glacier" in names

    def test_list_pagination_offset(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_pagination_user", password="pass1234!")
        # Use valid kind values; use unique name prefix to avoid UNIQUE constraint conflicts
        for i in range(5):
            _seed_game_object(db, name=f"PaginatedSceneObject {i}", kind="scene")
        db.flush()

        # Get first 2
        resp1 = client.get(
            "/game-objects?search=PaginatedSceneObject&limit=2&offset=0",
            headers=auth_headers(tokens["access_token"]),
        )
        assert resp1.status_code == 200
        page1 = resp1.json()

        # Get next 2
        resp2 = client.get(
            "/game-objects?search=PaginatedSceneObject&limit=2&offset=2",
            headers=auth_headers(tokens["access_token"]),
        )
        assert resp2.status_code == 200
        page2 = resp2.json()

        # Pages should not overlap
        ids1 = {obj["id"] for obj in page1}
        ids2 = {obj["id"] for obj in page2}
        assert ids1.isdisjoint(ids2)

    def test_list_response_shape(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_shape_user", password="pass1234!")
        _seed_game_object(db, name="Shape Test Obj", kind="item")
        db.flush()

        response = client.get(
            "/game-objects?kind=item",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        obj = next((o for o in data if o["name"] == "Shape Test Obj"), None)
        assert obj is not None
        assert "id" in obj
        assert "name" in obj
        assert "kind" in obj
        assert obj["kind"] == "item"
        assert "description" in obj
        assert "aliases" in obj
        assert isinstance(obj["aliases"], list)
        assert "first_appearance" in obj

    def test_filter_by_kind_excludes_other_kinds(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_excl_kind_user", password="pass1234!")
        # Use valid kind values from the CHECK constraint
        _seed_game_object(db, name="Excl Kind Creature", kind="creature")
        _seed_game_object(db, name="Excl Kind Organization", kind="organization")
        db.flush()

        response = client.get(
            "/game-objects?kind=creature",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        kinds = {obj["kind"] for obj in data}
        assert "creature" in kinds
        assert "organization" not in kinds

    def test_aliases_returned_as_list(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_aliases_list_user", password="pass1234!")
        _seed_game_object(
            db,
            name="Multi Alias Object",
            kind="item",
            aliases=["alias_one", "alias_two"],
        )
        db.flush()

        response = client.get(
            "/game-objects",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        ma_obj = next((o for o in data if o["name"] == "Multi Alias Object"), None)
        assert ma_obj is not None
        assert isinstance(ma_obj["aliases"], list)
        assert "alias_one" in ma_obj["aliases"]
        assert "alias_two" in ma_obj["aliases"]


class TestGameObjectDetailExtended:
    """Extended detail tests: 401, properties, refs."""

    def test_detail_requires_auth(self, client: TestClient, db: Session) -> None:
        go = _seed_game_object(db, name="Auth Required Object", kind="item")
        db.flush()

        response = client.get(f"/game-objects/{go.id}")
        assert response.status_code == 401

    def test_detail_properties_parsed_as_dict(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_props_dict_user", password="pass1234!")
        go = _seed_game_object(
            db,
            name="Props Dict Object",
            kind="item",
            properties={"damage": 5, "weight": "heavy", "magic": True},
        )
        db.flush()

        response = client.get(
            f"/game-objects/{go.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        props = data["properties"]
        assert isinstance(props, dict)
        assert props["damage"] == 5
        assert props["weight"] == "heavy"
        assert props["magic"] is True

    def test_detail_refs_tag_filter(self, client: TestClient, db: Session) -> None:
        tokens = register_and_login(client, username="go_tag_filter_user", password="pass1234!")
        go_src = _seed_game_object(db, name="Tag Filter Source", kind="character")
        go_t1 = _seed_game_object(db, name="Tag Filter T1", kind="item")
        go_t2 = _seed_game_object(db, name="Tag Filter T2", kind="location")
        _seed_ref(db, go_src, go_t1, tags=["ally", "carries"])
        _seed_ref(db, go_src, go_t2, tags=["visits"])
        db.flush()

        # Filter refs by tag "ally"
        response = client.get(
            f"/game-objects/{go_src.id}/refs?tag=ally",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["target"]["name"] == "Tag Filter T1"
        assert "ally" in data[0]["tags"]

    def test_detail_refs_direction_outgoing_by_default(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_outgoing_default_user", password="pass1234!")
        go_a = _seed_game_object(db, name="Outgoing Default A", kind="character")
        go_b = _seed_game_object(db, name="Outgoing Default B", kind="item")
        _seed_ref(db, go_a, go_b, tags=["default_direction"])
        db.flush()

        # Without direction= param, outgoing is default
        response = client.get(
            f"/game-objects/{go_a.id}/refs",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        names = [r["target"]["name"] for r in data]
        assert "Outgoing Default B" in names

    def test_refs_404_for_nonexistent_object(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_refs_404_user", password="pass1234!")
        response = client.get(
            "/game-objects/99999/refs",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 404

    def test_refs_401_unauthenticated(self, client: TestClient, db: Session) -> None:
        go = _seed_game_object(db, name="Refs Auth Object", kind="item")
        db.flush()

        response = client.get(f"/game-objects/{go.id}/refs")
        assert response.status_code == 401

    def test_detail_ref_target_has_id_name_kind(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_ref_target_user", password="pass1234!")
        go_src = _seed_game_object(db, name="Ref Target Source", kind="character")
        go_tgt = _seed_game_object(db, name="Ref Target Dest", kind="foe")
        _seed_ref(db, go_src, go_tgt, tags=["enemy"])
        db.flush()

        response = client.get(
            f"/game-objects/{go_src.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        ref = data["refs"][0]
        target = ref["target"]
        assert "id" in target
        assert "name" in target
        assert target["name"] == "Ref Target Dest"
        assert "kind" in target
        assert target["kind"] == "foe"

    def test_detail_empty_refs_returns_empty_list(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_no_refs_user", password="pass1234!")
        go = _seed_game_object(db, name="No Refs Object", kind="item")
        db.flush()

        response = client.get(
            f"/game-objects/{go.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["refs"] == []

    def test_first_appearance_in_detail_is_null_when_no_book(
        self, client: TestClient, db: Session
    ) -> None:
        tokens = register_and_login(client, username="go_detail_null_fa_user", password="pass1234!")
        go = _seed_game_object(db, name="Detail No FA", kind="item", first_book=None)
        db.flush()

        response = client.get(
            f"/game-objects/{go.id}",
            headers=auth_headers(tokens["access_token"]),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["first_appearance"] is None
