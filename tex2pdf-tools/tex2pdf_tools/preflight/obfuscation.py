r"""Detection of deliberately obfuscated TeX *source*.

A common evasion technique is to replace human-readable prose with TeX
machinery so the *rendered* PDF looks normal while the *source* cannot be
inspected, classified, or grepped without fully executing TeX.  Typical
mechanisms we look for here:

  * defining one macro per letter/word and writing the body as ``\a\b\c`` ...
    (a "macro army" of single-character control sequences);
  * ``\catcode`` reassignment -- changing the escape character, or making ASCII
    letters ``active`` (13) / ``other`` (12) -- and ``^^XX`` superscript-hex
    character notation (``^^5c`` etc.);
  * numeric character emission via ``\char``, ``\char"4A``, ``\symbol{}``;
  * runtime construction of control sequences with ``\csname`` / ``\scantokens``
    / ``\detokenize`` and long ``\expandafter`` chains, so the real tokens never
    appear literally in the file.

This behaviour was observed in the wild on arXiv (hidden prompt-injection
payloads aimed at LLM-assisted reviewers) and analysed in the security
literature:

  * "Hidden Prompts in Manuscripts Exploit AI-Assisted Peer Review",
    arXiv:2507.06185 -- https://arxiv.org/abs/2507.06185
  * "Exploiting PDF Obfuscation in LLMs, arXiv, and More",
    IACR ePrint 2026/278 -- https://eprint.iacr.org/2026/278
  * "LaTeXpOsEd: A Systematic Analysis of Information Leakage in Preprint
    Archives Using Large Language Models",
    arXiv:2510.03761 -- https://arxiv.org/pdf/2510.03761
  * "LaTeX Compilation: Challenges in the Era of LLMs",
    arXiv:2603.02873 -- https://arxiv.org/pdf/2603.02873
  * Practical CTF -- LaTeX -- https://book.jorianwoltjer.com/languages/latex

Because legitimate TeX is itself command-dense (math, TikZ, macro packages),
detection is intentionally *conservative*: it combines several independent
signals and only flags a file when a near-certain signal fires on its own, or
when "prose starvation" coincides with another encoding signal, or when two
encoding signals co-occur.  All thresholds are module-level constants so they
can be tuned, and style/generated files (``.sty``, ``.cls``, ``.bbl`` ...),
which are legitimately macro-heavy, are skipped -- a payload is placed in the
document body anyway.
"""

import os
import re

from .models import IssueType, TeXFileIssue, logger

#
# CONSERVATIVE THRESHOLDS
#
# These are deliberately set so that ordinary -- even very math/macro-heavy --
# documents do not trip them.  Tighten (lower the "min" knobs) only with care.

# Minimum number of non-whitespace characters in the analysed region before any
# density-based signal is considered; tiny files are never flagged.
OBFUSCATION_MIN_REGION_CHARS = 500

# S1 "prose starvation": fewer than this many real word tokens per 1000 chars
# of body is suspicious for a body that is otherwise substantial.
OBFUSCATION_MAX_WORDS_PER_KB = 5.0

# S2 numeric character emission (\char, \symbol{}, ^^XX): both an absolute count
# and a per-KB rate must be exceeded before the signal fires.
OBFUSCATION_MIN_EMISSION_COUNT = 20
OBFUSCATION_MIN_EMISSION_PER_KB = 10.0

# S4 "macro army": at least this many single-character control sequences defined
# with a short body (\def\a{...}, \let\a=...).
OBFUSCATION_MIN_LETTER_MACROS = 20
OBFUSCATION_MAX_LETTER_MACRO_BODY = 3

# S5 runtime tokenisation: a long \expandafter chain, or any \scantokens.
OBFUSCATION_MIN_EXPANDAFTER = 20

# File extensions that are legitimately command-dense and are never analysed.
OBFUSCATION_SKIP_EXTENSIONS = {
    ".sty",
    ".cls",
    ".clo",
    ".def",
    ".fd",
    ".bbl",
    ".bib",
    ".bst",
    ".ind",
    ".idx",
    ".toc",
    ".lof",
    ".lot",
}

#
# REGEXES (operate on the cleaned, decoded body)
#

# A comment runs from an unescaped % to end of line.
_RE_COMMENT = re.compile(r"(?<!\\)%.*")
# verbatim-like blocks whose contents must not be scanned.
_RE_VERBATIM = re.compile(
    r"\\begin\{(verbatim\*?|lstlisting|Verbatim|minted|alltt)\}.*?\\end\{\1\}",
    re.DOTALL,
)
# math we strip out before counting prose (so equation-heavy papers do not look
# "prose starved").
_RE_MATH = re.compile(
    r"\$\$.*?\$\$|\\\[.*?\\\]|\$.*?\$|\\\(.*?\\\)"
    r"|\\begin\{(equation\*?|align\*?|eqnarray\*?|gather\*?|multline\*?|math|displaymath)\}.*?\\end\{\1\}",
    re.DOTALL,
)
_RE_DOC_BODY = re.compile(r"\\begin\{document\}(.*?)\\end\{document\}", re.DOTALL)

# control sequences and braces, removed before counting plain-text words.
_RE_CONTROL_SEQ = re.compile(r"\\[a-zA-Z@]+|\\.")
_RE_WORD = re.compile(r"[A-Za-z]{2,}")

# S2: numeric character emission.
_RE_CHAR_EMISSION = re.compile(
    r"\\char(?![a-zA-Z])"  # \char13, \char`\A
    r"|\\char\""  # \char"4A
    r"|\\symbol\b"  # \symbol{...}
    r"|\^\^[0-9a-f]{2}"  # ^^5c  (lowercase hex, as TeX requires)
    r"|\^\^[@-_?]"  # ^^M and friends (control form)
)

