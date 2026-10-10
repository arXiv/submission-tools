"""Re-export of arxiv_pdf_watermark (submission-tools pdf-watermark/).

The watermark code lives in its own package now. This module stays so that
``from tex2pdf.pdf_watermark import ...`` in arxiv-converter (genpdf,
tex2pdf-api, autotex-api) keeps working; new code imports arxiv_pdf_watermark.
"""

from arxiv_pdf_watermark import (
    DEFAULT_WATERMARK_TIMEOUT,
    Watermark,
    WatermarkError,
    WatermarkFileTypeError,
    WatermarkTimeout,
    add_watermark_text_to_pdf,
    add_watermark_text_to_pdf_bounded,
)

__all__ = [
    "DEFAULT_WATERMARK_TIMEOUT",
    "Watermark",
    "WatermarkError",
    "WatermarkFileTypeError",
    "WatermarkTimeout",
    "add_watermark_text_to_pdf",
    "add_watermark_text_to_pdf_bounded",
]
