"""Unit tests for app/parser/llm.py.

All LLM calls are mocked — no real Anthropic API calls are made.
Cache files are written to a temporary directory injected via monkeypatch
so tests never pollute the project's ``.parser_cache/`` directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.parser.llm import (
    _cache_key,
    _get_cached,
    _set_cached,
    rewrite_choice,
    rewrite_choices_batch,
)
from app.parser.types import ChoiceData

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

RAW_TEXT = "If you wish to investigate the noise, turn to 85."
NARRATIVE = "You stand at the edge of a dark forest. The wind howls through the trees."
REWRITTEN = "If you wish to investigate the noise."


def _make_mock_client(response_text: str) -> MagicMock:
    """Build a mock Anthropic client that returns *response_text*."""
    content_block = MagicMock()
    content_block.text = response_text

    message = MagicMock()
    message.content = [content_block]

    client = MagicMock()
    client.messages.create.return_value = message
    return client


@pytest.fixture()
def tmp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``app.parser.llm._CACHE_DIR`` to a temporary directory."""
    cache_dir = tmp_path / ".parser_cache"
    monkeypatch.setattr("app.parser.llm._CACHE_DIR", cache_dir)
    return cache_dir


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_is_deterministic(self) -> None:
        key1 = _cache_key(RAW_TEXT, NARRATIVE)
        key2 = _cache_key(RAW_TEXT, NARRATIVE)
        assert key1 == key2

    def test_different_raw_text_produces_different_key(self) -> None:
        key1 = _cache_key("option A, turn to 10.", NARRATIVE)
        key2 = _cache_key("option B, turn to 20.", NARRATIVE)
        assert key1 != key2

    def test_different_narrative_produces_different_key(self) -> None:
        key1 = _cache_key(RAW_TEXT, "Forest scene.")
        key2 = _cache_key(RAW_TEXT, "Desert scene.")
        assert key1 != key2

    def test_returns_64_char_hex_string(self) -> None:
        key = _cache_key(RAW_TEXT, NARRATIVE)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# Cache read / write helpers
# ---------------------------------------------------------------------------


class TestGetCached:
    def test_returns_none_when_no_cache_file(self, tmp_cache: Path) -> None:
        result = _get_cached("nonexistent_key_abc123")
        assert result is None

    def test_returns_response_from_valid_cache_file(self, tmp_cache: Path) -> None:
        key = "test_key_abc"
        cache_file = tmp_cache / f"{key}.json"
        tmp_cache.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"prompt": "p", "response": REWRITTEN, "timestamp": "t", "model": "m"}),
            encoding="utf-8",
        )
        result = _get_cached(key)
        assert result == REWRITTEN

    def test_returns_none_on_malformed_json(self, tmp_cache: Path) -> None:
        key = "bad_json_key"
        tmp_cache.mkdir(parents=True, exist_ok=True)
        (tmp_cache / f"{key}.json").write_text("not valid json", encoding="utf-8")
        result = _get_cached(key)
        assert result is None

    def test_returns_none_when_response_key_missing(self, tmp_cache: Path) -> None:
        key = "missing_response"
        tmp_cache.mkdir(parents=True, exist_ok=True)
        (tmp_cache / f"{key}.json").write_text(
            json.dumps({"prompt": "p", "timestamp": "t"}), encoding="utf-8"
        )
        result = _get_cached(key)
        assert result is None


class TestSetCached:
    def test_creates_cache_directory_if_missing(self, tmp_cache: Path) -> None:
        assert not tmp_cache.exists()
        _set_cached("newkey", REWRITTEN, "some prompt")
        assert tmp_cache.is_dir()

    def test_writes_json_file_with_expected_fields(self, tmp_cache: Path) -> None:
        key = "write_test"
        _set_cached(key, REWRITTEN, "prompt text")
        cache_file = tmp_cache / f"{key}.json"
        assert cache_file.exists()
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert data["response"] == REWRITTEN
        assert data["prompt"] == "prompt text"
        assert "timestamp" in data
        assert "model" in data

    def test_round_trip_get_after_set(self, tmp_cache: Path) -> None:
        key = "round_trip"
        _set_cached(key, REWRITTEN, "prompt")
        result = _get_cached(key)
        assert result == REWRITTEN


