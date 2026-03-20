"""Integration tests for the authentication API endpoints.

Covers: register, login, refresh, change-password, and /me.
"""

import time
from datetime import timedelta

from fastapi.testclient import TestClient

from app.services.auth_service import create_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register(client: TestClient, username: str = "herouser", password: str = "Pass1234!") -> dict:
    """Register a user and return the parsed JSON response."""
    resp = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@test.com", "password": password},
    )
    return resp


def _login(client: TestClient, username: str = "herouser", password: str = "Pass1234!") -> dict:
    """Log in and return the response object."""
    return client.post("/auth/login", data={"username": username, "password": password})


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


# ---------------------------------------------------------------------------
# Happy path: full flow
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_returns_201_with_user_info(self, client: TestClient) -> None:
        resp = _register(client, "newuser")
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "newuser"
        assert data["email"] == "newuser@test.com"
        assert "id" in data
        assert "password" not in data
        assert "password_hash" not in data

    def test_register_duplicate_username_returns_400(self, client: TestClient) -> None:
        _register(client, "dupeuser")
        resp = _register(client, "dupeuser")
        assert resp.status_code == 400
        assert "already" in resp.json()["detail"].lower()

    def test_register_duplicate_email_returns_400(self, client: TestClient) -> None:
        # Register first user with email collision@test.com
        client.post(
            "/auth/register",
            json={"username": "user_a", "email": "collision@test.com", "password": "Pass1234!"},
        )
        # Register second user with the same email but different username
        resp = client.post(
            "/auth/register",
            json={"username": "user_b", "email": "collision@test.com", "password": "Pass1234!"},
        )
        assert resp.status_code == 400

    def test_register_password_too_short_returns_422(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/register",
            json={"username": "shortpass", "email": "shortpass@test.com", "password": "abc123"},
        )
        assert resp.status_code == 422

    def test_register_password_too_long_returns_422(self, client: TestClient) -> None:
        long_password = "A" * 129
        resp = client.post(
            "/auth/register",
            json={
                "username": "longpass",
                "email": "longpass@test.com",
                "password": long_password,
            },
        )
        assert resp.status_code == 422

    def test_register_password_exactly_8_chars_succeeds(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/register",
            json={"username": "minpass", "email": "minpass@test.com", "password": "12345678"},
        )
        assert resp.status_code == 201

    def test_register_password_exactly_128_chars_succeeds(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/register",
            json={
                "username": "maxpass",
                "email": "maxpass@test.com",
                "password": "A" * 128,
            },
        )
        assert resp.status_code == 201


class TestLogin:
    def test_login_returns_tokens(self, client: TestClient) -> None:
        _register(client, "loginuser")
        resp = _login(client, "loginuser")
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password_returns_400(self, client: TestClient) -> None:
        _register(client, "wrongpass")
        resp = _login(client, "wrongpass", password="WrongPassword1!")
        assert resp.status_code == 400

    def test_login_unknown_user_returns_400(self, client: TestClient) -> None:
        resp = _login(client, "ghostuser")
        assert resp.status_code == 400


class TestRefresh:
    def test_refresh_returns_new_access_token(self, client: TestClient) -> None:
        _register(client, "refreshuser")
        tokens = _login(client, "refreshuser").json()

        resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        # Verify the new token is usable for /me
        me_resp = client.get("/auth/me", headers=_auth_headers(data["access_token"]))
        assert me_resp.status_code == 200

    def test_refresh_with_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.post("/auth/refresh", json={"refresh_token": "not.a.valid.token"})
        assert resp.status_code == 401

    def test_refresh_with_expired_token_returns_401(self, client: TestClient) -> None:
        expired_token = create_token(
            data={"sub": "999", "username": "ghost"},
            token_type="refresh",
            expires_delta=timedelta(seconds=-1),
        )
        resp = client.post("/auth/refresh", json={"refresh_token": expired_token})
        assert resp.status_code == 401

    def test_refresh_with_access_token_as_refresh_returns_401(self, client: TestClient) -> None:
        """Using an access token in the refresh slot should be rejected."""
        _register(client, "wrongtypeuser")
        tokens = _login(client, "wrongtypeuser").json()
        resp = client.post(
            "/auth/refresh", json={"refresh_token": tokens["access_token"]}
        )
        assert resp.status_code == 401


