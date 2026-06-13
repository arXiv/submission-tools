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

# S6 "prose-aliasing macro army": a whole-document-tree signal.  The preamble (or
# a separate macros file) defines many macros whose body is a plain-language word
# (\newcommand{\trasmisero}{Warehouse\xspace}), and the body is then written
# almost entirely as calls to them, so the *source* carries no readable prose.
# Because the definitions and the calls can live in different files, this signal
# is evaluated per document tree (see detect_alias_army_in_tree), not per file.
#
# Calibrated on arXiv 2511/2512 (max over 427 legitimate bodies: 13 alias defs,
# 0.30 ratio only on tiny bodies with <20 calls) and on 20 known-obfuscated
# submissions (the Allen-Zhu family: 987-1990 defs, 0.71-0.85 ratio).  The three
# thresholds sit in the gap with >=3x margin on both sides.
OBFUSCATION_MIN_ALIAS_DEFS = 40  # distinct prose-bodied macros in the tree
OBFUSCATION_MIN_ALIAS_CALLS = 50  # absolute floor; never flag a small body
OBFUSCATION_MIN_ALIAS_RATIO = 0.5  # fraction of the body's control sequences
OBFUSCATION_MAX_ALIAS_BODY_CHARS = 40  # an alias body is a short word / phrase

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

# S6: macro definitions whose body we test for being a plain-language fragment.
# The braced-body alternatives use [^{}]* so a body containing nested braces
# (e.g. \newcommand{\R}{\mathbb{R}}) does not match -- only flat, text-like
# bodies are captured, which is exactly what a prose alias looks like.
_RE_MACRO_DEF = re.compile(
    r"\\(?:new|renew|provide)command\*?\s*\{?\\([A-Za-z]+)\}?(?:\[\d+\])?(?:\[[^\]]*\])?\s*\{([^{}]*)\}"
    r"|\\DeclareRobustCommand\*?\s*\{?\\([A-Za-z]+)\}?\s*\{([^{}]*)\}"
    r"|\\def\s*\\([A-Za-z]+)\s*\{([^{}]*)\}"
)
# A body is "prose" when, after dropping a trailing \xspace, it is letters plus
# simple word punctuation only (no braces, no other control sequences).
_RE_PROSE_BODY = re.compile(r"^[A-Za-z][A-Za-z0-9 ,.'\-]*?(?:\\xspace)?$")
_RE_XSPACE_SUFFIX = re.compile(r"\\xspace$")
_RE_CS_NAME = re.compile(r"\\([A-Za-z]+)")
_RE_WORD_RUN = re.compile(r"[A-Za-z]{2,}")


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


#
# S6: prose-aliasing macro army (evaluated per document tree)
#


def collect_prose_aliases(data: bytes) -> set[str]:
    r"""Return the names of macros defined in ``data`` whose body is plain prose.

    Scans the whole file (comments and verbatim blocks removed): a prose alias is
    a ``\newcommand`` / ``\renewcommand`` / ``\providecommand`` /
    ``\DeclareRobustCommand`` / ``\def`` whose body, after dropping a trailing
    ``\xspace``, is a short natural-language fragment (letters plus simple word
    punctuation, no braces or other control sequences).  These are the building
    blocks of a prose-aliasing macro army; see the module docstring and the
    ``OBFUSCATION_MIN_ALIAS_*`` thresholds.
    """
    text = data.decode("utf-8", errors="replace")
    text = _RE_COMMENT.sub("", text)
    text = _RE_VERBATIM.sub(" ", text)
    aliases: set[str] = set()
    for m in _RE_MACRO_DEF.finditer(text):
        groups = m.groups()
        name = body = None
        for name_idx, body_idx in ((0, 1), (2, 3), (4, 5)):
            if groups[name_idx] is not None:
                name, body = groups[name_idx], groups[body_idx]
                break
        if name is None or body is None:
            continue
        body = body.strip()
        core = _RE_XSPACE_SUFFIX.sub("", body).strip()
        if (
            1 <= len(core) <= OBFUSCATION_MAX_ALIAS_BODY_CHARS
            and _RE_WORD_RUN.search(core)
            and _RE_PROSE_BODY.match(body)
        ):
            aliases.add(name)
    return aliases


def alias_usage_in_body(data: bytes, aliases: set[str]) -> tuple[int, int, float]:
    r"""Measure how much the document body of ``data`` consists of alias calls.

    Returns ``(body_cs, alias_calls, ratio)`` where ``body_cs`` is the number of
    control sequences in the document body (the whole file for plain TeX without
    ``\begin{document}``, e.g. an ``\input``-ed section file), ``alias_calls`` is
    how many of those name a macro in ``aliases``, and ``ratio = alias_calls /
    body_cs``.  Comments and verbatim blocks are removed first.
    """
    text = data.decode("utf-8", errors="replace")
    body_match = _RE_DOC_BODY.search(text)
    region = body_match.group(1) if body_match else text
    region = _RE_COMMENT.sub("", region)
    region = _RE_VERBATIM.sub(" ", region)
    control_seqs = _RE_CS_NAME.findall(region)
    body_cs = len(control_seqs)
    if not body_cs:
        return 0, 0, 0.0
    alias_calls = sum(1 for c in control_seqs if c in aliases)
    return body_cs, alias_calls, alias_calls / body_cs


def s6_alias_army_flag(n_defs: int, alias_calls: int, ratio: float) -> bool:
    """Return ``True`` when all three conservative S6 thresholds hold together."""
    return (
        n_defs >= OBFUSCATION_MIN_ALIAS_DEFS
        and alias_calls >= OBFUSCATION_MIN_ALIAS_CALLS
        and ratio >= OBFUSCATION_MIN_ALIAS_RATIO
    )


def detect_alias_army_in_tree(tree_files: list[tuple[str, bytes]]) -> list[TeXFileIssue]:
    r"""Detect a prose-aliasing macro army across one document tree.

    ``tree_files`` is every file of a single document tree as ``(filename,
    data)`` -- the alias dictionary is unioned across all of them, so definitions
    in a separate ``macros.tex`` / ``macros.sty`` are taken into account even when
    the body that calls them lives in another file.  Returns one
    ``IssueType.obfuscated_source`` issue per body file that trips S6.  Style and
    other legitimately macro-dense file types (``OBFUSCATION_SKIP_EXTENSIONS``)
    are never themselves flagged; they only donate definitions to the alias set.
    """
    aliases: set[str] = set()
    for _filename, data in tree_files:
        aliases |= collect_prose_aliases(data)
    if len(aliases) < OBFUSCATION_MIN_ALIAS_DEFS:
        return []

    issues: list[TeXFileIssue] = []
    for filename, data in tree_files:
        if os.path.splitext(filename)[1].lower() in OBFUSCATION_SKIP_EXTENSIONS:
            continue
        body_cs, alias_calls, ratio = alias_usage_in_body(data, aliases)
        if s6_alias_army_flag(len(aliases), alias_calls, ratio):
            info = (
                f"obfuscation suspected: prose-aliasing-macro-army "
                f"[alias-defs={len(aliases)}, alias-calls={alias_calls}, "
                f"body-control-seqs={body_cs}, alias-ratio={ratio:.2f}]"
            )
            logger.debug("Alias-army obfuscation detected in %s: %s", filename, info)
            issues.append(TeXFileIssue(IssueType.obfuscated_source, info, filename=filename))
    return issues
