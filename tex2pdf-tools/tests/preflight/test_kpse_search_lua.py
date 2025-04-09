import subprocess
import unittest

from itertools import zip_longest

def run_script_get_output(stdin_lines: list[str], debug: str|None = None, workdir: str|None = None) -> list[str]:
    if workdir is None:
        workdir = "."
    exec_l = ["texlua", "tex2pdf_tools/preflight/kpse_search.lua", "-mark-sys-files", workdir]
    if debug:
        exec_l.append(debug)
    p = subprocess.run(
        exec_l,
        input="\n".join(stdin_lines),
        capture_output=True,
        text=True,
        check=False,
    )
    return p.stdout.splitlines()

class TestLuaScript(unittest.TestCase):
    def test_missing_input(self):
        ret = run_script_get_output([])
        self.assertEqual(ret, ["No paths read from stdin."])

    def test_settings(self):
        inp = ["#graphicspath=foo:bar", "#programname=pdflatex"]
        ret = run_script_get_output(inp, "-v")
        self.assertEqual(ret, [
            "DEBUG: ===== GRAPHICS PATH = foo:bar",
            "DEBUG: ===== PROGRAM NAME  = pdflatex",
            "No paths read from stdin."
        ])

    def test_multiple_article(self):
        inp = ["article", "cls", "article", "tex"]
        ret = run_script_get_output(inp, workdir="tests/preflight/fixture/overlapping-filenames")
        self.assertEqual(len(ret), 6)
        # we cannot directly compare, since the return might have different order
        for fname, exts, found in zip_longest(*[iter(ret)] * 3, fillvalue=""):
            if exts == "cls":
                self.assertEqual(found[:7], "SYSTEM:")
            elif exts == "tex":
                self.assertEqual(found, "./article.tex")
            else:
                self.assertFalse()
