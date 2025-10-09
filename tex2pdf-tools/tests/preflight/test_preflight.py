import json
import os
import pytest
import unittest
from mock import patch

import tex2pdf_tools.preflight
from tex2pdf_tools.preflight import BibCompiler, IssueType, UNICODE_TEX_PACKAGES
from tex2pdf_tools.preflight import PreflightResponse, generate_preflight_response

tex2pdf_tools.preflight.ENABLE_PDFETEX = True
tex2pdf_tools.preflight.ENABLE_XELATEX = True
tex2pdf_tools.preflight.update_list_of_supported_compilers()
UPDATED_COMPILER_LIST = tex2pdf_tools.preflight.SUPPORTED_COMPILERS.copy()
UPDATED_COMPILER_STR_LIST = tex2pdf_tools.preflight.SUPPORTED_COMPILERS_STR.copy()
# Reset the compiler list to the original state after tests
tex2pdf_tools.preflight.ENABLE_PDFETEX = False
tex2pdf_tools.preflight.ENABLE_XELATEX = False
tex2pdf_tools.preflight.update_list_of_supported_compilers()

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
            """{"pre_generated":true,"can_be_generated":true}"""
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

    @patch('tex2pdf_tools.preflight.SUPPORTED_COMPILERS', UPDATED_COMPILER_LIST)
    @patch('tex2pdf_tools.preflight.SUPPORTED_COMPILERS_STR', UPDATED_COMPILER_STR_LIST)
    def test_eps_dvips_enable_pdfetex(self):
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

    def test_epsfig_dvips(self):
        """Test epsfig image extraction."""
        dir_path = os.path.join(self.fixture_dir, "epsfig-test")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(pf.detected_toplevel_files[0].filename, "main.tex")
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                self.assertEqual(
                    sorted(tf.used_other_files),
                    ["bla.eps", "foo.eps"]
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
            IssueType.unsupported_compiler_type_image_mix
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

    def test_biber_good_version_32(self):
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
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.bbl_version_needs_previous_version)

    def test_biber_good_version_33(self):
        """Test bbl version not matching arXiv TeX version."""
        dir_path = os.path.join(self.fixture_dir, "bbl_version_good_33")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(tf.process.bibliography.processor, BibCompiler.biber)
        self.assertTrue(tf.process.bibliography.pre_generated)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)

    def test_biber_bad_version_31(self):
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

    def test_svg_compiler_detection(self):
        """Test correct compiler detection despite unsupported img extension."""
        dir_path = os.path.join(self.fixture_dir, "svg-include-compiler")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(
            pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )

    def test_overlapping_filenames(self):
        """Test same filename for multiple file types."""
        dir_path = os.path.join(self.fixture_dir, "overlapping-filenames")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        found_main = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_tex_files), ["article.tex"])
        assert found_main

    def test_overpic_filenames(self):
        """Test overpic environment detection."""
        dir_path = os.path.join(self.fixture_dir, "overpic")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        found_main = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_other_files), ["foo.jpg"])
        assert found_main

    def test_addplot_filenames(self):
        """Test addplot environment detection."""
        dir_path = os.path.join(self.fixture_dir, "addplot")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        found_main = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_other_files), ["data1.txt", "data2.txt"])
        assert found_main

    def test_addplot_2(self):
        """Test addplot environment detection."""
        dir_path = os.path.join(self.fixture_dir, "addplot-2")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 1)
        self.assertEqual(pf.tex_files[0].used_other_files, ['something.csv'])

    def test_quoted_arguments(self):
        """Test quoted arguments to commands."""
        dir_path = os.path.join(self.fixture_dir, "quoted-arguments")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        found_main = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_other_files), ["bla bla.jpg", "foo.png"])
        assert found_main

    def test_bbl_bib(self):
        """Test submission with bbl and bib present."""
        tex2pdf_tools.preflight.ENABLE_BIB_BBL = False
        dir_path = os.path.join(self.fixture_dir, "bbl-bib")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertTrue(tf.process.bibliography.pre_generated)
        self.assertTrue(tf.process.bibliography.can_be_generated)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(tf.used_bib_files, ["xxx.bib"])
        self.assertEqual(tf.used_other_files, ["main.bbl"])

    def test_bbl_no_bib(self):
        """Test submission with bbl but without bib present."""
        dir_path = os.path.join(self.fixture_dir, "bbl-no-bib")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertTrue(tf.process.bibliography.pre_generated)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(tf.used_bib_files, [])
        self.assertEqual(tf.used_other_files, ["main.bbl"])

    @patch('tex2pdf_tools.preflight.ENABLE_BIB_BBL', True)
    def test_bib_no_bbl(self):
        """Test submission with bib but without bbl present."""
        dir_path = os.path.join(self.fixture_dir, "bib-no-bbl")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertFalse(tf.process.bibliography.pre_generated)
        # bbl is missing, but we have bib around
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(tf.used_bib_files, ["xxx.bib"])
        self.assertEqual(tf.used_other_files, [])

    @patch('tex2pdf_tools.preflight.ENABLE_BIB_BBL', False)
    def test_bib_no_bbl_bib2bbl_disabled(self):
        """Test submission with bib but without bbl present."""
        dir_path = os.path.join(self.fixture_dir, "bib-no-bbl")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertFalse(tf.process.bibliography.pre_generated)
        # bbl is missing, but we have bib around
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.bbl_file_missing)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(tf.used_bib_files, ["xxx.bib"])
        self.assertEqual(tf.used_other_files, [])


    @patch('tex2pdf_tools.preflight.ENABLE_BIB_BBL', True)
    def test_multi_bib_no_bbl(self):
        """Test submission with multiple bib, no bbl, one bib missing."""
        dir_path = os.path.join(self.fixture_dir, "multi-bib-no-bbl")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertFalse(tf.process.bibliography.pre_generated)
        # bbl is missing, but we have bib around
        self.assertEqual(len(tf.issues), 2)
        self.assertEqual(
            sorted([issue.key for issue in tf.issues]),
            [IssueType.bbl_bib_file_missing, IssueType.issue_in_subfile]
        )
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.file_not_found)
        self.assertEqual(tf.issues[0].filename, "yyy.bib")
        self.assertEqual(tf.used_bib_files, ["xxx.bib"])
        self.assertEqual(tf.used_other_files, [])

    @patch('tex2pdf_tools.preflight.ENABLE_BIB_BBL', False)
    def test_multi_bib_no_bbl_bib2bbl_disabled(self):
        """Test submission with multiple bib, no bbl, one bib missing."""
        dir_path = os.path.join(self.fixture_dir, "multi-bib-no-bbl")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertFalse(tf.process.bibliography.pre_generated)
        # bbl is missing, but we have bib around
        self.assertEqual(len(tf.issues), 2)
        self.assertEqual(
            sorted([issue.key for issue in tf.issues]),
            [IssueType.bbl_file_missing, IssueType.issue_in_subfile]
        )
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.file_not_found)
        self.assertEqual(tf.issues[0].filename, "yyy.bib")
        self.assertEqual(tf.used_bib_files, ["xxx.bib"])
        self.assertEqual(tf.used_other_files, [])

    @patch('tex2pdf_tools.preflight.ENABLE_BIB_BBL', True)
    def test_no_bbl_no_bib(self):
        """Test submission with no bib nor bbl present."""
        dir_path = os.path.join(self.fixture_dir, "no-bbl-no-bib")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertFalse(tf.process.bibliography.pre_generated)
        self.assertEqual(len(tf.issues), 2)
        self.assertEqual(
            sorted([issue.key for issue in tf.issues]),
            [IssueType.bbl_bib_file_missing, IssueType.issue_in_subfile]
        )
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.file_not_found)
        self.assertEqual(tf.issues[0].filename, "xxx.bib")
        self.assertEqual(tf.used_bib_files, [])
        self.assertEqual(tf.used_other_files, [])

    @patch('tex2pdf_tools.preflight.ENABLE_BIB_BBL', False)
    def test_no_bbl_no_bib_bib2bbl_disabled(self):
        """Test submission with no bib nor bbl present."""
        dir_path = os.path.join(self.fixture_dir, "no-bbl-no-bib")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertFalse(tf.process.bibliography.pre_generated)
        self.assertEqual(len(tf.issues), 2)
        self.assertEqual(
            sorted([issue.key for issue in tf.issues]),
            [IssueType.bbl_file_missing, IssueType.issue_in_subfile]
        )
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.file_not_found)
        self.assertEqual(tf.issues[0].filename, "xxx.bib")
        self.assertEqual(tf.used_bib_files, [])
        self.assertEqual(tf.used_other_files, [])

    def test_biber_bibtex_mix(self):
        """Test submission with no bib nor bbl present."""
        dir_path = os.path.join(self.fixture_dir, "bibtex-and-biber")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.multiple_bibliography_types)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(tf.used_bib_files, ["xxx.bib", "xxx.bib"])
        self.assertEqual(tf.used_other_files, [])

    def test_biblatex_with_bibliography(self):
        """Test submission with using biblatex and \bibliography."""
        dir_path = os.path.join(self.fixture_dir, "biblatex-bibliography")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        self.assertEqual(tf.used_bib_files, ["xxx.bib"])
        self.assertEqual(tf.used_other_files, ["main.bbl"])

    def test_double_slash_normalization(self):
        """Test double slash normalization present."""
        dir_path = os.path.join(self.fixture_dir, "double-slash-normalization")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        found_main = False
        found_sub = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_other_files), ["subdir/img.png"])
                self.assertEqual(sorted(tf.used_tex_files), ["subdir/bla.tex"])
            if tf.filename == "subdir/bla.tex":
                found_sub = True
        assert found_main
        assert found_sub

    def test_plain_tex_sub(self):
        """Test plain tex files with sub files."""
        dir_path = os.path.join(self.fixture_dir, "plain-tex-sub")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(tf.process.compiler.engine, "tex")
        self.assertEqual(tf.process.compiler.lang, "tex")
        self.assertEqual(tf.process.compiler.output, "dvi")
        self.assertEqual(tf.process.compiler.postp, "dvips_ps2pdf")

    @patch('tex2pdf_tools.preflight.SUPPORTED_COMPILERS', UPDATED_COMPILER_LIST)
    @patch('tex2pdf_tools.preflight.SUPPORTED_COMPILERS_STR', UPDATED_COMPILER_STR_LIST)
    def test_plain_tex_sub_enable_pdfetex(self):
        """Test plain tex files with sub files."""
        dir_path = os.path.join(self.fixture_dir, "plain-tex-sub")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(tf.process.compiler.engine, "tex")
        self.assertEqual(tf.process.compiler.lang, "tex")
        self.assertEqual(tf.process.compiler.output, "pdf")
        self.assertEqual(tf.process.compiler.postp, "none")


    def test_plain_no_bye(self):
        """Test plain tex files without \bye."""
        dir_path = os.path.join(self.fixture_dir, "plain-tex-no-bye")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(tf.process.compiler.engine, "tex")
        self.assertEqual(tf.process.compiler.lang, "tex")
        self.assertEqual(tf.process.compiler.output, "dvi")
        self.assertEqual(tf.process.compiler.postp, "dvips_ps2pdf")

    def test_tikz_pgf_library_0(self):
        """Test tikzlibrary loading system pgfarrow.meta."""
        dir_path = os.path.join(self.fixture_dir, "arrowmeta")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 1)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)

    def test_tikz_pgf_library_1(self):
        """Test tikzlibrary loading tikzfoobar.code.tex."""
        dir_path = os.path.join(self.fixture_dir, "tikzlib-1")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        found_main = False
        found_tikz = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_tex_files), ["tikzlibraryfoobar.code.tex"])
            if tf.filename == "tikzlibraryfoobar.code.tex":
                found_tikz = True
        assert found_main
        assert found_tikz

    def test_tikz_pgf_library_2(self):
        """Test tikzlibrary loading pgffoobar.code.tex."""
        dir_path = os.path.join(self.fixture_dir, "tikzlib-2")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        found_main = False
        found_tikz = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_tex_files), ["pgflibraryfoobar.code.tex"])
            if tf.filename == "pgflibraryfoobar.code.tex":
                found_tikz = True
        assert found_main
        assert found_tikz

    def test_tikz_pgf_library_3(self):
        """Test tikzlibrary loading tikzfoobar.code.tex when both present."""
        dir_path = os.path.join(self.fixture_dir, "tikzlib-3")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 3)
        tf = pf.tex_files[0]
        self.assertEqual(len(tf.issues), 0)
        found_main = False
        found_tikz = False
        found_pgf = False
        for tf in pf.tex_files:
            if tf.filename == "main.tex":
                found_main = True
                self.assertEqual(sorted(tf.used_tex_files), ["tikzlibraryfoobar.code.tex"])
            if tf.filename == "pgflibraryfoobar.code.tex":
                found_pgf = True
            if tf.filename == "tikzlibraryfoobar.code.tex":
                found_tikz = True
        assert found_main
        assert found_tikz
        assert found_pgf

    def test_latex209(self):
        """Test submission in latex209 format."""
        dir_path = os.path.join(self.fixture_dir, "latex209")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(len(tf.issues), 1)
        self.assertEqual(tf.issues[0].key, IssueType.unsupported_compiler_type_latex209)


    def test_amstex_documentstyle(self):
        """Test documentstyle from amstex."""
        dir_path = os.path.join(self.fixture_dir, "amstex-documentstyle")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        tf = pf.detected_toplevel_files[0]
        self.assertEqual(tf.process.compiler.engine, "tex")
        self.assertEqual(tf.process.compiler.lang, "tex")
        self.assertEqual(tf.process.compiler.output, "dvi")
        self.assertEqual(tf.process.compiler.postp, "dvips_ps2pdf")

    def test_unicode_tex_packages(self):
        """Test submission with unicode packages."""
        for pkg in UNICODE_TEX_PACKAGES:
            dir_path = os.path.join(self.fixture_dir, f"unicode-tex-{pkg}")
            pf: PreflightResponse = generate_preflight_response(dir_path)
            self.assertEqual(pf.status.key.value, "success")
            self.assertEqual(len(pf.detected_toplevel_files), 1)
            self.assertEqual(len(pf.tex_files), 1)
            tf = pf.detected_toplevel_files[0]
            self.assertEqual(len(tf.issues), 1)
            issue = tf.issues[0]
            self.assertEqual(issue.key, IssueType.unsupported_compiler_type_unicode)

    @patch('tex2pdf_tools.preflight.SUPPORTED_COMPILERS', UPDATED_COMPILER_LIST)
    @patch('tex2pdf_tools.preflight.SUPPORTED_COMPILERS_STR', UPDATED_COMPILER_STR_LIST)
    def test_unicode_tex_packages_xelatex_enabled(self):
        """Test submission with unicode packages."""
        for pkg in UNICODE_TEX_PACKAGES:
            dir_path = os.path.join(self.fixture_dir, f"unicode-tex-{pkg}")
            pf: PreflightResponse = generate_preflight_response(dir_path)
            print(f"ENABLE_XELATEX: {tex2pdf_tools.preflight.ENABLE_XELATEX}")
            print(f"preflight response: {pf}")
            print(f"enabled compilers = {tex2pdf_tools.preflight.SUPPORTED_COMPILERS}")
            self.assertEqual(pf.status.key.value, "success")
            self.assertEqual(len(pf.detected_toplevel_files), 1)
            self.assertEqual(len(pf.tex_files), 1)
            tf = pf.detected_toplevel_files[0]
            self.assertEqual(len(tf.issues), 0)
            self.assertEqual(tf.process.compiler.engine, "xetex")

    def test_img_in_cls(self):
        """Test detection of images loaded in cls files."""
        dir_path = os.path.join(self.fixture_dir, "img-in-cls")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 2)
        found_cls: bool = False
        for tf in pf.tex_files:
            if tf.filename == "rsproca_new.cls":
                found_cls = True
                self.assertEqual(
                    sorted(tf.used_other_files),
                    sorted([
                        "RS_Pubs_Logo_Line_CMYK.pdf", "RSTA_OpenAccesslogo_RGB.pdf",
                        "RS_crossmark_logo.pdf", "PROCEEDINGS_A_RGB.pdf"
                    ])
                )
        self.assertTrue(found_cls)

    def test_tcblibrary(self):
        """Test detection of tcblibrary loaded files."""
        dir_path = os.path.join(self.fixture_dir, "tcblibrary")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        self.assertEqual(pf.status.key.value, "success")
        self.assertEqual(len(pf.detected_toplevel_files), 1)
        self.assertEqual(len(pf.tex_files), 1)
        self.assertEqual(len(pf.tex_files[0].issues), 0)

