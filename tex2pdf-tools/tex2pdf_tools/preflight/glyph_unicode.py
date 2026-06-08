r"""Detection of font glyph / ToUnicode remapping in a produced or uploaded PDF.

The attack: the PDF renders correct-looking glyphs, but the *extractable* text --
copy/paste, the font's ``ToUnicode`` cmap -- yields garbage characters.  A human
reader sees a normal paper while any text extractor (LLM reviewers, plagiarism
checks, indexing) reads nonsense.  Documented as bypassing arXiv's font
heuristics in:

  * "Exploiting PDF Obfuscation in LLMs, arXiv, and More",
    IACR ePrint 2026/278 -- https://eprint.iacr.org/2026/278

Detection method (intentionally conservative -- the *garbage-extraction* case):
``pymupdf``'s ``Page.get_texttrace()`` yields, per drawn glyph, the Unicode
codepoint a text extractor would recover (``ucs``).  We flag a document when a
large fraction of its rendered glyphs extract as "bad" codepoints -- the Unicode
replacement char (U+FFFD), an unmapped slot (0), or a Private-Use-Area codepoint
-- while glyphs are clearly being drawn.

Important design point (verified empirically): the *absence* of a ``ToUnicode``
map is NOT a signal.  Standard base-14 fonts (e.g. Helvetica) carry no
``ToUnicode`` yet extract perfectly via their standard encoding.  The verdict
therefore rests only on extraction quality, never on ToUnicode presence.

Not covered (out of scope): *valid-but-wrong* remaps, where a glyph shaped "A"
maps to a plausible-but-incorrect Unicode "Z".  Catching that needs glyph-shape
or OCR comparison against the extracted text.

Any failure to open/parse the PDF (including a missing ``pymupdf``) degrades to
"nothing found" -- this check must never break PDF production.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import logger

try:
    import pymupdf

    _HAVE_PYMUPDF = True
except ImportError:  # pragma: no cover - exercised only where pymupdf is absent
    _HAVE_PYMUPDF = False


#
# CONSERVATIVE THRESHOLDS (tunable)
#
# Ignore documents with little text -- a verdict needs a meaningful sample.
GLYPH_MISMATCH_MIN_GLYPHS = 200
# Fraction of (non-whitespace) rendered glyphs that must extract as "bad" before
# a finding is reported.  A normal or even math-heavy paper stays well below
# this because its prose extracts fine; only a wholesale remap crosses it.
GLYPH_MISMATCH_BAD_RATIO = 0.5
# How many example bad codepoints to keep for the report.
GLYPH_MISMATCH_SAMPLE = 40


@dataclass
class GlyphMismatchResult:
    """Outcome of analysing one PDF for glyph/ToUnicode mismatch."""

    flagged: bool = False
    total_glyphs: int = 0
    bad_glyphs: int = 0
    bad_ratio: float = 0.0
    fonts: list[str] = field(default_factory=list)
    sample: list[int] = field(default_factory=list)
    error: str | None = None


def _is_whitespace(ucs: int) -> bool:
    try:
        return chr(ucs).isspace()
    except (ValueError, OverflowError):
        return False


def _is_bad_ucs(ucs: int) -> bool:
    """Return True if the extracted codepoint indicates broken text extraction."""
    if ucs in (0, 0xFFFD):
        return True
    if 0xE000 <= ucs <= 0xF8FF:  # BMP Private Use Area
        return True
    if 0xF0000 <= ucs <= 0xFFFFD:  # Supplementary PUA-A
        return True
    if 0x100000 <= ucs <= 0x10FFFD:  # Supplementary PUA-B
        return True
    if ucs < 0x20 and ucs not in (0x09, 0x0A, 0x0D):  # control char, not tab/LF/CR
        return True
    return False


def _evaluate(glyphs: Iterable[tuple[int, str]]) -> GlyphMismatchResult:
    """Tally a stream of (ucs, font) glyphs into a verdict (pure; no pymupdf)."""
    total = 0
    bad = 0
    fonts: set[str] = set()
    sample: list[int] = []
    for ucs, font in glyphs:
        if _is_whitespace(ucs):
            continue
        total += 1
        if _is_bad_ucs(ucs):
            bad += 1
            fonts.add(font)
            if len(sample) < GLYPH_MISMATCH_SAMPLE:
                sample.append(ucs)
    ratio = bad / total if total else 0.0
    flagged = total >= GLYPH_MISMATCH_MIN_GLYPHS and ratio >= GLYPH_MISMATCH_BAD_RATIO
    return GlyphMismatchResult(
        flagged=flagged,
        total_glyphs=total,
        bad_glyphs=bad,
        bad_ratio=ratio,
        fonts=sorted(fonts),
        sample=sample,
    )


def _iter_glyphs(doc: "pymupdf.Document") -> Iterable[tuple[int, str]]:
    """Yield (ucs, font) for every drawn glyph; a bad page is skipped, not fatal."""
    for pageno, page in enumerate(doc, start=1):
        try:
            spans = page.get_texttrace()
        except Exception as e:  # one bad page must not abort the check
            logger.debug("glyph/ToUnicode analysis failed on page %d: %s", pageno, e)
            continue
        for span in spans:
            font = str(span.get("font", "?"))
            for ch in span.get("chars", []):
                yield int(ch[0]), font


def analyze_glyph_unicode(pdf_path: str) -> GlyphMismatchResult:
    """Analyse a PDF for font glyph / ToUnicode remapping.

    Returns a :class:`GlyphMismatchResult`.  Never raises: any error (including a
    missing ``pymupdf``) yields an unflagged result so PDF production is never
    broken.
    """
    if not _HAVE_PYMUPDF:
        logger.debug("pymupdf not available, skipping glyph/ToUnicode check")
        return GlyphMismatchResult(error="pymupdf not available")
    try:
        with pymupdf.open(pdf_path) as doc:
            return _evaluate(_iter_glyphs(doc))
    except Exception as e:  # never break PDF production
        logger.debug("glyph/ToUnicode analysis could not open %s: %s", pdf_path, e)
        return GlyphMismatchResult(error=str(e))
