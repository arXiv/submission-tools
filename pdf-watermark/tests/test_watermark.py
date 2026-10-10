import os
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import pdf_oxide
import pikepdf
from PIL import Image, ImageChops

from arxiv_pdf_watermark import (
    Watermark,
    WatermarkTimeout,
    _watermark_should_overlay,
    add_watermark_text_to_pdf,
    add_watermark_text_to_pdf_bounded,
)

SELF_DIR = os.path.abspath(os.path.dirname(__file__))

watermark_pdf = os.path.join(SELF_DIR, "output/watermark.pdf")
in_pdf = os.path.join(SELF_DIR, "fixture/Test.pdf")

CUSTOM_FONT_BASENAME = "IBMPlexSans-Medium.otf"

_FONT_FILE_KEYS = ("/FontFile", "/FontFile2", "/FontFile3")


def _embedded_font_basefonts(path: str) -> set[str]:
    """Return the BaseFont names of every embedded (FontFile) font on page 0.

    Recurses into Form XObject resources (the watermark text is composited as an
    XObject) and into Type0 descendant fonts (where the font program lives).
    """
    names: set[str] = set()

    def _has_program(font_obj) -> bool:
        if any(k in font_obj for k in _FONT_FILE_KEYS):
            return True
        descriptor = font_obj.get("/FontDescriptor")
        if descriptor is not None and any(k in descriptor for k in _FONT_FILE_KEYS):
            return True
        for descendant in font_obj.get("/DescendantFonts", []) or []:
            fd = descendant.get("/FontDescriptor")
            if fd is not None and any(k in fd for k in _FONT_FILE_KEYS):
                return True
        return False

    def _scan(resources) -> None:
        for font_obj in dict(resources.get("/Font", {})).values():
            if _has_program(font_obj):
                names.add(str(font_obj.get("/BaseFont")))
        for xobject in dict(resources.get("/XObject", {})).values():
            if "/Resources" in xobject:
                _scan(xobject.Resources)

    with pikepdf.open(path) as pdf:
        _scan(pdf.pages[0].Resources)
    return names


def _core_ink_color(path: str) -> tuple[int, int, int]:
    """Return the average RGB of the watermark's core (non-antialiased) ink.

    Renders page 0 at 150 dpi, restricts to the left-margin band where the
    watermark sits, and averages only the strongly-inked pixels (channel sum
    < 450) so anti-aliased edges near white do not skew the result.
    """
    doc = pdf_oxide.PdfDocument(path)
    pixmap = doc.render_pixmap(0, dpi=150)
    image = Image.frombytes("RGBA", (pixmap.width, pixmap.height), pixmap.data).convert("RGB")
    strip = image.crop((0, 0, int(40 * 150 / 72), image.height))
    ink = [p for p in strip.get_flattened_data() if sum(p) < 450]
    if not ink:
        raise AssertionError("no watermark ink found in the left margin")
    return tuple(round(sum(channel) / len(ink)) for channel in zip(*ink))  # type: ignore[return-value]


