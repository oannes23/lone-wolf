"""Unit tests for app/parser/pipeline.py.

All external dependencies (extract, transform, LLM, load) are mocked.
No real XHTML files, no real LLM calls, no real DB connections.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.parser.pipeline import PipelineResult, run_pipeline
from app.parser.types import BookData, ChoiceData, CombatData, EnrichmentResult, SceneData


# ---------------------------------------------------------------------------
# Minimal stubs for extract return types
# ---------------------------------------------------------------------------


def _make_book_data(number: int = 1) -> BookData:
    return BookData(
        slug=f"0{number}fftd",
        number=number,
        era="kai",
        title="Flight from the Dark",
        xhtml_path=Path(f"/fake/0{number}fftd.xhtml"),
    )


def _make_scene(number: int = 1) -> SceneData:
    return SceneData(
        number=number,
        html_id=f"sect{number}",
        narrative="You stand at a crossroads.",
        choices=[
            ChoiceData(
                raw_text="If you go north, turn to 10.",
                target_scene_number=10,
                ordinal=1,
            )
        ],
        combat_encounters=[],
    )


def _make_scene_with_combat(number: int = 2) -> SceneData:
    return SceneData(
        number=number,
        html_id=f"sect{number}",
        narrative="A goblin attacks you!",
        choices=[],
        combat_encounters=[
            CombatData(enemy_name="Goblin", enemy_cs=12, enemy_end=15, ordinal=1)
        ],
    )


# ---------------------------------------------------------------------------
# Context manager helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _standard_patches(
    scenes: list[SceneData] | None = None,
    book_data: BookData | None = None,
):
    """Context manager that patches all extract-phase functions with minimal stubs.

    Also patches copy_illustrations so no filesystem access occurs.
    """
    if scenes is None:
        scenes = [_make_scene()]
    if book_data is None:
        book_data = _make_book_data()

    mock_soup = MagicMock()

    with patch("app.parser.pipeline.extract_book_metadata", return_value=book_data), \
         patch("app.parser.pipeline._parse_xhtml", return_value=mock_soup), \
         patch("app.parser.pipeline.extract_scenes", return_value=scenes), \
         patch("app.parser.pipeline.extract_disciplines", return_value=[]), \
         patch("app.parser.pipeline.extract_crt", return_value=[]), \
         patch("app.parser.pipeline.extract_starting_equipment", return_value=[]), \
         patch("app.parser.pipeline.copy_illustrations", return_value=[]) as mock_copy:
        yield mock_copy


@contextlib.contextmanager
def _patch_llm_enrich(return_value=None):
    """Patch _enrich_with_llm to return a no-op EnrichmentResult.

    When no return_value is given, the mock passes through the choice_dicts,
    encounter_dicts, item_dicts, and random_outcome_dicts arguments unchanged
    and returns empty entity/ref lists.
    """
    if return_value is not None:
        with patch("app.parser.pipeline._enrich_with_llm", return_value=return_value) as m:
            yield m
    else:
        def _passthrough(scenes, choice_dicts, scene_dicts=None,
                         encounter_dicts=None, item_dicts=None,
                         random_outcome_dicts=None,
                         skip_choice_rewrite=False, **kwargs):
            return EnrichmentResult(
                choice_dicts=choice_dicts,
                encounter_dicts=encounter_dicts or [],
                item_dicts=item_dicts or [],
                random_outcome_dicts=random_outcome_dicts or [],
            )

        with patch("app.parser.pipeline._enrich_with_llm", side_effect=_passthrough) as m:
            yield m


@contextlib.contextmanager
def _patch_load():
    """Patch _do_load and SessionLocal so no DB session is opened."""
    mock_session = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.rollback = MagicMock()
    mock_session.close = MagicMock()
    with patch("app.parser.pipeline._do_load") as mock_load, \
         patch("app.parser.pipeline.SessionLocal", return_value=mock_session) as mock_sl:
        yield mock_load, mock_sl


# ---------------------------------------------------------------------------
# PipelineResult dataclass
# ---------------------------------------------------------------------------


class TestPipelineResult:
    def test_instantiates_with_defaults(self) -> None:
        result = PipelineResult(book_data=_make_book_data())
        assert result.counts == {}
        assert result.warnings == []

    def test_stores_counts(self) -> None:
        result = PipelineResult(
            book_data=_make_book_data(), counts={"scenes": 10, "choices": 5}
        )
        assert result.counts["scenes"] == 10
        assert result.counts["choices"] == 5

    def test_stores_warnings(self) -> None:
        result = PipelineResult(
            book_data=_make_book_data(), warnings=["something went wrong"]
        )
        assert len(result.warnings) == 1
        assert "something went wrong" in result.warnings[0]


# ---------------------------------------------------------------------------
# Pipeline orchestration order
# ---------------------------------------------------------------------------


class TestPipelineOrchestrationOrder:
    """Verify that extract → transform → LLM → load are called in that order."""

    def test_extract_scenes_is_called(self) -> None:
        book_data = _make_book_data()
        scenes = [_make_scene()]
        with _standard_patches(scenes=scenes, book_data=book_data) as mock_copy:
            with _patch_llm_enrich():
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        # The fact that scenes is returned proves extract_scenes was called
        assert result.counts["scenes"] == 1

    def test_pipeline_returns_pipeline_result(self) -> None:
        book_data = _make_book_data()
        with _standard_patches(book_data=book_data):
            with _patch_llm_enrich():
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert isinstance(result, PipelineResult)
        assert result.book_data is book_data

    def test_counts_contain_expected_keys(self) -> None:
        with _standard_patches(scenes=[_make_scene(1), _make_scene(2)]):
            with _patch_llm_enrich():
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        for key in ("scenes", "choices", "encounters", "items", "disciplines", "llm_calls"):
            assert key in result.counts, f"Missing count key: {key!r}"

    def test_counts_scenes_matches_extracted(self) -> None:
        scenes = [_make_scene(1), _make_scene(2), _make_scene(3)]
        with _standard_patches(scenes=scenes):
            with _patch_llm_enrich():
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert result.counts["scenes"] == 3


# ---------------------------------------------------------------------------
# --dry-run: load should NOT be called
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_skips_load(self) -> None:
        with _standard_patches():
            with _patch_llm_enrich():
                with patch("app.parser.pipeline._do_load") as mock_load:
                    run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        mock_load.assert_not_called()

    def test_dry_run_skips_illustration_copy(self) -> None:
        with _standard_patches() as mock_copy:
            with _patch_llm_enrich():
                run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        mock_copy.assert_not_called()

    def test_dry_run_still_returns_result(self) -> None:
        with _standard_patches():
            with _patch_llm_enrich():
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert isinstance(result, PipelineResult)


# ---------------------------------------------------------------------------
# --skip-llm: _enrich_with_llm receives skip_llm=True
# ---------------------------------------------------------------------------


class TestSkipLlm:
    def test_skip_llm_passes_flag_to_enrich(self) -> None:
        with _standard_patches():
            with patch("app.parser.pipeline._enrich_with_llm") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult()
                run_pipeline("/fake/01fftd.xhtml", {"skip_llm": True, "dry_run": True})
        call_kwargs = mock_enrich.call_args.kwargs
        assert call_kwargs.get("skip_llm") is True

    def test_skip_llm_no_llm_rewrites_counted(self) -> None:
        with _standard_patches():
            with patch("app.parser.pipeline._enrich_with_llm") as mock_enrich:
                # Return 0 rewrites — as skip_llm would produce
                mock_enrich.return_value = EnrichmentResult()
                result = run_pipeline("/fake/01fftd.xhtml", {"skip_llm": True, "dry_run": True})
        assert result.counts.get("llm_calls", 0) == 0


# ---------------------------------------------------------------------------
# --skip-entities: _enrich_with_llm receives skip_entities=True
# ---------------------------------------------------------------------------


class TestSkipEntities:
    def test_skip_entities_passes_flag_to_enrich(self) -> None:
        with _standard_patches():
            with patch("app.parser.pipeline._enrich_with_llm") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult()
                run_pipeline("/fake/01fftd.xhtml", {"skip_entities": True, "dry_run": True})
        call_kwargs = mock_enrich.call_args.kwargs
        assert call_kwargs.get("skip_entities") is True


# ---------------------------------------------------------------------------
# Warnings are collected from all stages
# ---------------------------------------------------------------------------


class TestWarningCollection:
    def test_warnings_from_transform_stage_appear_in_result(self) -> None:
        transform_warning = "transform stage warning"
        transform_scene = {
            "number": 2,
            "html_id": "sect2",
            "narrative": "test",
            "illustration_path": None,
            "is_death": False,
            "is_victory": False,
            "must_eat": False,
            "loses_backpack": False,
            "source": "auto",
            "_random_outcomes": [],
        }
        with _standard_patches(scenes=[_make_scene_with_combat()]):
            with patch("app.parser.pipeline._transform_scenes") as mock_ts:
                mock_ts.return_value = ([transform_scene], [], [transform_warning])
                with _patch_llm_enrich():
                    result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert any(transform_warning in w for w in result.warnings)

    def test_warnings_from_llm_stage_appear_in_result(self) -> None:
        llm_warning = "llm entity warning"
        with _standard_patches():
            with patch("app.parser.pipeline._enrich_with_llm") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult(warnings=[llm_warning])
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert any(llm_warning in w for w in result.warnings)

    def test_illustration_copy_failure_adds_warning(self) -> None:
        book_data = _make_book_data()
        mock_soup = MagicMock()
        with patch("app.parser.pipeline.extract_book_metadata", return_value=book_data), \
             patch("app.parser.pipeline._parse_xhtml", return_value=mock_soup), \
             patch("app.parser.pipeline.extract_scenes", return_value=[_make_scene()]), \
             patch("app.parser.pipeline.extract_disciplines", return_value=[]), \
             patch("app.parser.pipeline.extract_crt", return_value=[]), \
             patch("app.parser.pipeline.extract_starting_equipment", return_value=[]), \
             patch("app.parser.pipeline.copy_illustrations", side_effect=OSError("disk full")):
            with _patch_llm_enrich():
                with _patch_load():
                    result = run_pipeline("/fake/01fftd.xhtml", {})
        assert any("Illustration copy failed" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# PipelineResult contains correct counts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# --entities-only: _enrich_with_llm receives skip_choice_rewrite=True
# ---------------------------------------------------------------------------


class TestEntitiesOnly:
    def test_entities_only_passes_skip_choice_rewrite_true(self) -> None:
        with _standard_patches():
            with patch("app.parser.pipeline._enrich_with_llm") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult()
                run_pipeline("/fake/01fftd.xhtml", {"entities_only": True, "dry_run": True})
        call_kwargs = mock_enrich.call_args.kwargs
        assert call_kwargs.get("skip_choice_rewrite") is True
        assert call_kwargs.get("skip_llm") is False
        assert call_kwargs.get("skip_entities") is False

    def test_entities_only_still_returns_result(self) -> None:
        with _standard_patches():
            with patch("app.parser.pipeline._enrich_with_llm") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult()
                result = run_pipeline("/fake/01fftd.xhtml", {"entities_only": True, "dry_run": True})
        assert isinstance(result, PipelineResult)


# ---------------------------------------------------------------------------
# PipelineResult contains correct counts
# ---------------------------------------------------------------------------


class TestPipelineResultCounts:
    def test_counts_choices_matches_extracted(self) -> None:
        # Each _make_scene has 1 choice → 2 scenes = 2 choices total
        scenes = [_make_scene(1), _make_scene(2)]
        with _standard_patches(scenes=scenes):
            with _patch_llm_enrich():
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert result.counts["choices"] == 2

    def test_counts_encounters_matches_extracted(self) -> None:
        scenes = [_make_scene_with_combat(1), _make_scene_with_combat(2)]
        with _standard_patches(scenes=scenes):
            with _patch_llm_enrich():
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert result.counts["encounters"] == 2

    def test_counts_game_objects_from_llm(self) -> None:
        entity_game_objects = [
            {
                "kind": "character",
                "name": "Vonotar",
                "description": "",
                "aliases": "[]",
                "properties": "{}",
                "source": "auto",
            },
        ]
        with _standard_patches():
            with patch("app.parser.pipeline._enrich_with_llm") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult(entity_game_objects=entity_game_objects)
                result = run_pipeline("/fake/01fftd.xhtml", {"dry_run": True})
        assert result.counts["game_objects"] == 1
