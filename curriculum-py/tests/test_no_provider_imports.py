"""Verify that core package modules do not import LLM provider SDKs.

This test suite exists to catch accidental hard-dependencies being introduced
into the provider-agnostic modules. It works by inspecting the AST of each
source file rather than importing the module, so it catches both direct imports
and inline deferred imports (e.g. ``import openai`` inside a function body).

The only modules where provider imports are permitted are those under
``adapters/``.
"""

from __future__ import annotations

import ast
from pathlib import Path

# All provider SDK top-level module names that must not appear in core code.
FORBIDDEN: frozenset[str] = frozenset({
    "openai",
    "anthropic",
    "google.generativeai",
    "langchain",
    "llama_index",
    "crewai",
})

_PKG_ROOT = Path(__file__).parent.parent
_CORE_MODULES = {
    "core": _PKG_ROOT / "src" / "cv_skill" / "core.py",
    "schema": _PKG_ROOT / "src" / "cv_skill" / "schema.py",
    "ats": _PKG_ROOT / "src" / "cv_skill" / "ats.py",
    "errors": _PKG_ROOT / "src" / "cv_skill" / "errors.py",
    "cli": _PKG_ROOT / "src" / "cv_skill" / "cli.py",
}


def _collect_imports(source_path: Path) -> set[str]:
    """Parse ``source_path`` and collect all module names that are imported.

    Handles both:
    - ``import foo`` / ``import foo.bar``
    - ``from foo import bar`` / ``from foo.bar import baz``

    Args:
        source_path: Path to a Python source file.

    Returns:
        Set of top-level module names encountered in any import statement.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # Only keep the top-level component, e.g. "google" from "google.cloud".
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
    return found


def _assert_no_forbidden_imports(module_label: str, source_path: Path) -> None:
    """Assert that ``source_path`` contains no forbidden provider imports.

    Args:
        module_label: Human-readable label for error messages.
        source_path: Path to the Python source file to inspect.
    """
    assert source_path.exists(), f"{module_label}: source file not found at {source_path}"
    imports = _collect_imports(source_path)
    violations = imports & FORBIDDEN
    assert not violations, (
        f"{module_label} imports forbidden provider SDK(s): {violations}. "
        f"All imports found: {sorted(imports)}"
    )


# ── Per-module test functions (picked up by pytest individually) ──────────────


def test_core_has_no_provider_imports() -> None:
    """cv_skill.core must not import any LLM provider SDK."""
    _assert_no_forbidden_imports("core", _CORE_MODULES["core"])


def test_schema_has_no_provider_imports() -> None:
    """cv_skill.schema must not import any LLM provider SDK."""
    _assert_no_forbidden_imports("schema", _CORE_MODULES["schema"])


def test_ats_has_no_provider_imports() -> None:
    """cv_skill.ats must not import any LLM provider SDK."""
    _assert_no_forbidden_imports("ats", _CORE_MODULES["ats"])


def test_errors_has_no_provider_imports() -> None:
    """cv_skill.errors must not import any LLM provider SDK."""
    _assert_no_forbidden_imports("errors", _CORE_MODULES["errors"])


def test_cli_has_no_provider_imports() -> None:
    """cv_skill.cli must not directly import any LLM provider SDK.

    The CLI lazily loads adapters via importlib; it must not import provider
    SDKs at module level.
    """
    _assert_no_forbidden_imports("cli", _CORE_MODULES["cli"])


def test_all_core_files_exist() -> None:
    """All core module files must be present."""
    for label, path in _CORE_MODULES.items():
        assert path.exists(), f"Core module '{label}' not found at {path}"
