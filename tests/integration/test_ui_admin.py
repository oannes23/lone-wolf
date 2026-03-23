"""Integration tests for Story 9.1: Admin UI Scaffolding & Auth.

Covers:
- GET /admin/ui/login returns 200 with form
- POST /admin/ui/login with valid admin credentials sets admin_session cookie
- POST /admin/ui/login with wrong password re-renders with error
- GET /admin/ui/dashboard without auth redirects to admin login
- GET /admin/ui/dashboard with valid admin cookie returns 200
- Player session cookie does NOT grant admin access
- GET /admin/ui/logout clears admin_session cookie
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.admin import AdminUser
from app.services.auth_service import create_access_token, hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_admin(
    db: Session,
    username: str = "adminui",
    password: str = "AdminPass1!",
) -> AdminUser:
    """Insert an AdminUser into the test database."""
    admin = AdminUser(username=username, password_hash=hash_password(password))
    db.add(admin)
    db.flush()
    return admin


def _admin_login_cookie(
    client: TestClient,
    db: Session,
    username: str = "adminui",
    password: str = "AdminPass1!",
) -> str:
    """Create an admin and log in via the UI route. Returns admin_session cookie."""
    _make_admin(db, username=username, password=password)
    resp = client.post(
        "/admin/ui/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"Expected 303, got {resp.status_code}"
    cookie = resp.cookies.get("admin_session")
    assert cookie, "Expected admin_session cookie in login response"
    return cookie


def _player_session_cookie(client: TestClient) -> str:
    """Register a player and return a player session cookie."""
    client.post(
        "/auth/register",
        json={"username": "uiadminplayer", "email": "uiadminplayer@test.com", "password": "Pass1234!"},
    )
    resp = client.post(
        "/ui/login",
        data={"username": "uiadminplayer", "password": "Pass1234!"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    return resp.cookies.get("session")


# ---------------------------------------------------------------------------
# GET /admin/ui/login
# ---------------------------------------------------------------------------


class TestAdminLogin:
    def test_get_admin_login_page_returns_200(self, client: TestClient) -> None:
        resp = client.get("/admin/ui/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert b"<form" in resp.content
        assert b'action="/admin/ui/login"' in resp.content

    def test_admin_login_page_has_username_and_password_fields(
        self, client: TestClient
    ) -> None:
        resp = client.get("/admin/ui/login")
        assert resp.status_code == 200
        assert b'name="username"' in resp.content
        assert b'name="password"' in resp.content

    def test_admin_login_success_sets_cookie_and_redirects(
        self, client: TestClient, db: Session
    ) -> None:
        _make_admin(db)
        resp = client.post(
            "/admin/ui/login",
            data={"username": "adminui", "password": "AdminPass1!"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/ui/dashboard"
        assert "admin_session" in resp.cookies

    def test_admin_login_cookie_is_httponly_and_samesite_lax(
        self, client: TestClient, db: Session
    ) -> None:
        _make_admin(db, username="cookieadmin")
        resp = client.post(
            "/admin/ui/login",
            data={"username": "cookieadmin", "password": "AdminPass1!"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        set_cookie_header = resp.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie_header
        assert "samesite=lax" in set_cookie_header

    def test_admin_login_wrong_password_returns_401_with_error(
        self, client: TestClient, db: Session
    ) -> None:
        _make_admin(db, username="badpassadmin")
        resp = client.post(
            "/admin/ui/login",
            data={"username": "badpassadmin", "password": "WrongPass!"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert b"Incorrect" in resp.content

    def test_admin_login_unknown_user_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/admin/ui/login",
            data={"username": "nobody_admin", "password": "AdminPass1!"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert b"Incorrect" in resp.content

    def test_admin_login_error_re_renders_form(
        self, client: TestClient, db: Session
    ) -> None:
        _make_admin(db, username="formrerender")
        resp = client.post(
            "/admin/ui/login",
            data={"username": "formrerender", "password": "WrongPass!"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert b"<form" in resp.content
        assert b'action="/admin/ui/login"' in resp.content


# ---------------------------------------------------------------------------
# GET /admin/ui/dashboard
# ---------------------------------------------------------------------------


class TestAdminDashboard:
    def test_dashboard_without_auth_redirects_to_admin_login(
        self, client: TestClient
    ) -> None:
        resp = client.get("/admin/ui/dashboard", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_dashboard_with_invalid_token_redirects_to_admin_login(
        self, client: TestClient
    ) -> None:
        resp = client.get(
            "/admin/ui/dashboard",
            cookies={"admin_session": "invalid.jwt.token"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_dashboard_with_valid_admin_cookie_returns_200(
        self, client: TestClient, db: Session
    ) -> None:
        cookie = _admin_login_cookie(client, db, username="dashboardadmin")
        resp = client.get(
            "/admin/ui/dashboard",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert b"Dashboard" in resp.content

    def test_dashboard_shows_summary_cards(
        self, client: TestClient, db: Session
    ) -> None:
        cookie = _admin_login_cookie(client, db, username="cardadmin")
        resp = client.get(
            "/admin/ui/dashboard",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        # Each card should be present
        assert b"Open Reports" in resp.content
        assert b"Total Users" in resp.content
        assert b"Total Characters" in resp.content
        assert b"Books with Content" in resp.content

    def test_dashboard_shows_admin_nav_links(
        self, client: TestClient, db: Session
    ) -> None:
        cookie = _admin_login_cookie(client, db, username="navadmin")
        resp = client.get(
            "/admin/ui/dashboard",
            cookies={"admin_session": cookie},
        )
        assert resp.status_code == 200
        assert b"/admin/ui/dashboard" in resp.content
        assert b"/admin/ui/reports" in resp.content
        assert b"/admin/ui/users" in resp.content
        assert b"/admin/ui/logout" in resp.content

    def test_player_session_cookie_does_not_grant_admin_access(
        self, client: TestClient, db: Session
    ) -> None:
        player_cookie = _player_session_cookie(client)
        resp = client.get(
            "/admin/ui/dashboard",
            cookies={"admin_session": player_cookie},  # player token in admin cookie slot
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]

    def test_player_session_cookie_in_wrong_key_does_not_grant_access(
        self, client: TestClient, db: Session
    ) -> None:
        """Sending a player 'session' cookie (not 'admin_session') grants no admin access."""
        player_cookie = _player_session_cookie(client)
        resp = client.get(
            "/admin/ui/dashboard",
            cookies={"session": player_cookie},  # wrong cookie name
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# GET /admin/ui/logout
# ---------------------------------------------------------------------------


class TestAdminLogout:
    def test_logout_clears_admin_session_cookie_and_redirects(
        self, client: TestClient, db: Session
    ) -> None:
        cookie = _admin_login_cookie(client, db, username="logoutadmin")

        resp = client.get(
            "/admin/ui/logout",
            cookies={"admin_session": cookie},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/ui/login"

        # Cookie should be cleared — look for empty value or max-age=0
        set_cookie = resp.headers.get("set-cookie", "")
        assert "admin_session" in set_cookie
        assert 'admin_session=""' in set_cookie or "max-age=0" in set_cookie.lower()

    def test_logout_without_session_still_redirects(self, client: TestClient) -> None:
        resp = client.get("/admin/ui/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/ui/login"

    def test_logout_then_dashboard_redirects_to_login(
        self, client: TestClient, db: Session
    ) -> None:
        """After logout, the admin_session cookie is gone, so dashboard redirects."""
        _admin_login_cookie(client, db, username="logoutflow")

        # Logout clears the cookie
        client.get("/admin/ui/logout", follow_redirects=False)

        # Now dashboard should redirect (client no longer has admin_session cookie)
        resp = client.get("/admin/ui/dashboard", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/ui/login" in resp.headers["location"]
