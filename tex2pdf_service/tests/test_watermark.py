import os
import unittest

from tex2pdf.pdf_watermark import gen_watermark_pdf, add_watermark_text_to_pdf

watermark_pdf = "tests/test-output/watermark.pdf"
in_pdf = "tests/fixture/smoke/Test.pdf"

class MyTestCase(unittest.TestCase):

    def setUp(self) -> None:
        os.makedirs(os.path.dirname(watermark_pdf), exist_ok=True)

    def test_watermark_pdf(self):
        if os.path.exists(watermark_pdf):
            os.unlink(watermark_pdf)
        gen_watermark_pdf("This is a watermark!", in_pdf, watermark_pdf)
        with open(watermark_pdf, "rb") as pdfd:
            self.assertTrue(pdfd.read(4) == b"%PDF")

    def test_watermarking(self):
        add_watermark_text_to_pdf("""<link href="https://en.wikipedia.org/wiki/Waterworld">Water World</link> is in Orlando, FL.""", in_pdf,
                                   "tests/test-output/Test.pdf")

if __name__ == '__main__':
    unittest.main()
