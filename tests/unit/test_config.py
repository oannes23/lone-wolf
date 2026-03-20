"""Tests for app/config.py — settings loading and validation."""

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


class TestSettings:
    def test_loads_required_jwt_secret_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET", "my-test-secret")
        settings = Settings()
        assert settings.JWT_SECRET == "my-test-secret"  # noqa: S105

    def test_raises_when_jwt_secret_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_defaults_are_applied(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET", "x")
        settings = Settings()
        assert settings.DATABASE_URL == "sqlite:///./lone_wolf.db"
        assert settings.JWT_ALGORITHM == "HS256"
        assert settings.ACCESS_TOKEN_EXPIRE_HOURS == 24
        assert settings.REFRESH_TOKEN_EXPIRE_DAYS == 7
        assert settings.ADMIN_TOKEN_EXPIRE_HOURS == 8
        assert settings.ROLL_TOKEN_EXPIRE_HOURS == 1

    def test_overrides_database_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET", "x")
        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        settings = Settings()
        assert settings.DATABASE_URL == "sqlite:///:memory:"

    def test_overrides_token_expiry_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_SECRET", "x")
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_HOURS", "48")
        settings = Settings()
        assert settings.ACCESS_TOKEN_EXPIRE_HOURS == 48

    def test_get_settings_returns_settings_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # JWT_SECRET is set by the .env file present in the repo root
        result = get_settings()
        assert isinstance(result, Settings)
