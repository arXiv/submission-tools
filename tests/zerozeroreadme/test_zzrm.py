import io
import os
import unittest

import pytest

from tex2pdf.preflight_parser import ParseSyntaxError
from tex2pdf.zerozeroreadme import ZeroZeroReadMe


class Test00README(unittest.TestCase):
    fixture_dir: str

    def setUp(self) -> None:
        self.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixture"))

    def test_zzrm_v1_01(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "fake-file-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)

    def test_zzrm_v2_01(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_01")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "yaml-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("pdflatex", zzrm.process.compiler.compiler_string)
        self.assertEqual(False, zzrm.stamp)

    def test_zzrm_v2_syntax_error(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_syntax_error")
        with pytest.raises(ParseSyntaxError) as exc_info:
            _ = ZeroZeroReadMe(dir_path)
        assert str(exc_info.value).startswith("Validation error on parsing: ")

    def test_zzrm_v2_02(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_02")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "jackson-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("latex", zzrm.process.compiler.compiler_string)
        self.assertEqual(False, zzrm.stamp)

    def test_zzrm_v2_03(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_03")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "toml-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("pdflatex", zzrm.process.compiler.compiler_string)
        self.assertEqual(False, zzrm.stamp)

    def test_zzrm_v2_04(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_04")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "yaml1.tex", "yaml2.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("pdflatex", zzrm.process.compiler.compiler_string)
        self.assertEqual(False, zzrm.stamp)

    def test_zzrm_out_yaml(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        sio = io.StringIO()
        zzrm.to_yaml(sio)
        sio.flush()
        sio.seek(0)
        data = sio.read()
        expected = """process:
  compiler: pdflatex
  fontmaps:
  - myfonts1.map
  - myfonts2.map
sources:
- filename: fake-file-1.tex
  usage: include
- filename: fake-file-2.tex
  usage: toplevel
- filename: fake-file-3.TEX
  usage: ignore
- filename: fake-file-2.dvi
  orientation: landscape
- filename: fake-file-4.dvi
  keep_comments: true
- filename: fake-file-5.tex
  usage: toplevel
stamp: false
"""
        self.assertEqual(expected, data)

    def test_zzrm_out_toml(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        data = zzrm.to_toml()
        expected = """sources = [
    { filename = "fake-file-1.tex", usage = "include" },
    { filename = "fake-file-2.tex", usage = "toplevel" },
    { filename = "fake-file-3.TEX", usage = "ignore" },
    { filename = "fake-file-2.dvi", orientation = "landscape" },
    { filename = "fake-file-4.dvi", keep_comments = true },
    { filename = "fake-file-5.tex", usage = "toplevel" },
]
stamp = false

[process]
compiler = "pdflatex"
fontmaps = [
    "myfonts1.map",
    "myfonts2.map",
]
"""
        self.assertEqual(expected, data)

    def test_zzrm_out_json(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        data = zzrm.to_json()
        expected = """{
    "process": {
        "compiler": "pdflatex",
        "fontmaps": [
            "myfonts1.map",
            "myfonts2.map"
        ]
    },
    "sources": [
        {
            "filename": "fake-file-1.tex",
            "usage": "include"
        },
        {
            "filename": "fake-file-2.tex",
            "usage": "toplevel"
        },
        {
            "filename": "fake-file-3.TEX",
            "usage": "ignore"
        },
        {
            "filename": "fake-file-2.dvi",
            "orientation": "landscape"
        },
        {
            "filename": "fake-file-4.dvi",
            "keep_comments": true
        },
        {
            "filename": "fake-file-5.tex",
            "usage": "toplevel"
        }
    ],
    "stamp": false
}"""
        self.assertEqual(expected, data)
