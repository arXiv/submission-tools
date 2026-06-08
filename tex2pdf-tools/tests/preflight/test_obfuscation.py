"""Tests for source-obfuscation detection (Goal A).

See tex2pdf_tools/preflight/obfuscation.py for the technique taxonomy and the
conservative decision rule.  The bulk of the tests exercise the pure detection
function directly; one integration test checks the "suspicious" status
surfacing through generate_preflight_response and its feature-flag toggle.
"""

import os

import tex2pdf_tools.preflight
from tex2pdf_tools.preflight import IssueType, PreflightResponse, generate_preflight_response
from tex2pdf_tools.preflight.obfuscation import detect_obfuscation_issues

_DIR = os.path.abspath(os.path.dirname(__file__))
FIXTURE_DIR = os.path.join(_DIR, "fixture")

# A realistic chunk of prose so negative cases are above the size threshold.
PROSE = (
    "In this paper we study the asymptotic behaviour of a family of operators "
    "acting on a separable Hilbert space. We first recall the relevant definitions "
    "and then prove the main theorem, which generalises earlier results to the "
    "non-compact setting. Our approach combines spectral methods with a careful "
    "analysis of the resolvent near the boundary of the essential spectrum. "
    "Several examples illustrate the sharpness of the hypotheses, and we close "
    "with a discussion of open problems and possible extensions to operator pencils. "
)


def _has_obfuscation(issues) -> bool:
    return any(i.key == IssueType.obfuscated_source for i in issues)


# --------------------------------------------------------------------------- #
# Positive cases (must flag)
# --------------------------------------------------------------------------- #


def test_catcode_escape_reassignment_flags():
    body = b"\\catcode`\\|=0\n" + (PROSE * 2).encode()
    src = b"\\documentclass{article}\n\\begin{document}\n" + body + b"\n\\end{document}\n"
    issues = detect_obfuscation_issues("main.tex", src)
    assert _has_obfuscation(issues)
    assert "catcode-escape-reassignment" in issues[0].info


def test_catcode_letter_active_flags():
    src = b"\\begin{document}\n\\catcode`\\a=13\n" + (PROSE * 2).encode() + b"\n\\end{document}\n"
    issues = detect_obfuscation_issues("main.tex", src)
    assert _has_obfuscation(issues)
    assert "catcode-letter-recategorization" in issues[0].info


def test_char_emission_body_flags():
    body = b"\\char72\\char101\\char108\\char108\\char111\\char32" * 30
    src = b"\\begin{document}\n" + body + b"\n\\end{document}\n"
    issues = detect_obfuscation_issues("main.tex", src)
    assert _has_obfuscation(issues)
    assert "char-emission" in issues[0].info


def test_hex_caret_notation_flags():
    body = (b"^^5c" * 150) + b" "
    src = b"\\begin{document}\n" + body + b"\n\\end{document}\n"
    issues = detect_obfuscation_issues("main.tex", src)
    assert _has_obfuscation(issues)


def test_single_char_macro_army_flags():
    defs = b"".join(f"\\def\\{c}{{x}}\n".encode() for c in "abcdefghijklmnopqrstuvwxyz")
    usage = b"".join(f"\\{c}".encode() for c in "abcdefghijklmnopqrstuvwxyz") * 20
    src = b"\\begin{document}\n" + defs + usage + b"\n\\end{document}\n"
    issues = detect_obfuscation_issues("main.tex", src)
    assert _has_obfuscation(issues)
    assert "single-char-macro-army" in issues[0].info


# --------------------------------------------------------------------------- #
# Negative cases (must NOT flag) — false-positive guards
# --------------------------------------------------------------------------- #


def test_normal_prose_not_flagged():
    src = b"\\documentclass{article}\n\\begin{document}\n" + (PROSE * 3).encode() + b"\n\\end{document}\n"
    assert not _has_obfuscation(detect_obfuscation_issues("main.tex", src))


def test_math_heavy_not_flagged():
    eqs = b"\\begin{equation} \\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2} \\end{equation}\n" * 30
    src = b"\\begin{document}\n" + PROSE.encode() + eqs + b"\\end{document}\n"
    assert not _has_obfuscation(detect_obfuscation_issues("main.tex", src))


def test_tikz_heavy_not_flagged():
    tikz = b"\\draw (0,0) -- (1,1) -- (2,0) -- cycle; \\node at (1,1) {a};\n" * 40
    src = (
        b"\\begin{document}\n" + PROSE.encode() + b"\\begin{tikzpicture}\n"
        + tikz + b"\\end{tikzpicture}\n\\end{document}\n"
    )
    assert not _has_obfuscation(detect_obfuscation_issues("main.tex", src))


def test_lone_expandafter_signal_not_flagged():
    # A single weak signal (runtime tokenization) with normal prose must not flag.
    src = b"\\begin{document}\n" + (b"\\expandafter\\x " * 25) + PROSE.encode() + b"\n\\end{document}\n"
    assert not _has_obfuscation(detect_obfuscation_issues("main.tex", src))


def test_small_file_not_flagged():
    src = b"\\begin{document}\n\\catcode`\\|=0\n\\char72\\char101\n\\end{document}\n"
    assert not _has_obfuscation(detect_obfuscation_issues("main.tex", src))


def test_style_file_skipped():
    # Would fire (catcode escape) but .sty is legitimately macro-heavy and skipped.
    src = b"\\catcode`\\|=0\n" + (b"\\char72\\char101\\char108" * 40)
    assert not _has_obfuscation(detect_obfuscation_issues("evil.sty", src))


def test_comments_not_counted():
    # Obfuscation-looking content only inside comments must be ignored.
    src = (
        b"\\begin{document}\n" + (b"% \\catcode`\\|=0 \\char72\\char101\n" * 40)
        + (PROSE * 2).encode() + b"\n\\end{document}\n"
    )
    assert not _has_obfuscation(detect_obfuscation_issues("main.tex", src))


# --------------------------------------------------------------------------- #
# Integration: suspicious status surfacing + feature-flag toggle
# --------------------------------------------------------------------------- #


def test_obfuscation_sets_suspicious_status(monkeypatch):
    monkeypatch.setattr(tex2pdf_tools.preflight, "OBFUSCATION_SETS_SUSPICIOUS_STATUS", True)
    dir_path = os.path.join(FIXTURE_DIR, "obfuscation_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "suspicious"
    flagged = [tf for tf in pf.tex_files if _has_obfuscation(tf.issues)]
    assert flagged, "expected at least one tex file flagged as obfuscated"


def test_obfuscation_status_toggle_off(monkeypatch):
    monkeypatch.setattr(tex2pdf_tools.preflight, "OBFUSCATION_SETS_SUSPICIOUS_STATUS", False)
    dir_path = os.path.join(FIXTURE_DIR, "obfuscation_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    # Per-file issue is still attached, but the overall status is not flipped.
    assert pf.status.key.value == "success"
    assert any(_has_obfuscation(tf.issues) for tf in pf.tex_files)
