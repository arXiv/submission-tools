r"""Detection of hidden / invisible text in a produced or uploaded PDF (Goal B).

A submission can render normally to a human while carrying text that is not
visible in the rendered page -- used to smuggle instructions at LLM-assisted
reviewers/indexers (prompt injection), or to mismatch the visible and the
machine-extractable content.  The common mechanisms are:

  * text whose colour matches the (local) background -- the classic
    "white text on white" trick;
  * text set in a sub-pixel font size;
  * text positioned off the visible page area;
  * text drawn in the invisible text-rendering mode (PDF ``Tr 3``) / zero
    opacity.

These were observed in the wild on arXiv and analysed in:

  * "Hidden Prompts in Manuscripts Exploit AI-Assisted Peer Review",
    arXiv:2507.06185 -- https://arxiv.org/abs/2507.06185
  * "Exploiting PDF Obfuscation in LLMs, arXiv, and More",
    IACR ePrint 2026/278 -- https://eprint.iacr.org/2026/278
  * "Publish to Perish: Prompt Injection Attacks on LLM-Assisted Peer Review",
    arXiv:2508.20863 -- https://arxiv.org/pdf/2508.20863

Detection works at the PDF level (downstream of whatever LaTeX trick produced
the PDF), so it covers both compiled-from-TeX and PDF-only submissions through
the shared ``run_pdf_checks`` registry.

Design notes (intentionally conservative, to minimise false positives):

  * The primary "is it actually visible?" test is a **rendered-contrast** check:
    a text span is invisible if the pixels under its bounding box, in a render
    of the page on a white background, are (near-)uniform in colour.  This is
    colour-agnostic -- it catches white-on-white, colour-matched, and
    renders-nothing (``Tr 3``) text alike, by reusing the pixmap technique from
    ``pdf_watermark.py`` (``Pixmap.color_topusage`` / per-pixel sampling).
  * Crucially, this avoids the big false-positive class: scanned PDFs carry a
    legitimate **invisible OCR text layer** positioned *under the visible
    scanned glyphs*.  Because those glyphs are visible, the region under the OCR
    span is NOT uniform, so it is not flagged.  A free-floating hidden message
    sits over blank background, so its region IS uniform and is flagged.
  * Only spans carrying a meaningful amount of text trigger a finding
    (``HIDDEN_TEXT_MIN_CHARS``), and the extracted hidden text is captured for
    moderator review.
  * Any failure to open/parse the PDF (including a missing ``pymupdf``) degrades
    to "nothing found" -- this check must never break PDF production.
"""

import math
import string
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
# Minimum number of non-whitespace hidden characters (summed over the document)
# before a finding is reported.  A stray invisible strut never trips this.
HIDDEN_TEXT_MIN_CHARS = 30
# Font sizes (pt) below this are treated as effectively invisible.
HIDDEN_TEXT_MIN_FONT_PT = 2.0
# DPI at which the page is rendered for the contrast test.
HIDDEN_TEXT_RENDER_DPI = 100
# A span's bbox region counts as "uniform" (=> invisible) if the spread between
# the max and min sampled value of every RGB channel is below this (0..255).
HIDDEN_TEXT_CONTRAST_MIN = 24
# A span is "off page" only if its whole bbox lies outside the visible page area
# by at least this margin (pt) -- avoids flagging normal bleed/crop edges.
HIDDEN_TEXT_OFFPAGE_MARGIN_PT = 2.0
# Cap on pixels sampled per span (bounds the cost on text-heavy pages).
HIDDEN_TEXT_MAX_SAMPLES_PER_SPAN = 64
# Truncate the captured hidden text reported back to the caller.
HIDDEN_TEXT_REPORT_MAX_CHARS = 2000

_PRINTABLE = set(string.printable)


@dataclass
class HiddenTextResult:
    """Outcome of analysing one PDF for hidden text."""

    flagged: bool = False
    hidden_char_count: int = 0
    signals: dict[str, int] = field(default_factory=dict)
    pages: list[int] = field(default_factory=list)
    text: str = ""
    error: str | None = None


def _nonspace_len(s: str) -> int:
    return len(s.strip())


def _span_offpage(bbox: "pymupdf.Rect", page_rect: "pymupdf.Rect") -> bool:
    m = HIDDEN_TEXT_OFFPAGE_MARGIN_PT
    return bool(
        bbox.x1 <= page_rect.x0 - m
        or bbox.x0 >= page_rect.x1 + m
        or bbox.y1 <= page_rect.y0 - m
        or bbox.y0 >= page_rect.y1 + m
    )


