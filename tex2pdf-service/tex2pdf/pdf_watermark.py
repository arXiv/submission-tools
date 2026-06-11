"""Adding the watermark string to the PDF file.

The watermark is a short, vertical (rotated 90°) line of text placed in the
left margin of the first page, optionally hyperlinked.

Implementation notes:
    The work is split between two non-restrictively-licensed libraries:

    * ``pdf_oxide`` (MIT/Apache) builds the watermark text as a small,
      single-page PDF -- handling base-14 *and* embedded/subsetted custom fonts
      -- and renders pages so we can measure the true glyph extent and decide
      whether the watermark should sit on top of or beneath existing content.
    * ``pikepdf`` (MPL-2.0) composites that watermark page onto the first page
      of the source PDF as a rotated Form XObject, adds the optional URI link,
      and writes the result.
"""

import collections
import contextlib
import io
import logging
import pathlib
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pdf_oxide
import pikepdf
from PIL import Image, ImageChops

from .service_logger import get_logger

Watermark = collections.namedtuple("Watermark", ["text", "link"])

# Name under which a custom font is registered with pdf_oxide and referenced
# from the watermark page's content stream.
_WATERMARK_FONT_NAME = "ArxivWatermarkFont"

# Right edge (PDF points, distance from the left paper edge) of the vertical
# watermark band. Glyphs extend left from here; the band is centered vertically.
_BAND_RIGHT = 32.0

# Resolution used to measure the true glyph extent of the rendered watermark.
_INK_DPI = 150


class WatermarkError(Exception):
    """Custom exception for watermark errors."""

    pass


class WatermarkFileTypeError(WatermarkError):
    """Exception raised for unsupported file types."""

    pass


def hex_to_rgbf(hex_color: str) -> tuple[float, float, float]:
    """
    Convert a hex color string to tuple of floats.

    Convert a hex color string (e.g., '#4ba36c' or '4ba36c') to
    a tuple of floats (R, G, B) in the range 0.0 - 1.0.
    """
    # Remove '#' if present
    hex_color = hex_color.lstrip("#")

    # Validate length
    if len(hex_color) != 6:
        raise ValueError("Hex color must be 6 characters long.")

    # Convert hex to integer RGB values
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    # Convert to floats between 0 and 1
    return r / 255.0, g / 255.0, b / 255.0


@contextlib.contextmanager
def _quiet_pdf_oxide_logs() -> Iterator[None]:
    """Silence pdf_oxide's benign parse-recovery warnings while reading a PDF.

    Third-party PDFs routinely trip warnings such as "Dictionary used where
    Stream expected, treating as empty stream" on the ``pdf_oxide`` logger; the
    library recovers fine. Raise that logger to ERROR for the duration so we do
    not spam logs, then restore the previous level.
    """
    pdf_oxide_logger = logging.getLogger("pdf_oxide")
    previous = pdf_oxide_logger.level
    pdf_oxide_logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        pdf_oxide_logger.setLevel(previous)


def _render_page_rgb(doc: "pdf_oxide.PdfDocument", page_index: int, dpi: int) -> Image.Image:
    """Render a page to an RGB Pillow image (pdf_oxide renders onto a white canvas)."""
    pixmap = doc.render_pixmap(page_index, dpi=dpi)
    return Image.frombytes("RGBA", (pixmap.width, pixmap.height), pixmap.data).convert("RGB")


