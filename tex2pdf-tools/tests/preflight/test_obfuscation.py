"""Tests for source-obfuscation detection (Goal A).

See tex2pdf_tools/preflight/obfuscation.py for the technique taxonomy and the
conservative decision rule.  The bulk of the tests exercise the pure detection
function directly; one integration test checks the "suspicious" status
surfacing through generate_preflight_response and its feature-flag toggle.
"""

import os
import string

import pytest

import tex2pdf_tools.preflight
from tex2pdf_tools.preflight import IssueType, PreflightResponse, generate_preflight_response
from tex2pdf_tools.preflight.obfuscation import detect_alias_army_in_tree, detect_obfuscation_issues

_DIR = os.path.abspath(os.path.dirname(__file__))
FIXTURE_DIR = os.path.join(_DIR, "fixture")

# The real in-the-wild example (kept under tex2pdf-service, not copied into the
# test tree because it is ~285 KB).  The regression test below skips when absent.
_REAL_EXAMPLE = os.path.normpath(
    os.path.join(
        _DIR, "..", "..", "..", "tex2pdf-service", "obfuscated-tex-examples", "2407.20311v1", "logi-math-ob.tex"
    )
)

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
        b"\\begin{document}\n"
        + PROSE.encode()
        + b"\\begin{tikzpicture}\n"
        + tikz
        + b"\\end{tikzpicture}\n\\end{document}\n"
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
        b"\\begin{document}\n"
        + (b"% \\catcode`\\|=0 \\char72\\char101\n" * 40)
        + (PROSE * 2).encode()
        + b"\n\\end{document}\n"
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


# --------------------------------------------------------------------------- #
# S6: prose-aliasing macro army (per document tree)
# --------------------------------------------------------------------------- #


def _alias_names(n: int) -> list[str]:
    r"""Return n distinct letters-only control-sequence names (\qaa, \qab, ...)."""
    names = [f"q{a}{b}" for a in string.ascii_lowercase for b in string.ascii_lowercase]
    assert n <= len(names)
    return names[:n]


def _alias_defs(names, body: str = "word\\xspace") -> str:
    return "".join(f"\\newcommand{{\\{nm}}}{{{body}}}\n" for nm in names)


def _alias_calls(names, n_calls: int) -> str:
    return " ".join(f"\\{names[i % len(names)]}" for i in range(n_calls))


def _army_tex(n_defs: int, n_calls: int) -> bytes:
    names = _alias_names(n_defs)
    src = (
        "\\documentclass{article}\n"
        + _alias_defs(names)
        + "\\begin{document}\n"
        + _alias_calls(names, n_calls)
        + "\n\\end{document}\n"
    )
    return src.encode()


def _has_alias_army(issues) -> bool:
    return any(i.key == IssueType.obfuscated_source and "prose-aliasing-macro-army" in i.info for i in issues)


# --- positive cases (must flag) ---


def test_prose_alias_macro_army_same_file_flags():
    issues = detect_alias_army_in_tree([("main.tex", _army_tex(60, 120))])
    assert _has_alias_army(issues)
    assert issues[0].filename == "main.tex"


def test_prose_alias_macro_army_split_files_flags():
    # Definitions live in a (skip-listed) style file; the body that calls them is
    # in main.tex.  Only the whole-tree check can catch this.
    names = _alias_names(60)
    main = (
        "\\documentclass{article}\n\\usepackage{thedefs}\n\\begin{document}\n"
        + _alias_calls(names, 120)
        + "\n\\end{document}\n"
    ).encode()
    sty = ("\\ProvidesPackage{thedefs}\n" + _alias_defs(names)).encode()
    issues = detect_alias_army_in_tree([("main.tex", main), ("thedefs.sty", sty)])
    assert _has_alias_army(issues)
    # The body file is flagged, never the style file that only donates definitions.
    assert [i.filename for i in issues] == ["main.tex"]


@pytest.mark.skipif(not os.path.exists(_REAL_EXAMPLE), reason="real-world example not present")
def test_real_world_example_flags():
    with open(_REAL_EXAMPLE, "rb") as fh:
        data = fh.read()
    issues = detect_alias_army_in_tree([(os.path.basename(_REAL_EXAMPLE), data)])
    assert _has_alias_army(issues)


# --- negative cases (must NOT flag) — false-positive guards ---


def test_alias_defs_below_threshold_not_flagged():
    # 39 prose-bodied macros, heavily used: one short of the def threshold (40).
    assert not _has_alias_army(detect_alias_army_in_tree([("main.tex", _army_tex(39, 120))]))


def test_few_text_shortcuts_not_flagged():
    # A handful of e.g./i.e.-style shortcuts -> far below the def threshold.
    names = _alias_names(15)
    src = (
        "\\documentclass{article}\n"
        + _alias_defs(names, body="e.g.\\xspace")
        + "\\begin{document}\n"
        + _alias_calls(names, 120)
        + "\n\\end{document}\n"
    ).encode()
    assert not _has_alias_army(detect_alias_army_in_tree([("main.tex", src)]))


def test_many_text_macros_normal_body_not_flagged():
    # 50 prose shortcut macros, but a body dominated by ordinary markup and prose:
    # the alias calls are a minority of the body's control sequences (ratio < 0.5).
    names = _alias_names(50)
    markup = ("\\section{Intro} " + PROSE + "\\textbf{x} \\emph{y} \\cite{z} \\ref{w} ") * 40
    body = markup + _alias_calls(names, 60)
    src = (
        "\\documentclass{article}\n" + _alias_defs(names) + "\\begin{document}\n" + body + "\n\\end{document}\n"
    ).encode()
    assert not _has_alias_army(detect_alias_army_in_tree([("main.tex", src)]))


def test_math_macros_not_flagged():
    # 50 math macros: braced bodies are not prose, so they are not aliases at all.
    names = _alias_names(50)
    defs = "".join(f"\\newcommand{{\\{nm}}}{{\\mathbb{{R}}}}\n" for nm in names)
    src = (
        "\\documentclass{article}\n" + defs + "\\begin{document}\n" + _alias_calls(names, 120) + "\n\\end{document}\n"
    ).encode()
    assert not _has_alias_army(detect_alias_army_in_tree([("main.tex", src)]))


# --- integration: suspicious status surfacing through generate_preflight_response ---


def test_alias_army_sets_suspicious_status_single_file(monkeypatch):
    monkeypatch.setattr(tex2pdf_tools.preflight, "OBFUSCATION_SETS_SUSPICIOUS_STATUS", True)
    pf: PreflightResponse = generate_preflight_response(os.path.join(FIXTURE_DIR, "obfuscation_2"))
    assert pf.status.key.value == "suspicious"
    assert any(tf.filename == "main.tex" and _has_alias_army(tf.issues) for tf in pf.tex_files)


def test_alias_army_split_tree_flags_body_file(monkeypatch):
    monkeypatch.setattr(tex2pdf_tools.preflight, "OBFUSCATION_SETS_SUSPICIOUS_STATUS", True)
    pf: PreflightResponse = generate_preflight_response(os.path.join(FIXTURE_DIR, "obfuscation_3"))
    assert pf.status.key.value == "suspicious"
    flagged = {tf.filename for tf in pf.tex_files if _has_alias_army(tf.issues)}
    assert "main.tex" in flagged  # the body file is flagged ...
    assert "thedefs.sty" not in flagged  # ... but the style file that holds the defs is not
