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
    _parse_json_llm,
    _scene_analysis_cache_key,
    _set_cached,
    _validate_scene_analysis,
    analyze_scene,
    rewrite_choice,
    rewrite_choices_batch,
)
from app.parser.types import ChoiceData, SceneAnalysisData

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


# ---------------------------------------------------------------------------
# Scene analysis — cache key
# ---------------------------------------------------------------------------

COMBAT_NARRATIVE = (
    "A Kraan swoops down from the sky. You must fight it.\n"
    "Kraan: COMBAT SKILL 16   ENDURANCE 24\n"
    "You may evade combat after 3 rounds by turning to 85."
)

SCENE_ANALYSIS_JSON = json.dumps({
    "entities": [
        {"kind": "creature", "name": "Kraan", "description": "A flying reptilian creature", "aliases": []},
    ],
    "relationships": [],
    "combat_encounters": [
        {"enemy_name": "Kraan", "combat_skill": 16, "endurance": 24, "ordinal": 1},
    ],
    "items": [],
    "random_outcomes": [],
    "evasion": {"rounds": 3, "target_scene": 85, "damage": 0},
    "combat_modifiers": [],
    "conditions": [],
    "scene_flags": {
        "must_eat": False, "loses_backpack": False,
        "is_death": False, "is_victory": False, "mindblast_immune": False,
    },
})


class TestSceneAnalysisCacheKey:
    def test_is_deterministic(self) -> None:
        k1 = _scene_analysis_cache_key("narrative", 1, 42)
        k2 = _scene_analysis_cache_key("narrative", 1, 42)
        assert k1 == k2

    def test_different_scene_different_key(self) -> None:
        k1 = _scene_analysis_cache_key("narrative", 1, 42)
        k2 = _scene_analysis_cache_key("narrative", 1, 43)
        assert k1 != k2

    def test_different_book_different_key(self) -> None:
        k1 = _scene_analysis_cache_key("narrative", 1, 42)
        k2 = _scene_analysis_cache_key("narrative", 2, 42)
        assert k1 != k2

    def test_returns_64_char_hex(self) -> None:
        key = _scene_analysis_cache_key("narrative", 1, 1)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# Scene analysis — validation
# ---------------------------------------------------------------------------


