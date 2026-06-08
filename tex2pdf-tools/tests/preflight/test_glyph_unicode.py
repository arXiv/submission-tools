"""Tests for font glyph / ToUnicode mismatch detection (#1).

The verdict logic is tested directly via the pure ``_evaluate`` seam and
``_is_bad_ucs`` (a malicious remapped font cannot be conjured in-memory with
pymupdf, which normalises inserted codepoints). The check wiring, severity
toggle, and PDF-only preflight surfacing are tested by monkeypatching the
analyzer to return a flagged result, plus an end-to-end negative on a real PDF.
"""

import os

import pymupdf

import tex2pdf_tools.preflight.pdf_checks as pdf_checks
from tex2pdf_tools.preflight import IssueType, PreflightResponse, generate_preflight_response
from tex2pdf_tools.preflight.glyph_unicode import (
    GLYPH_MISMATCH_MIN_GLYPHS,
    GlyphMismatchResult,
    _evaluate,
    _is_bad_ucs,
    analyze_glyph_unicode,
)
from tex2pdf_tools.preflight.models import CheckSeverity
from tex2pdf_tools.preflight.pdf_checks import check_glyph_unicode_mismatch, run_checks

# --------------------------------------------------------------------------- #
# _is_bad_ucs
# --------------------------------------------------------------------------- #


def test_is_bad_ucs_flags_garbage():
    for cp in (0, 0xFFFD, 0xE000, 0xF8FF, 0xF0001, 0x100001, 0x01):
        assert _is_bad_ucs(cp), hex(cp)


def test_is_bad_ucs_accepts_normal():
    for cp in (ord("A"), ord("z"), ord("7"), 0x00E9, 0x4E2D, 0x09, 0x0A, 0x0D):
        assert not _is_bad_ucs(cp), hex(cp)


# --------------------------------------------------------------------------- #
# _evaluate verdict
# --------------------------------------------------------------------------- #


def _stream(ucs_list):
    return [(u, "BadFont") for u in ucs_list]


def test_evaluate_flags_wholesale_garbage():
    res = _evaluate(_stream([0xE000 + (i % 100) for i in range(300)]))
    assert res.flagged
    assert res.bad_ratio == 1.0
    assert res.fonts == ["BadFont"]
    assert res.sample  # captured some examples


def test_evaluate_below_min_glyphs_not_flagged():
    res = _evaluate(_stream([0xE000] * (GLYPH_MISMATCH_MIN_GLYPHS - 1)))
    assert not res.flagged


def test_evaluate_below_ratio_not_flagged():
    # 220 good + 100 bad => ratio ~0.31, well under 0.5
    stream = _stream([ord("a")] * 220) + _stream([0xE000] * 100)
    res = _evaluate(stream)
    assert res.total_glyphs == 320
    assert not res.flagged


def test_evaluate_mostly_bad_flagged():
    stream = _stream([ord("a")] * 50) + _stream([0xFFFD] * 250)
    res = _evaluate(stream)
    assert res.flagged
    assert round(res.bad_ratio, 2) == 0.83


def test_evaluate_whitespace_ignored():
    res = _evaluate(_stream([0x20, 0x09, 0x0A] * 100))
    assert res.total_glyphs == 0
    assert not res.flagged


# --------------------------------------------------------------------------- #
# End-to-end negative on a real PDF
# --------------------------------------------------------------------------- #


def _normal_pdf(tmp_path) -> str:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    para = "The quick brown fox jumps over the lazy dog. " * 4
    y = 100
    for _ in range(15):
        page.insert_text((40, y), para, fontsize=10)
        y += 18
    path = os.path.join(str(tmp_path), "main.pdf")
    doc.save(path)
    doc.close()
    return path


def test_normal_pdf_not_flagged(tmp_path):
    res = analyze_glyph_unicode(_normal_pdf(tmp_path))
    assert res.total_glyphs > GLYPH_MISMATCH_MIN_GLYPHS
    assert res.bad_glyphs == 0
    assert not res.flagged


def test_missing_pdf_degrades_gracefully():
    res = analyze_glyph_unicode("/no/such/file.pdf")
    assert not res.flagged and res.error is not None


# --------------------------------------------------------------------------- #
# Check wiring + severity toggle (analyzer monkeypatched to flag)
# --------------------------------------------------------------------------- #

_FLAGGED = GlyphMismatchResult(
    flagged=True, total_glyphs=400, bad_glyphs=380, bad_ratio=0.95, fonts=["ABCDEF+Evil"], sample=[0xE000, 0xE001]
)


def test_check_warning_does_not_fail_run(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_checks, "analyze_glyph_unicode", lambda _p: _FLAGGED)
    monkeypatch.setitem(pdf_checks.PDF_CHECKS, "glyph-unicode", (check_glyph_unicode_mismatch, CheckSeverity.warning))
    pdf = _normal_pdf(tmp_path)
    succeeded, errors, warnings = run_checks(pdf, ["glyph-unicode"])
    assert succeeded
    assert len(warnings) == 1 and not errors
    assert warnings[0].issues[0].key == IssueType.glyph_unicode_mismatch


def test_check_error_fails_run(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_checks, "analyze_glyph_unicode", lambda _p: _FLAGGED)
    monkeypatch.setitem(pdf_checks.PDF_CHECKS, "glyph-unicode", (check_glyph_unicode_mismatch, CheckSeverity.error))
    pdf = _normal_pdf(tmp_path)
    succeeded, errors, warnings = run_checks(pdf, ["glyph-unicode"])
    assert not succeeded
    assert len(errors) == 1 and not warnings
    assert errors[0].issues[0].key == IssueType.glyph_unicode_mismatch


# --------------------------------------------------------------------------- #
# PDF-only preflight integration
# --------------------------------------------------------------------------- #


def test_pdf_only_flag_mode_suspicious(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_checks, "analyze_glyph_unicode", lambda _p: _FLAGGED)
    monkeypatch.setitem(pdf_checks.PDF_CHECKS, "glyph-unicode", (check_glyph_unicode_mismatch, CheckSeverity.warning))
    _normal_pdf(tmp_path)
    pf: PreflightResponse = generate_preflight_response(str(tmp_path))
    assert pf.status.key.value == "suspicious"
    assert len(pf.detected_toplevel_files) == 1
    assert any(i.key == IssueType.glyph_unicode_mismatch for i in pf.detected_toplevel_files[0].issues)


def test_pdf_only_reject_mode_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_checks, "analyze_glyph_unicode", lambda _p: _FLAGGED)
    monkeypatch.setitem(pdf_checks.PDF_CHECKS, "glyph-unicode", (check_glyph_unicode_mismatch, CheckSeverity.error))
    _normal_pdf(tmp_path)
    pf: PreflightResponse = generate_preflight_response(str(tmp_path))
    assert pf.status.key.value == "error"