def _build_watermark_overlay(
    text: str,
    fsize: float,
    rgb: tuple[float, float, float],
    font_file: str | None,
) -> tuple[bytes, tuple[float, float, float, float]]:
    """Build a single-page PDF holding the watermark text laid out horizontally.

    Returns the PDF bytes and the glyphs' true bounding box ``(x0, y0, x1, y1)``
    in PDF points. The caller rotates and positions this page when compositing
    it onto the source PDF; the bounding box lets it center the text exactly,
    independent of the (possibly custom) font's metrics.
    """
    # pdf_oxide's text measurement only knows base-14 metrics, so it is just a
    # rough size hint here; the page is made generously wide so even a wider
    # custom face is never clipped by the Form XObject bounding box.
    # NB: the pdf_oxide type stub mistypes DocumentBuilder.page() (it lists the
    # self-handle as an extra positional), hence the ignores on .page() calls.
    approx = pdf_oxide.DocumentBuilder().page(10.0, fsize * 1.6).font("Times-Roman", fsize).measure(text)  # type: ignore[call-arg, arg-type]
    page_width = max(approx, 1.0) * 2.0 + 4.0 * fsize
    page_height = fsize * 1.8
    baseline = 0.4 * fsize

    builder = pdf_oxide.DocumentBuilder()
    font_name = "Times-Roman"
    if font_file:
        # Use the font file stem as the recorded PostScript name (pdf_oxide does
        # not reliably parse it from the face) and subset on build().
        embedded = pdf_oxide.EmbeddedFont.from_bytes(Path(font_file).read_bytes(), Path(font_file).stem)
        font_name = _WATERMARK_FONT_NAME
        builder.register_embedded_font(font_name, embedded)

    page = builder.page(page_width, page_height)  # type: ignore[call-arg, arg-type]
    page.font(font_name, fsize).at(0.0, baseline).inline_color(rgb[0], rgb[1], rgb[2], text)
    overlay_pdf = bytes(page.done().build())

    # Measure the actual drawn extent by rendering and finding the non-background
    # bounding box. This is font-agnostic and exact, unlike base-14 metrics.
    scale = _INK_DPI / 72.0
    with _quiet_pdf_oxide_logs():
        image = _render_page_rgb(pdf_oxide.PdfDocument.from_bytes(overlay_pdf), 0, _INK_DPI)
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    bbox = ImageChops.difference(image, background).getbbox()
    if bbox is None:
        # Nothing visible was drawn (e.g. whitespace-only text); use a thin box.
        ink = (0.0, 0.0, max(approx, 1.0), fsize)
    else:
        ink = (bbox[0] / scale, bbox[1] / scale, bbox[2] / scale, bbox[3] / scale)
    return overlay_pdf, ink


def _watermark_should_overlay(
    in_pdf: pathlib.Path | str, band: tuple[float, float, float, float], page_height: float
) -> bool:
    """Decide whether to draw the watermark on top of (True) or beneath (False) content.

    Renders the watermark band of the source page and counts distinct colors: a
    single color means the band is blank/uni-color, so the watermark can sit on
    top; anything else means there is content there, so the watermark is placed
    underneath to avoid obscuring it. Mirrors the previous behavior.
    """
    logger = get_logger()
    left, bottom, right, top = band
    try:
        with _quiet_pdf_oxide_logs():
            image = _render_page_rgb(pdf_oxide.PdfDocument(str(in_pdf)), 0, 72)
        # Pixel space (72 dpi == 1 px per point) has a top-left origin, so the
        # PDF y axis is flipped.
        crop = (int(left), int(page_height - top), int(right) + 1, int(page_height - bottom))
        band_image = image.crop(crop)
        colors = band_image.getcolors(maxcolors=1 << 24)
        color_count = len(colors) if colors is not None else 2
        logger.debug("Color count in watermark area: %s", color_count)
        return color_count <= 1
    except Exception as exc:
        # If we cannot inspect the band, default to overlaying on top (the
        # common case for the usually-blank left margin).
        logger.warning("Could not analyze watermark area, defaulting to overlay: %s", exc)
        return True


