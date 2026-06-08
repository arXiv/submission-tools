r"""Detection of text hidden *behind* an opaque image in a produced/uploaded PDF.

A submission can draw text and then paint an opaque image on top of it: the text
is invisible to a human reader but remains in the PDF text layer, so any text
extractor (LLM reviewers, indexing, plagiarism checks) still reads it.  This is
the occlusion variant of hidden-text smuggling -- and, unlike the white-on-white
/ tiny-font cases, it cannot be found by a rendered-contrast test (the covering
image *does* render, so the region looks "visible").  Background:

  * "Hidden Prompts in Manuscripts Exploit AI-Assisted Peer Review",
    arXiv:2507.06185 -- https://arxiv.org/abs/2507.06185
  * "Exploiting PDF Obfuscation in LLMs, arXiv, and More",
    IACR ePrint 2026/278 -- https://eprint.iacr.org/2026/278

Detection uses draw order, which ``pymupdf`` exposes directly:

  * ``Page.get_bboxlog()`` lists every drawing operation (``fill-text``,
    ``fill-image``, ...) **in rendering order** with its bounding box;
  * ``Page.get_texttrace()`` gives each text span a ``seqno`` that aligns with
    the ``get_bboxlog`` index, plus its bbox and characters;
  * ``Page.get_image_info()`` reports ``has-mask`` (soft-mask transparency).

A text span is occluded when an **opaque** image is drawn *after* it (higher
draw index) and its bbox *fully covers* the span.  We only consider opaque
images (no soft mask) and require full coverage and a meaningful amount of text,
to stay conservative.  Any failure to open/parse the PDF (including a missing
``pymupdf``) degrades to "nothing found" -- this check must never break PDF
production.

Out of scope: occlusion by an opaque vector fill (``fill-path``); only raster
images are treated as occluders in this version.
"""

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
# Minimum number of occluded (non-whitespace) characters before a finding.
OCCLUDED_MIN_CHARS = 30
# A covering image must contain the text bbox to within this margin (pt).
OCCLUDE_COVER_MARGIN_PT = 1.0
# Truncate the captured occluded text reported back to the caller.
OCCLUDED_REPORT_MAX_CHARS = 2000

# A sentinel seqno for spans missing one, so they never look "before" anything.
_NO_SEQNO = 1 << 30


@dataclass
class OccludedTextResult:
    """Outcome of analysing one PDF for image-occluded text."""

    flagged: bool = False
    occluded_char_count: int = 0
    pages: list[int] = field(default_factory=list)
    text: str = ""
    error: str | None = None


def _safe_chr(ucs: int) -> str:
    try:
        return chr(ucs)
    except (ValueError, OverflowError):
        return ""


def _covers(outer: tuple, inner: tuple, margin: float) -> bool:
    """Return True if rectangle ``outer`` contains ``inner`` (within ``margin`` pt)."""
    ox0, oy0, ox1, oy1 = outer
    ix0, iy0, ix1, iy1 = inner
    return bool(ox0 <= ix0 + margin and oy0 <= iy0 + margin and ox1 >= ix1 - margin and oy1 >= iy1 - margin)


def _find_occluded(
    spans: list[tuple[int, tuple, str]],
    occluders: list[tuple[int, tuple]],
    margin: float,
) -> list[str]:
    """Return the text of spans drawn before, and fully covered by, an occluder.

    Args:
        spans: ``(seqno, bbox, text)`` per text span, in any order.
        occluders: ``(draw_index, bbox)`` per opaque image.
        margin: coverage tolerance in pt.
    """
    out: list[str] = []
    for seqno, bbox, text in spans:
        if not text.strip():
            continue
        for idx, obox in occluders:
            if idx > seqno and _covers(obox, bbox, margin):
                out.append(text)
                break
    return out


def analyze_occluded_text(pdf_path: str) -> OccludedTextResult:
    """Analyse a PDF for text hidden behind opaque images.

    Returns an :class:`OccludedTextResult`.  Never raises: any error (including a
    missing ``pymupdf``) yields an unflagged result so PDF production is never
    broken.
    """
    if not _HAVE_PYMUPDF:
        logger.debug("pymupdf not available, skipping occluded-text check")
        return OccludedTextResult(error="pymupdf not available")

    occluded: list[str] = []
    pages: list[int] = []
    try:
        with pymupdf.open(pdf_path) as doc:
            for pageno, page in enumerate(doc, start=1):
                try:
                    spans = []
                    for s in page.get_texttrace():
                        text = "".join(_safe_chr(int(c[0])) for c in s.get("chars", []))
                        spans.append((int(s.get("seqno", _NO_SEQNO)), tuple(s["bbox"]), text))
                    masked = {
                        tuple(round(v) for v in im["bbox"])
                        for im in page.get_image_info(xrefs=True)
                        if im.get("has-mask")
                    }
                    occluders = [
                        (idx, tuple(bbox))
                        for idx, (kind, bbox) in enumerate(page.get_bboxlog())
                        if kind == "fill-image" and tuple(round(v) for v in bbox) not in masked
                    ]
                    found = _find_occluded(spans, occluders, OCCLUDE_COVER_MARGIN_PT)
                    if found:
                        occluded.extend(found)
                        pages.append(pageno)
                except Exception as e:  # one bad page must not abort the check
                    logger.debug("occluded-text analysis failed on page %d: %s", pageno, e)
                    continue
    except Exception as e:  # never break PDF production
        logger.debug("occluded-text analysis could not open %s: %s", pdf_path, e)
        return OccludedTextResult(error=str(e))

    count = sum(len(t.strip()) for t in occluded)
    flagged = count >= OCCLUDED_MIN_CHARS
    captured = " ".join(t.strip() for t in occluded if t.strip())[:OCCLUDED_REPORT_MAX_CHARS] if flagged else ""
    return OccludedTextResult(flagged=flagged, occluded_char_count=count, pages=pages, text=captured)
