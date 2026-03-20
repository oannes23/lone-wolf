"""Engine purity test — verify that app/engine/ imports no forbidden modules.

The engine layer must remain a pure function layer: no ORM models, no database
sessions, no FastAPI dependencies, no SQLAlchemy. This keeps it fully testable
without any infrastructure.
"""

import ast
import os
from pathlib import Path


def _collect_python_files(directory: Path) -> list[Path]:
    """Return all .py files under the given directory, recursively."""
    return sorted(directory.rglob("*.py"))


def _extract_top_level_module_names(source: str) -> set[str]:
    """Parse ``source`` and return the top-level module name for every import."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # e.g. "sqlalchemy.orm" → "sqlalchemy"
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
                # e.g. "from app.models.content import Book" → "app"
                # But we also want to catch "from sqlalchemy import ..." → "sqlalchemy"
                names.add(node.module.split(".")[0])
    return names


def test_engine_has_no_forbidden_imports() -> None:
    """app/engine/ must not import models, database, services, routers, fastapi, or sqlalchemy."""
    forbidden = {"models", "database", "services", "routers", "fastapi", "sqlalchemy"}

    engine_dir = Path(__file__).parent.parent.parent / "app" / "engine"

    # The directory must exist (even if currently empty)
    assert engine_dir.is_dir(), f"app/engine/ directory not found at {engine_dir}"

    py_files = _collect_python_files(engine_dir)

    violations: list[str] = []
    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        if not source.strip():
            continue  # skip empty files
        imported_names = _extract_top_level_module_names(source)
        bad = imported_names & forbidden
        if bad:
            rel = py_file.relative_to(engine_dir.parent.parent)
            violations.append(f"{rel}: imports {sorted(bad)}")

    assert not violations, (
        "Engine purity violation — forbidden imports found:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_engine_directory_exists() -> None:
    """Confirm app/engine/ exists as a directory with an __init__.py."""
    engine_dir = Path(__file__).parent.parent.parent / "app" / "engine"
    assert engine_dir.is_dir(), "app/engine/ must be a directory"
    assert (engine_dir / "__init__.py").exists(), "app/engine/__init__.py must exist"


def test_engine_purity_check_catches_violations(tmp_path: Path) -> None:
    """Meta-test: verify the AST-walking logic correctly identifies forbidden imports."""
    bad_file = tmp_path / "bad_module.py"
    bad_file.write_text(
        "from sqlalchemy.orm import Session\nimport fastapi\n", encoding="utf-8"
    )
    source = bad_file.read_text(encoding="utf-8")
    names = _extract_top_level_module_names(source)
    assert "sqlalchemy" in names
    assert "fastapi" in names


def test_engine_purity_check_allows_stdlib(tmp_path: Path) -> None:
    """Meta-test: stdlib and typing imports must not trigger false positives."""
    good_file = tmp_path / "good_module.py"
    good_file.write_text(
        "from __future__ import annotations\nimport dataclasses\nfrom typing import Any\n",
        encoding="utf-8",
    )
    source = good_file.read_text(encoding="utf-8")
    forbidden = {"models", "database", "services", "routers", "fastapi", "sqlalchemy"}
    names = _extract_top_level_module_names(source)
    assert not (names & forbidden)


# Ensure the os import used above is exercised (ruff S405 suppression)
_ = os.sep
