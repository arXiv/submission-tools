"""Plugin discovery for preflight QA checks.

This module is the *host* side of a small plugin system.  Check implementations
are discovered at runtime via Python entry points (:mod:`importlib.metadata`).
**No check heuristics live in the public package** -- only the contract
(:class:`CheckSpec`), the discovery/merge helpers, and a fail-open invocation
wrapper.  When no plugin is installed every entry-point group resolves empty and
the corresponding checks simply do not run.

Entry-point groups (the public contract with plugins):

  * ``tex2pdf_tools.preflight.file_checks``        -> ``provider() -> CheckSpec``
  * ``tex2pdf_tools.preflight.pdf_checks``         -> ``provider() -> CheckSpec``
  * ``tex2pdf_tools.preflight.source_file_checks`` -> ``fn(filename, data) -> list[TeXFileIssue]``
  * ``tex2pdf_tools.preflight.source_tree_checks`` -> ``fn(tree_files) -> list[TeXFileIssue]``

File/PDF check entry points resolve to a zero-argument *provider* returning a
:class:`CheckSpec`; using a provider (rather than the bare function) lets the
plugin decide its severity lazily -- e.g. from its own feature flags -- at load
time.  Source-check entry points resolve directly to the detection callable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any

from .models import CheckSeverity, logger

# Entry-point group names.
FILE_CHECKS_GROUP = "tex2pdf_tools.preflight.file_checks"
PDF_CHECKS_GROUP = "tex2pdf_tools.preflight.pdf_checks"
SOURCE_FILE_CHECKS_GROUP = "tex2pdf_tools.preflight.source_file_checks"
SOURCE_TREE_CHECKS_GROUP = "tex2pdf_tools.preflight.source_tree_checks"


@dataclass
class CheckSpec:
    """What a file/pdf check plugin provides: a name, the callable, and a severity."""

    name: str
    func: Callable[..., Any]
    severity: CheckSeverity = CheckSeverity.error


def _load_entry_points(group: str) -> list:
    try:
        return list(entry_points(group=group))
    except Exception as e:  # pragma: no cover - importlib edge cases
        logger.warning("Could not enumerate entry points for group %s: %s", group, e)
        return []


def merge_check_specs(group: str, registry: dict[str, tuple[Callable, CheckSeverity]]) -> None:
    """Discover check plugins in ``group`` and merge them into ``registry`` in place.

    Built-ins win: a discovered check whose name is already present is logged and
    skipped -- it never overwrites a built-in or an earlier plugin.  Both
    discovery and provider invocation are fail-open: a broken plugin is logged
    and skipped, never raised.
    """
    for ep in _load_entry_points(group):
        try:
            provider = ep.load()
            spec = provider()
        except Exception as e:
            logger.warning("Failed to load check plugin %r from group %s: %s", ep.name, group, e)
            continue
        if not isinstance(spec, CheckSpec):
            logger.warning("Check plugin %r did not return a CheckSpec; skipping", ep.name)
            continue
        if spec.name in registry:
            logger.warning("Duplicate check name %r from plugin %r; skipping (built-ins win)", spec.name, ep.name)
            continue
        registry[spec.name] = (spec.func, spec.severity)


def load_callables(group: str) -> list[Callable]:
    """Discover source-check plugins in ``group`` (each entry point -> a callable).

    Fail-open: a plugin that cannot be loaded is logged and skipped.
    """
    out: list[Callable] = []
    for ep in _load_entry_points(group):
        try:
            out.append(ep.load())
        except Exception as e:
            logger.warning("Failed to load source-check plugin %r from group %s: %s", ep.name, group, e)
    return out


def safe_call(func: Callable, *args: Any, default: Any = None, label: str = "") -> Any:
    """Invoke a plugin callable, fail-open: log and return ``default`` on any error."""
    try:
        return func(*args)
    except Exception as e:
        name = label or getattr(func, "__name__", "") or repr(func)
        logger.warning("Check plugin %s raised during invocation: %s", name, e)
        return default
