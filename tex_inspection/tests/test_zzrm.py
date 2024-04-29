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