# ---------------------------------------------------------------------------
# rewrite_choice — prompt construction and response handling
# ---------------------------------------------------------------------------


class TestRewriteChoice:
    def test_calls_llm_with_correct_model(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"

    def test_prompt_contains_raw_text(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_content = call_kwargs["messages"][0]["content"]
        assert RAW_TEXT in prompt_content

    def test_prompt_contains_scene_narrative_context(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_content = call_kwargs["messages"][0]["content"]
        assert NARRATIVE[:100] in prompt_content

    def test_returns_rewritten_text_from_llm(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        result = rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        assert result == REWRITTEN

    def test_strips_whitespace_from_llm_response(self, tmp_cache: Path) -> None:
        client = _make_mock_client("  " + REWRITTEN + "\n")
        result = rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        assert result == REWRITTEN

    def test_narrative_truncated_to_500_chars_in_prompt(self, tmp_cache: Path) -> None:
        long_narrative = "x" * 1000
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, long_narrative, client=client, no_cache=True)
        call_kwargs = client.messages.create.call_args.kwargs
        prompt_content = call_kwargs["messages"][0]["content"]
        # Exactly 500 x's, not 1000
        assert "x" * 500 in prompt_content
        assert "x" * 501 not in prompt_content


# ---------------------------------------------------------------------------
# rewrite_choice — skip_llm flag
# ---------------------------------------------------------------------------


class TestRewriteChoiceSkipLlm:
    def test_skip_llm_returns_raw_text(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        result = rewrite_choice(RAW_TEXT, NARRATIVE, client=client, skip_llm=True)
        assert result == RAW_TEXT

    def test_skip_llm_does_not_call_llm(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, skip_llm=True)
        client.messages.create.assert_not_called()

    def test_skip_llm_does_not_write_cache(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, skip_llm=True)
        assert not tmp_cache.exists() or list(tmp_cache.glob("*.json")) == []


# ---------------------------------------------------------------------------
# rewrite_choice — cache hit / miss
# ---------------------------------------------------------------------------


class TestRewriteChoiceCacheBehavior:
    def test_cache_miss_calls_llm(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client)
        client.messages.create.assert_called_once()

    def test_cache_miss_writes_result_to_cache(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client)
        key = _cache_key(RAW_TEXT, NARRATIVE)
        assert (tmp_cache / f"{key}.json").exists()

    def test_cache_hit_does_not_call_llm(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        # Prime the cache
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client)
        client.messages.create.reset_mock()
        # Second call should use cache
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client)
        client.messages.create.assert_not_called()

    def test_cache_hit_returns_cached_value(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client)
        # Change the mock so we can tell if cache is used
        client.messages.create.return_value.content[0].text = "different text"
        result = rewrite_choice(RAW_TEXT, NARRATIVE, client=client)
        assert result == REWRITTEN


# ---------------------------------------------------------------------------
# rewrite_choice — no_cache flag
# ---------------------------------------------------------------------------


class TestRewriteChoiceNoCache:
    def test_no_cache_always_calls_llm(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        assert client.messages.create.call_count == 2

    def test_no_cache_does_not_read_existing_cache(self, tmp_cache: Path) -> None:
        """Even when a cache file exists, no_cache=True should bypass it."""
        # Write a cache entry manually
        key = _cache_key(RAW_TEXT, NARRATIVE)
        _set_cached(key, "stale cached value", "old prompt")

        client = _make_mock_client(REWRITTEN)
        result = rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        # Should get the live LLM result, not the stale cache
        assert result == REWRITTEN
        client.messages.create.assert_called_once()

    def test_no_cache_does_not_write_to_cache(self, tmp_cache: Path) -> None:
        client = _make_mock_client(REWRITTEN)
        rewrite_choice(RAW_TEXT, NARRATIVE, client=client, no_cache=True)
        key = _cache_key(RAW_TEXT, NARRATIVE)
        assert not (tmp_cache / f"{key}.json").exists()


# ---------------------------------------------------------------------------
# rewrite_choice — error handling
# ---------------------------------------------------------------------------


class TestRewriteChoiceErrorHandling:
    def test_api_error_falls_back_to_raw_text(self, tmp_cache: Path) -> None:
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API unavailable")
        result = rewrite_choice(RAW_TEXT, NARRATIVE, client=client)
        assert result == RAW_TEXT

    def test_client_creation_failure_falls_back_to_raw_text(self, tmp_cache: Path) -> None:
        """When no client is provided and Anthropic() raises, fall back gracefully."""
        import sys

        import anthropic as real_anthropic

        mock_anthropic = MagicMock(spec=real_anthropic)
        mock_anthropic.Anthropic.side_effect = RuntimeError("No API key")

        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            result = rewrite_choice(RAW_TEXT, NARRATIVE, client=None)
        assert result == RAW_TEXT


# ---------------------------------------------------------------------------
# rewrite_choices_batch
# ---------------------------------------------------------------------------


class TestRewriteChoicesBatch:
    def test_returns_list_of_display_texts(self, tmp_cache: Path) -> None:
        choices = [
            ChoiceData(raw_text="If you go north, turn to 10.", target_scene_number=10, ordinal=1),
            ChoiceData(raw_text="If you go south, turn to 20.", target_scene_number=20, ordinal=2),
        ]
        client = _make_mock_client("rewritten text")
        results = rewrite_choices_batch(choices, NARRATIVE, client=client, no_cache=True)
        assert len(results) == 2

    def test_preserves_order(self, tmp_cache: Path) -> None:
        choices = [
            ChoiceData(raw_text="Choice A, turn to 1.", target_scene_number=1, ordinal=1),
            ChoiceData(raw_text="Choice B, turn to 2.", target_scene_number=2, ordinal=2),
            ChoiceData(raw_text="Choice C, turn to 3.", target_scene_number=3, ordinal=3),
        ]

        def make_response(index: int) -> MagicMock:
            content_block = MagicMock()
            content_block.text = f"Rewritten {index}"
            message = MagicMock()
            message.content = [content_block]
            return message

        client = MagicMock()
        responses = [make_response(i) for i in range(3)]
        client.messages.create.side_effect = responses

        results = rewrite_choices_batch(choices, NARRATIVE, client=client, no_cache=True)
        assert results[0] == "Rewritten 0"
        assert results[1] == "Rewritten 1"
        assert results[2] == "Rewritten 2"

    def test_skip_llm_returns_raw_texts(self, tmp_cache: Path) -> None:
        choices = [
            ChoiceData(raw_text="Go left, turn to 5.", target_scene_number=5, ordinal=1),
            ChoiceData(raw_text="Go right, turn to 6.", target_scene_number=6, ordinal=2),
        ]
        client = _make_mock_client("should not be called")
        results = rewrite_choices_batch(choices, NARRATIVE, client=client, skip_llm=True)
        assert results[0] == "Go left, turn to 5."
        assert results[1] == "Go right, turn to 6."
        client.messages.create.assert_not_called()

    def test_empty_choices_returns_empty_list(self, tmp_cache: Path) -> None:
        results = rewrite_choices_batch([], NARRATIVE)
        assert results == []

    def test_no_cache_bypasses_cache_for_all_choices(self, tmp_cache: Path) -> None:
        choices = [
            ChoiceData(raw_text="Go left, turn to 5.", target_scene_number=5, ordinal=1),
        ]
        client = _make_mock_client(REWRITTEN)
        rewrite_choices_batch(choices, NARRATIVE, client=client, no_cache=True)
        rewrite_choices_batch(choices, NARRATIVE, client=client, no_cache=True)
        assert client.messages.create.call_count == 2
