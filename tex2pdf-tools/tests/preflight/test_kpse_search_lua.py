import subprocess
import unittest

def run_script_get_output(stdin_lines: list[str]) -> list[str]:
    p = subprocess.run(
        ["texlua", "tex2pdf_tools/preflight/kpse_search.lua", "-mark-sys-files", "."],
        input="\n".join(stdin_lines),
        capture_output=True,
        text=True,
        check=False,
    )
    return p.stdout.splitlines()

class TestLuaScript(unittest.TestCase):
    def test_simple(self):
        inp = ["#graphicspath=foo:bar", "#programname=pdflatex"]
        ret = run_script_get_output(inp)
        self.assertEqual(ret, [
            "DEBUG: ===== GRAPHICS PATH = foo:bar",
            "DEBUG: ===== PROGRAM NAME  = pdflatex",
            "No paths read from stdin."
        ])

