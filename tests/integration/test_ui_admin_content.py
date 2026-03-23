"""Integration tests for Story 9.2: Admin Content Management Pages.

Covers:
- GET /admin/ui/content returns content type index (200)
- GET /admin/ui/content without auth redirects to admin login
- GET /admin/ui/content/books returns list page (empty initially, 200)
- GET /admin/ui/content/invalid-type returns 404
- POST /admin/ui/content/books/new creates a book with source='manual'
- GET /admin/ui/content/books/{id} shows edit form
- POST /admin/ui/content/books/{id} updates the book
- POST /admin/ui/content/books/{id}/delete deletes the book
- GET /admin/ui/content/scenes/{id} uses the scene-specific template
- Source badge renders correctly for auto and manual content
- Pagination works (create >25 items, verify page links)
- Wizard templates are read-only (no Save/Delete buttons in response body)
"""

import pytest
from fastapi.testclient import TestClient

from app.models.admin import AdminUser
from app.models.content import Book, Scene
from app.services.auth_service import hash_password
from tests.factories import make_book, make_scene


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(db, username: str = "contentadmin92", password: str = "AdminPass1!") -> AdminUser:
    """Insert an admin user into the test database."""
    admin = AdminUser(username=username, password_hash=hash_password(password))
    db.add(admin)
    db.flush()
    return admin