class TestValidateSceneAnalysis:
    def test_returns_none_for_non_dict(self) -> None:
        assert _validate_scene_analysis([]) is None
        assert _validate_scene_analysis("string") is None
        assert _validate_scene_analysis(None) is None

    def test_empty_dict_returns_defaults(self) -> None:
        result = _validate_scene_analysis({})
        assert result is not None
        assert result["entities"] == []
        assert result["combat_encounters"] == []
        assert result["items"] == []
        assert result["evasion"] is None
        assert result["scene_flags"]["must_eat"] is False

    def test_validates_combat_encounters(self) -> None:
        raw = {
            "combat_encounters": [
                {"enemy_name": "Kraan", "combat_skill": 16, "endurance": 24, "ordinal": 1},
                {"enemy_name": "", "combat_skill": 10, "endurance": 12},  # empty name — filtered
                {"enemy_name": "Giak", "combat_skill": "bad", "endurance": 12},  # bad CS — filtered
            ],
        }
        result = _validate_scene_analysis(raw)
        assert len(result["combat_encounters"]) == 1
        assert result["combat_encounters"][0]["enemy_name"] == "Kraan"

    def test_validates_items(self) -> None:
        raw = {
            "items": [
                {"item_name": "Sword", "item_type": "weapon", "quantity": 1, "action": "gain"},
                {"item_name": "Junk", "item_type": "invalid_type", "quantity": 1, "action": "gain"},
                {"item_name": "Gold", "item_type": "gold", "quantity": 5, "action": "invalid"},
            ],
        }
        result = _validate_scene_analysis(raw)
        assert len(result["items"]) == 1
        assert result["items"][0]["item_name"] == "Sword"

    def test_validates_evasion(self) -> None:
        raw = {"evasion": {"rounds": 3, "target_scene": 85, "damage": 2}}
        result = _validate_scene_analysis(raw)
        assert result["evasion"] == {"rounds": 3, "target_scene": 85, "damage": 2}

    def test_evasion_null(self) -> None:
        raw = {"evasion": None}
        result = _validate_scene_analysis(raw)
        assert result["evasion"] is None

    def test_evasion_missing_required_fields(self) -> None:
        raw = {"evasion": {"rounds": 3}}  # missing target_scene
        result = _validate_scene_analysis(raw)
        assert result["evasion"] is None

    def test_validates_conditions_with_or(self) -> None:
        raw = {
            "conditions": [
                {
                    "choice_ordinal": 1,
                    "condition_type": "discipline",
                    "condition_value": {"any": ["Tracking", "Huntmastery"]},
                },
            ],
        }
        result = _validate_scene_analysis(raw)
        assert len(result["conditions"]) == 1
        # Dict value should be JSON-encoded
        assert '"any"' in result["conditions"][0]["condition_value"]

    def test_validates_scene_flags(self) -> None:
        raw = {"scene_flags": {"must_eat": True, "is_death": True}}
        result = _validate_scene_analysis(raw)
        assert result["scene_flags"]["must_eat"] is True
        assert result["scene_flags"]["is_death"] is True
        assert result["scene_flags"]["loses_backpack"] is False  # default

    def test_validates_combat_modifiers(self) -> None:
        raw = {
            "combat_modifiers": [
                {"modifier_type": "undead", "value": None},
                {"modifier_type": "cs_bonus", "value": 2},
                {"modifier_type": "invalid_type", "value": 1},  # filtered
            ],
        }
        result = _validate_scene_analysis(raw)
        assert len(result["combat_modifiers"]) == 2

    def test_validates_random_outcomes(self) -> None:
        raw = {
            "random_outcomes": [
                {"range_min": 0, "range_max": 4, "effect_type": "endurance_change", "effect_value": -2},
                {"range_min": 5, "range_max": 9, "effect_type": "invalid_effect"},  # filtered
            ],
        }
        result = _validate_scene_analysis(raw)
        assert len(result["random_outcomes"]) == 1
        assert result["random_outcomes"][0]["effect_value"] == "-2"  # converted to str

    def test_non_list_entities_returns_empty(self) -> None:
        result = _validate_scene_analysis({"entities": "not a list"})
        assert result is not None
        assert result["entities"] == []

    def test_non_int_quantity_defaults_to_one(self) -> None:
        raw = {
            "items": [
                {"item_name": "Sword", "item_type": "weapon", "quantity": "five", "action": "gain"},
            ],
        }
        result = _validate_scene_analysis(raw)
        assert len(result["items"]) == 1
        assert result["items"][0]["quantity"] == 1

    def test_float_combat_skill_coerced(self) -> None:
        raw = {
            "combat_encounters": [
                {"enemy_name": "Kraan", "combat_skill": 16.0, "endurance": 24, "ordinal": 1},
            ],
        }
        result = _validate_scene_analysis(raw)
        assert len(result["combat_encounters"]) == 1
        assert result["combat_encounters"][0]["enemy_cs"] == 16
        assert isinstance(result["combat_encounters"][0]["enemy_cs"], int)


# ---------------------------------------------------------------------------
# Scene analysis — analyze_scene function
# ---------------------------------------------------------------------------


