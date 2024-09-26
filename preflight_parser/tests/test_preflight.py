import json
import os
import unittest

from preflight_parser import PreflightResponse, generate_preflight_response


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixture"))

    def test_preflight_0(self):
        """Test for empty/missing directory response."""
        dir_path = "/no/such/directory/should/exist"
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "error")
        self.assertEqual(pf.status.info, "No TeX files found")
        self.assertEqual(len(pf.detected_toplevel_files), 0)
        self.assertEqual(len(pf.tex_files), 0)

    def test_preflight_1(self):
        dir_path = os.path.join(self.fixture_dir, "include_1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.tex_files[0].used_other_files, ["ImageOfNobelPrize.jpg"])
        # check for correct detection of output==pdf when a jpg is included
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )

    def test_preflight_single_tex_1(self):
        dir_path = os.path.join(self.fixture_dir, "single_tex_1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )

    def test_preflight_single_tex_2(self):
        dir_path = os.path.join(self.fixture_dir, "single_tex_2")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        # we do NOT check for 00README entries, so nothing is ignored
        self.assertEqual(len(pf.detected_toplevel_files), 3)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )

    def test_preflight_single_tex_3(self):
        """Test recursive inclusion."""
        dir_path = os.path.join(self.fixture_dir, "single_tex_3")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )
        for tf in pf.tex_files:
            if tf.filename == "fake-file-1.tex":
                self.assertEqual(tf.used_tex_files, ["fake-file-2.TEX", "fake-file-3.tex"])
            self.assertEqual(tf.language.value, "latex")

    def test_preflight_single_tex_4(self):
        """Test recursive inclusion."""
        dir_path = os.path.join(self.fixture_dir, "single_tex_4")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 2)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )
        for tf in pf.tex_files:
            if tf.filename == "fake-file-1.tex":
                self.assertEqual(tf.used_tex_files, ["fake-file-2.TEX", "fake-file-3.tex"])
                self.assertEqual(tf.issues[0].info, "fake-package.sty")
                self.assertEqual(tf.issues[0].key.value, "file_not_found")
            self.assertEqual(tf.language.value, "latex")

    def test_preflight_multi_tex_3(self):
        """Test multiple files, inclusions, plain tex."""
        dir_path = os.path.join(self.fixture_dir, "multi_tex_3")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 8)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )
        found = False
        for tf in pf.detected_toplevel_files:
            print(f"===> {tf.filename}")
            if tf.filename == "plain-main.tex":
                self.assertEqual(
                    tf.process.compiler.json(exclude_none=True, exclude_defaults=True),
                    """{"engine": "tex", "lang": "tex", "output": "dvi", "postp": "dvips_ps2pdf"}""",
                )
                found = True
                break
        self.assertTrue(found)
        # make sure that we do not detect section3.tex as toplevel
        found = False
        for tf in pf.detected_toplevel_files:
            if tf.filename == "section3.tex":
                found = True
                break
        self.assertTrue(not found)

    def test_preflight_roundtrip(self):
        """Test roundtrip behavior from json response via PreFlightResponse to json."""
        dir_path = os.path.join(self.fixture_dir, "2311.03267")
        pf_json: str = generate_preflight_response(dir_path, json=True)
        pf_dict: dict = json.loads(pf_json)
        pf: PreflightResponse = PreflightResponse(**pf_dict)
        pf_json_roundtrip = pf.json(exclude_none=True, exclude_defaults=True)
        self.assertEqual(pf_json, pf_json_roundtrip)

    def test_preflight_pre_postamble(self):
        """Test recursive inclusion."""
        dir_path = os.path.join(self.fixture_dir, "pre-postamble")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )

    def test_preflight_bye_no_newline(self):
        """Test recursive inclusion."""
        dir_path = os.path.join(self.fixture_dir, "bye-no-newline")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "tex", "output": "dvi", "postp": "dvips_ps2pdf"}""",
        )
