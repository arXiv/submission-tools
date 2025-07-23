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
            # let us check for page color as well as overlap
            pix = page.get_pixmap(clip=pymupdf.Rect(lef, top, rig, bot), alpha=True)
            color_count = pix.color_count()
            color_topusage = pix.color_topusage()
            # cases:
            # 1. transparent page, no contents --> color_topusage == (1.0, b'\x00\x00\x00\x00')
            # 2. transparent page, with contents -->
            #    depending on the amount of contents and possible images, but with normal text
            #    we would still get
            #        color_topusage == (0.NNNNNNNNNNN, b'\x00\x00\x00\xff')
            #    with 0.NNNNNNNNNNN being >= 0.5 the percentage of transparent in the box
            # 3. non-transparent page, no contents --> color_topusage == (1.0,b'\xff\xff\xff\xff')
            #    (in case of white background, some other byte string for another color)
            # 4. non-transparent page, with contents -->
            #    as above but
            #        color_topusage == (0.NNNNNNNNNNN, b'\xff\xff\xff\xff')
            if color_count == 1:
                # if we have only one color in the rect, it is either transparent or some
                # background color, but not real information
                # TODO: for real overlay detection, we need to adjust this
                overlay = True
                if color_topusage == (1.0, b"\x00\x00\x00\x00"):
                    # transparent background, so we can overlay
                    no_overlap = True
                else:
                    # some uni-color background, maybe from a logo or background design
                    no_overlap = False
            else:
                overlay = False
                no_overlap = False
            logger.debug("Color count in watermark area: %d", color_count)
            logger.debug("Color top usage in watermark area: %s", color_topusage)
            logger.debug("Detected no_overlap: %s", no_overlap)
            # this should fix most cases:
            # - transparent or uni-color background get an overlay on top of it
            # - everything else gets an "underlay" (i.e. the watermark is below the content)
            page.insert_text(
                pymupdf.Point(rig, bot),
                watermark.text,
                fontname=fname,
                fontsize=fsize,
                rotate=90,
                color=(0.5, 0.5, 0.5),
                overlay=overlay,
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
        logger.error("Failed to open PDF file: %s - %s", in_pdf, exc, exc_info=True)
        raise WatermarkFileTypeError()
    except Exception as exc:
        logger.error("Failed to open PDF file: %s - %s", in_pdf, exc, exc_info=True)
        raise WatermarkError()
