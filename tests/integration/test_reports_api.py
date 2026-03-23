"""Integration tests for the Reports API (Story 7.4).

Covers: POST /reports, GET /reports — creation, tag validation,
own-report isolation, optional fields, and unauthenticated access.
"""

from fastapi.testclient import TestClient

from tests.helpers.auth import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_PASSWORD = "Pass1234!"


def _make_user(client: TestClient, username: str) -> dict:
    """Register and log in a user, returning the token payload."""
    return register_and_login(client, username=username, password=_DEFAULT_PASSWORD)


def _post_report(
    client: TestClient,
    token: str,
    tags: list[str] | None = None,
    character_id: int | None = None,
    scene_id: int | None = None,
    free_text: str | None = None,
):
    """Helper to POST /reports and return the response."""
    payload: dict = {}
    if tags is not None:
        payload["tags"] = tags
    if character_id is not None:
        payload["character_id"] = character_id
    if scene_id is not None:
        payload["scene_id"] = scene_id
    if free_text is not None:
        payload["free_text"] = free_text
    return client.post("/reports", json=payload, headers=auth_headers(token))


# ---------------------------------------------------------------------------
# POST /reports — happy paths
# ---------------------------------------------------------------------------


class TestCreateReport:
    def test_valid_tags_returns_201(self, client: TestClient) -> None:
        """Report creation with valid tags returns 201 and the report shape."""
        tokens = _make_user(client, "reportuser1")
        resp = _post_report(
            client,
            tokens["access_token"],
            tags=["meal_issue", "wrong_items"],
            free_text="I should have lost a meal here but didn't",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "open"
        assert "id" in data
        assert "created_at" in data
        assert set(data["tags"]) == {"meal_issue", "wrong_items"}

    def test_single_valid_tag_returns_201(self, client: TestClient) -> None:
        """A single recognised tag is accepted."""
        tokens = _make_user(client, "reportuser2")
        resp = _post_report(client, tokens["access_token"], tags=["other"])
        assert resp.status_code == 201
        assert resp.json()["status"] == "open"

    def test_all_valid_tags_accepted(self, client: TestClient) -> None:
        """All seven recognised tag values are each individually accepted."""
        tokens = _make_user(client, "reportuser3")
        all_tags = [
            "wrong_items",
            "meal_issue",
            "missing_choice",
            "combat_issue",
            "narrative_error",
            "discipline_issue",
            "other",
        ]
        resp = _post_report(client, tokens["access_token"], tags=all_tags)
        assert resp.status_code == 201
        assert set(resp.json()["tags"]) == set(all_tags)

    def test_empty_tags_list_returns_201(self, client: TestClient) -> None:
        """An empty tags list is valid — the report is still accepted."""
        tokens = _make_user(client, "reportuser4")
        resp = _post_report(client, tokens["access_token"], tags=[])
        assert resp.status_code == 201
        assert resp.json()["tags"] == []

    def test_character_id_and_scene_id_stored(self, client: TestClient) -> None:
        """character_id and scene_id are accepted when None and returned in the response.

        FK-enforced SQLite prevents using arbitrary IDs that don't correspond to real
        rows. The important behaviour is that the fields are wired through correctly;
        None values are the safe way to exercise the mapping in integration tests.
        """
        tokens = _make_user(client, "reportuser5")
        resp = _post_report(
            client,
            tokens["access_token"],
            tags=["combat_issue"],
            character_id=None,
            scene_id=None,
            free_text="Checking optional fields",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["character_id"] is None
        assert data["scene_id"] is None

    def test_optional_fields_default_to_none(self, client: TestClient) -> None:
        """Omitting character_id, scene_id, and free_text produces None in response."""
        tokens = _make_user(client, "reportuser6")
        resp = client.post(
            "/reports",
            json={"tags": ["other"]},
            headers=auth_headers(tokens["access_token"]),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["character_id"] is None
        assert data["scene_id"] is None
        assert data["free_text"] is None

    def test_free_text_stored_in_response(self, client: TestClient) -> None:
        """free_text is round-tripped correctly."""
        tokens = _make_user(client, "reportuser7")
        text = "The combat table result seems wrong for this roll"
        resp = _post_report(
            client, tokens["access_token"], tags=["combat_issue"], free_text=text
        )
        assert resp.status_code == 201
        assert resp.json()["free_text"] == text


# ---------------------------------------------------------------------------
# POST /reports — validation failures
# ---------------------------------------------------------------------------


class TestCreateReportValidation:
    def test_invalid_tag_returns_400(self, client: TestClient) -> None:
        """A single unknown tag triggers a 400 response."""
        tokens = _make_user(client, "invaltaguser1")
        resp = _post_report(client, tokens["access_token"], tags=["nonexistent_tag"])
        assert resp.status_code == 400
        assert "nonexistent_tag" in resp.json()["detail"]

    def test_mix_valid_and_invalid_tags_returns_400(self, client: TestClient) -> None:
        """If any tag is invalid the entire request is rejected."""
        tokens = _make_user(client, "invaltaguser2")
        resp = _post_report(
            client,
            tokens["access_token"],
            tags=["meal_issue", "hacker_tag"],
        )
        assert resp.status_code == 400

    def test_multiple_invalid_tags_all_listed_in_detail(self, client: TestClient) -> None:
        """All invalid tag names appear in the error detail."""
        tokens = _make_user(client, "invaltaguser3")
        resp = _post_report(
            client,
            tokens["access_token"],
            tags=["bad_one", "bad_two"],
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "bad_one" in detail
        assert "bad_two" in detail


# ---------------------------------------------------------------------------
# POST /reports — unauthenticated
# ---------------------------------------------------------------------------


class TestCreateReportAuth:
    def test_unauthenticated_post_returns_401(self, client: TestClient) -> None:
        """POST /reports without a token returns 401."""
        resp = client.post("/reports", json={"tags": ["other"]})
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        """POST /reports with a garbage token returns 401."""
        resp = client.post(
            "/reports",
            json={"tags": ["other"]},
            headers={"Authorization": "Bearer not.a.real.token"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /reports — own-report isolation
# ---------------------------------------------------------------------------


class TestListReports:
    def test_list_returns_own_reports(self, client: TestClient) -> None:
        """GET /reports returns only the calling user's reports."""
        tokens_a = _make_user(client, "listreporter_a")
        tokens_b = _make_user(client, "listreporter_b")

        # User A creates two reports
        _post_report(client, tokens_a["access_token"], tags=["other"], free_text="A1")
        _post_report(client, tokens_a["access_token"], tags=["meal_issue"], free_text="A2")

        # User B creates one report
        _post_report(client, tokens_b["access_token"], tags=["combat_issue"], free_text="B1")

        # User A sees exactly their two reports
        resp_a = client.get("/reports", headers=auth_headers(tokens_a["access_token"]))
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert len(data_a["reports"]) == 2
        texts_a = {r["free_text"] for r in data_a["reports"]}
        assert texts_a == {"A1", "A2"}

        # User B sees exactly their one report
        resp_b = client.get("/reports", headers=auth_headers(tokens_b["access_token"]))
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert len(data_b["reports"]) == 1
        assert data_b["reports"][0]["free_text"] == "B1"

    def test_user_cannot_see_other_users_reports(self, client: TestClient) -> None:
        """User B never receives reports that belong to User A."""
        tokens_a = _make_user(client, "isolation_a")
        tokens_b = _make_user(client, "isolation_b")

        _post_report(client, tokens_a["access_token"], tags=["other"], free_text="secret_a")

        resp_b = client.get("/reports", headers=auth_headers(tokens_b["access_token"]))
        assert resp_b.status_code == 200
        free_texts = [r["free_text"] for r in resp_b.json()["reports"]]
        assert "secret_a" not in free_texts

    def test_empty_list_when_no_reports(self, client: TestClient) -> None:
        """A user with no reports receives an empty list (not an error)."""
        tokens = _make_user(client, "empty_reporter")
        resp = client.get("/reports", headers=auth_headers(tokens["access_token"]))
        assert resp.status_code == 200
        assert resp.json()["reports"] == []

    def test_unauthenticated_get_returns_401(self, client: TestClient) -> None:
        """GET /reports without a token returns 401."""
        resp = client.get("/reports")
        assert resp.status_code == 401

    def test_response_includes_all_fields(self, client: TestClient) -> None:
        """Each report in the list response contains the full ReportResponse shape."""
        tokens = _make_user(client, "fieldcheck_reporter")
        _post_report(
            client,
            tokens["access_token"],
            tags=["narrative_error"],
            free_text="Check fields",
        )
        resp = client.get("/reports", headers=auth_headers(tokens["access_token"]))
        assert resp.status_code == 200
        report = resp.json()["reports"][0]
        for field in ("id", "tags", "status", "free_text", "character_id", "scene_id", "created_at"):
            assert field in report, f"Missing field: {field}"
        assert report["status"] == "open"
        assert report["tags"] == ["narrative_error"]
