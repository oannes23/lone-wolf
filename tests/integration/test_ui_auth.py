"""Integration tests for the UI auth routes (HTMX + Jinja2 layer).

Covers: login, register, logout, change-password, and protected-page redirect.
"""

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_user(client: TestClient, username: str = "uiuser", password: str = "Pass1234!") -> None:
    """Register a user via the JSON API endpoint."""
    resp = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": password},
    )
    assert resp.status_code == 201


def _login_cookie(client: TestClient, username: str = "uiuser", password: str = "Pass1234!") -> str:
    """Log in via the UI route and return the session cookie value."""
    resp = client.post(
        "/ui/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"Expected 303, got {resp.status_code}"
    cookie = resp.cookies.get("session")
    assert cookie, "Expected session cookie in login response"
    return cookie


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


class TestUILogin:
    def test_get_login_page_returns_200(self, client: TestClient) -> None:
        resp = client.get("/ui/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert b"<form" in resp.content
        assert b'action="/ui/login"' in resp.content

    def test_login_success_sets_session_cookie_and_redirects(self, client: TestClient) -> None:
        _register_user(client)
        resp = client.post(
            "/ui/login",
            data={"username": "uiuser", "password": "Pass1234!"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/characters"
        assert "session" in resp.cookies

    def test_login_cookie_is_httponly_and_samesite_lax(self, client: TestClient) -> None:
        _register_user(client, "cookieuser")
        resp = client.post(
            "/ui/login",
            data={"username": "cookieuser", "password": "Pass1234!"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        # httpx TestClient stores the Set-Cookie header; check it contains HttpOnly and SameSite
        set_cookie_header = resp.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie_header
        assert "samesite=lax" in set_cookie_header

    def test_login_wrong_password_returns_401_with_error(self, client: TestClient) -> None:
        _register_user(client, "failuser")
        resp = client.post(
            "/ui/login",
            data={"username": "failuser", "password": "WrongPass1!"},
            follow_redirects=False,
        )
        assert resp.status_code == 401
        assert b"Incorrect" in resp.content

    def test_login_unknown_user_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/ui/login",
            data={"username": "nobody", "password": "Pass1234!"},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_login_page_shows_register_link(self, client: TestClient) -> None:
        resp = client.get("/ui/login")
        assert b"/ui/register" in resp.content


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


class TestUIRegister:
    def test_get_register_page_returns_200(self, client: TestClient) -> None:
        resp = client.get("/ui/register")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert b"<form" in resp.content
        assert b'action="/ui/register"' in resp.content

    def test_register_success_redirects_to_login(self, client: TestClient) -> None:
        resp = client.post(
            "/ui/register",
            data={"username": "newuiuser", "email": "newuiuser@test.com", "password": "Pass1234!"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"

    def test_register_duplicate_username_shows_error(self, client: TestClient) -> None:
        _register_user(client, "dupeui")
        resp = client.post(
            "/ui/register",
            data={"username": "dupeui", "email": "other@test.com", "password": "Pass1234!"},
            follow_redirects=False,
        )
        assert resp.status_code == 400
        assert b"already" in resp.content.lower()

    def test_register_short_password_shows_error(self, client: TestClient) -> None:
        resp = client.post(
            "/ui/register",
            data={"username": "shortpass", "email": "short@test.com", "password": "abc"},
            follow_redirects=False,
        )
        assert resp.status_code == 422
        assert b"8" in resp.content  # mentions 8 character minimum

    def test_register_page_shows_login_link(self, client: TestClient) -> None:
        resp = client.get("/ui/register")
        assert b"/ui/login" in resp.content


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


class TestUILogout:
    def test_logout_clears_cookie_and_redirects_to_login(self, client: TestClient) -> None:
        _register_user(client, "logoutuser")
        _login_cookie(client, "logoutuser")

        resp = client.get("/ui/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"

        # Cookie should be cleared — look for empty value or max-age=0
        set_cookie = resp.headers.get("set-cookie", "")
        assert "session" in set_cookie
        # Either the cookie value is empty or max-age=0 indicates deletion
        assert 'session=""' in set_cookie or "max-age=0" in set_cookie.lower()

    def test_logout_without_session_still_redirects(self, client: TestClient) -> None:
        resp = client.get("/ui/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/ui/login"


# ---------------------------------------------------------------------------
# Protected page redirects to login
# ---------------------------------------------------------------------------


class TestUIProtectedRedirect:
    def test_change_password_page_without_cookie_redirects_to_login(
        self, client: TestClient
    ) -> None:
        resp = client.get("/ui/change-password", follow_redirects=False)
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]

    def test_change_password_page_with_valid_cookie_returns_200(
        self, client: TestClient
    ) -> None:
        _register_user(client, "protecteduser")
        cookie = _login_cookie(client, "protecteduser")

        resp = client.get(
            "/ui/change-password",
            cookies={"session": cookie},
        )
        assert resp.status_code == 200
        assert b"<form" in resp.content

    def test_invalid_token_cookie_redirects_to_login(self, client: TestClient) -> None:
        resp = client.get(
            "/ui/change-password",
            cookies={"session": "invalid.jwt.token"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/ui/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


class TestUIChangePassword:
    def test_change_password_success_shows_confirmation(self, client: TestClient) -> None:
        _register_user(client, "pwduser")
        cookie = _login_cookie(client, "pwduser")

        resp = client.post(
            "/ui/change-password",
            data={"current_password": "Pass1234!", "new_password": "NewPass5678!"},
            cookies={"session": cookie},
        )
        assert resp.status_code == 200
        assert b"Password changed" in resp.content

    def test_change_password_wrong_current_shows_error(self, client: TestClient) -> None:
        _register_user(client, "pwderr")
        cookie = _login_cookie(client, "pwderr")

        resp = client.post(
            "/ui/change-password",
            data={"current_password": "WrongPass!", "new_password": "NewPass5678!"},
            cookies={"session": cookie},
        )
        assert resp.status_code == 400
        assert b"incorrect" in resp.content.lower()

    def test_change_password_short_new_shows_error(self, client: TestClient) -> None:
        _register_user(client, "pwdshort")
        cookie = _login_cookie(client, "pwdshort")

        resp = client.post(
            "/ui/change-password",
            data={"current_password": "Pass1234!", "new_password": "abc"},
            cookies={"session": cookie},
        )
        assert resp.status_code == 422
        assert b"8" in resp.content

    def test_change_password_updates_session_cookie(self, client: TestClient) -> None:
        _register_user(client, "cookierefresh")
        cookie = _login_cookie(client, "cookierefresh")

        resp = client.post(
            "/ui/change-password",
            data={"current_password": "Pass1234!", "new_password": "NewPass5678!"},
            cookies={"session": cookie},
        )
        assert resp.status_code == 200
        # A new session cookie should be set in the response
        assert "session" in resp.cookies
