import os
import unittest

import pytest

from tex2pdf_tools.zerozeroreadme import (
    ZeroZeroReadMe,
    ZZRMFileNotFoundError,
    ZZRMParseError,
    ZZRMUnsupportedFileError,
)

unittest.TestCase.maxDiff = None

monkeypatch = pytest.MonkeyPatch()
monkeypatch.setenv("PYTEST_RUNNING_ALLOW_CURRENT_TL", "1")

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
        self.assertEqual(zzrm.spec_version, 1)

    def test_zzrm_v1_01_from_file(self) -> None:
        file_path = os.path.join(self.fixture_dir, "zzrm_v1_01", "00README.XXX")
        zzrm = ZeroZeroReadMe(file_path)
        self.assertEqual(["fake-file-2.tex", "fake-file-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual(zzrm.spec_version, 1)

    def test_zzrm_v2_yaml_ignored(self) -> None:
        # zzrm_v2_01 contains a 00README.yaml, which is no longer supported.
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_01")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertIsNone(zzrm.readme_filename)
        self.assertIn("00README.yaml", zzrm.ignored_formats)
        self.assertEqual([], zzrm.toplevels)

    def test_zzrm_v2_yaml_ignored_from_file(self) -> None:
        file_path = os.path.join(self.fixture_dir, "zzrm_v2_01", "00README.yaml")
        zzrm = ZeroZeroReadMe(file_path)
        self.assertIsNone(zzrm.readme_filename)
        self.assertIn("00README.yaml", zzrm.ignored_formats)

    def test_zzrm_v2_syntax_error_ignored(self) -> None:
        # zzrm_v2_syntax_error contains a 00README.yaml; previously this raised
        # ZZRMParseError on parsing, now it is silently ignored with a warning.
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_syntax_error")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertIsNone(zzrm.readme_filename)
        self.assertIn("00README.yaml", zzrm.ignored_formats)

    def test_zzrm_v2_02(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_02")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(["fake-file-2.tex", "jackson-5.tex"], zzrm.toplevels)
        self.assertEqual(set(["fake-file-1.tex"]), zzrm.includes)
        self.assertEqual(set(["fake-file-3.TEX"]), zzrm.ignores)
        self.assertEqual(["myfonts1.map", "myfonts2.map"], zzrm.fontmaps)
        self.assertEqual(set(["fake-file-2.dvi"]), zzrm.landscapes)
        self.assertEqual(set(["fake-file-4.dvi"]), zzrm.keepcomments)
        self.assertEqual("latex+dvips_ps2pdf", zzrm.process.compiler.compiler_string)
        self.assertEqual(False, zzrm.stamp)
        self.assertEqual(zzrm.spec_version, 1)

    def test_zzrm_v2_toml_ignored(self) -> None:
        # zzrm_v2_03 contains a 00README.toml, which is no longer supported.
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_03")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertIsNone(zzrm.readme_filename)
        self.assertIn("00README.toml", zzrm.ignored_formats)

    def test_zzrm_v2_multiple_yaml_ignored(self) -> None:
        # zzrm_v2_04 contains multiple 00README.yaml files; all ignored.
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_04")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertIsNone(zzrm.readme_filename)
        self.assertTrue(any(f.endswith(".yaml") for f in zzrm.ignored_formats))

    def test_zzrm_v2_05(self) -> None:
        # zzrm_v2_05 has 00README.json, .yaml, and .toml. With the new policy,
        # the .yaml and .toml are ignored; the .json fixture has a schema
        # mismatch (legacy fontmaps shape) so parsing it raises.
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_05")
        with pytest.raises(ZZRMParseError):
            _ = ZeroZeroReadMe(dir_path)

    def test_zzrm_v2_unsupported_extension_raises(self) -> None:
        # init_from_file with a non-00README extension still raises.
        file_path = os.path.join(self.fixture_dir, "zzrm_v1_01", "00README.XXX")
        bad_path = file_path + ".bogus"
        with pytest.raises((ZZRMUnsupportedFileError, ZZRMFileNotFoundError)):
            _ = ZeroZeroReadMe(bad_path)

    def test_zzrm_out_json(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v1_01")
        zzrm = ZeroZeroReadMe(dir_path)
        data = zzrm.to_json()
        expected = """{
    "comment": "This is the specification file for processing source files for individual arXiv submissions.\\nDetails on the specification are at https://info.arxiv.org/help/00README.html",
    "process": {
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
    "stamp": false,
    "spec_version": 1
}"""
        self.assertEqual(expected, data)

    def test_zzrm_texlive_version(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_texlive_version")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(2024, zzrm.texlive_version)
        self.assertEqual(zzrm.spec_version, 1)

    def test_zzrm_comment(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_comment")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(zzrm.comment, "This is a genious comment")

    def test_zzrm_comment_number(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_comment_number")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(zzrm.comment, "42")

    def test_zzrm_v2_version_out_of_range(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_version_out_of_range")
        with pytest.raises(ZZRMParseError):
            _ = ZeroZeroReadMe(dir_path)

    def test_zzrm_pdftex(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_pdftex")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual("pdftex", zzrm.process.compiler.compiler_string)

    def test_zzrm_pdfetex(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_pdfetex")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual("pdftex", zzrm.process.compiler.compiler_string)

    def test_zzrm_tl_version_current(self) -> None:
        dir_path = os.path.join(self.fixture_dir, "zzrm_v2_current")
        zzrm = ZeroZeroReadMe(dir_path)
        self.assertEqual(2025, zzrm.texlive_version)