class TestMe:
    def test_me_returns_user_info(self, client: TestClient) -> None:
        _register(client, "meuser")
        tokens = _login(client, "meuser").json()

        resp = client.get("/auth/me", headers=_auth_headers(tokens["access_token"]))
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "meuser"
        assert data["email"] == "meuser@test.com"
        assert "id" in data

    def test_me_without_token_returns_401(self, client: TestClient) -> None:
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_me_with_invalid_token_returns_401(self, client: TestClient) -> None:
        resp = client.get("/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
        assert resp.status_code == 401


class TestFullFlow:
    def test_register_login_refresh_me(self, client: TestClient) -> None:
        """End-to-end happy path: register -> login -> refresh -> /me."""
        reg = _register(client, "flowuser")
        assert reg.status_code == 201

        tokens = _login(client, "flowuser").json()
        assert tokens["access_token"]

        refreshed = client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        ).json()
        assert refreshed["access_token"]

        me = client.get("/auth/me", headers=_auth_headers(refreshed["access_token"])).json()
        assert me["username"] == "flowuser"


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------


class TestChangePassword:
    def test_change_password_succeeds(self, client: TestClient) -> None:
        _register(client, "changeme")
        tokens = _login(client, "changeme").json()

        resp = client.post(
            "/auth/change-password",
            json={"current_password": "Pass1234!", "new_password": "NewPass5678!"},
            headers=_auth_headers(tokens["access_token"]),
        )
        assert resp.status_code == 200
        assert "message" in resp.json()

    def test_change_password_wrong_current_returns_400(self, client: TestClient) -> None:
        _register(client, "wrongcurrent")
        tokens = _login(client, "wrongcurrent").json()

        resp = client.post(
            "/auth/change-password",
            json={"current_password": "NotTheRightPassword!", "new_password": "NewPass5678!"},
            headers=_auth_headers(tokens["access_token"]),
        )
        assert resp.status_code == 400

    def test_old_token_rejected_after_password_change(self, client: TestClient) -> None:
        """After a password change, old access tokens must be rejected."""
        _register(client, "staleme")
        old_tokens = _login(client, "staleme").json()
        old_access = old_tokens["access_token"]

        # Change the password
        client.post(
            "/auth/change-password",
            json={"current_password": "Pass1234!", "new_password": "NewPass5678!"},
            headers=_auth_headers(old_access),
        )

        # The old access token should now be rejected on /me
        resp = client.get("/auth/me", headers=_auth_headers(old_access))
        assert resp.status_code == 401

    def test_new_token_accepted_after_password_change(self, client: TestClient) -> None:
        """After a password change, tokens obtained with the new password work.

        A 1-second sleep is required because JWT iat has second granularity and
        password_changed_at is set to now+1s. The new login must occur at least
        1 second after the change for its token's iat to exceed password_changed_at.
        """
        _register(client, "freshtoken")
        old_tokens = _login(client, "freshtoken").json()

        client.post(
            "/auth/change-password",
            json={"current_password": "Pass1234!", "new_password": "NewPass5678!"},
            headers=_auth_headers(old_tokens["access_token"]),
        )

        # Wait for password_changed_at (now+1s) to be in the past
        time.sleep(1.1)

        new_tokens = _login(client, "freshtoken", password="NewPass5678!").json()
        resp = client.get("/auth/me", headers=_auth_headers(new_tokens["access_token"]))
        assert resp.status_code == 200

    def test_change_password_new_too_short_returns_422(self, client: TestClient) -> None:
        _register(client, "shortchange")
        tokens = _login(client, "shortchange").json()

        resp = client.post(
            "/auth/change-password",
            json={"current_password": "Pass1234!", "new_password": "short"},
            headers=_auth_headers(tokens["access_token"]),
        )
        assert resp.status_code == 422

    def test_change_password_without_auth_returns_401(self, client: TestClient) -> None:
        resp = client.post(
            "/auth/change-password",
            json={"current_password": "Pass1234!", "new_password": "NewPass5678!"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_login_rate_limit_429_on_sixth_request(self, client: TestClient) -> None:
        """POST /auth/login is limited to 5/minute. The 6th request should be 429."""
        _register(client, "ratelimituser")
        # Send 5 requests — all within rate limit
        for _ in range(5):
            client.post(
                "/auth/login",
                data={"username": "ratelimituser", "password": "Pass1234!"},
            )
        # 6th request should hit the rate limit
        resp = client.post(
            "/auth/login",
            data={"username": "ratelimituser", "password": "Pass1234!"},
        )
        assert resp.status_code == 429

    def test_register_rate_limit_429_on_fourth_request(self, client: TestClient) -> None:
        """POST /auth/register is limited to 3/minute. The 4th request should be 429."""
        for i in range(3):
            client.post(
                "/auth/register",
                json={
                    "username": f"ratelimitreg{i}",
                    "email": f"ratelimitreg{i}@test.com",
                    "password": "Pass1234!",
                },
            )
        # 4th request should hit the rate limit
        resp = client.post(
            "/auth/register",
            json={
                "username": "ratelimitreg_extra",
                "email": "ratelimitreg_extra@test.com",
                "password": "Pass1234!",
            },
        )
        assert resp.status_code == 429
