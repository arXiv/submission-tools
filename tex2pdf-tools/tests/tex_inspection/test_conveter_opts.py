import os
import unittest

from tex2pdf_tools.tex_inspection import find_pdfoutput_1


class TestConverterSelection(unittest.TestCase):
    def setUp(self):
        self.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixture"))

    def test_yes(self):
        this_fixture = os.path.join(self.fixture_dir, "inspection", "pdfoutput_1")
        yes = find_pdfoutput_1("fake-file-1.Tex", this_fixture)
        self.assertTrue(yes)
        pass

    def test_no(self):
        this_fixture = os.path.join(self.fixture_dir, "inspection", "multi_tex_1")
        yes = find_pdfoutput_1("fake-file-1.Tex", this_fixture)
        self.assertFalse(yes)
        pass


if __name__ == "__main__":
    unittest.main()
