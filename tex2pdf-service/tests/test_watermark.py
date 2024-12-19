import os
import unittest

from tex2pdf.pdf_watermark import Watermark, add_watermark_text_to_pdf

SELF_DIR = os.path.abspath(os.path.dirname(__file__))

watermark_pdf = os.path.join(SELF_DIR, "output/watermark.pdf")
in_pdf = os.path.join(SELF_DIR, "fixture/smoke/Test.pdf")


class MyTestCase(unittest.TestCase):
    def setUp(self) -> None:
        os.makedirs(os.path.dirname(watermark_pdf), exist_ok=True)

    def test_watermarking(self):
        add_watermark_text_to_pdf(
            Watermark("Water World is in Orlando, FL.", "https://en.wikipedia.org/wiki/Waterworld"),
            in_pdf,
            os.path.join(SELF_DIR, "output/Test.pdf"),
        )


if __name__ == "__main__":
    unittest.main()
