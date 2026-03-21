"""Integration tests for POST /characters/roll — stat rolling and roll token."""

from fastapi.testclient import TestClient

from app.services.auth_service import decode_token
from tests.factories import make_book


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client: TestClient, username: str = "rolluser") -> str:
    """Register a user, log in, and return the access token."""
    client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Pass1234!",
        },
    )
    resp = client.post("/auth/login", data={"username": username, "password": "Pass1234!"})
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRollStats:
    def test_roll_returns_valid_cs_and_end_ranges(self, client: TestClient, db) -> None:
        """CS must be 10–19 and END must be 20–29 for Kai era Book 1."""
        book = make_book(db, number=1, era="kai")
        token = _register_and_login(client, "csrange")

        resp = client.post(
            "/characters/roll",
            json={"book_id": book.id},
            headers=_auth_headers(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert 10 <= data["combat_skill_base"] <= 19
        assert 20 <= data["endurance_base"] <= 29
        assert data["era"] == "kai"

    def test_roll_token_decodes_with_expected_claims(self, client: TestClient, db) -> None:
        """The roll_token must contain sub, cs, end, book_id, and type='roll'."""
        book = make_book(db, number=1, era="kai")
        token = _register_and_login(client, "tokencheck")

        resp = client.post(
            "/characters/roll",
            json={"book_id": book.id},
            headers=_auth_headers(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        payload = decode_token(data["roll_token"], expected_type="roll")

        assert payload["type"] == "roll"
        assert "sub" in payload
        assert int(payload["sub"]) > 0  # sub matches a real user id
        assert payload["cs"] == data["combat_skill_base"]
        assert payload["end"] == data["endurance_base"]
        assert payload["book_id"] == book.id

    def test_invalid_book_id_returns_404(self, client: TestClient, db) -> None:
        """A book_id that does not exist in the database must return 404."""
        token = _register_and_login(client, "nobook")

        resp = client.post(
            "/characters/roll",
            json={"book_id": 99999},
            headers=_auth_headers(token),
        )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_non_book1_returns_400(self, client: TestClient, db) -> None:
        """Attempting to roll for Book 2 must return 400 (MVP restriction)."""
        book2 = make_book(db, number=2, era="kai")
        token = _register_and_login(client, "book2user")

        resp = client.post(
            "/characters/roll",
            json={"book_id": book2.id},
            headers=_auth_headers(token),
        )

        assert resp.status_code == 400
        assert "book 1" in resp.json()["detail"].lower()

    def test_unauthenticated_request_returns_401(self, client: TestClient, db) -> None:
        """A request without a Bearer token must return 401."""
        book = make_book(db, number=1, era="kai")

        resp = client.post(
            "/characters/roll",
            json={"book_id": book.id},
        )

        assert resp.status_code == 401

    def test_formula_shows_correct_breakdown(self, client: TestClient, db) -> None:
        """formula.cs and formula.end must match the rolled stat values."""
        book = make_book(db, number=1, era="kai")
        token = _register_and_login(client, "formulacheck")

        resp = client.post(
            "/characters/roll",
            json={"book_id": book.id},
            headers=_auth_headers(token),
        )

        assert resp.status_code == 200
        data = resp.json()
        cs = data["combat_skill_base"]
        end = data["endurance_base"]
        cs_bonus = cs - 10
        end_bonus = end - 20

        assert data["formula"]["cs"] == f"10 + {cs_bonus}"
        assert data["formula"]["end"] == f"20 + {end_bonus}"
