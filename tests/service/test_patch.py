import os
import unittest
from tex2pdf.service.tex_patching import fix_tex_sources

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
        os.makedirs("tests/test-output", exist_ok=True)
        with open("tests/test-output/test.tex", "w", encoding="utf-8") as fd:
            fd.write(test1)
        pass

    def test_fixer(self):
        fix_tex_sources("tests/test-output", toplevels=["test.tex"])
        result = read_file("tests/test-output/test.tex")
        self.assertEqual(first_expected, result)



if __name__ == '__main__':
    unittest.main()
