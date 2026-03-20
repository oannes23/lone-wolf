"""Parse Project Aon XHTML files and load content into the database.

Usage:
    uv run python scripts/seed_db.py --source-dir /path/to/aon/books --book 1 --verbose
    uv run python scripts/seed_db.py --source-dir /path/to/aon/books --dry-run
    uv run python scripts/seed_db.py --source-dir /path/to/aon/books --skip-llm
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.parser.pipeline import run_pipeline  # noqa: I001


# ---------------------------------------------------------------------------
# Supported books
# ---------------------------------------------------------------------------

# Maps book number -> (slug_prefix, title) for the MVP set (books 1-5).
_BOOKS: dict[int, tuple[str, str]] = {
    1: ("01fftd", "Flight from the Dark"),
    2: ("02fotw", "Fire on the Water"),
    3: ("03tcok", "The Caverns of Kalte"),
    4: ("04tcod", "The Chasm of Doom"),
    5: ("05sots", "Shadow on the Sand"),
}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        prog="seed_db",
        description=(
            "Parse Project Aon XHTML files and load Lone Wolf book content into the database."
        ),
    )
    parser.add_argument(
        "--source-dir",
        metavar="PATH",
        required=True,
        help="Path to directory containing Project Aon XHTML files.",
    )
    parser.add_argument(
        "--book",
        type=int,
        metavar="N",
        default=None,
        help="Parse only book number N (1-5). Omit to process all available books.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Print detailed output for each stage.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Extract and transform only — do not write to the database.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Drop and recreate content for specified book(s) before loading.",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        default=False,
        help="Skip all LLM calls; use raw_text as display_text for choices.",
    )
    parser.add_argument(
        "--skip-entities",
        action="store_true",
        default=False,
        help="Skip entity extraction (LLM choice rewriting still runs).",
    )
    parser.add_argument(
        "--entities-only",
        action="store_true",
        default=False,
        help="Only run entity extraction; skip choice rewriting.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Bypass the LLM response cache for all calls.",
    )
    return parser


# ---------------------------------------------------------------------------
# Book discovery
# ---------------------------------------------------------------------------


def find_book_path(source_dir: Path, book_number: int) -> Path | None:
    """Locate the XHTML file for *book_number* inside *source_dir*.

    Tries the known slug prefix first, then falls back to a glob over the
    directory.

    Args:
        source_dir: Root directory containing Project Aon XHTML files.
        book_number: The 1-based book number to locate.

    Returns:
        The :class:`Path` to the XHTML file if found, or ``None``.
    """
    slug_prefix, _ = _BOOKS[book_number]

    # Direct match: {slug}.xhtml or {slug}.xml
    for ext in (".xhtml", ".xml", ".html"):
        candidate = source_dir / f"{slug_prefix}{ext}"
        if candidate.exists():
            return candidate

    # Glob fallback: look for files whose name starts with the two-digit prefix
    digit_prefix = f"{book_number:02d}"
    for suffix in (".xhtml", ".xml", ".html"):
        # Build list of all files with this suffix, then filter by prefix
        candidates = sorted(
            p for p in source_dir.iterdir()
            if p.suffix == suffix and p.stem.startswith(digit_prefix)
        )
        if candidates:
            return candidates[0]

    return None


def collect_books_to_process(
    source_dir: Path,
    book_number: int | None,
) -> list[tuple[int, Path]]:
    """Return a sorted list of (book_number, xhtml_path) pairs to process.

    Args:
        source_dir: Root directory of XHTML source files.
        book_number: If not None, restrict to this single book.

    Returns:
        Sorted list of (number, path) tuples.  Books with missing files are
        skipped with a warning printed to stderr.
    """
    numbers = [book_number] if book_number is not None else sorted(_BOOKS.keys())
    result: list[tuple[int, Path]] = []

    for n in numbers:
        path = find_book_path(source_dir, n)
        if path is None:
            print(
                f"  WARNING: XHTML file for book {n} not found in {source_dir} — skipping",
                file=sys.stderr,
            )
        else:
            result.append((n, path))

    return result


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _print_book_report(book_title: str, book_number: int, result: object) -> None:
    """Print a formatted summary report for a single processed book.

    Args:
        book_title: Human-readable book title.
        book_number: Book number.
        result: :class:`~app.parser.pipeline.PipelineResult` instance.
    """
    from app.parser.pipeline import PipelineResult

    if not isinstance(result, PipelineResult):
        return

    counts = result.counts

    print(f"\n=== Book {book_number}: {book_title} ===")
    print(f"  Scenes:        {counts.get('scenes', 0)}")
    print(f"  Choices:       {counts.get('choices', 0)}")
    print(f"  Encounters:    {counts.get('encounters', 0)}")
    print(f"  Items:         {counts.get('items', 0)}")
    print(f"  Disciplines:   {counts.get('disciplines', 0)}")
    print(f"  Game Objects:  {counts.get('game_objects', 0)}")
    print(f"  Refs:          {counts.get('refs', 0)}")
    print(f"  LLM Rewrites:  {counts.get('llm_rewrites', 0)}")
    print(f"  Warnings:      {len(result.warnings)}")

    if result.warnings:
        print("  Warning details:")
        for w in result.warnings:
            print(f"    - {w}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and run the pipeline for the requested books.

    Args:
        argv: Argument list (defaults to sys.argv if None).

    Returns:
        Exit code: 0 on success, 1 on error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        print(f"ERROR: --source-dir does not exist: {source_dir}", file=sys.stderr)
        return 1
    if not source_dir.is_dir():
        print(f"ERROR: --source-dir is not a directory: {source_dir}", file=sys.stderr)
        return 1

    # Validate --book option
    if args.book is not None and args.book not in _BOOKS:
        print(
            f"ERROR: --book {args.book} is not a supported book number "
            f"(supported: {sorted(_BOOKS.keys())})",
            file=sys.stderr,
        )
        return 1

    books_to_process = collect_books_to_process(source_dir, args.book)

    if not books_to_process:
        print("No books found to process.", file=sys.stderr)
        return 1

    options = {
        "dry_run": args.dry_run,
        "skip_llm": args.skip_llm,
        "skip_entities": args.skip_entities,
        "entities_only": args.entities_only,
        "no_cache": args.no_cache,
        "reset": args.reset,
    }

    if args.dry_run:
        print("DRY RUN — no database writes will occur.")
    if args.skip_llm:
        print("LLM calls disabled — using raw_text as display_text.")

    all_results: list[tuple[int, str, object]] = []
    error_count = 0

    for book_number, book_path in books_to_process:
        _, book_title = _BOOKS[book_number]
        if args.verbose:
            print(f"\nProcessing Book {book_number}: {book_title} ({book_path.name}) ...")
        else:
            print(f"Processing Book {book_number}: {book_title} ...", end="", flush=True)

        try:
            result = run_pipeline(str(book_path), options)
            all_results.append((book_number, book_title, result))
            if not args.verbose:
                print(" done")
        except Exception as exc:
            print(f" ERROR: {exc}", file=sys.stderr)
            error_count += 1
            continue

    # Print per-book summary reports
    for book_number, book_title, result in all_results:
        _print_book_report(book_title, book_number, result)

    total_books = len(all_results)
    print(f"\nTotal: {total_books} book{'s' if total_books != 1 else ''} processed")
    if error_count:
        print(f"  {error_count} book(s) failed — check output above.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