def _extracted_watermark_text(path: str) -> str:
    """Reconstruct the watermark string from the first page.

    The watermark is composited as a rotated (90°) Form XObject. pdf_oxide's
    ``to_plain_text``/``extract_text`` drop such rotated-XObject spans during
    reading-order assembly (they collapse to zero spans), so use
    ``extract_chars`` -- which recovers every glyph via the font's ToUnicode
    CMap -- and order the chars bottom-to-top (ascending ``origin_y``), the
    direction the vertical watermark reads.
    """
    doc = pdf_oxide.PdfDocument(path)
    chars = doc.extract_chars(0)
    return "".join(c.char for c in sorted(chars, key=lambda c: c.origin_y))


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

    def test_watermark_is_centered_and_unclipped(self):
        """Watermark must span the full text length and be vertically centered.

        Regression guard against a leaked page base-CTM shrinking/clipping it:
        ``in_pdf`` (Test.pdf) sets an unbalanced base transform in its content
        stream; without isolating it the watermark collapses to ~1/4 size near
        the top of the page.
        """
        text = "Water World is in Orlando, FL."
        out_path = os.path.join(SELF_DIR, "output/Test_centered.pdf")
        add_watermark_text_to_pdf(Watermark(text, None), in_pdf, out_path)

        # Render page 0 (72 dpi -> 1 px per point) and locate the watermark ink
        # in the left margin. The render glyph shapes may be wrong (a known
        # pdf_oxide rasterizer quirk for /Encoding-less base-14 fonts) but the
        # ink position and extent are accurate.
        doc = pdf_oxide.PdfDocument(out_path)
        page_height = doc.page_media_box(0)[3]
        pixmap = doc.render_pixmap(0, dpi=72)
        image = Image.frombytes("RGBA", (pixmap.width, pixmap.height), pixmap.data).convert("RGB")
        strip = image.crop((0, 0, 60, image.height))
        bbox = ImageChops.difference(strip, Image.new("RGB", strip.size, (255, 255, 255))).getbbox()
        self.assertIsNotNone(bbox, "no watermark ink found in the left margin")
        # Pixel space is top-left origin; convert the vertical span to PDF points.
        y_low, y_high = page_height - bbox[3], page_height - bbox[1]
        length = y_high - y_low
        center = (y_low + y_high) / 2.0
        # The text is ~250 pt long at 20 pt; a clipped watermark would be ~60 pt.
        self.assertGreater(length, 180, f"watermark looks clipped: span {length:.0f} pt")
        self.assertAlmostEqual(
            center, page_height / 2.0, delta=60, msg=f"watermark not vertically centered: center {center:.0f} pt"
        )

    def test_default_watermark_is_gray_not_black(self):
        """The default watermark must render in #808080 gray, not full black.

        Regression guard: pdf_oxide's inline_color() emits the glyphs without a
        fill-color operator, so without _inject_fill_color the text would fall
        back to the default black. Verify the stamped ink is the requested gray.
        """
        out_path = os.path.join(SELF_DIR, "output/Test_gray.pdf")
        add_watermark_text_to_pdf(Watermark("arXiv:2601.00001", None), in_pdf, out_path)
        r, g, b = _core_ink_color(out_path)
        # #808080 == (128, 128, 128): neutral gray, clearly not black.
        self.assertAlmostEqual(r, 128, delta=16, msg=f"ink not gray: {(r, g, b)}")
        self.assertAlmostEqual(g, 128, delta=16, msg=f"ink not gray: {(r, g, b)}")
        self.assertAlmostEqual(b, 128, delta=16, msg=f"ink not gray: {(r, g, b)}")

    def test_watermark_color_is_honored(self):
        """A caller-supplied fcolor must be reflected in the stamped ink."""
        out_path = os.path.join(SELF_DIR, "output/Test_red.pdf")
        add_watermark_text_to_pdf(Watermark("arXiv:2601.00001", None), in_pdf, out_path, fcolor="#ff0000")
        r, g, b = _core_ink_color(out_path)
        self.assertGreater(r, 200, f"red channel too low: {(r, g, b)}")
        self.assertLess(g, 60, f"green channel too high: {(r, g, b)}")
        self.assertLess(b, 60, f"blue channel too high: {(r, g, b)}")


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
        # The watermark text must be present and extractable on the first page.
        self.assertIn(text, _extracted_watermark_text(out_path))
        # The custom font must be embedded (subset) and carry a "Plex" base name.
        font_names = _embedded_font_basefonts(out_path)
        self.assertTrue(
            any("Plex" in n for n in font_names),
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


class TestAddWatermarkTextToPdfBounded(unittest.TestCase):
    """add_watermark_text_to_pdf_bounded() must actually stamp, and must actually kill a hung worker.

    The worker is a genuine subprocess (python -m arxiv_pdf_watermark._watermark_worker_main),
    not a multiprocessing.Process: the hypercorn worker that calls this in
    production is itself a daemonic multiprocessing.Process, and Python
    refuses to let a daemonic process start further multiprocessing children.
    """

    def test_normal_case_produces_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "out.pdf")
            add_watermark_text_to_pdf_bounded(Watermark("arXiv:2601.00001", None), in_pdf, out_path, timeout=30)
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 0)

    def test_hung_worker_is_killed_and_raises_timeout(self):
        with mock.patch.dict(os.environ, {"TEX2PDF_WATERMARK_TEST_HANG": "1"}):
            t0 = time.perf_counter()
            with self.assertRaises(WatermarkTimeout):
                add_watermark_text_to_pdf_bounded(Watermark("x", None), in_pdf, "/tmp/wont-be-written.pdf", timeout=3)
            elapsed = time.perf_counter() - t0
        self.assertTrue(2 < elapsed < 15, f"fired at unexpected time: {elapsed}")


class TestOverlayDecision(unittest.TestCase):
    """The over/under decision looks at the band where pdf_oxide renders it.

    pdf_oxide renders the crop box turned by /Rotate, and a page beyond its
    render budget at reduced scale, so the band must be mapped into the render.
    """

    BAND = (18.0, 231.0, 32.0, 561.0)  # the stamp band on a letter page
    IN_BAND = b"0 g 20 380 10 40 re f"  # a small square inside the band
    BELOW_BAND = b"0 g 20 80 10 40 re f"  # the same square 300pt lower
    PAGES = (
        {},
        {"/CropBox": [0, 0, 612, 492]},  # trims 300pt off the top
        {"/CropBox": [10, 0, 612, 792]},
        {"/Rotate": 90},
        {"/Rotate": 180},
        {"/Rotate": 270},
        {"/MediaBox": [0, 0, 5000, 5000]},  # 25 Mpx at 72 dpi: rendered scaled down
    )

    def _overlay(self, content: bytes, entries: dict) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "page.pdf")
            with pikepdf.new() as pdf:
                pdf.add_blank_page(page_size=(612, 792))
                page = pdf.pages[0]
                page.Contents = pdf.make_stream(content)
                for key, value in entries.items():
                    page.obj[key] = value
                pdf.save(path)
            return _watermark_should_overlay(path, self.BAND)

    def test_content_in_the_band_goes_on_top_of_the_stamp(self):
        for entries in self.PAGES:
            with self.subTest(entries=entries):
                self.assertFalse(self._overlay(self.IN_BAND, entries))

    def test_stamp_goes_on_top_of_a_blank_band(self):
        for entries in self.PAGES:
            with self.subTest(entries=entries):
                self.assertTrue(self._overlay(self.BELOW_BAND, entries))


if __name__ == "__main__":
    unittest.main()
