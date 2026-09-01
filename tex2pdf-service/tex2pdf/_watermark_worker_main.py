"""Standalone entry point for the watermarking subprocess.

Run as ``python -m tex2pdf._watermark_worker_main`` by
add_watermark_text_to_pdf_bounded() in pdf_watermark.py, so that a hang in
the underlying pdf_oxide/pikepdf call can be killed by terminating this
whole OS process, regardless of what the hang looks like internally.

Usage: python -m tex2pdf._watermark_worker_main IN_PDF OUT_PDF TEXT LINK FONT FSIZE FCOLOR
Empty string means "not given" (None) for TEXT/LINK/FONT/FSIZE/FCOLOR.
Exits 0 on success. On failure, prints "<ExceptionClassName>: <message>" to
stderr and exits 1.
"""

import os
import sys
import time

from .pdf_watermark import Watermark, WatermarkError, add_watermark_text_to_pdf


def main(argv: list[str]) -> int:
    if os.environ.get("TEX2PDF_WATERMARK_TEST_HANG") == "1":
        # ponytail: test-only hook so tests can exercise the timeout/kill path
        # against a real subprocess without needing a genuinely pathological PDF.
        time.sleep(300)
        return 0

    in_pdf, out_pdf, text, link, font, fsize, fcolor = argv[:7]
    watermark = Watermark(text or None, link or None)
    try:
        add_watermark_text_to_pdf(
            watermark,
            in_pdf,
            out_pdf,
            font=font or None,
            fsize=int(fsize) if fsize else None,
            fcolor=fcolor or None,
        )
    except WatermarkError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
