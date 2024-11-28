import os
import unittest
from tex2pdf.service.tex_patching import fix_tex_sources

TEST_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)), "output/test-patch")

test1 = r"""
\usepackage{minted}
\usepackage[frozencache]{minted}
\usepackage{auto-pst-pdf}
\usepackage[testing]{auto-pst-pdf}
\graphicspath{{foo}}
\graphicspath{{foo}{bar/}{baz}}
"""

first_expected = r"""
\usepackage{minted}
\usepackage[frozencache]{minted}
%\usepackage{auto-pst-pdf}
%\usepackage[testing]{auto-pst-pdf}
\graphicspath{{foo}{foo/}}
\graphicspath{{foo}{foo/}{bar/}{baz}{baz/}}
"""

def read_file(filename) -> str:
    with open(filename, "r", encoding="utf-8") as fd:
        return fd.read()

class TestTexPatch(unittest.TestCase):
    def setUp(self):
        os.makedirs(TEST_DIR, exist_ok=True)
        with open(os.path.join(TEST_DIR, "test.tex"), "w", encoding="utf-8") as fd:
            fd.write(test1)
        pass

    def test_fixer(self):
        fix_tex_sources(TEST_DIR, toplevels=["test.tex"])
        result = read_file(os.path.join(TEST_DIR, "test.tex"))
        self.assertEqual(first_expected, result)



if __name__ == '__main__':
    unittest.main()