# S3: dangerous \catcode reassignment.  We target the escape character and ASCII
# letters specifically; \makeatletter (catcode of @) and the like are NOT
# matched, so ordinary package-style tricks do not trip this.
_RE_CATCODE_ESCAPE = re.compile(
    r"\\catcode\s*`\\?\\\s*=\s*\d+"  # \catcode`\\=...  (reassign the escape char)
    r"|\\catcode\s*`?\\?.\s*=\s*0\b"  # \catcode`X=0     (make X an escape char)
)
_RE_CATCODE_LETTER_ACTIVE = re.compile(
    r"\\catcode\s*`\\?[A-Za-z]\s*=\s*(?:13|12)\b"  # letter -> active/other
)

# S4: single-character macro definitions with a short body.
_RE_LETTER_DEF = re.compile(r"\\def\s*\\(.)\s*\{([^{}]*)\}|\\let\s*\\(.)\s*=?\s*")

# S5: runtime tokenisation.
_RE_EXPANDAFTER = re.compile(r"\\expandafter\b")
_RE_SCANTOKENS = re.compile(r"\\scantokens\b")


def _strip_for_prose(region: str) -> str:
    """Remove control sequences, braces and ^^-notation so only plain text remains."""
    s = _RE_CHAR_EMISSION.sub(" ", region)
    s = _RE_CONTROL_SEQ.sub(" ", s)
    return s.replace("{", " ").replace("}", " ")


def detect_obfuscation_issues(filename: str, data: bytes) -> list[TeXFileIssue]:
    """Analyse a single TeX file and return obfuscation issues (usually empty).

    Args:
        filename: relative path of the file (used for the issue and to skip
            style/generated file types).
        data: raw file content (bytes, with line endings already normalised).

    Returns:
        A list with at most one :class:`TeXFileIssue` of type
        ``obfuscated_source`` when the conservative decision rule fires.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext in OBFUSCATION_SKIP_EXTENSIONS:
        return []

    text = data.decode("utf-8", errors="replace")

    # Restrict to the document body for LaTeX; the preamble legitimately holds
    # many definitions.  Plain TeX has no \begin{document}, so we use the whole
    # file in that case.
    body_match = _RE_DOC_BODY.search(text)
    region = body_match.group(1) if body_match else text

    # Remove comments and verbatim blocks (real content, not obfuscation).
    region = _RE_COMMENT.sub("", region)
    region = _RE_VERBATIM.sub(" ", region)

    region_chars = len(re.sub(r"\s", "", region))
    if region_chars < OBFUSCATION_MIN_REGION_CHARS:
        return []
    kb = region_chars / 1000.0

    # --- prose region (math removed so equations don't look like starvation) ---
    prose_region = _RE_MATH.sub(" ", region)
    word_tokens = len(_RE_WORD.findall(_strip_for_prose(prose_region)))
    words_per_kb = word_tokens / kb

    # --- signals ---
    emission_count = len(_RE_CHAR_EMISSION.findall(region))
    emission_per_kb = emission_count / kb

    letter_macros = 0
    for m in _RE_LETTER_DEF.finditer(region):
        if m.group(1) is not None:  # \def\<char>{<body>}
            if len(m.group(2)) <= OBFUSCATION_MAX_LETTER_MACRO_BODY:
                letter_macros += 1
        else:  # \let\<char>=
            letter_macros += 1

    expandafter_count = len(_RE_EXPANDAFTER.findall(region))

    s1 = region_chars >= OBFUSCATION_MIN_REGION_CHARS and words_per_kb < OBFUSCATION_MAX_WORDS_PER_KB
    s2 = emission_count >= OBFUSCATION_MIN_EMISSION_COUNT and emission_per_kb >= OBFUSCATION_MIN_EMISSION_PER_KB
    s3_escape = bool(_RE_CATCODE_ESCAPE.search(region))
    s3_letter = bool(_RE_CATCODE_LETTER_ACTIVE.search(region))
    s3 = s3_escape or s3_letter
    s4 = letter_macros >= OBFUSCATION_MIN_LETTER_MACROS
    s5 = expandafter_count >= OBFUSCATION_MIN_EXPANDAFTER or bool(_RE_SCANTOKENS.search(region))

    fired: list[str] = []
    if s3_escape:
        fired.append("catcode-escape-reassignment")
    if s3_letter:
        fired.append("catcode-letter-recategorization")
    if s1:
        fired.append("prose-starvation")
    if s2:
        fired.append("char-emission")
    if s4:
        fired.append("single-char-macro-army")
    if s5:
        fired.append("runtime-tokenization")

    # Conservative decision rule: a near-certain catcode signal on its own, OR
    # prose starvation paired with any encoding signal, OR two encoding signals
    # co-occurring.  A single weak signal never flags.
    flag = s3 or (s1 and (s2 or s4 or s5)) or (s2 and s4) or (s2 and s5) or (s4 and s5)
    if not flag:
        return []

    info = (
        f"obfuscation suspected: {', '.join(fired)} "
        f"[words/KB={words_per_kb:.1f}, char-emission/KB={emission_per_kb:.1f}, "
        f"single-char-macros={letter_macros}, expandafter={expandafter_count}]"
    )
    logger.debug("Obfuscation detected in %s: %s", filename, info)
    return [TeXFileIssue(IssueType.obfuscated_source, info, filename=filename)]
