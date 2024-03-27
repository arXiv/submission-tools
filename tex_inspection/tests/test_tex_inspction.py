import unittest
import os

from tex_inspection import ZeroZeroReadMe, find_primary_tex

class TestTexInspection(unittest.TestCase):
    fixture_dir: str

    def setUp(self):
        self.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixture"))

    def test_primary_single_tex_1(self):
        dir_path = os.path.join(self.fixture_dir, "inspection", "single_tex_1")
        zzrm = ZeroZeroReadMe(dir_path)
        primary_tex = find_primary_tex(dir_path, zzrm)
        self.assertEqual(["NOBEL_PRIZE_WINNER.TEX"], primary_tex)

    def test_primary_single_tex_2(self):
        dir_path = os.path.join(self.fixture_dir, "inspection", "single_tex_2")
        zzrm = ZeroZeroReadMe(dir_path)
        primary_tex = find_primary_tex(dir_path, zzrm)
        self.assertEqual(["fake-file-2.TEX"], primary_tex)

    def test_primary_single_tex_3(self):
        dir_path = os.path.join(self.fixture_dir, "inspection", "single_tex_3")
        zzrm = ZeroZeroReadMe(dir_path)
        primary_tex = find_primary_tex(dir_path, zzrm)
        self.assertEqual(["fake-file-1.tex"], primary_tex)

    def test_primary_multi_tex_1(self):
        dir_path = os.path.join(self.fixture_dir, "inspection", "multi_tex_1")
        zzrm = ZeroZeroReadMe(dir_path)
        primary_tex = find_primary_tex(dir_path, zzrm)
        self.assertEqual(["fake-file-1.Tex", "fake-file-2.tex", "fake-file-3.TEX"], primary_tex)

    def test_primary_multi_tex_2(self):
        dir_path = os.path.join(self.fixture_dir, "inspection", "multi_tex_2")
        zzrm = ZeroZeroReadMe(dir_path)
        primary_tex = find_primary_tex(dir_path, zzrm)
        self.assertEqual(["fake-file-2.tex", "fake-file-1.Tex"], primary_tex)
