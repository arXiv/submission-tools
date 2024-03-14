import unittest

from tex2pdf.tex_inspection import find_pdfoutput_1

class TestConverterSelection(unittest.TestCase):
    def test_yes(self):
        yes = find_pdfoutput_1("fake-file-1.Tex", "tests/fixture/inspection/pdfoutput_1")
        self.assertTrue(yes)
        pass

    def test_no(self):
        yes = find_pdfoutput_1("fake-file-1.Tex", "tests/fixture/inspection/multi_tex_1")
        self.assertFalse(yes)
        pass


if __name__ == '__main__':
    unittest.main()
