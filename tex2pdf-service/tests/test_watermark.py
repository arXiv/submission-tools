"""ConverterDriver's use of the watermark.

The watermark itself is tested in pdf-watermark/tests.
"""

import tempfile
import unittest
from unittest import mock

from arxiv_pdf_watermark import Watermark
from tex2pdf.converter_driver import ConverterDriver


class TestConverterDriverFontForwarding(unittest.TestCase):
    """ConverterDriver must forward the watermark font customization to add_watermark_text_to_pdf_bounded."""

    def _make_driver(self, **kwargs) -> ConverterDriver:
        return ConverterDriver(
            work_dir=tempfile.mkdtemp(),
            source="dummy.tar.gz",
            watermark=Watermark("watermark text", "https://arxiv.org"),
            **kwargs,
        )

    def test_defaults_forwarded(self):
        driver = self._make_driver()
        with mock.patch("tex2pdf.converter_driver.add_watermark_text_to_pdf_bounded") as stamp:
            driver._watermark("/in.pdf", "/out.pdf")
        stamp.assert_called_once_with(
            driver.water, "/in.pdf", "/out.pdf", font=None, fsize=None, fcolor=None, timeout=mock.ANY
        )
        timeout = stamp.call_args.kwargs["timeout"]
        self.assertTrue(0 < timeout <= 60)

    def test_custom_values_forwarded(self):
        driver = self._make_driver(
            watermark_font="IBMPlexSans-Medium.otf",
            watermark_font_size=32,
            watermark_font_color="#ff0000",
        )
        with mock.patch("tex2pdf.converter_driver.add_watermark_text_to_pdf_bounded") as stamp:
            driver._watermark("/in.pdf", "/out.pdf")
        stamp.assert_called_once_with(
            driver.water,
            "/in.pdf",
            "/out.pdf",
            font="IBMPlexSans-Medium.otf",
            fsize=32,
            fcolor="#ff0000",
            timeout=mock.ANY,
        )
        timeout = stamp.call_args.kwargs["timeout"]
        self.assertTrue(0 < timeout <= 60)


if __name__ == "__main__":
    unittest.main()
