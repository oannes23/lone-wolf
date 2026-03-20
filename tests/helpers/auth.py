"""Authentication helpers for tests.

These stubs are wired to the auth endpoints that will be implemented in later
epics. Once auth endpoints exist, ``register_and_login`` will work end-to-end
against the TestClient. Until then, callers may use ``auth_headers`` directly
with a manually constructed token.
"""

from httpx import Client


def register_and_login(
    client: Client,
    username: str = "testuser",
    password: str = "testpass123",  # noqa: S107
) -> dict[str, str]:
    """Register a user and log in, returning the token response dict.

    Expected response shape (once auth endpoints are implemented)::

        {
            "access_token": "...",
            "refresh_token": "...",
            "token_type": "bearer",
        }

    Raises ``AssertionError`` if registration or login fails.
    """
    reg_response = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    assert reg_response.status_code == 201, (
        f"Registration failed: {reg_response.status_code} {reg_response.text}"
    )

    login_response = client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert login_response.status_code == 200, (
        f"Login failed: {login_response.status_code} {login_response.text}"
    )
    return login_response.json()


def auth_headers(access_token: str) -> dict[str, str]:
    """Return an Authorization header dict for use with TestClient requests."""
    return {"Authorization": f"Bearer {access_token}"}