class TestAnalyzeScene:
    def test_skip_llm_returns_none(self, tmp_cache: Path) -> None:
        result = analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=1,
            existing_catalog={}, skip_llm=True,
        )
        assert result is None

    def test_empty_narrative_returns_none(self, tmp_cache: Path) -> None:
        result = analyze_scene(
            "", [], book_id=1, scene_number=1,
            existing_catalog={}, client=_make_mock_client(SCENE_ANALYSIS_JSON),
        )
        assert result is None

    def test_whitespace_only_narrative_returns_none(self, tmp_cache: Path) -> None:
        result = analyze_scene(
            "   \n  ", [], book_id=1, scene_number=1,
            existing_catalog={}, client=_make_mock_client(SCENE_ANALYSIS_JSON),
        )
        assert result is None

    def test_returns_scene_analysis_data(self, tmp_cache: Path) -> None:
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        result = analyze_scene(
            COMBAT_NARRATIVE, ["If you wish to fight, turn to 100."],
            book_id=1, scene_number=42, existing_catalog={},
            client=client, no_cache=True,
        )
        assert isinstance(result, SceneAnalysisData)
        assert len(result.combat_encounters) == 1
        assert result.combat_encounters[0]["enemy_name"] == "Kraan"
        assert result.evasion == {"rounds": 3, "target_scene": 85, "damage": 0}
        assert len(result.entities) == 1

    def test_calls_llm_with_system_and_user_messages(self, tmp_cache: Path) -> None:
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        analyze_scene(
            COMBAT_NARRATIVE, ["Choice 1"],
            book_id=1, scene_number=5, existing_catalog={},
            client=client, no_cache=True,
        )
        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["max_tokens"] == 4096
        assert "system" in call_kwargs
        assert "combat_encounters" in call_kwargs["system"]
        user_content = call_kwargs["messages"][0]["content"]
        assert "Scene 5" in user_content
        assert "Choice 1" in user_content

    def test_narrative_in_prompt(self, tmp_cache: Path) -> None:
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=1,
            existing_catalog={}, client=client, no_cache=True,
        )
        user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Kraan" in user_content

    def test_choices_included_in_prompt(self) -> None:
        """Choices text should appear in the user message."""
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        analyze_scene(
            COMBAT_NARRATIVE,
            ["If you have Tracking, turn to 50.", "Go north, turn to 100."],
            book_id=1, scene_number=1, existing_catalog={},
            client=client, no_cache=True,
        )
        user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Tracking" in user_content
        assert "1." in user_content
        assert "2." in user_content

    def test_no_choices_placeholder(self) -> None:
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=1,
            existing_catalog={}, client=client, no_cache=True,
        )
        user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "death or victory" in user_content

    def test_cache_hit_skips_llm(self, tmp_cache: Path) -> None:
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        # First call populates cache
        analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=42,
            existing_catalog={}, client=client,
        )
        client.messages.create.reset_mock()
        # Second call should hit cache
        result = analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=42,
            existing_catalog={}, client=client,
        )
        client.messages.create.assert_not_called()
        assert isinstance(result, SceneAnalysisData)

    def test_no_cache_always_calls_llm(self, tmp_cache: Path) -> None:
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=42,
            existing_catalog={}, client=client, no_cache=True,
        )
        analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=42,
            existing_catalog={}, client=client, no_cache=True,
        )
        assert client.messages.create.call_count == 2

    def test_malformed_json_returns_none(self, tmp_cache: Path) -> None:
        client = _make_mock_client("this is not json at all")
        result = analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=1,
            existing_catalog={}, client=client, no_cache=True,
        )
        assert result is None

    def test_api_error_returns_none(self, tmp_cache: Path) -> None:
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API error")
        result = analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=1,
            existing_catalog={}, client=client, no_cache=True,
        )
        assert result is None

    def test_entities_filtered_by_catalog(self, tmp_cache: Path) -> None:
        """Entities already in the catalog should be excluded."""
        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        catalog = {"kraan": {"kind": "creature", "name": "Kraan"}}
        result = analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=1,
            existing_catalog=catalog, client=client, no_cache=True,
        )
        assert result is not None
        assert len(result.entities) == 0  # Kraan filtered out

    def test_scene_flags_all_false_by_default(self, tmp_cache: Path) -> None:
        minimal_json = json.dumps({"scene_flags": {}})
        client = _make_mock_client(minimal_json)
        result = analyze_scene(
            "A simple scene.", [], book_id=1, scene_number=1,
            existing_catalog={}, client=client, no_cache=True,
        )
        assert result is not None
        assert result.scene_flags["must_eat"] is False
        assert result.scene_flags["is_death"] is False

    def test_client_none_anthropic_import_fails_returns_none(self, tmp_cache):
        """When no client is provided and Anthropic() raises, return None gracefully."""
        import sys
        import anthropic as real_anthropic
        mock_anthropic = MagicMock(spec=real_anthropic)
        mock_anthropic.Anthropic.side_effect = RuntimeError("No API key")
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            result = analyze_scene(
                COMBAT_NARRATIVE, [], book_id=1, scene_number=1,
                existing_catalog={}, client=None,
            )
        assert result is None

    def test_cache_hit_invalid_data_falls_through_to_llm(self, tmp_cache):
        """When cache has invalid data, fall through and make a fresh LLM call."""
        # Prime cache with a valid JSON array (not a dict — fails _validate_scene_analysis)
        key = _scene_analysis_cache_key(COMBAT_NARRATIVE, 1, 42)
        _set_cached(key, "[1, 2, 3]", "old prompt")

        client = _make_mock_client(SCENE_ANALYSIS_JSON)
        result = analyze_scene(
            COMBAT_NARRATIVE, [], book_id=1, scene_number=42,
            existing_catalog={}, client=client,
        )
        # Should have fallen through to LLM
        client.messages.create.assert_called_once()
        assert isinstance(result, SceneAnalysisData)
