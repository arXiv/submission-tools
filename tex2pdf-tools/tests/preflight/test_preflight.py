import json
import os
import unittest

from tex2pdf_tools.preflight import BibCompiler, IssueType
from tex2pdf_tools.preflight import PreflightResponse, generate_preflight_response


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
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )

    def test_preflight_single_tex_1(self):
        dir_path = os.path.join(self.fixture_dir, "single_tex_1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )

    def test_preflight_single_tex_2(self):
        dir_path = os.path.join(self.fixture_dir, "single_tex_2")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        # we do NOT check for 00README entries, so nothing is ignored
        self.assertEqual(len(pf.detected_toplevel_files), 3)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )

    def test_preflight_single_tex_3(self):
        """Test recursive inclusion."""
        dir_path = os.path.join(self.fixture_dir, "single_tex_3")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
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
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
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
        found = False
        for tf in pf.detected_toplevel_files:
            if tf.filename == "main.tex":
                self.assertEqual(
                    tf.process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
                    """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
                )
                found = True
                break
        self.assertTrue(found)
        found = False
        for tf in pf.detected_toplevel_files:
            if tf.filename == "plain-main.tex":
                self.assertEqual(
                    tf.process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
                    """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvips_ps2pdf"}""",
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
        pf_json_roundtrip = pf.model_dump_json(exclude_none=True, exclude_defaults=True)
        self.assertEqual(pf_json, pf_json_roundtrip)

    def test_preflight_pre_postamble(self):
        """Test recursive inclusion."""
        dir_path = os.path.join(self.fixture_dir, "pre-postamble")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )

    def test_preflight_bye_no_newline(self):
        """Test recursive inclusion."""
        dir_path = os.path.join(self.fixture_dir, "bye-no-newline")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )

    def test_preflight_pdf_only_submission(self):
        """Test PDF only submission."""
        dir_path = os.path.join(self.fixture_dir, "single-pdf")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "hello-world.pdf")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"pdf","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(pf.detected_toplevel_files[0].process.compiler.compiler_string, "pdf_submission")

    def test_preflight_multi_pdf_only_submission(self):
        """Test PDF only submission."""
        dir_path = os.path.join(self.fixture_dir, "multi-pdf")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 2)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "foo.pdf")
        self.assertEqual(pf.detected_toplevel_files[1].filename, "hello-world.pdf")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"pdf","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(
            pf.detected_toplevel_files[1].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"pdf","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(pf.detected_toplevel_files[0].process.compiler.compiler_string, "pdf_submission")
        self.assertEqual(pf.detected_toplevel_files[1].process.compiler.compiler_string, "pdf_submission")

    def test_preflight_html_only_submission(self):
        """Test HTML only submission."""
        dir_path = os.path.join(self.fixture_dir, "html_1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "paper.html")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"html","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.compiler_string,
            "html_submission"
        )

    def test_preflight_multi_html_only_submission(self):
        """Test HTML only submission."""
        dir_path = os.path.join(self.fixture_dir, "html_multi")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 2)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "another.html")
        self.assertEqual(pf.detected_toplevel_files[1].filename, "paper.html")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"html","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(
            pf.detected_toplevel_files[1].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"html","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.compiler_string,
            "html_submission"
        )
        self.assertEqual(
            pf.detected_toplevel_files[1].process.compiler.compiler_string,
            "html_submission"
        )

    def test_anc_files_submission(self):
        """Test submission with ancillary files."""
        dir_path = os.path.join(self.fixture_dir, "anc_files_1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )
        self.assertEqual(len(pf.ancillary_files), 2)

    def test_index_biblio_1(self):
        """Test index and bibliographies."""
        dir_path = os.path.join(self.fixture_dir, "index_test_1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )
        self.assertEqual(
            pf.detected_toplevel_files[0].process.index.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"pre_generated":true}"""
        )
        self.assertEqual(
            pf.detected_toplevel_files[0].process.bibliography.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"pre_generated":true}"""
        )
        for tf in pf.tex_files:
            if tf.filename == "ms.tex":
                self.assertEqual(tf.used_tex_files, ["the-rest.tex"])
                self.assertEqual(tf.used_idx_files, ["ms.adx", "ms.bdx"])
                self.assertEqual(tf.used_ind_files, ["ms.and", "ms.bnd"])
                self.assertEqual(tf.used_other_files, ["ms.bbl"])

    def test_index_biblio_2(self):
        """Test index and bibliographies - missing index definition."""
        dir_path = os.path.join(self.fixture_dir, "index_test_2")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        for tf in pf.detected_toplevel_files:
            if tf.filename == "ms.tex":
                self.assertEqual(len(tf.issues), 1)
                self.assertEqual(tf.issues[0].info, "index definition for tag-b not found")

    def test_preflight_no_hyperref(self):
        dir_path = os.path.join(self.fixture_dir, "single_tex_1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(pf.detected_toplevel_files[0].hyperref_found, False)

    def test_preflight_with_hyperref(self):
        dir_path = os.path.join(self.fixture_dir, "use_hyperref")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(pf.detected_toplevel_files[0].hyperref_found, True)

    def test_eps_dvips(self):
        """Test dvips_ps2pdf selection when eps are included."""
        dir_path = os.path.join(self.fixture_dir, "eps-test")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )

    def test_mixed_images(self):
        """Test failure when mixing png and eps."""
        dir_path = os.path.join(self.fixture_dir, "mixed-images")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        self.assertTrue(pf.detected_toplevel_files[0].process.compiler is None)
        self.assertEqual(
            pf.detected_toplevel_files[0].issues[0].key,
            "unsupported_compiler_type"
        )

    def test_multi_include_cmds(self):
        """Test multiple consecutive include commands."""
        dir_path = os.path.join(self.fixture_dir, "multi-include-cmds")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        found_main = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_tex_files), ["a.sty", "b.sty", "c.tex", "e.tex"])
                self.assertEqual(sorted(tf.used_other_files), ["aa.jpg", "bb.jpg", "cc.jpg", "dd.png", "ee.jpg"])
        assert found_main

    def test_no_final_newline(self):
        """Test whether detection of include command works with no final newline."""
        dir_path = os.path.join(self.fixture_dir, "last-line-no-newline")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        found_foo_tex = False
        for tf in pf.tex_files:
            if tf.filename == "foo.tex":
                found_foo_tex = True
                self.assertEqual(tf.used_tex_files, ["bla.tex"])
        self.assertTrue(found_foo_tex)

    def test_biber_good_version(self):
        """Test bbl version matching arXiv TeX version."""
        dir_path = os.path.join(self.fixture_dir, "bbl_version_good")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(tf.process.bibliography.processor, BibCompiler.biber)
        self.assertTrue(tf.process.bibliography.pre_generated)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)

    def test_biber_bad_version(self):
        """Test bbl version not matching arXiv TeX version."""
        dir_path = os.path.join(self.fixture_dir, "bbl_version_mismatch")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(tf.process.bibliography.processor, BibCompiler.biber)
        self.assertTrue(tf.process.bibliography.pre_generated)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 1)
        issue = tf.issues[0]
        self.assertEqual(issue.key, IssueType.bbl_version_mismatch)
        self.assertEqual(issue.filename, "bla.bbl")

    def test_multi_usepackage(self):
        """Test usepackage with multiple entries."""
        dir_path = os.path.join(self.fixture_dir, "multi-usepackage")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        found_main = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_tex_files), ["a.sty", "b.sty", "c.sty"])
        assert found_main