def add_watermark_text_to_pdf(
    watermark: Watermark,
    in_pdf: pathlib.Path | str,
    out_pdf: str | io.FileIO,
    font: str | None = None,
    fsize: int | None = None,
    fcolor: str | None = None,
) -> None:
    """combines/overlays the watermark PDF with the source PDF."""
    logger = get_logger()
    font_file: str | None = None
    # None means "use the default"; the defaults live here, in one place.
    if fsize is None:
        fsize = 20
    if fcolor is None:
        fcolor = "#808080"

    if font:
        # if the font parameter is specified, it needs to be either a full path to a otf/tff font file,
        # or just a Font.otf that is then looked up with kpsewhich
        if font[0] == "/":
            font_file = font
        else:
            font_file = subprocess.run(["kpsewhich", font], capture_output=True, text=True, check=False).stdout.rstrip()
        if not font_file or not Path(font_file).exists():
            raise WatermarkError(f"Font not found {font}")

    if watermark.text is None:
        # nothing to do, just return
        return

    rgb = hex_to_rgbf(fcolor)

    try:
        logger.debug("Trying to open PDF file: %s", in_pdf)
        with pikepdf.open(in_pdf) as source:
            logger.debug("pikepdf open file succeeded")
            # do not stamp PDFs that look like PDF/A files
            # see https://github.com/pymupdf/PyMuPDF/discussions/2169#discussioncomment-4657130
            output_intents = source.Root.get("/OutputIntents")
            if isinstance(output_intents, pikepdf.Array) and len(output_intents) > 0:
                logger.warning("Passed PDF file looks like PDF/A, not stamping: %s", in_pdf)
                return

            page = source.pages[0]
            media_box = page.MediaBox
            page_height = float(media_box[3]) - float(media_box[1])

            # Build the watermark text as its own little PDF page and find the
            # true glyph extent (x0,y0,x1,y1) within that page.
            overlay_pdf, (ix0, iy0, ix1, iy1) = _build_watermark_overlay(watermark.text, float(fsize), rgb, font_file)

            # Rotate the overlay 90° counter-clockwise: cm [0 1 -1 0 tx ty] maps
            # overlay point (x,y) -> (tx - y, ty + x). Choose tx/ty so the glyph
            # box lands in the left margin, centered vertically and reading bottom
            # to top. Resulting band on the page (PDF points):
            tx = _BAND_RIGHT + iy0
            ty = page_height / 2.0 - (ix0 + ix1) / 2.0
            band_left = _BAND_RIGHT - (iy1 - iy0)
            band_bottom = ty + ix0
            band_top = ty + ix1
            band = (band_left, band_bottom, _BAND_RIGHT, band_top)

            # Decide placement order based on what is already in the band.
            put_on_top = _watermark_should_overlay(in_pdf, band, page_height)
            logger.debug("Detected put_on_top: %s", put_on_top)

            # Import the watermark page as a Form XObject and place it.
            with pikepdf.open(io.BytesIO(overlay_pdf)) as overlay_doc:
                xobject = pikepdf.Page(overlay_doc.pages[0]).as_form_xobject()
                xref = source.copy_foreign(xobject)
            page_obj = pikepdf.Page(page)
            # Use a fixed resource name rather than letting pikepdf invent a random
            # one: a random name makes the stamped PDF differ on every run for
            # otherwise identical input, which breaks reproducible builds and the
            # byte-exact comparisons in the test suites.
            name = page_obj.add_resource(xref, pikepdf.Name.XObject, name=pikepdf.Name("/ArXivWatermark"))
            # Wrap the existing content in q/Q so the page's base CTM (some PDFs
            # set a scale/flip transform that is never balanced) cannot leak into
            # our appended content stream and distort the watermark.
            page_obj.contents_add(b"q\n", prepend=True)
            page_obj.contents_add(b"\nQ\n", prepend=False)
            snippet = f"q 0 1 -1 0 {tx:.4f} {ty:.4f} cm {name} Do Q".encode()
            # prepend => underlay (beneath content); append => overlay (on top)
            page_obj.contents_add(snippet, prepend=not put_on_top)

            if watermark.link:
                annotation = pikepdf.Dictionary(
                    Type=pikepdf.Name.Annot,
                    Subtype=pikepdf.Name.Link,
                    Rect=[band_left, band_bottom, _BAND_RIGHT, band_top],
                    Border=[0, 0, 0],
                    A=pikepdf.Dictionary(
                        Type=pikepdf.Name.Action,
                        S=pikepdf.Name.URI,
                        URI=pikepdf.String(watermark.link),
                    ),
                )
                indirect = source.make_indirect(annotation)
                if "/Annots" in page:
                    page.Annots.append(indirect)
                else:
                    page.Annots = pikepdf.Array([indirect])

            if isinstance(out_pdf, io.FileIO):
                logger.debug("Saving to FileIO object")
                source.save(out_pdf, compress_streams=True)
            else:
                logger.debug("Saving watermarked PDF to %s", out_pdf)
                source.save(str(out_pdf), compress_streams=True)
    except pikepdf.PdfError as exc:
        logger.error("Failed to open PDF file: %s - %s", in_pdf, exc, exc_info=True)
        raise WatermarkFileTypeError()
    except WatermarkError:
        raise
    except Exception as exc:
        logger.error("Failed to watermark PDF file: %s - %s", in_pdf, exc, exc_info=True)
        raise WatermarkError()
