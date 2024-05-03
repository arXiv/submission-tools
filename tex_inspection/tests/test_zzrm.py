import io
import unittest
import os
from tex_inspection import ZeroZeroReadMe

class Test00README(unittest.TestCase):
    fixture_dir: str

    def setUp(self):
        self.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixture"))

    def test_zzrm_v1_01(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "fake-file-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)

    def test_zzrm_v2_01(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v2_01")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "yaml-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("pdflatex", zzrm.compilation["compiler"])
        self.assertEqual(True, zzrm.postprocess["stamp"])

    def test_zzrm_v2_02(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v2_02")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "jackson-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("latex", zzrm.compilation["compiler"])
        self.assertEqual(True, zzrm.postprocess["stamp"])

    def test_zzrm_v2_03(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v2_03")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "toml-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("pdflatex", zzrm.compilation["compiler"])
        self.assertEqual(True, zzrm.postprocess["stamp"])

    def test_zzrm_v2_04(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v2_04")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", 'yaml1.tex', 'yaml2.tex'], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("pdflatex", zzrm.compilation["compiler"])
        self.assertEqual(True, zzrm.postprocess["stamp"])

    def test_zzrm_out_yaml(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        sio = io.StringIO()
        zzrm.to_yaml(sio)
        sio.flush()
        sio.seek(0)
        data = sio.read()
        expected = \
"""compilation:
  compiler: pdflatex
  fontmaps:
  - myfonts1.map
  - myfonts2.map
sources:
- filename: fake-file-1.tex
  included: true
- filename: fake-file-2.tex
- filename: fake-file-3.TEX
  ignored: true
- filename: fake-file-2.dvi
  orientation: landscape
- filename: fake-file-4.dvi
  keep_comments: true
- filename: fake-file-5.tex
postprocess:
  stamp: false
"""
        self.assertEqual(expected, data)

    def test_zzrm_out_toml(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        sio = io.StringIO()
        zzrm.to_toml(sio)
        sio.flush()
        sio.seek(0)
        data = sio.read()
        expected = \
"""[[sources]]
filename = "fake-file-1.tex"
included = true

[[sources]]
filename = "fake-file-2.tex"

[[sources]]
filename = "fake-file-3.TEX"
ignored = true

[[sources]]
filename = "fake-file-2.dvi"
orientation = "landscape"

[[sources]]
filename = "fake-file-4.dvi"
keep_comments = true

[[sources]]
filename = "fake-file-5.tex"

[compilation]
compiler = "pdflatex"
fontmaps = [ "myfonts1.map", "myfonts2.map",]

[postprocess]
stamp = false
"""
        self.assertEqual(expected, data)

    def test_zzrm_out_json(self):
        dir_path = os.path.join(self.fixture_dir, "zzrm", "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        sio = io.StringIO()
        zzrm.to_json(sio)
        sio.flush()
        sio.seek(0)
        data = sio.read()
        expected = \
"""{
    "compilation": {
        "compiler": "pdflatex",
        "fontmaps": [
            "myfonts1.map",
            "myfonts2.map"
        ]
    },
    "sources": [
        {
            "filename": "fake-file-1.tex",
            "included": true
        },
        {
            "filename": "fake-file-2.tex"
        },
        {
            "filename": "fake-file-3.TEX",
            "ignored": true
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
            "filename": "fake-file-5.tex"
        }
    ],
    "postprocess": {
        "stamp": false
    }
}"""
        self.assertEqual(expected, data)
