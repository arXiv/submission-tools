import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import pymupdf
from tex2pdf.converter_driver import ConverterDriver
from tex2pdf.pdf_watermark import Watermark, add_watermark_text_to_pdf

SELF_DIR = os.path.abspath(os.path.dirname(__file__))

watermark_pdf = os.path.join(SELF_DIR, "output/watermark.pdf")
in_pdf = os.path.join(SELF_DIR, "fixture/smoke/Test.pdf")

CUSTOM_FONT_BASENAME = "IBMPlexSans-Medium.otf"


def _kpsewhich_font() -> str | None:
    """Return absolute path of CUSTOM_FONT_BASENAME via kpsewhich, else None."""
    if not shutil.which("kpsewhich"):
        return None
    result = subprocess.run(["kpsewhich", CUSTOM_FONT_BASENAME], capture_output=True, text=True, check=False)
    path = result.stdout.strip()
    return path if path and os.path.exists(path) else None


class MyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        os.makedirs(os.path.dirname(watermark_pdf), exist_ok=True)

    def test_watermarking(self):
        add_watermark_text_to_pdf(
            Watermark("Water World is in Orlando, FL.", "https://en.wikipedia.org/wiki/Waterworld"),
            in_pdf,
            os.path.join(SELF_DIR, "output/Test.pdf"),
        )


@unittest.skipUnless(_kpsewhich_font(), f"{CUSTOM_FONT_BASENAME} not found via kpsewhich")
class TestCustomFont(unittest.TestCase):
    """Tests for the custom-font branch of add_watermark_text_to_pdf.

    Each test produces a PDF and verifies that it opens, contains the watermark
    text, and embeds the custom font under the registered name.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.font_full_path = _kpsewhich_font()
        cls.font_basename = CUSTOM_FONT_BASENAME
        cls.out_dir = os.path.join(SELF_DIR, "output")
        os.makedirs(cls.out_dir, exist_ok=True)

    def _assert_watermark_pdf(self, out_path: str, text: str) -> None:
        self.assertTrue(os.path.exists(out_path), f"{out_path} was not produced")
        self.assertGreater(os.path.getsize(out_path), 0)
        with pymupdf.open(out_path) as doc:
            self.assertTrue(doc.is_pdf)
            page_text = doc[0].get_text()
            self.assertIn(text, page_text)
            # After subset_fonts() the font is renamed to "<6-char prefix>+IBM Plex Sans Medium".
            font_names = {f[3] for f in doc[0].get_fonts()}
            self.assertTrue(
                any("IBM Plex Sans" in n or "Plex" in n for n in font_names),
                f"Custom font not embedded; saw fonts: {font_names}",
            )

    def test_custom_font_full_path(self):
        text = "Watermark via full path"
        out_path = os.path.join(self.out_dir, "Test_font_fullpath.pdf")
        add_watermark_text_to_pdf(
            Watermark(text, "https://arxiv.org"),
            in_pdf,
            out_path,
            font=self.font_full_path,
        )
        self._assert_watermark_pdf(out_path, text)

    def test_custom_font_kpsewhich_lookup(self):
        text = "Watermark via kpsewhich"
        out_path = os.path.join(self.out_dir, "Test_font_kpsewhich.pdf")
        add_watermark_text_to_pdf(
            Watermark(text, "https://arxiv.org"),
            in_pdf,
            out_path,
            font=self.font_basename,
        )
        self._assert_watermark_pdf(out_path, text)

    def test_custom_font_red_large(self):
        text = "Big red watermark"
        out_path = os.path.join(self.out_dir, "Test_font_red_large.pdf")
        add_watermark_text_to_pdf(
            Watermark(text, "https://arxiv.org"),
            in_pdf,
            out_path,
            font=self.font_basename,
            fsize=32,
            fcolor="#ff0000",
        )
        self._assert_watermark_pdf(out_path, text)

    def test_custom_font_blue_small(self):
        text = "Small blue watermark"
        out_path = os.path.join(self.out_dir, "Test_font_blue_small.pdf")
        add_watermark_text_to_pdf(
            Watermark(text, "https://arxiv.org"),
            in_pdf,
            out_path,
            font=self.font_basename,
            fsize=10,
            fcolor="#0000ff",
        )
        self._assert_watermark_pdf(out_path, text)


class TestConverterDriverFontForwarding(unittest.TestCase):
    """ConverterDriver must forward the watermark font customization to add_watermark_text_to_pdf."""

    def _make_driver(self, **kwargs) -> ConverterDriver:
        return ConverterDriver(
            work_dir=tempfile.mkdtemp(),
            source="dummy.tar.gz",
            watermark=Watermark("watermark text", "https://arxiv.org"),
            **kwargs,
        )

    def test_defaults_forwarded(self):
        driver = self._make_driver()
        with mock.patch("tex2pdf.converter_driver.add_watermark_text_to_pdf") as stamp:
            driver._watermark("/in.pdf", "/out.pdf")
        stamp.assert_called_once_with(driver.water, "/in.pdf", "/out.pdf", font=None, fsize=None, fcolor=None)

    def test_custom_values_forwarded(self):
        driver = self._make_driver(
            watermark_font="IBMPlexSans-Medium.otf",
            watermark_font_size=32,
            watermark_font_color="#ff0000",
        )
        with mock.patch("tex2pdf.converter_driver.add_watermark_text_to_pdf") as stamp:
            driver._watermark("/in.pdf", "/out.pdf")
        stamp.assert_called_once_with(
            driver.water,
            "/in.pdf",
            "/out.pdf",
            font="IBMPlexSans-Medium.otf",
            fsize=32,
            fcolor="#ff0000",
        )


if __name__ == "__main__":
    unittest.main()
