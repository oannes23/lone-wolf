"""Unit tests for scripts/seed_db.py CLI.

Tests argument parsing and basic CLI behaviour without running any actual
pipeline (no XHTML files, no DB, no LLM calls).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make sure the scripts directory is importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from seed_db import build_parser, collect_books_to_process, find_book_path, main


# ---------------------------------------------------------------------------
# Argument parser — option existence
# ---------------------------------------------------------------------------


class TestArgParserOptions:
    """Verify that build_parser() exposes all documented CLI options."""

    def _parse(self, args: list[str]) -> object:
        return build_parser().parse_args(args)

    def test_source_dir_is_required(self) -> None:
        with pytest.raises(SystemExit):
            self._parse([])

    def test_source_dir_stores_path_string(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.source_dir == str(tmp_path)

    def test_book_defaults_to_none(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.book is None

    def test_book_stores_integer(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--book", "1"])
        assert ns.book == 1

    def test_verbose_defaults_false(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.verbose is False

    def test_verbose_flag_sets_true(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--verbose"])
        assert ns.verbose is True

    def test_dry_run_defaults_false(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.dry_run is False

    def test_dry_run_flag_sets_true(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--dry-run"])
        assert ns.dry_run is True

    def test_reset_defaults_false(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.reset is False

    def test_reset_flag_sets_true(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--reset"])
        assert ns.reset is True

    def test_skip_llm_defaults_false(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.skip_llm is False

    def test_skip_llm_flag_sets_true(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--skip-llm"])
        assert ns.skip_llm is True

    def test_skip_entities_defaults_false(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.skip_entities is False

    def test_skip_entities_flag_sets_true(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--skip-entities"])
        assert ns.skip_entities is True

    def test_entities_only_defaults_false(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.entities_only is False

    def test_entities_only_flag_sets_true(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--entities-only"])
        assert ns.entities_only is True

    def test_no_cache_defaults_false(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path)])
        assert ns.no_cache is False

    def test_no_cache_flag_sets_true(self, tmp_path: Path) -> None:
        ns = self._parse(["--source-dir", str(tmp_path), "--no-cache"])
        assert ns.no_cache is True

    def test_all_flags_together(self, tmp_path: Path) -> None:
        ns = self._parse([
            "--source-dir", str(tmp_path),
            "--book", "2",
            "--verbose",
            "--dry-run",
            "--reset",
            "--skip-llm",
            "--skip-entities",
            "--entities-only",
            "--no-cache",
        ])
        assert ns.book == 2
        assert ns.verbose is True
        assert ns.dry_run is True
        assert ns.reset is True
        assert ns.skip_llm is True
        assert ns.skip_entities is True
        assert ns.entities_only is True
        assert ns.no_cache is True


# ---------------------------------------------------------------------------
# --help output (smoke test)
# ---------------------------------------------------------------------------


class TestHelpOutput:
    def test_help_exits_with_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            build_parser().parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_help_mentions_source_dir(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--help"])
        out = capsys.readouterr().out
        assert "--source-dir" in out

    def test_help_mentions_skip_llm(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--help"])
        out = capsys.readouterr().out
        assert "--skip-llm" in out

    def test_help_mentions_dry_run(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--help"])
        out = capsys.readouterr().out
        assert "--dry-run" in out

    def test_help_mentions_entities_only(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--help"])
        out = capsys.readouterr().out
        assert "--entities-only" in out


# ---------------------------------------------------------------------------
# find_book_path
# ---------------------------------------------------------------------------


class TestFindBookPath:
    def test_finds_xhtml_file_by_slug(self, tmp_path: Path) -> None:
        xhtml_file = tmp_path / "01fftd.xhtml"
        xhtml_file.touch()
        result = find_book_path(tmp_path, 1)
        assert result == xhtml_file

    def test_finds_xml_file_as_fallback(self, tmp_path: Path) -> None:
        xml_file = tmp_path / "01fftd.xml"
        xml_file.touch()
        result = find_book_path(tmp_path, 1)
        assert result == xml_file

    def test_returns_none_when_no_file(self, tmp_path: Path) -> None:
        result = find_book_path(tmp_path, 1)
        assert result is None

    def test_glob_fallback_with_non_standard_name(self, tmp_path: Path) -> None:
        xhtml_file = tmp_path / "01lonewolf.xhtml"
        xhtml_file.touch()
        result = find_book_path(tmp_path, 1)
        assert result == xhtml_file


# ---------------------------------------------------------------------------
# collect_books_to_process
# ---------------------------------------------------------------------------


class TestCollectBooksToProcess:
    def test_specific_book_returns_single_entry(self, tmp_path: Path) -> None:
        xhtml_file = tmp_path / "01fftd.xhtml"
        xhtml_file.touch()
        result = collect_books_to_process(tmp_path, book_number=1)
        assert len(result) == 1
        assert result[0][0] == 1
        assert result[0][1] == xhtml_file

    def test_missing_book_skips_with_warning(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        # Book 1 file is not present
        result = collect_books_to_process(tmp_path, book_number=1)
        assert result == []
        err = capsys.readouterr().err
        assert "not found" in err.lower() or "WARNING" in err

    def test_all_books_returns_sorted_list(self, tmp_path: Path) -> None:
        # Create files for books 1, 2, 3
        for slug in ("01fftd", "02fotw", "03tcok"):
            (tmp_path / f"{slug}.xhtml").touch()
        result = collect_books_to_process(tmp_path, book_number=None)
        numbers = [n for n, _ in result]
        assert numbers == sorted(numbers)
        assert 1 in numbers
        assert 2 in numbers
        assert 3 in numbers

    def test_missing_books_omitted_from_all(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        # Only book 2 is present
        (tmp_path / "02fotw.xhtml").touch()
        result = collect_books_to_process(tmp_path, book_number=None)
        numbers = [n for n, _ in result]
        assert 2 in numbers
        assert 1 not in numbers


# ---------------------------------------------------------------------------
# main() function integration
# ---------------------------------------------------------------------------


class TestMainFunction:
    def test_returns_1_when_source_dir_missing(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"
        exit_code = main(["--source-dir", str(nonexistent)])
        assert exit_code == 1

    def test_returns_1_when_no_books_found(self, tmp_path: Path) -> None:
        # source_dir exists but has no XHTML files
        exit_code = main(["--source-dir", str(tmp_path), "--book", "1"])
        assert exit_code == 1

    def test_returns_1_for_invalid_book_number(self, tmp_path: Path) -> None:
        exit_code = main(["--source-dir", str(tmp_path), "--book", "99"])
        assert exit_code == 1

    def test_returns_0_on_successful_run(self, tmp_path: Path) -> None:
        xhtml_file = tmp_path / "01fftd.xhtml"
        xhtml_file.write_text("<html><title>Flight from the Dark</title></html>", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.book_data = MagicMock()
        mock_result.counts = {
            "scenes": 10,
            "choices": 15,
            "encounters": 3,
            "items": 5,
            "disciplines": 10,
            "game_objects": 0,
            "refs": 0,
            "llm_rewrites": 0,
            "random_outcomes": 0,
            "starting_equipment": 0,
        }
        mock_result.warnings = []

        with patch("seed_db.run_pipeline", return_value=mock_result):
            exit_code = main([
                "--source-dir", str(tmp_path),
                "--book", "1",
                "--dry-run",
                "--skip-llm",
            ])

        assert exit_code == 0

    def test_options_passed_to_pipeline(self, tmp_path: Path) -> None:
        """Verify that CLI flags are correctly forwarded into the options dict."""
        xhtml_file = tmp_path / "01fftd.xhtml"
        xhtml_file.write_text("<html><title>Test</title></html>", encoding="utf-8")

        mock_result = MagicMock()
        mock_result.book_data = MagicMock()
        mock_result.counts = {}
        mock_result.warnings = []

        captured_options: list[dict] = []

        def capture_pipeline(path: str, options: dict) -> object:
            captured_options.append(dict(options))
            return mock_result

        with patch("seed_db.run_pipeline", side_effect=capture_pipeline):
            main([
                "--source-dir", str(tmp_path),
                "--book", "1",
                "--dry-run",
                "--skip-llm",
                "--no-cache",
            ])

        assert len(captured_options) == 1
        opts = captured_options[0]
        assert opts["dry_run"] is True
        assert opts["skip_llm"] is True
        assert opts["no_cache"] is True
