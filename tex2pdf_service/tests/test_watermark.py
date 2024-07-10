import os
import unittest

from tex2pdf.pdf_watermark import add_watermark_text_to_pdf

watermark_pdf = "tests/test-output/watermark.pdf"
in_pdf = "tests/fixture/smoke/Test.pdf"

class MyTestCase(unittest.TestCase):

    def setUp(self) -> None:
        os.makedirs(os.path.dirname(watermark_pdf), exist_ok=True)

    def test_watermarking(self):
        add_watermark_text_to_pdf("Water World is in Orlando, FL.", 
                                  "https://en.wikipedia.org/wiki/Waterworld",
                                  in_pdf, "tests/test-output/Test.pdf"
                                 )

if __name__ == '__main__':
    unittest.main()
