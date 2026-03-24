"""Unit tests for Story 5.4: LLM entity extraction in app/parser/llm.py.

All LLM calls are mocked — no real Anthropic API calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

from app.parser.llm import (
    _filter_new_entities,
    _parse_json_llm,
    create_foe_game_object,
    create_item_game_object,
    create_scene_game_object,
    extract_entities,
    infer_relationships,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(text: str) -> MagicMock:
    """Build a minimal mock Anthropic message response containing *text*."""
    content_block = MagicMock()
    content_block.text = text
    message = MagicMock()
    message.content = [content_block]
    return message


def _make_client(response_text: str) -> MagicMock:
    """Return a mock Anthropic client whose messages.create() returns *response_text*."""
    client = MagicMock()
    client.messages.create.return_value = _make_message(response_text)
    return client


# ---------------------------------------------------------------------------
# _parse_json_llm
# ---------------------------------------------------------------------------


class TestParseJsonLlm:
    """Tests for the internal JSON parsing helper."""

    def test_plain_json_array(self) -> None:
        result = _parse_json_llm('[{"kind": "character", "name": "Banedon"}]')
        assert isinstance(result, list)
        assert result[0]["name"] == "Banedon"

    def test_markdown_fenced_json(self) -> None:
        text = '```json\n[{"kind": "location", "name": "Holmgard"}]\n```'
        result = _parse_json_llm(text)
        assert isinstance(result, list)
        assert result[0]["name"] == "Holmgard"

    def test_malformed_json_returns_none(self) -> None:
        result = _parse_json_llm("this is not json at all")
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        result = _parse_json_llm("")
        assert result is None

    def test_partial_fence_no_close(self) -> None:
        # Fence opened but never closed — should still parse inner content
        text = "```json\n[1, 2, 3]"
        result = _parse_json_llm(text)
        assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# _filter_new_entities
# ---------------------------------------------------------------------------


class TestFilterNewEntities:
    """Tests for the entity deduplication / validation helper."""

    def test_passes_valid_entity(self) -> None:
        raw = [{"kind": "character", "name": "Banedon", "description": "A wizard", "aliases": []}]
        result = _filter_new_entities(raw, {})
        assert len(result) == 1
        assert result[0]["name"] == "Banedon"

    def test_deduplicates_case_insensitive(self) -> None:
        raw = [{"kind": "character", "name": "Banedon", "description": "", "aliases": []}]
        existing = {"banedon": {"name": "Banedon"}}
        result = _filter_new_entities(raw, existing)
        assert result == []

    def test_skips_unknown_kind(self) -> None:
        raw = [{"kind": "artifact", "name": "Sommerswerd", "description": "", "aliases": []}]
        result = _filter_new_entities(raw, {})
        assert result == []

    def test_skips_missing_name(self) -> None:
        raw = [{"kind": "creature", "description": "no name"}]
        result = _filter_new_entities(raw, {})
        assert result == []

    def test_skips_non_dict_entries(self) -> None:
        raw = ["not a dict", 42, None]
        result = _filter_new_entities(raw, {})  # type: ignore[arg-type]
        assert result == []

    def test_aliases_defaults_to_empty_list_when_not_list(self) -> None:
        raw = [{"kind": "location", "name": "Sommerlund", "description": "", "aliases": "alias"}]
        result = _filter_new_entities(raw, {})
        assert result[0]["aliases"] == []

    def test_multiple_entities_partial_dedup(self) -> None:
        raw = [
            {"kind": "character", "name": "Banedon", "description": "", "aliases": []},
            {"kind": "location", "name": "Holmgard", "description": "", "aliases": []},
        ]
        existing = {"banedon": {}}
        result = _filter_new_entities(raw, existing)
        assert len(result) == 1
        assert result[0]["name"] == "Holmgard"


# ---------------------------------------------------------------------------
# extract_entities
# ---------------------------------------------------------------------------


class TestExtractEntities:
    """Tests for the public extract_entities() function."""

    def test_skip_entities_returns_empty(self) -> None:
        result = extract_entities(
            narrative="Lone Wolf fights a Gourgaz.",
            book_id=1,
            existing_catalog={},
            skip_entities=True,
        )
        assert result == []

    def test_empty_narrative_returns_empty(self) -> None:
        result = extract_entities(
            narrative="",
            book_id=1,
            existing_catalog={},
        )
        assert result == []

    def test_whitespace_only_narrative_returns_empty(self) -> None:
        result = extract_entities(
            narrative="   \n  ",
            book_id=1,
            existing_catalog={},
        )
        assert result == []

    def test_llm_called_with_narrative_in_prompt(self) -> None:
        narrative = "You meet Banedon the wizard in the ruins of Holmgard."
        llm_response = json.dumps(
            [
                {
                    "kind": "character",
                    "name": "Banedon",
                    "description": "A wizard",
                    "aliases": [],
                }
            ]
        )
        client = _make_client(llm_response)
        result = extract_entities(
            narrative=narrative,
            book_id=1,
            existing_catalog={},
            client=client,
            no_cache=True,
        )
        assert len(result) == 1
        assert result[0]["name"] == "Banedon"
        assert result[0]["kind"] == "character"
        # Verify LLM was called and the narrative text appeared in the prompt
        assert client.messages.create.call_count == 1
        call_kwargs = client.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        prompt_text = messages[0]["content"]
        assert narrative[:50] in prompt_text

    def test_new_entity_not_in_catalog_is_returned(self) -> None:
        llm_response = json.dumps(
            [{"kind": "creature", "name": "Gourgaz", "description": "A lizard warrior", "aliases": []}]
        )
        client = _make_client(llm_response)
        result = extract_entities(
            narrative="A Gourgaz blocks your path.",
            book_id=1,
            existing_catalog={},
            client=client,
            no_cache=True,
        )
        assert any(e["name"] == "Gourgaz" for e in result)

    def test_entity_already_in_catalog_not_returned(self) -> None:
        llm_response = json.dumps(
            [{"kind": "creature", "name": "Gourgaz", "description": "A lizard warrior", "aliases": []}]
        )
        client = _make_client(llm_response)
        result = extract_entities(
            narrative="A Gourgaz blocks your path.",
            book_id=1,
            existing_catalog={"gourgaz": {"name": "Gourgaz"}},
            client=client,
            no_cache=True,
        )
        assert result == []

    def test_deduplication_is_case_insensitive(self) -> None:
        llm_response = json.dumps(
            [{"kind": "character", "name": "BANEDON", "description": "", "aliases": []}]
        )
        client = _make_client(llm_response)
        result = extract_entities(
            narrative="You see Banedon.",
            book_id=1,
            existing_catalog={"banedon": {}},
            client=client,
            no_cache=True,
        )
        assert result == []

    def test_malformed_json_response_returns_empty(self) -> None:
        client = _make_client("Here are the entities: Banedon is a wizard.")
        result = extract_entities(
            narrative="You meet Banedon.",
            book_id=1,
            existing_catalog={},
            client=client,
            no_cache=True,
        )
        assert result == []

    def test_llm_error_returns_empty(self) -> None:
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API timeout")
        result = extract_entities(
            narrative="You meet Banedon.",
            book_id=1,
            existing_catalog={},
            client=client,
            no_cache=True,
        )
        assert result == []

    def test_cache_hit_skips_llm_call(self, tmp_path: pytest.TempdirFixture) -> None:
        narrative = "You enter the city of Holmgard."
        llm_response = json.dumps(
            [{"kind": "location", "name": "Holmgard", "description": "A city", "aliases": []}]
        )
        client = _make_client(llm_response)

        # Patch _CACHE_DIR to use tmp_path so we don't pollute the real cache
        with patch("app.parser.llm._CACHE_DIR", tmp_path):
            # First call — should hit LLM and write cache
            result1 = extract_entities(
                narrative=narrative,
                book_id=1,
                existing_catalog={},
                client=client,
                no_cache=False,
            )
            assert len(result1) == 1
            assert client.messages.create.call_count == 1

            # Second call — should hit cache, not LLM
            result2 = extract_entities(
                narrative=narrative,
                book_id=1,
                existing_catalog={},
                client=client,
                no_cache=False,
            )
            assert len(result2) == 1
            # LLM should still only have been called once
            assert client.messages.create.call_count == 1

    def test_no_cache_flag_bypasses_cache(self, tmp_path: pytest.TempdirFixture) -> None:
        narrative = "You enter the city of Holmgard."
        llm_response = json.dumps(
            [{"kind": "location", "name": "Holmgard", "description": "A city", "aliases": []}]
        )
        client = _make_client(llm_response)

        with patch("app.parser.llm._CACHE_DIR", tmp_path):
            # First call with no_cache=True — LLM called, cache not written
            extract_entities(
                narrative=narrative,
                book_id=1,
                existing_catalog={},
                client=client,
                no_cache=True,
            )
            assert client.messages.create.call_count == 1

            # Second call with no_cache=True — LLM called again
            extract_entities(
                narrative=narrative,
                book_id=1,
                existing_catalog={},
                client=client,
                no_cache=True,
            )
            assert client.messages.create.call_count == 2

    def test_returns_correct_entity_fields(self) -> None:
        llm_response = json.dumps(
            [
                {
                    "kind": "organization",
                    "name": "Brotherhood of the Crystal Star",
                    "description": "A guild of magicians",
                    "aliases": ["the Brotherhood", "Crystal Star Guild"],
                }
            ]
        )
        client = _make_client(llm_response)
        result = extract_entities(
            narrative="The Brotherhood of the Crystal Star send a messenger.",
            book_id=2,
            existing_catalog={},
            client=client,
            no_cache=True,
        )
        assert len(result) == 1
        entity = result[0]
        assert entity["kind"] == "organization"
        assert entity["name"] == "Brotherhood of the Crystal Star"
        assert "magicians" in entity["description"]
        assert "the Brotherhood" in entity["aliases"]

    def test_valid_entity_kinds_accepted(self) -> None:
        """All four valid entity kinds should pass validation."""
        for kind in ("character", "location", "creature", "organization"):
            llm_response = json.dumps(
                [{"kind": kind, "name": "TestEntity", "description": "", "aliases": []}]
            )
            client = _make_client(llm_response)
            result = extract_entities(
                narrative="Test narrative.",
                book_id=1,
                existing_catalog={},
                client=client,
                no_cache=True,
            )
            assert len(result) == 1, f"Expected entity with kind={kind!r} to be accepted"

    def test_invalid_entity_kind_rejected(self) -> None:
        llm_response = json.dumps(
            [{"kind": "artifact", "name": "Sommerswerd", "description": "", "aliases": []}]
        )
        client = _make_client(llm_response)
        result = extract_entities(
            narrative="You find the Sommerswerd.",
            book_id=1,
            existing_catalog={},
            client=client,
            no_cache=True,
        )
        assert result == []


# ---------------------------------------------------------------------------
# infer_relationships
# ---------------------------------------------------------------------------


class TestInferRelationships:
    """Tests for infer_relationships()."""

    def test_fewer_than_two_entities_returns_empty(self) -> None:
        result = infer_relationships(
            entities=[{"kind": "character", "name": "Banedon", "description": "", "aliases": []}],
            scene_context={"scene_number": 1, "narrative": "You see Banedon."},
        )
        assert result == []

    def test_empty_entities_returns_empty(self) -> None:
        result = infer_relationships(
            entities=[],
            scene_context={"scene_number": 1, "narrative": ""},
        )
        assert result == []

    def test_relationships_returned_correctly(self) -> None:
        llm_response = json.dumps(
            [
                {
                    "source_name": "Banedon",
                    "target_name": "Holmgard",
                    "tags": ["spatial", "located_in"],
                }
            ]
        )
        client = _make_client(llm_response)
        entities = [
            {"kind": "character", "name": "Banedon", "description": "", "aliases": []},
            {"kind": "location", "name": "Holmgard", "description": "", "aliases": []},
        ]
        result = infer_relationships(
            entities=entities,
            scene_context={"scene_number": 1, "narrative": "Banedon is in Holmgard."},
            client=client,
            no_cache=True,
        )
        assert len(result) == 1
        assert result[0]["source_name"] == "Banedon"
        assert result[0]["target_name"] == "Holmgard"
        assert "spatial" in result[0]["tags"]
        assert "located_in" in result[0]["tags"]

    def test_malformed_json_returns_empty(self) -> None:
        client = _make_client("Banedon knows Holmgard well.")
        entities = [
            {"kind": "character", "name": "Banedon", "description": "", "aliases": []},
            {"kind": "location", "name": "Holmgard", "description": "", "aliases": []},
        ]
        result = infer_relationships(
            entities=entities,
            scene_context={"scene_number": 1, "narrative": "Banedon is in Holmgard."},
            client=client,
            no_cache=True,
        )
        assert result == []

    def test_llm_error_returns_empty(self) -> None:
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("network error")
        entities = [
            {"kind": "character", "name": "Banedon", "description": "", "aliases": []},
            {"kind": "location", "name": "Holmgard", "description": "", "aliases": []},
        ]
        result = infer_relationships(
            entities=entities,
            scene_context={"scene_number": 1, "narrative": "narrative"},
            client=client,
            no_cache=True,
        )
        assert result == []

    def test_missing_source_or_target_skipped(self) -> None:
        llm_response = json.dumps(
            [
                {"source_name": "", "target_name": "Holmgard", "tags": ["spatial"]},
                {"source_name": "Banedon", "target_name": "", "tags": ["spatial"]},
                {"source_name": "Banedon", "target_name": "Holmgard", "tags": ["spatial"]},
            ]
        )
        client = _make_client(llm_response)
        entities = [
            {"kind": "character", "name": "Banedon", "description": "", "aliases": []},
            {"kind": "location", "name": "Holmgard", "description": "", "aliases": []},
        ]
        result = infer_relationships(
            entities=entities,
            scene_context={"scene_number": 1, "narrative": "narrative"},
            client=client,
            no_cache=True,
        )
        assert len(result) == 1
        assert result[0]["source_name"] == "Banedon"

    def test_non_list_tags_defaults_to_empty(self) -> None:
        llm_response = json.dumps(
            [{"source_name": "Banedon", "target_name": "Holmgard", "tags": "spatial"}]
        )
        client = _make_client(llm_response)
        entities = [
            {"kind": "character", "name": "Banedon", "description": "", "aliases": []},
            {"kind": "location", "name": "Holmgard", "description": "", "aliases": []},
        ]
        result = infer_relationships(
            entities=entities,
            scene_context={"scene_number": 1, "narrative": "narrative"},
            client=client,
            no_cache=True,
        )
        assert result[0]["tags"] == []

    def test_cache_hit_skips_llm(self, tmp_path: pytest.TempdirFixture) -> None:
        llm_response = json.dumps(
            [{"source_name": "Banedon", "target_name": "Holmgard", "tags": ["spatial"]}]
        )
        client = _make_client(llm_response)
        entities = [
            {"kind": "character", "name": "Banedon", "description": "", "aliases": []},
            {"kind": "location", "name": "Holmgard", "description": "", "aliases": []},
        ]
        scene_context = {"scene_number": 1, "narrative": "Banedon is in Holmgard."}

        with patch("app.parser.llm._CACHE_DIR", tmp_path):
            infer_relationships(
                entities=entities,
                scene_context=scene_context,
                client=client,
                no_cache=False,
            )
            assert client.messages.create.call_count == 1

            infer_relationships(
                entities=entities,
                scene_context=scene_context,
                client=client,
                no_cache=False,
            )
            assert client.messages.create.call_count == 1  # still 1 — cache hit


# ---------------------------------------------------------------------------
# Game object creation helpers
# ---------------------------------------------------------------------------


class TestCreateItemGameObject:
    """Tests for create_item_game_object()."""

    def test_basic_item(self) -> None:
        result = create_item_game_object(
            {"item_name": "Sword", "item_type": "weapon", "quantity": 1}
        )
        assert result["kind"] == "item"
        assert result["name"] == "Sword"
        assert result["item_type"] == "weapon"
        assert result["quantity"] == 1

    def test_defaults_item_type_to_backpack(self) -> None:
        result = create_item_game_object({"item_name": "Potion"})
        assert result["item_type"] == "backpack"

    def test_defaults_quantity_to_one(self) -> None:
        result = create_item_game_object({"item_name": "Dagger", "item_type": "weapon"})
        assert result["quantity"] == 1

    def test_empty_item_name(self) -> None:
        result = create_item_game_object({})
        assert result["name"] == ""
        assert result["kind"] == "item"

    def test_description_included(self) -> None:
        result = create_item_game_object(
            {"item_name": "Helm", "item_type": "backpack", "description": "A sturdy helm"}
        )
        assert result["description"] == "A sturdy helm"

    def test_custom_quantity(self) -> None:
        result = create_item_game_object(
            {"item_name": "Gold Crowns", "item_type": "gold", "quantity": 15}
        )
        assert result["quantity"] == 15


class TestCreateFoeGameObject:
    """Tests for create_foe_game_object()."""

    def test_basic_foe(self) -> None:
        result = create_foe_game_object(
            {"enemy_name": "Gourgaz", "enemy_cs": 20, "enemy_end": 30, "ordinal": 1}
        )
        assert result["kind"] == "foe"
        assert result["name"] == "Gourgaz"
        assert result["combat_skill"] == 20
        assert result["endurance"] == 30
        assert result["ordinal"] == 1

    def test_defaults_combat_skill_and_endurance_to_zero(self) -> None:
        result = create_foe_game_object({"enemy_name": "Unknown"})
        assert result["combat_skill"] == 0
        assert result["endurance"] == 0

    def test_defaults_ordinal_to_one(self) -> None:
        result = create_foe_game_object({"enemy_name": "Guard", "enemy_cs": 14, "enemy_end": 20})
        assert result["ordinal"] == 1

    def test_empty_foe(self) -> None:
        result = create_foe_game_object({})
        assert result["kind"] == "foe"
        assert result["name"] == ""


class TestCreateSceneGameObject:
    """Tests for create_scene_game_object()."""

    def test_basic_scene(self) -> None:
        result = create_scene_game_object(
            {"number": 42, "html_id": "sect42", "narrative": "You enter a dark cave."}
        )
        assert result["kind"] == "scene"
        assert result["scene_number"] == 42
        assert result["html_id"] == "sect42"
        assert "dark cave" in result["narrative_snippet"]

    def test_narrative_snippet_truncated_to_200(self) -> None:
        long_narrative = "A" * 500
        result = create_scene_game_object({"number": 1, "html_id": "sect1", "narrative": long_narrative})
        assert len(result["narrative_snippet"]) == 200

    def test_no_narrative_gives_empty_snippet(self) -> None:
        result = create_scene_game_object({"number": 1, "html_id": "sect1"})
        assert result["narrative_snippet"] == ""

    def test_illustration_path_included(self) -> None:
        result = create_scene_game_object(
            {"number": 5, "html_id": "sect5", "illustration_path": "images/ill5.png"}
        )
        assert result["illustration_path"] == "images/ill5.png"

    def test_illustration_path_defaults_to_none(self) -> None:
        result = create_scene_game_object({"number": 1, "html_id": "sect1"})
        assert result["illustration_path"] is None

    def test_defaults_scene_number_to_zero(self) -> None:
        result = create_scene_game_object({})
        assert result["scene_number"] == 0