def _admin_cookie(client: TestClient, db, username: str = "contentadmin92") -> str:
    """Create an admin and return a valid admin_session cookie value."""
    _make_admin(db, username=username)
    resp = client.post(
        "/admin/ui/login",
        data={"username": username, "password": "AdminPass1!"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"Expected 303, got {resp.status_code}: {resp.text[:200]}"
    cookie = resp.cookies.get("admin_session")
    assert cookie, "Expected admin_session cookie in login response"
    return cookie


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------


class TestAdminContentAuthGuard:
    def test_content_index_without_auth_redirects_to_admin_login(
        self, client: TestClient
    ) -> None:
        resp = client.get("/admin/ui/content", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_content_list_without_auth_redirects_to_admin_login(
        self, client: TestClient
    ) -> None:
        resp = client.get("/admin/ui/content/books", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Content index
# ---------------------------------------------------------------------------


class TestAdminContentIndex:
    def test_content_index_returns_200_with_resource_links(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db)
        resp = client.get("/admin/ui/content", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert b"Content Management" in resp.content
        assert b"Books" in resp.content
        assert b"Scenes" in resp.content
        assert b"Choices" in resp.content
        assert b"Wizard Templates" in resp.content

    def test_content_index_shows_new_links_for_non_readonly(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="idx_admin")
        resp = client.get("/admin/ui/content", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        # Books should have a "New" link
        assert b"/admin/ui/content/books/new" in resp.content

    def test_content_index_shows_readonly_label_for_wizard_templates(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="idx_admin2")
        resp = client.get("/admin/ui/content", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert b"read-only" in resp.content


# ---------------------------------------------------------------------------
# Content list
# ---------------------------------------------------------------------------


class TestAdminContentList:
    def test_books_list_returns_200_when_empty(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="list_admin1")
        resp = client.get("/admin/ui/content/books", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert b"Books" in resp.content

    def test_books_list_shows_existing_books(
        self, client: TestClient, db
    ) -> None:
        make_book(db, title="The Caverns of Kalte")
        cookie = _admin_cookie(client, db, username="list_admin2")
        resp = client.get("/admin/ui/content/books", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert b"Caverns of Kalte" in resp.content

    def test_invalid_resource_type_returns_404(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="list_admin3")
        resp = client.get(
            "/admin/ui/content/invalid-type", cookies={"admin_session": cookie}
        )
        assert resp.status_code == 404

    def test_list_has_new_button(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="list_admin4")
        resp = client.get("/admin/ui/content/books", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert b"/admin/ui/content/books/new" in resp.content

    def test_list_shows_back_link(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="list_admin5")
        resp = client.get("/admin/ui/content/books", cookies={"admin_session": cookie})
        assert resp.status_code == 200
        assert b"/admin/ui/content" in resp.content


# ---------------------------------------------------------------------------
# Create (POST /admin/ui/content/books/new)
# ---------------------------------------------------------------------------


class TestAdminContentCreate:
    def test_get_new_form_returns_200(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="create_admin1")
        resp = client.get(
            "/admin/ui/content/books/new", cookies={"admin_session": cookie}
        )
        assert resp.status_code == 200
        assert b"<form" in resp.content

    def test_create_book_redirects_to_detail(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="create_admin2")
        resp = client.post(
            "/admin/ui/content/books/new",
            data={
                "slug": "flight-from-the-dark",
                "number": "1",
                "title": "Flight from the Dark",
                "era": "kai",
                "series": "lone_wolf",
                "start_scene_number": "1",
                "max_total_picks": "5",
            },
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/ui/content/books/" in resp.headers["location"]

    def test_create_book_sets_correct_fields(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="create_admin3")
        resp = client.post(
            "/admin/ui/content/books/new",
            data={
                "slug": "fire-on-the-water-ui",
                "number": "2",
                "title": "Fire on the Water",
                "era": "kai",
                "series": "lone_wolf",
                "start_scene_number": "1",
                "max_total_picks": "5",
            },
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        book = db.query(Book).filter(Book.slug == "fire-on-the-water-ui").first()
        assert book is not None
        assert book.title == "Fire on the Water"
        assert book.era == "kai"

    def test_create_wizard_template_returns_405(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="create_admin4")
        resp = client.post(
            "/admin/ui/content/wizard-templates/new",
            data={"name": "test_wizard", "description": "test"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 405

    def test_get_new_wizard_template_form_returns_405(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="create_admin5")
        resp = client.get(
            "/admin/ui/content/wizard-templates/new",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Detail / edit
# ---------------------------------------------------------------------------


class TestAdminContentDetail:
    def test_get_book_detail_returns_200_with_form(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db, title="The Chasm of Doom")
        cookie = _admin_cookie(client, db, username="detail_admin1")
        resp = client.get(
            f"/admin/ui/content/books/{book.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"<form" in resp.content
        assert b"Chasm of Doom" in resp.content

    def test_get_nonexistent_resource_returns_404(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="detail_admin2")
        resp = client.get(
            "/admin/ui/content/books/99999",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 404

    def test_detail_shows_delete_button(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        cookie = _admin_cookie(client, db, username="detail_admin3")
        resp = client.get(
            f"/admin/ui/content/books/{book.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"Delete" in resp.content
        assert f"/admin/ui/content/books/{book.id}/delete".encode() in resp.content

    def test_detail_shows_save_button(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        cookie = _admin_cookie(client, db, username="detail_admin4")
        resp = client.get(
            f"/admin/ui/content/books/{book.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"Save" in resp.content


# ---------------------------------------------------------------------------
# Update (POST /admin/ui/content/books/{id})
# ---------------------------------------------------------------------------


class TestAdminContentUpdate:
    def test_update_book_redirects_to_detail(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db, title="Shadow on the Sand")
        cookie = _admin_cookie(client, db, username="update_admin1")
        resp = client.post(
            f"/admin/ui/content/books/{book.id}",
            data={
                "slug": book.slug,
                "number": str(book.number),
                "title": "Shadow on the Sand (Updated)",
                "era": "kai",
                "series": "lone_wolf",
                "start_scene_number": "1",
                "max_total_picks": "5",
            },
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert f"/admin/ui/content/books/{book.id}" in resp.headers["location"]

    def test_update_book_persists_changes(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db, title="Original Title")
        cookie = _admin_cookie(client, db, username="update_admin2")
        client.post(
            f"/admin/ui/content/books/{book.id}",
            data={
                "slug": book.slug,
                "number": str(book.number),
                "title": "Updated Title",
                "era": "kai",
                "series": "lone_wolf",
                "start_scene_number": "1",
                "max_total_picks": "5",
            },
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        db.expire(book)
        assert book.title == "Updated Title"

    def test_update_wizard_template_returns_405(
        self, client: TestClient, db
    ) -> None:
        from app.models.wizard import WizardTemplate
        wt = WizardTemplate(name="test_wt_92_update", description="test")
        db.add(wt)
        db.flush()
        cookie = _admin_cookie(client, db, username="update_admin3")
        resp = client.post(
            f"/admin/ui/content/wizard-templates/{wt.id}",
            data={"name": "hacked", "description": "hacked"},
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestAdminContentDelete:
    def test_delete_book_redirects_to_list(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        cookie = _admin_cookie(client, db, username="delete_admin1")
        resp = client.post(
            f"/admin/ui/content/books/{book.id}/delete",
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/ui/content/books"

    def test_delete_book_removes_it_from_db(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        book_id = book.id
        cookie = _admin_cookie(client, db, username="delete_admin2")
        client.post(
            f"/admin/ui/content/books/{book_id}/delete",
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        assert db.query(Book).filter(Book.id == book_id).first() is None

    def test_delete_nonexistent_returns_404(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="delete_admin3")
        resp = client.post(
            "/admin/ui/content/books/99999/delete",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 404

    def test_delete_wizard_template_returns_405(
        self, client: TestClient, db
    ) -> None:
        from app.models.wizard import WizardTemplate
        wt = WizardTemplate(name="test_wt_92_del", description="test")
        db.add(wt)
        db.flush()
        cookie = _admin_cookie(client, db, username="delete_admin4")
        resp = client.post(
            f"/admin/ui/content/wizard-templates/{wt.id}/delete",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Scene-specific template
# ---------------------------------------------------------------------------


class TestAdminSceneDetail:
    def test_scene_detail_uses_scene_specific_template(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, narrative="A dark forest surrounds you.")
        cookie = _admin_cookie(client, db, username="scene_admin1")
        resp = client.get(
            f"/admin/ui/content/scenes/{scene.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        # Scene-specific template has the narrative textarea
        assert b"narrative" in resp.content
        assert b"A dark forest surrounds you." in resp.content

    def test_scene_detail_shows_flags(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, is_death=True, is_victory=False)
        cookie = _admin_cookie(client, db, username="scene_admin2")
        resp = client.get(
            f"/admin/ui/content/scenes/{scene.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"is_death" in resp.content
        assert b"is_victory" in resp.content

    def test_scene_detail_shows_linked_content_sections(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book)
        cookie = _admin_cookie(client, db, username="scene_admin3")
        resp = client.get(
            f"/admin/ui/content/scenes/{scene.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        # Expandable sections for linked content
        assert b"Choices" in resp.content
        assert b"Combat Encounters" in resp.content
        assert b"Scene Items" in resp.content

    def test_scene_detail_shows_source_badge(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, source="auto")
        cookie = _admin_cookie(client, db, username="scene_admin4")
        resp = client.get(
            f"/admin/ui/content/scenes/{scene.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"source-badge-auto" in resp.content

    def test_scene_detail_manual_source_badge(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        scene = make_scene(db, book, source="manual")
        cookie = _admin_cookie(client, db, username="scene_admin5")
        resp = client.get(
            f"/admin/ui/content/scenes/{scene.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"source-badge-manual" in resp.content


# ---------------------------------------------------------------------------
# Source badge
# ---------------------------------------------------------------------------


class TestSourceBadge:
    def test_source_badge_auto_renders_in_list(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        make_scene(db, book, source="auto")
        cookie = _admin_cookie(client, db, username="badge_admin1")
        resp = client.get(
            "/admin/ui/content/scenes", cookies={"admin_session": cookie}
        )
        assert resp.status_code == 200
        assert b"source-badge-auto" in resp.content

    def test_source_badge_manual_renders_in_list(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        make_scene(db, book, source="manual")
        cookie = _admin_cookie(client, db, username="badge_admin2")
        resp = client.get(
            "/admin/ui/content/scenes", cookies={"admin_session": cookie}
        )
        assert resp.status_code == 200
        assert b"source-badge-manual" in resp.content


# ---------------------------------------------------------------------------
# Wizard templates — read-only
# ---------------------------------------------------------------------------


class TestWizardTemplatesReadOnly:
    def test_wizard_templates_list_returns_200(
        self, client: TestClient, db
    ) -> None:
        cookie = _admin_cookie(client, db, username="wt_admin1")
        resp = client.get(
            "/admin/ui/content/wizard-templates",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"Wizard Templates" in resp.content

    def test_wizard_template_detail_has_no_save_button(
        self, client: TestClient, db
    ) -> None:
        from app.models.wizard import WizardTemplate
        wt = WizardTemplate(name="character_creation_92", description="Creation wizard")
        db.add(wt)
        db.flush()
        cookie = _admin_cookie(client, db, username="wt_admin2")
        resp = client.get(
            f"/admin/ui/content/wizard-templates/{wt.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        # Read-only view: should NOT have Save or Delete buttons
        assert b'type="submit"' not in resp.content
        # Should show the name
        assert b"character_creation_92" in resp.content

    def test_wizard_template_detail_has_no_delete_button(
        self, client: TestClient, db
    ) -> None:
        from app.models.wizard import WizardTemplate
        wt = WizardTemplate(name="book_advance_92", description="Advance wizard")
        db.add(wt)
        db.flush()
        cookie = _admin_cookie(client, db, username="wt_admin3")
        resp = client.get(
            f"/admin/ui/content/wizard-templates/{wt.id}",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"Delete" not in resp.content


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestAdminContentPagination:
    def test_pagination_links_appear_when_more_than_25_items(
        self, client: TestClient, db
    ) -> None:
        # Create 26 books to trigger pagination
        for i in range(26):
            db.add(Book(
                slug=f"pagination-book-{i:03d}",
                number=9000 + i,
                title=f"Pagination Test Book {i}",
                era="kai",
                series="lone_wolf",
                start_scene_number=1,
                max_total_picks=5,
            ))
        db.flush()

        cookie = _admin_cookie(client, db, username="page_admin1")
        resp = client.get(
            "/admin/ui/content/books?page=1", cookies={"admin_session": cookie}
        )
        assert resp.status_code == 200
        # Should show pagination controls
        assert b"Next" in resp.content

    def test_pagination_page_2_accessible(
        self, client: TestClient, db
    ) -> None:
        for i in range(26):
            db.add(Book(
                slug=f"pg2-book-{i:03d}",
                number=8000 + i,
                title=f"Page2 Test Book {i}",
                era="kai",
                series="lone_wolf",
                start_scene_number=1,
                max_total_picks=5,
            ))
        db.flush()

        cookie = _admin_cookie(client, db, username="page_admin2")
        resp = client.get(
            "/admin/ui/content/books?page=2", cookies={"admin_session": cookie}
        )
        assert resp.status_code == 200
        assert b"Previous" in resp.content

    def test_pagination_shows_count_summary(
        self, client: TestClient, db
    ) -> None:
        # Just 2 books, no pagination needed but count summary should still appear
        make_book(db, title="Count Test A")
        make_book(db, title="Count Test B")
        cookie = _admin_cookie(client, db, username="page_admin3")
        resp = client.get(
            "/admin/ui/content/books", cookies={"admin_session": cookie}
        )
        assert resp.status_code == 200
        # Should show "Showing X-Y of Z"
        assert b"Showing" in resp.content or b"of" in resp.content


# ---------------------------------------------------------------------------
# Scene create — source set to manual
# ---------------------------------------------------------------------------


class TestSceneCreateSourceManual:
    def test_create_scene_sets_source_manual(
        self, client: TestClient, db
    ) -> None:
        book = make_book(db)
        cookie = _admin_cookie(client, db, username="src_admin1")
        resp = client.post(
            "/admin/ui/content/scenes/new",
            data={
                "book_id": str(book.id),
                "number": "999",
                "html_id": "sect999",
                "narrative": "You stand at a crossroads.",
                "is_death": "",
                "is_victory": "",
                "must_eat": "",
                "loses_backpack": "",
            },
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        scene = db.query(Scene).filter(
            Scene.book_id == book.id, Scene.number == 999
        ).first()
        assert scene is not None
        assert scene.source == "manual"
