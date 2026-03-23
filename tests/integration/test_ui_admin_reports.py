"""Integration tests for the admin report triage UI (Story 9.3).

Covers: report list, filtering, detail view, triage form submission, stats page,
status badge rendering, auth redirect, and scene snippet display.
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.admin import AdminUser, Report
from app.models.content import Book, Scene
from app.models.player import User
from app.services.auth_service import create_admin_token, hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(db: Session, username: str = "triageadmin") -> AdminUser:
    """Create and flush an AdminUser, return the instance."""
    admin = AdminUser(
        username=username,
        password_hash=hash_password("AdminPass1!"),
    )
    db.add(admin)
    db.flush()
    return admin


def _admin_cookie(admin: AdminUser) -> str:
    """Generate an admin_session JWT for the given admin."""
    return create_admin_token(admin_id=admin.id)


def _make_user(db: Session, username: str = "playerone") -> User:
    """Create and flush a player User, return the instance."""
    user = User(
        username=username,
        email=f"{username}@test.com",
        password_hash=hash_password("Pass1234!"),
        max_characters=5,
    )
    db.add(user)
    db.flush()
    return user


def _make_report(
    db: Session,
    user_id: int,
    *,
    status: str = "open",
    tags: list[str] | None = None,
    free_text: str | None = None,
    scene_id: int | None = None,
    character_id: int | None = None,
    admin_notes: str | None = None,
) -> Report:
    """Create and flush a Report, return the instance."""
    now = datetime.now(tz=UTC)
    report = Report(
        user_id=user_id,
        status=status,
        tags=json.dumps(tags or []),
        free_text=free_text,
        scene_id=scene_id,
        character_id=character_id,
        admin_notes=admin_notes,
        created_at=now,
        updated_at=now,
    )
    db.add(report)
    db.flush()
    return report


def _make_book_and_scene(db: Session, narrative: str = "You stand at the crossroads.") -> Scene:
    """Create a Book and a Scene, return the Scene instance."""
    book = Book(
        slug="flight-from-the-dark",
        number=1,
        title="Flight from the Dark",
        era="kai",
        series="lone_wolf",
        start_scene_number=1,
        max_total_picks=10,
    )
    db.add(book)
    db.flush()
    scene = Scene(
        book_id=book.id,
        number=42,
        html_id="sect42",
        narrative=narrative,
        is_death=False,
        is_victory=False,
        must_eat=False,
        loses_backpack=False,
        source="auto",
    )
    db.add(scene)
    db.flush()
    return scene


# ---------------------------------------------------------------------------
# GET /admin/ui/reports — list
# ---------------------------------------------------------------------------


class TestReportList:
    def test_returns_200_with_report_table(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db)
        user = _make_user(db)
        _make_report(db, user.id, tags=["meal_issue"])

        resp = client.get(
            "/admin/ui/reports",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"Report Queue" in resp.content
        assert b"<table" in resp.content

    def test_unauthenticated_redirects_to_admin_login(self, client: TestClient) -> None:
        resp = client.get("/admin/ui/reports", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_status_filter_open_shows_only_open(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "adminfilter1")
        user = _make_user(db, "filteruser1")
        _make_report(db, user.id, status="open", tags=["wrong_items"])
        _make_report(db, user.id, status="resolved")

        resp = client.get(
            "/admin/ui/reports?status=open",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        # resolved badge should not appear; open badge should
        assert "status-badge-open" in content
        assert "status-badge-resolved" not in content

    def test_tags_filter_shows_only_matching_reports(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "adminfilter2")
        user = _make_user(db, "filteruser2")
        _make_report(db, user.id, tags=["meal_issue"])
        _make_report(db, user.id, tags=["wrong_items"])

        resp = client.get(
            "/admin/ui/reports?tags=meal_issue",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "meal_issue" in content
        # The report without meal_issue tag should not render its tag
        assert "wrong_items" not in content

    def test_status_badges_use_correct_css_classes(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "adminbadge")
        user = _make_user(db, "badgeuser")
        _make_report(db, user.id, status="open")
        _make_report(db, user.id, status="triaging")

        resp = client.get(
            "/admin/ui/reports",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "status-badge-open" in content
        assert "status-badge-triaging" in content

    def test_links_to_detail_page(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "adminlink")
        user = _make_user(db, "linkuser")
        report = _make_report(db, user.id)

        resp = client.get(
            "/admin/ui/reports",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert f"/admin/ui/reports/{report.id}".encode() in resp.content


# ---------------------------------------------------------------------------
# GET /admin/ui/reports/{id} — detail
# ---------------------------------------------------------------------------


class TestReportDetail:
    def test_shows_report_info_and_triage_form(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "admind1")
        user = _make_user(db, "detailuser1")
        report = _make_report(
            db, user.id, tags=["meal_issue"], free_text="Lost a meal here.", status="open"
        )

        resp = client.get(
            f"/admin/ui/reports/{report.id}",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert str(report.id) in content
        assert "meal_issue" in content
        assert "Lost a meal here." in content
        assert "<form" in content
        assert 'name="status"' in content
        assert 'name="admin_notes"' in content

    def test_shows_scene_narrative_snippet_when_scene_id_set(
        self, client: TestClient, db: Session
    ) -> None:
        admin = _make_admin(db, "admind2")
        user = _make_user(db, "detailuser2")
        scene = _make_book_and_scene(db, narrative="You stand at the bridge.")
        report = _make_report(db, user.id, scene_id=scene.id)

        resp = client.get(
            f"/admin/ui/reports/{report.id}",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        assert b"You stand at the bridge." in resp.content

    def test_no_scene_snippet_when_no_scene_id(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "admind3")
        user = _make_user(db, "detailuser3")
        report = _make_report(db, user.id, scene_id=None)

        resp = client.get(
            f"/admin/ui/reports/{report.id}",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        # scene-snippet element should not appear
        assert b"scene-snippet" not in resp.content

    def test_unauthenticated_redirects(self, client: TestClient, db: Session) -> None:
        resp = client.get("/admin/ui/reports/99", follow_redirects=False)
        assert resp.status_code == 303


# ---------------------------------------------------------------------------
# POST /admin/ui/reports/{id} — triage form submission
# ---------------------------------------------------------------------------


class TestReportTriage:
    def test_updates_status_and_admin_notes(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "admint1")
        user = _make_user(db, "triageuser1")
        report = _make_report(db, user.id, status="open")

        resp = client.post(
            f"/admin/ui/reports/{report.id}",
            data={"status": "triaging", "admin_notes": "Looking into this."},
            cookies={"admin_session": _admin_cookie(admin)},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        db.refresh(report)
        assert report.status == "triaging"
        assert report.admin_notes == "Looking into this."

    def test_resolved_status_auto_sets_resolved_by(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "admint2")
        user = _make_user(db, "triageuser2")
        report = _make_report(db, user.id, status="open")

        resp = client.post(
            f"/admin/ui/reports/{report.id}",
            data={"status": "resolved", "admin_notes": "Fixed in content."},
            cookies={"admin_session": _admin_cookie(admin)},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        db.refresh(report)
        assert report.status == "resolved"
        assert report.resolved_by == admin.id

    def test_wont_fix_also_sets_resolved_by(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "admint3")
        user = _make_user(db, "triageuser3")
        report = _make_report(db, user.id, status="open")

        resp = client.post(
            f"/admin/ui/reports/{report.id}",
            data={"status": "wont_fix", "admin_notes": ""},
            cookies={"admin_session": _admin_cookie(admin)},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        db.refresh(report)
        assert report.resolved_by == admin.id

    def test_invalid_status_returns_422_with_error(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "admint4")
        user = _make_user(db, "triageuser4")
        report = _make_report(db, user.id, status="open")

        resp = client.post(
            f"/admin/ui/reports/{report.id}",
            data={"status": "bad_status", "admin_notes": ""},
            cookies={"admin_session": _admin_cookie(admin)},
            follow_redirects=False,
        )
        assert resp.status_code == 422
        assert b"Invalid status" in resp.content

    def test_redirect_goes_to_detail_page(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "admint5")
        user = _make_user(db, "triageuser5")
        report = _make_report(db, user.id, status="open")

        resp = client.post(
            f"/admin/ui/reports/{report.id}",
            data={"status": "triaging", "admin_notes": ""},
            cookies={"admin_session": _admin_cookie(admin)},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert f"/admin/ui/reports/{report.id}" in resp.headers["location"]


# ---------------------------------------------------------------------------
# GET /admin/ui/reports/stats — stats page
# ---------------------------------------------------------------------------


class TestReportStats:
    def test_shows_aggregate_stats(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "adminstats")
        user = _make_user(db, "statsuser")
        _make_report(db, user.id, status="open", tags=["meal_issue"])
        _make_report(db, user.id, status="resolved", tags=["meal_issue", "wrong_items"])
        _make_report(db, user.id, status="triaging")

        resp = client.get(
            "/admin/ui/reports/stats",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "Report Statistics" in content
        # Total count should appear
        assert "3" in content
        # Resolution rate
        assert "%" in content
        # By-tag section
        assert "meal_issue" in content

    def test_unauthenticated_redirects(self, client: TestClient) -> None:
        resp = client.get("/admin/ui/reports/stats", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_status_badges_on_stats_page(self, client: TestClient, db: Session) -> None:
        admin = _make_admin(db, "adminstatsbadge")
        user = _make_user(db, "statsuser2")
        _make_report(db, user.id, status="open")
        _make_report(db, user.id, status="resolved")

        resp = client.get(
            "/admin/ui/reports/stats",
            cookies={"admin_session": _admin_cookie(admin)},
        )
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "status-badge-open" in content
        assert "status-badge-resolved" in content