def _region_is_uniform(pix: "pymupdf.Pixmap", page_rect: "pymupdf.Rect", bbox: "pymupdf.Rect", zoom: float) -> bool:
    """Return True if the pixels under bbox are (near-)uniform => text not visible."""
    px0 = int((bbox.x0 - page_rect.x0) * zoom)
    py0 = int((bbox.y0 - page_rect.y0) * zoom)
    px1 = math.ceil((bbox.x1 - page_rect.x0) * zoom)
    py1 = math.ceil((bbox.y1 - page_rect.y0) * zoom)
    px0 = max(0, min(px0, pix.width - 1))
    py0 = max(0, min(py0, pix.height - 1))
    px1 = max(0, min(px1, pix.width))
    py1 = max(0, min(py1, pix.height))
    if px1 <= px0 or py1 <= py0:
        # Nothing rendered there (e.g. clipped away) -> not visible.
        return True

    step_x = max(1, (px1 - px0) // 8)
    step_y = max(1, (py1 - py0) // 8)
    mins = [255, 255, 255]
    maxs = [0, 0, 0]
    samples = 0
    for py in range(py0, py1, step_y):
        for px in range(px0, px1, step_x):
            r, g, b = (int(c) for c in pix.pixel(px, py)[:3])
            for i, v in enumerate((r, g, b)):
                if v < mins[i]:
                    mins[i] = v
                if v > maxs[i]:
                    maxs[i] = v
            samples += 1
            if samples >= HIDDEN_TEXT_MAX_SAMPLES_PER_SPAN:
                break
        if samples >= HIDDEN_TEXT_MAX_SAMPLES_PER_SPAN:
            break
    if samples == 0:
        return True
    spread = max(maxs[i] - mins[i] for i in range(3))
    return spread < HIDDEN_TEXT_CONTRAST_MIN


def _analyze_page(page: "pymupdf.Page", zoom: float, found: dict[str, list[str]]) -> None:
    page_rect = page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
    # A clip far larger than the page forces get_text to also return glyphs
    # placed outside the visible page area (off-page hidden text), which the
    # default extraction silently drops.
    info = page.get_text("dict", clip=pymupdf.Rect(-10000, -10000, 10000, 10000))
    for block in info.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                bbox = pymupdf.Rect(span["bbox"])
                if _span_offpage(bbox, page_rect):
                    found["off_page"].append(text)
                elif span.get("size", 99.0) < HIDDEN_TEXT_MIN_FONT_PT:
                    found["tiny_font"].append(text)
                elif _region_is_uniform(pix, page_rect, bbox, zoom):
                    found["color_match"].append(text)


def analyze_hidden_text(pdf_path: str) -> HiddenTextResult:
    """Analyse a PDF for hidden/invisible text.

    Returns a :class:`HiddenTextResult`.  Never raises: any error (including a
    missing ``pymupdf``) yields an unflagged result so PDF production is never
    broken.
    """
    if not _HAVE_PYMUPDF:
        logger.debug("pymupdf not available, skipping hidden-text check")
        return HiddenTextResult(error="pymupdf not available")

    zoom = HIDDEN_TEXT_RENDER_DPI / 72.0
    found: dict[str, list[str]] = {"color_match": [], "tiny_font": [], "off_page": []}
    pages: list[int] = []
    try:
        with pymupdf.open(pdf_path) as doc:
            for pageno, page in enumerate(doc, start=1):
                before = sum(len(v) for v in found.values())
                try:
                    _analyze_page(page, zoom, found)
                except Exception as e:  # one bad page must not abort the check
                    logger.debug("hidden-text analysis failed on page %d: %s", pageno, e)
                    continue
                if sum(len(v) for v in found.values()) > before:
                    pages.append(pageno)
    except Exception as e:  # never break PDF production
        logger.debug("hidden-text analysis could not open %s: %s", pdf_path, e)
        return HiddenTextResult(error=str(e))

    signals = {k: sum(_nonspace_len(t) for t in v) for k, v in found.items() if v}
    hidden_char_count = sum(signals.values())
    flagged = hidden_char_count >= HIDDEN_TEXT_MIN_CHARS

    captured = ""
    if flagged:
        parts = [t.strip() for v in found.values() for t in v if t.strip()]
        captured = " ".join(parts)[:HIDDEN_TEXT_REPORT_MAX_CHARS]

    return HiddenTextResult(
        flagged=flagged,
        hidden_char_count=hidden_char_count,
        signals=signals,
        pages=pages,
        text=captured,
    )
