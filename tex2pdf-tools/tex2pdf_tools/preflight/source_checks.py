"""Host-side runners for source (TeX) check plugins.

These iterate the discovered source-check plugins and aggregate the
:class:`~.models.TeXFileIssue` objects they return.  No heuristics live here;
with no plugin installed both runners return ``[]`` and preflight is unaffected.
The discovered callables are cached so discovery does not run per file (the
per-file runner is called in a tight loop over every TeX file).
"""

from __future__ import annotations

from collections.abc import Callable

from .models import TeXFileIssue
from .plugin_api import (
    SOURCE_FILE_CHECKS_GROUP,
    SOURCE_TREE_CHECKS_GROUP,
    load_callables,
    safe_call,
)

_file_checks: list[Callable] | None = None
_tree_checks: list[Callable] | None = None


def _file_check_callables() -> list[Callable]:
    global _file_checks  # noqa: PLW0603
    if _file_checks is None:
        _file_checks = load_callables(SOURCE_FILE_CHECKS_GROUP)
    return _file_checks


def _tree_check_callables() -> list[Callable]:
    global _tree_checks  # noqa: PLW0603
    if _tree_checks is None:
        _tree_checks = load_callables(SOURCE_TREE_CHECKS_GROUP)
    return _tree_checks


def reset_source_checks() -> None:
    """Test hook: drop the cached plugin callables so the next call re-discovers."""
    global _file_checks, _tree_checks  # noqa: PLW0603
    _file_checks = None
    _tree_checks = None


def run_source_file_checks(filename: str, data: bytes) -> list[TeXFileIssue]:
    """Run every per-file source-check plugin on one file's raw bytes."""
    issues: list[TeXFileIssue] = []
    for fn in _file_check_callables():
        res = safe_call(fn, filename, data, default=[], label=f"source-file-check:{getattr(fn, '__name__', '?')}")
        if res:
            issues.extend(res)
    return issues


def run_source_tree_checks(tree_files: list[tuple[str, bytes]]) -> list[TeXFileIssue]:
    """Run every whole-tree source-check plugin on a document tree."""
    issues: list[TeXFileIssue] = []
    for fn in _tree_check_callables():
        res = safe_call(fn, tree_files, default=[], label=f"source-tree-check:{getattr(fn, '__name__', '?')}")
        if res:
            issues.extend(res)
    return issues
