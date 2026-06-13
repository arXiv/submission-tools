"""Tests for the check-plugin host mechanism.

These exercise discovery/merge, the built-ins-win collision policy, fail-open
behaviour, and the source-check + suspicious-status wiring -- all *without* a
real installed plugin, by injecting fakes through the documented test hooks
(``reset_checks`` / the cached callable lists) and by monkeypatching the
entry-point enumeration.  The public package ships no heuristics, so with no
plugin installed every registry is empty and the checks no-op.
"""

import pytest

import tex2pdf_tools.preflight as preflight
from tex2pdf_tools.preflight import file_checks, pdf_checks, plugin_api, source_checks
from tex2pdf_tools.preflight.models import (
    CheckResult,
    CheckSeverity,
    IssueType,
    PreflightStatusValues,
    TeXFileIssue,
)
from tex2pdf_tools.preflight.plugin_api import CheckSpec


@pytest.fixture(autouse=True)
def _reset_registries():
    """Reset cached registries before and after each test for isolation."""
    pdf_checks.reset_checks()
    file_checks.reset_checks()
    source_checks.reset_source_checks()
    yield
    pdf_checks.reset_checks()
    file_checks.reset_checks()
    source_checks.reset_source_checks()


class _FakeEP:
    """Minimal stand-in for importlib.metadata.EntryPoint."""

    def __init__(self, name, obj):
        self.name = name
        self._obj = obj

    def load(self):
        return self._obj


def _ok_check(res, severity):
    return CheckResult(check_passed=True, info="", long_info="", severity=severity, issues=[])


# --------------------------------------------------------------------------- #
# No plugin installed -> empty registries, everything no-ops
# --------------------------------------------------------------------------- #


def test_builtin_only_registries(monkeypatch):
    monkeypatch.setattr(plugin_api, "_load_entry_points", lambda group: [])
    pdf_checks._ensure_loaded()
    file_checks._ensure_loaded()
    assert set(pdf_checks.PDF_CHECKS) == {"javascript"}
    assert set(file_checks.FILE_CHECKS) == {"no-exe", "image-sizes", "pdf-are-pdf"}


def test_source_checks_noop_without_plugins(monkeypatch):
    monkeypatch.setattr(plugin_api, "_load_entry_points", lambda group: [])
    assert source_checks.run_source_file_checks("main.tex", b"hello") == []
    assert source_checks.run_source_tree_checks([("main.tex", b"hello")]) == []


# --------------------------------------------------------------------------- #
# Discovery + merge semantics
# --------------------------------------------------------------------------- #


def test_plugin_pdf_check_is_discovered(monkeypatch):
    def provider():
        return CheckSpec("fake-pdf", _ok_check, CheckSeverity.warning)

    monkeypatch.setattr(
        plugin_api,
        "_load_entry_points",
        lambda group: [_FakeEP("fp", provider)] if group == plugin_api.PDF_CHECKS_GROUP else [],
    )
    pdf_checks._ensure_loaded()
    assert "javascript" in pdf_checks.PDF_CHECKS  # built-in still present
    assert "fake-pdf" in pdf_checks.PDF_CHECKS  # discovered


def test_builtins_win_on_name_collision(monkeypatch):
    """A plugin re-registering a built-in name is skipped, not honoured."""
    sentinel = object()

    def provider():
        return CheckSpec("javascript", sentinel, CheckSeverity.error)

    monkeypatch.setattr(
        plugin_api,
        "_load_entry_points",
        lambda group: [_FakeEP("dup", provider)] if group == plugin_api.PDF_CHECKS_GROUP else [],
    )
    pdf_checks._ensure_loaded()
    assert pdf_checks.PDF_CHECKS["javascript"][0] is not sentinel  # built-in kept


def test_merge_is_fail_open(monkeypatch):
    """A broken provider is logged and skipped; good ones still register."""

    def boom():
        raise RuntimeError("broken plugin")

    def good():
        return CheckSpec("good", _ok_check, CheckSeverity.warning)

    monkeypatch.setattr(
        plugin_api, "_load_entry_points", lambda group: [_FakeEP("bad", boom), _FakeEP("good", good)]
    )
    registry: dict = {}
    plugin_api.merge_check_specs("any-group", registry)  # must not raise
    assert "good" in registry
    assert "bad" not in registry


# --------------------------------------------------------------------------- #
# Source-check wiring -> suspicious status (opt-in) + arbitrary key round-trip
# --------------------------------------------------------------------------- #


def _flagging_source_check(filename, data):
    # Emits a plugin-private issue key that is NOT a member of IssueType.
    return [TeXFileIssue("obfuscated_source", "looks obfuscated", filename)]


def _write_min_tex(tmp_path):
    (tmp_path / "main.tex").write_text(
        r"\documentclass{article}" + "\n" + r"\begin{document}" + "\nhello\n" + r"\end{document}" + "\n"
    )


def test_suspicious_status_when_flag_on(tmp_path, monkeypatch):
    _write_min_tex(tmp_path)
    monkeypatch.setattr(source_checks, "_file_checks", [_flagging_source_check])
    monkeypatch.setattr(preflight, "SOURCE_CHECK_SETS_SUSPICIOUS", True)

    pf = preflight.generate_preflight_response(str(tmp_path))
    assert pf.status.key == PreflightStatusValues.suspicious
    keys = [iss.key for tf in pf.tex_files for iss in tf.issues]
    assert "obfuscated_source" in keys
    # The plugin-private string key round-trips through JSON serialization.
    js = preflight.generate_preflight_response(str(tmp_path), json=True)
    assert "obfuscated_source" in js


def test_no_suspicious_when_flag_off(tmp_path, monkeypatch):
    _write_min_tex(tmp_path)
    monkeypatch.setattr(source_checks, "_file_checks", [_flagging_source_check])
    monkeypatch.setattr(preflight, "SOURCE_CHECK_SETS_SUSPICIOUS", False)

    pf = preflight.generate_preflight_response(str(tmp_path))
    # Issue is still surfaced, but status stays success (opt-in flag is off).
    assert pf.status.key == PreflightStatusValues.success
    keys = [iss.key for tf in pf.tex_files for iss in tf.issues]
    assert "obfuscated_source" in keys


def test_source_plugin_failopen_does_not_break_preflight(tmp_path, monkeypatch):
    _write_min_tex(tmp_path)

    def boom(filename, data):
        raise RuntimeError("boom")

    monkeypatch.setattr(source_checks, "_file_checks", [boom])
    monkeypatch.setattr(preflight, "SOURCE_CHECK_SETS_SUSPICIOUS", True)

    pf = preflight.generate_preflight_response(str(tmp_path))
    assert pf.status.key == PreflightStatusValues.success  # crash swallowed, no flag


def test_builtin_issue_key_still_enum():
    """Built-in checks keep emitting IssueType members (so .key.value works)."""
    issue = TeXFileIssue(IssueType.oversized_image, "big", "fig.png")
    assert issue.key == IssueType.oversized_image
    assert issue.key.value == "oversized_image"
