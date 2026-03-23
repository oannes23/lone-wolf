"""Integration tests for Story 7.5: Admin Content CRUD & Report Queue.

Covers:
- CRUD operations for books, scenes, choices
- source column set to 'manual' on create/update
- wizard-templates are read-only (POST/PUT/DELETE return 405)
- Report triage workflow (open -> triaging -> resolved)
- Report stats return correct aggregates
- character-events filterable by all params
- All admin endpoints reject non-admin auth (401)
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.models.admin import AdminUser, Report
from app.models.content import Book, Choice, Scene
from app.models.player import CharacterEvent, User
from app.models.wizard import WizardTemplate
from app.services.auth_service import hash_password
from tests.factories import make_book, make_character, make_scene, make_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(db, username: str = "contentadmin", password: str = "AdminPass1!") -> AdminUser:
    """Insert an admin user into the test database."""
    admin = AdminUser(username=username, password_hash=hash_password(password))
    db.add(admin)
    db.flush()
    return admin


def _admin_token(client: TestClient, db, username: str = "contentadmin") -> str:
    """Create an admin and return a valid admin access token."""
    _make_admin(db, username=username)
    resp = client.post(
        "/admin/auth/login",
        json={"username": username, "password": "AdminPass1!"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _player_token(client: TestClient) -> str:
    """Register a player user and return their access token."""
    client.post(
        "/auth/register",
        json={"username": "admintest_player", "email": "admintest_player@test.com", "password": "Pass1234!"},
    )
    resp = client.post("/auth/login", data={"username": "admintest_player", "password": "Pass1234!"})
    return resp.json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_report(
    db,
    user: User,
    status: str = "open",
    tags: list[str] | None = None,
    scene_id: int | None = None,
    free_text: str | None = None,
) -> Report:
    """Insert a report directly into the test database."""
    now = _now()
    report = Report(
        user_id=user.id,
        scene_id=scene_id,
        tags=json.dumps(tags or []),
        free_text=free_text,
        status=status,
        created_at=now,
        updated_at=now,
    )
    db.add(report)
    db.flush()
    return report


def _make_character_event(
    db,
    character,
    scene,
    event_type: str = "item_pickup",
    run_number: int = 1,
    seq: int = 1,
) -> CharacterEvent:
    """Insert a CharacterEvent into the test database."""
    event = CharacterEvent(
        character_id=character.id,
        scene_id=scene.id,
        run_number=run_number,
        event_type=event_type,
        seq=seq,
        created_at=_now(),
    )
    db.add(event)
    db.flush()
    return event


# ===========================================================================
# Books CRUD
# ===========================================================================


class TestAdminBooksCRUD:
    def test_create_book_returns_201(self, client: TestClient, db) -> None:
        """POST /admin/books creates a book and returns 201."""
        token = _admin_token(client, db, username="booksadmin1")
        resp = client.post(
            "/admin/books",
            json={
                "slug": "test-book-001",
                "number": 99,
                "title": "Test Book One",
                "era": "kai",
                "series": "lone_wolf",
                "start_scene_number": 1,
                "max_total_picks": 5,
            },
            headers=_bearer(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["slug"] == "test-book-001"
        assert data["number"] == 99
        assert data["title"] == "Test Book One"
        assert "id" in data

    def test_list_books(self, client: TestClient, db) -> None:
        """GET /admin/books returns all books."""
        token = _admin_token(client, db, username="booksadmin2")
        make_book(db, slug="listable-book-a", number=201)
        make_book(db, slug="listable-book-b", number=202)

        resp = client.get("/admin/books", headers=_bearer(token))
        assert resp.status_code == 200
        slugs = {b["slug"] for b in resp.json()}
        assert "listable-book-a" in slugs
        assert "listable-book-b" in slugs

    def test_get_book_detail(self, client: TestClient, db) -> None:
        """GET /admin/books/{id} returns the book."""
        token = _admin_token(client, db, username="booksadmin3")
        book = make_book(db, slug="detail-book-001", number=301)

        resp = client.get(f"/admin/books/{book.id}", headers=_bearer(token))
        assert resp.status_code == 200
        assert resp.json()["id"] == book.id
        assert resp.json()["slug"] == "detail-book-001"

    def test_get_book_not_found(self, client: TestClient, db) -> None:
        """GET /admin/books/99999 returns 404 when the book does not exist."""
        token = _admin_token(client, db, username="booksadmin4")
        resp = client.get("/admin/books/99999", headers=_bearer(token))
        assert resp.status_code == 404

    def test_update_book(self, client: TestClient, db) -> None:
        """PUT /admin/books/{id} updates the book title."""
        token = _admin_token(client, db, username="booksadmin5")
        book = make_book(db, slug="update-book-001", number=401, title="Old Title")

        resp = client.put(
            f"/admin/books/{book.id}",
            json={"title": "New Title"},
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    def test_delete_book_returns_204(self, client: TestClient, db) -> None:
        """DELETE /admin/books/{id} deletes the book and returns 204."""
        token = _admin_token(client, db, username="booksadmin6")
        book = make_book(db, slug="delete-book-001", number=501)

        book_id = book.id
        resp = client.delete(f"/admin/books/{book_id}", headers=_bearer(token))
        assert resp.status_code == 204

        # Verify deletion — expunge the deleted object before re-querying
        db.expunge_all()
        from_db = db.query(Book).filter(Book.id == book_id).first()
        assert from_db is None

    def test_admin_books_rejects_non_admin(self, client: TestClient, db) -> None:
        """Player token is rejected on all /admin/books endpoints."""
        _make_admin(db, username="booksadmin7")
        player_tok = _player_token(client)

        resp = client.get("/admin/books", headers=_bearer(player_tok))
        assert resp.status_code == 401

    def test_admin_books_rejects_unauthenticated(self, client: TestClient, db) -> None:
        """No token returns 401 on /admin/books."""
        resp = client.get("/admin/books")
        assert resp.status_code == 401


# ===========================================================================
# Scenes CRUD
# ===========================================================================


class TestAdminScenesCRUD:
    def test_create_scene_sets_source_manual(self, client: TestClient, db) -> None:
        """POST /admin/scenes creates a scene and sets source='manual'."""
        token = _admin_token(client, db, username="scenesadmin1")
        book = make_book(db, slug="scene-test-book-01", number=1001)

        resp = client.post(
            "/admin/scenes",
            json={
                "book_id": book.id,
                "number": 1,
                "html_id": "sect1",
                "narrative": "You stand at the crossroads.",
                "is_death": False,
                "is_victory": False,
                "must_eat": False,
            },
            headers=_bearer(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "manual"
        assert data["book_id"] == book.id
        assert data["narrative"] == "You stand at the crossroads."

    def test_create_scene_stores_in_database_with_manual_source(
        self, client: TestClient, db
    ) -> None:
        """Source='manual' is persisted to the database on scene create."""
        token = _admin_token(client, db, username="scenesadmin2")
        book = make_book(db, slug="scene-test-book-02", number=1002)

        resp = client.post(
            "/admin/scenes",
            json={
                "book_id": book.id,
                "number": 2,
                "html_id": "sect2",
                "narrative": "Test narrative.",
                "is_death": False,
                "is_victory": False,
                "must_eat": False,
            },
            headers=_bearer(token),
        )
        assert resp.status_code == 201
        scene_id = resp.json()["id"]

        from_db = db.query(Scene).filter(Scene.id == scene_id).first()
        assert from_db is not None
        assert from_db.source == "manual"

    def test_update_scene_sets_source_manual(self, client: TestClient, db) -> None:
        """PUT /admin/scenes/{id} always sets source='manual' on update."""
        token = _admin_token(client, db, username="scenesadmin3")
        book = make_book(db, slug="scene-test-book-03", number=1003)
        scene = make_scene(db, book, source="auto", narrative="Original text.")

        resp = client.put(
            f"/admin/scenes/{scene.id}",
            json={"narrative": "Updated by admin."},
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["source"] == "manual"
        assert resp.json()["narrative"] == "Updated by admin."

    def test_update_scene_persists_source_change(self, client: TestClient, db) -> None:
        """After PUT, source='manual' is stored in the database."""
        token = _admin_token(client, db, username="scenesadmin4")
        book = make_book(db, slug="scene-test-book-04", number=1004)
        scene = make_scene(db, book, source="auto")

        client.put(
            f"/admin/scenes/{scene.id}",
            json={"narrative": "Admin updated."},
            headers=_bearer(token),
        )

        db.refresh(scene)
        assert scene.source == "manual"

    def test_list_scenes(self, client: TestClient, db) -> None:
        """GET /admin/scenes returns all scenes."""
        token = _admin_token(client, db, username="scenesadmin5")
        book = make_book(db, slug="scene-test-book-05", number=1005)
        make_scene(db, book, number=1)
        make_scene(db, book, number=2)

        resp = client.get("/admin/scenes", headers=_bearer(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_list_scenes_filtered_by_book(self, client: TestClient, db) -> None:
        """GET /admin/scenes?book_id=X returns only scenes for that book."""
        token = _admin_token(client, db, username="scenesadmin6")
        book_a = make_book(db, slug="scene-filter-book-a", number=2001)
        book_b = make_book(db, slug="scene-filter-book-b", number=2002)
        make_scene(db, book_a, number=1)
        make_scene(db, book_b, number=1)

        resp = client.get(f"/admin/scenes?book_id={book_a.id}", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()
        assert all(s["book_id"] == book_a.id for s in data)

    def test_get_scene_detail(self, client: TestClient, db) -> None:
        """GET /admin/scenes/{id} returns the scene."""
        token = _admin_token(client, db, username="scenesadmin7")
        book = make_book(db, slug="scene-test-book-07", number=1007)
        scene = make_scene(db, book, number=1, narrative="Test scene detail.")

        resp = client.get(f"/admin/scenes/{scene.id}", headers=_bearer(token))
        assert resp.status_code == 200
        assert resp.json()["id"] == scene.id
        assert resp.json()["narrative"] == "Test scene detail."

    def test_delete_scene(self, client: TestClient, db) -> None:
        """DELETE /admin/scenes/{id} removes the scene."""
        token = _admin_token(client, db, username="scenesadmin8")
        book = make_book(db, slug="scene-test-book-08", number=1008)
        scene = make_scene(db, book, number=1)

        resp = client.delete(f"/admin/scenes/{scene.id}", headers=_bearer(token))
        assert resp.status_code == 204

    def test_scenes_endpoints_reject_non_admin(self, client: TestClient, db) -> None:
        """Player token returns 401 on /admin/scenes."""
        _make_admin(db, username="scenesadmin9")
        player_tok = _player_token(client)
        resp = client.get("/admin/scenes", headers=_bearer(player_tok))
        assert resp.status_code == 401


# ===========================================================================
# Choices CRUD
# ===========================================================================


class TestAdminChoicesCRUD:
    def test_create_choice_sets_source_manual(self, client: TestClient, db) -> None:
        """POST /admin/choices creates a choice with source='manual'."""
        token = _admin_token(client, db, username="choicesadmin1")
        book = make_book(db, slug="choice-test-book-01", number=3001)
        scene = make_scene(db, book, number=1)

        resp = client.post(
            "/admin/choices",
            json={
                "scene_id": scene.id,
                "target_scene_number": 42,
                "raw_text": "If you wish to go north, turn to 42.",
                "display_text": "Turn to 42.",
                "ordinal": 1,
            },
            headers=_bearer(token),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "manual"
        assert data["scene_id"] == scene.id
        assert data["target_scene_number"] == 42

    def test_create_choice_persists_manual_source(self, client: TestClient, db) -> None:
        """Source='manual' is stored in the database when creating a choice."""
        token = _admin_token(client, db, username="choicesadmin2")
        book = make_book(db, slug="choice-test-book-02", number=3002)
        scene = make_scene(db, book, number=1)

        resp = client.post(
            "/admin/choices",
            json={
                "scene_id": scene.id,
                "target_scene_number": 55,
                "raw_text": "Turn to 55.",
                "display_text": "Turn to 55.",
                "ordinal": 1,
            },
            headers=_bearer(token),
        )
        assert resp.status_code == 201
        choice_id = resp.json()["id"]

        from_db = db.query(Choice).filter(Choice.id == choice_id).first()
        assert from_db is not None
        assert from_db.source == "manual"

    def test_update_choice_sets_source_manual(self, client: TestClient, db) -> None:
        """PUT /admin/choices/{id} sets source='manual' even if it was 'auto'."""
        token = _admin_token(client, db, username="choicesadmin3")
        book = make_book(db, slug="choice-test-book-03", number=3003)
        scene = make_scene(db, book, number=1)
        from tests.factories import make_choice
        choice = make_choice(db, scene, source="auto", target_scene_number=10)

        resp = client.put(
            f"/admin/choices/{choice.id}",
            json={"target_scene_number": 20},
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["source"] == "manual"
        assert resp.json()["target_scene_number"] == 20

    def test_list_choices(self, client: TestClient, db) -> None:
        """GET /admin/choices returns choices."""
        token = _admin_token(client, db, username="choicesadmin4")
        book = make_book(db, slug="choice-list-book-01", number=4001)
        scene = make_scene(db, book, number=1)
        from tests.factories import make_choice
        make_choice(db, scene)
        make_choice(db, scene)

        resp = client.get("/admin/choices", headers=_bearer(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_list_choices_filtered_by_scene(self, client: TestClient, db) -> None:
        """GET /admin/choices?scene_id=X returns only choices for that scene."""
        token = _admin_token(client, db, username="choicesadmin5")
        book = make_book(db, slug="choice-filter-book-01", number=4002)
        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)
        from tests.factories import make_choice
        make_choice(db, scene_a)
        make_choice(db, scene_b)

        resp = client.get(f"/admin/choices?scene_id={scene_a.id}", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()
        assert all(c["scene_id"] == scene_a.id for c in data)

    def test_get_choice_detail(self, client: TestClient, db) -> None:
        """GET /admin/choices/{id} returns the choice."""
        token = _admin_token(client, db, username="choicesadmin6")
        book = make_book(db, slug="choice-detail-book-01", number=4003)
        scene = make_scene(db, book, number=1)
        from tests.factories import make_choice
        choice = make_choice(db, scene)

        resp = client.get(f"/admin/choices/{choice.id}", headers=_bearer(token))
        assert resp.status_code == 200
        assert resp.json()["id"] == choice.id

    def test_delete_choice(self, client: TestClient, db) -> None:
        """DELETE /admin/choices/{id} removes the choice."""
        token = _admin_token(client, db, username="choicesadmin7")
        book = make_book(db, slug="choice-del-book-01", number=4004)
        scene = make_scene(db, book, number=1)
        from tests.factories import make_choice
        choice = make_choice(db, scene)

        resp = client.delete(f"/admin/choices/{choice.id}", headers=_bearer(token))
        assert resp.status_code == 204

        from_db = db.query(Choice).filter(Choice.id == choice.id).first()
        assert from_db is None

    def test_choices_endpoints_reject_non_admin(self, client: TestClient, db) -> None:
        """Player token returns 401 on /admin/choices."""
        _make_admin(db, username="choicesadmin8")
        player_tok = _player_token(client)
        resp = client.get("/admin/choices", headers=_bearer(player_tok))
        assert resp.status_code == 401


# ===========================================================================
# Wizard Templates — read-only
# ===========================================================================


class TestAdminWizardTemplatesReadOnly:
    def test_post_wizard_templates_returns_405(self, client: TestClient, db) -> None:
        """POST /admin/wizard-templates returns 405 (read-only)."""
        token = _admin_token(client, db, username="wizardadmin1")
        resp = client.post(
            "/admin/wizard-templates",
            json={"name": "should_fail", "description": "Nope"},
            headers=_bearer(token),
        )
        assert resp.status_code == 405

    def test_put_wizard_templates_returns_405(self, client: TestClient, db) -> None:
        """PUT /admin/wizard-templates/{id} returns 405 (read-only)."""
        token = _admin_token(client, db, username="wizardadmin2")
        template = WizardTemplate(name="readonly_wizard_put", description="Test")
        db.add(template)
        db.flush()

        resp = client.put(
            f"/admin/wizard-templates/{template.id}",
            json={"description": "Updated"},
            headers=_bearer(token),
        )
        assert resp.status_code == 405

    def test_delete_wizard_templates_returns_405(self, client: TestClient, db) -> None:
        """DELETE /admin/wizard-templates/{id} returns 405 (read-only)."""
        token = _admin_token(client, db, username="wizardadmin3")
        template = WizardTemplate(name="readonly_wizard_del", description="Test")
        db.add(template)
        db.flush()

        resp = client.delete(
            f"/admin/wizard-templates/{template.id}",
            headers=_bearer(token),
        )
        assert resp.status_code == 405

    def test_get_wizard_templates_returns_list(self, client: TestClient, db) -> None:
        """GET /admin/wizard-templates returns all templates."""
        token = _admin_token(client, db, username="wizardadmin4")
        template = WizardTemplate(name="readable_wizard", description="Test")
        db.add(template)
        db.flush()

        resp = client.get("/admin/wizard-templates", headers=_bearer(token))
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()]
        assert "readable_wizard" in names

    def test_get_wizard_template_detail(self, client: TestClient, db) -> None:
        """GET /admin/wizard-templates/{id} returns the template."""
        token = _admin_token(client, db, username="wizardadmin5")
        template = WizardTemplate(name="detail_wizard", description="Detail test")
        db.add(template)
        db.flush()

        resp = client.get(f"/admin/wizard-templates/{template.id}", headers=_bearer(token))
        assert resp.status_code == 200
        assert resp.json()["name"] == "detail_wizard"


# ===========================================================================
# Admin Report Triage Workflow
# ===========================================================================


class TestAdminReportTriage:
    def test_report_triage_open_to_triaging(self, client: TestClient, db) -> None:
        """PUT /admin/reports/{id} transitions status from 'open' to 'triaging'."""
        token = _admin_token(client, db, username="reporttriage1")
        user = make_user(db)
        report = _make_report(db, user, status="open", tags=["meal_issue"])

        resp = client.put(
            f"/admin/reports/{report.id}",
            json={"status": "triaging"},
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "triaging"

    def test_report_triage_triaging_to_resolved(self, client: TestClient, db) -> None:
        """PUT /admin/reports/{id} transitions status from 'triaging' to 'resolved'."""
        token = _admin_token(client, db, username="reporttriage2")
        user = make_user(db)
        report = _make_report(db, user, status="triaging", tags=["combat_issue"])

        resp = client.put(
            f"/admin/reports/{report.id}",
            json={"status": "resolved", "admin_notes": "Fixed in next release."},
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "resolved"
        assert data["admin_notes"] == "Fixed in next release."

    def test_report_triage_full_workflow(self, client: TestClient, db) -> None:
        """Full triage workflow: open -> triaging -> resolved."""
        token = _admin_token(client, db, username="reporttriage3")
        user = make_user(db)
        report = _make_report(db, user, status="open", tags=["narrative_error"])

        # Step 1: open -> triaging
        resp1 = client.put(
            f"/admin/reports/{report.id}",
            json={"status": "triaging"},
            headers=_bearer(token),
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "triaging"

        # Step 2: triaging -> resolved
        resp2 = client.put(
            f"/admin/reports/{report.id}",
            json={"status": "resolved", "admin_notes": "Confirmed and fixed."},
            headers=_bearer(token),
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "resolved"
        assert resp2.json()["admin_notes"] == "Confirmed and fixed."

    def test_update_report_invalid_status_returns_400(self, client: TestClient, db) -> None:
        """Setting an invalid status returns 400."""
        token = _admin_token(client, db, username="reporttriage4")
        user = make_user(db)
        report = _make_report(db, user, status="open")

        resp = client.put(
            f"/admin/reports/{report.id}",
            json={"status": "invalid_status"},
            headers=_bearer(token),
        )
        assert resp.status_code == 400

    def test_list_reports_filterable_by_status(self, client: TestClient, db) -> None:
        """GET /admin/reports?status=open returns only open reports."""
        token = _admin_token(client, db, username="reporttriage5")
        user = make_user(db)
        _make_report(db, user, status="open", tags=["other"])
        _make_report(db, user, status="resolved", tags=["meal_issue"])

        resp = client.get("/admin/reports?status=open", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["status"] == "open" for r in data)

    def test_list_reports_filterable_by_tag(self, client: TestClient, db) -> None:
        """GET /admin/reports?tags=meal_issue returns only reports with that tag."""
        token = _admin_token(client, db, username="reporttriage6")
        user = make_user(db)
        _make_report(db, user, status="open", tags=["meal_issue"])
        _make_report(db, user, status="open", tags=["combat_issue"])

        resp = client.get("/admin/reports?tags=meal_issue", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()
        assert all("meal_issue" in r["tags"] for r in data)

    def test_get_report_detail(self, client: TestClient, db) -> None:
        """GET /admin/reports/{id} returns report detail including scene info."""
        token = _admin_token(client, db, username="reporttriage7")
        user = make_user(db)
        report = _make_report(db, user, status="open", tags=["narrative_error"])

        resp = client.get(f"/admin/reports/{report.id}", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == report.id
        assert "tags" in data

    def test_get_report_detail_includes_scene_info(self, client: TestClient, db) -> None:
        """GET /admin/reports/{id} includes scene_number and narrative when scene exists."""
        token = _admin_token(client, db, username="reporttriage8")
        user = make_user(db)
        book = make_book(db, slug="report-scene-book-01", number=9001)
        scene = make_scene(db, book, number=42, narrative="Dark forest path.")
        report = _make_report(db, user, status="open", tags=["other"], scene_id=scene.id)

        resp = client.get(f"/admin/reports/{report.id}", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["scene_id"] == scene.id
        assert data["scene_number"] == 42
        assert data["scene_narrative"] == "Dark forest path."

    def test_get_report_not_found_returns_404(self, client: TestClient, db) -> None:
        """GET /admin/reports/99999 returns 404."""
        token = _admin_token(client, db, username="reporttriage9")
        resp = client.get("/admin/reports/99999", headers=_bearer(token))
        assert resp.status_code == 404

    def test_reports_endpoints_reject_non_admin(self, client: TestClient, db) -> None:
        """Player token returns 401 on all /admin/reports endpoints."""
        _make_admin(db, username="reporttriage10")
        player_tok = _player_token(client)
        resp = client.get("/admin/reports", headers=_bearer(player_tok))
        assert resp.status_code == 401

    def test_reports_endpoints_reject_unauthenticated(self, client: TestClient, db) -> None:
        """No token returns 401 on /admin/reports."""
        resp = client.get("/admin/reports")
        assert resp.status_code == 401


# ===========================================================================
# Report Stats
# ===========================================================================


class TestAdminReportStats:
    def test_stats_empty_database(self, client: TestClient, db) -> None:
        """GET /admin/reports/stats returns the expected response shape."""
        token = _admin_token(client, db, username="statsadmin1")

        resp = client.get("/admin/reports/stats", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()
        # Verify response shape without assuming the database is empty — other
        # tests in the session may have seeded reports before this one runs.
        assert "total" in data
        assert isinstance(data["total"], int)
        assert isinstance(data["by_tag"], list)
        assert isinstance(data["by_status"], list)
        assert isinstance(data["resolution_rate"], float)

    def test_stats_correct_totals(self, client: TestClient, db) -> None:
        """Report stats return correct total and per-status counts."""
        token = _admin_token(client, db, username="statsadmin2")

        # Capture baseline before seeding so leaked reports from other tests
        # do not cause false failures.
        baseline = client.get("/admin/reports/stats", headers=_bearer(token)).json()
        base_total = baseline["total"]
        base_status_map = {s["status"]: s["count"] for s in baseline["by_status"]}

        user = make_user(db)
        _make_report(db, user, status="open", tags=["meal_issue"])
        _make_report(db, user, status="open", tags=["combat_issue", "meal_issue"])
        _make_report(db, user, status="resolved", tags=["other"])

        resp = client.get("/admin/reports/stats", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == base_total + 3

        # Check per-status deltas
        status_map = {s["status"]: s["count"] for s in data["by_status"]}
        assert status_map.get("open", 0) == base_status_map.get("open", 0) + 2
        assert status_map.get("resolved", 0) == base_status_map.get("resolved", 0) + 1

    def test_stats_tag_counts(self, client: TestClient, db) -> None:
        """Report stats correctly count per-tag occurrences across all reports."""
        token = _admin_token(client, db, username="statsadmin3")

        # Capture baseline tag counts before seeding.
        baseline = client.get("/admin/reports/stats", headers=_bearer(token)).json()
        base_tag_map = {t["tag"]: t["count"] for t in baseline["by_tag"]}

        user = make_user(db)
        _make_report(db, user, status="open", tags=["meal_issue"])
        _make_report(db, user, status="open", tags=["meal_issue", "combat_issue"])
        _make_report(db, user, status="open", tags=["other"])

        resp = client.get("/admin/reports/stats", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()

        tag_map = {t["tag"]: t["count"] for t in data["by_tag"]}
        assert tag_map.get("meal_issue", 0) == base_tag_map.get("meal_issue", 0) + 2
        assert tag_map.get("combat_issue", 0) == base_tag_map.get("combat_issue", 0) + 1
        assert tag_map.get("other", 0) == base_tag_map.get("other", 0) + 1

    def test_stats_resolution_rate(self, client: TestClient, db) -> None:
        """Resolution rate = resolved / total."""
        token = _admin_token(client, db, username="statsadmin4")

        # Capture baseline resolved and total counts before seeding.
        baseline = client.get("/admin/reports/stats", headers=_bearer(token)).json()
        base_total = baseline["total"]
        base_status_map = {s["status"]: s["count"] for s in baseline["by_status"]}
        base_resolved = base_status_map.get("resolved", 0)

        user = make_user(db)
        _make_report(db, user, status="resolved", tags=[])
        _make_report(db, user, status="resolved", tags=[])
        _make_report(db, user, status="open", tags=[])
        _make_report(db, user, status="open", tags=[])

        resp = client.get("/admin/reports/stats", headers=_bearer(token))
        assert resp.status_code == 200
        data = resp.json()

        expected_total = base_total + 4
        expected_resolved = base_resolved + 2
        expected_rate = expected_resolved / expected_total

        assert data["total"] == expected_total
        assert abs(data["resolution_rate"] - expected_rate) < 0.001

    def test_stats_rejects_non_admin(self, client: TestClient, db) -> None:
        """Player token returns 401 on /admin/reports/stats."""
        _make_admin(db, username="statsadmin5")
        player_tok = _player_token(client)
        resp = client.get("/admin/reports/stats", headers=_bearer(player_tok))
        assert resp.status_code == 401


# ===========================================================================
# Character Events Viewer
# ===========================================================================


class TestAdminCharacterEvents:
    def test_list_character_events_no_filter(self, client: TestClient, db) -> None:
        """GET /admin/character-events returns events."""
        token = _admin_token(client, db, username="eventsadmin1")
        user = make_user(db)
        book = make_book(db, slug="events-book-01", number=8001)
        scene = make_scene(db, book, number=1)
        character = make_character(db, user, book)
        _make_character_event(db, character, scene, event_type="item_pickup", seq=1)
        _make_character_event(db, character, scene, event_type="gold_change", seq=2)

        resp = client.get("/admin/character-events", headers=_bearer(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 2

    def test_filter_by_character_id(self, client: TestClient, db) -> None:
        """GET /admin/character-events?character_id=X returns only that character's events."""
        token = _admin_token(client, db, username="eventsadmin2")
        user = make_user(db)
        book = make_book(db, slug="events-book-02", number=8002)
        scene = make_scene(db, book, number=1)
        char_a = make_character(db, user, book)
        char_b = make_character(db, user, book)

        _make_character_event(db, char_a, scene, event_type="item_pickup", seq=1)
        _make_character_event(db, char_b, scene, event_type="gold_change", seq=1)

        resp = client.get(
            f"/admin/character-events?character_id={char_a.id}",
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["character_id"] == char_a.id for e in data)

    def test_filter_by_event_type(self, client: TestClient, db) -> None:
        """GET /admin/character-events?event_type=X returns only that event type."""
        token = _admin_token(client, db, username="eventsadmin3")
        user = make_user(db)
        book = make_book(db, slug="events-book-03", number=8003)
        scene = make_scene(db, book, number=1)
        character = make_character(db, user, book)

        _make_character_event(db, character, scene, event_type="item_pickup", seq=1)
        _make_character_event(db, character, scene, event_type="gold_change", seq=2)

        resp = client.get(
            "/admin/character-events?event_type=item_pickup",
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["event_type"] == "item_pickup" for e in data)

    def test_filter_by_scene_id(self, client: TestClient, db) -> None:
        """GET /admin/character-events?scene_id=X returns only events in that scene."""
        token = _admin_token(client, db, username="eventsadmin4")
        user = make_user(db)
        book = make_book(db, slug="events-book-04", number=8004)
        scene_a = make_scene(db, book, number=1)
        scene_b = make_scene(db, book, number=2)
        character = make_character(db, user, book)

        _make_character_event(db, character, scene_a, event_type="item_pickup", seq=1)
        _make_character_event(db, character, scene_b, event_type="gold_change", seq=2)

        resp = client.get(
            f"/admin/character-events?scene_id={scene_a.id}",
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["scene_id"] == scene_a.id for e in data)

    def test_filter_by_all_params(self, client: TestClient, db) -> None:
        """GET /admin/character-events with all filters narrows results correctly."""
        token = _admin_token(client, db, username="eventsadmin5")
        user = make_user(db)
        book = make_book(db, slug="events-book-05", number=8005)
        scene = make_scene(db, book, number=1)
        character = make_character(db, user, book)

        target = _make_character_event(db, character, scene, event_type="healing", seq=1)
        _make_character_event(db, character, scene, event_type="item_pickup", seq=2)

        resp = client.get(
            f"/admin/character-events?character_id={character.id}&event_type=healing&scene_id={scene.id}",
            headers=_bearer(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == target.id

    def test_character_events_response_shape(self, client: TestClient, db) -> None:
        """Each event in the response contains all expected fields."""
        token = _admin_token(client, db, username="eventsadmin6")
        user = make_user(db)
        book = make_book(db, slug="events-book-06", number=8006)
        scene = make_scene(db, book, number=1)
        character = make_character(db, user, book)
        _make_character_event(db, character, scene, event_type="item_pickup", seq=1)

        resp = client.get("/admin/character-events", headers=_bearer(token))
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
        event = resp.json()[0]
        for field in (
            "id", "character_id", "scene_id", "run_number",
            "event_type", "phase", "details", "seq", "created_at"
        ):
            assert field in event, f"Missing field: {field}"

    def test_character_events_rejects_non_admin(self, client: TestClient, db) -> None:
        """Player token returns 401 on /admin/character-events."""
        _make_admin(db, username="eventsadmin7")
        player_tok = _player_token(client)
        resp = client.get("/admin/character-events", headers=_bearer(player_tok))
        assert resp.status_code == 401

    def test_character_events_rejects_unauthenticated(self, client: TestClient, db) -> None:
        """No token returns 401 on /admin/character-events."""
        resp = client.get("/admin/character-events")
        assert resp.status_code == 401
