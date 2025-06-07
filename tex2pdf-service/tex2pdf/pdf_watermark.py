"""Adding the watermark string to the PDF file."""

import collections
import io
import pathlib

import pymupdf

from .service_logger import get_logger

Watermark = collections.namedtuple("Watermark", ["text", "link"])


class WatermarkError(Exception):
    """Custom exception for watermark errors."""

    pass


class WatermarkFileTypeError(WatermarkError):
    """Exception raised for unsupported file types."""

    pass


def add_watermark_text_to_pdf(watermark: Watermark, in_pdf: pathlib.Path | str, out_pdf: str | io.FileIO) -> None:
    """combines/overlays the watermark PDF with the source PDF."""
    logger = get_logger()
    fname = "Times-Roman"
    fsize = 20

    if watermark.text is None:
        # nothing to do, just return
        return

    try:
        logger.debug("Trying to open PDF file: %s", in_pdf)
        with pymupdf.open(in_pdf) as source:
            logger.debug("pymupdf open file succeeded")
            # pymupdf.open() can open multiple file types, including PDF, XPS, and EPUB.
            # When a non-PDF is submitted, raise an error.
            if not source.is_pdf:
                logger.error("Passed file is not a PDF: %s", in_pdf)
                raise WatermarkFileTypeError()
            # do not stamp PDFs that look like PDF/A files
            # see https://github.com/pymupdf/PyMuPDF/discussions/2169#discussioncomment-4657130
            catalog = source.pdf_catalog()
            output_intents_xref = source.xref_get_key(catalog, "OutputIntents")
            if output_intents_xref and output_intents_xref[0] == "array":
                logger.warning("Passed PDF file looks like PDF/A, not stamping: %s", in_pdf)
                return
            # do the work
            page = source[0]
            page_size = page.mediabox_size
            wm_length = pymupdf.get_text_length(watermark.text, fontname=fname, fontsize=fsize)
            lef = 32 - fsize
            rig = 32
            top = (page_size[1] - wm_length) / 2
            bot = (page_size[1] + wm_length) / 2
            page.insert_text(
                pymupdf.Point(rig, bot),
                watermark.text,
                fontname=fname,
                fontsize=fsize,
                rotate=90,
                color=(0.5, 0.5, 0.5),
                overlay=False,
            )
            if watermark.link:
                page.insert_link(
                    {"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(lef, top, rig, bot), "uri": watermark.link}
                )
            if isinstance(out_pdf, io.FileIO):
                logger.debug("Saving to FileIO object")
                source.save(out_pdf)
            else:
                logger.debug("Saving watermarked PDF to %s", out_pdf)
                with open(out_pdf, "wb") as fd:
                    source.save(fd)
    except pymupdf.FileDataError as exc:
        logger.error("Failed to open PDF file: %s - %s", in_pdf, exc)
        raise WatermarkFileTypeError()
    except Exception as exc:
        logger.error("Failed to open PDF file: %s - %s", in_pdf, exc)
        raise WatermarkError()
