import subprocess
import unittest

def run_script_get_output(stdin_lines: list[str], debug: str|None = None) -> list[str]:
    exec_l = ["texlua", "tex2pdf_tools/preflight/kpse_search.lua", "-mark-sys-files", "."]
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

