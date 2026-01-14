import json
import os
import pytest
import unittest
from mock import patch

import tex2pdf_tools.preflight
from tex2pdf_tools.preflight import IssueType, UNICODE_TEX_PACKAGES
from tex2pdf_tools.preflight import PreflightResponse, generate_preflight_response

_DIR = os.path.abspath(os.path.dirname(__file__))
FIXTURE_DIR = os.path.join(_DIR, "fixture")

monkeypatch = pytest.MonkeyPatch()


def test_preflight_0():
    """Test for empty/missing directory response."""
    dir_path = "/no/such/directory/should/exist"
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "error"
    assert pf.status.info == "No TeX files found"
    assert len(pf.detected_toplevel_files) == 0
    assert len(pf.tex_files) == 0

def test_preflight_0():
    """Test for empty/missing directory response."""
    dir_path = "/no/such/directory/should/exist"
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "error"
    assert pf.status.info == "No TeX files found"
    assert len(pf.detected_toplevel_files) == 0
    assert len(pf.tex_files) == 0

def test_preflight_1():
    dir_path = os.path.join(FIXTURE_DIR, "include_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.tex_files[0].used_other_files == ["ImageOfNobelPrize.jpg"]
    # check for correct detection of output==pdf when a jpg is included
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""

def test_preflight_single_tex_1():
    dir_path = os.path.join(FIXTURE_DIR, "single_tex_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""

def test_preflight_single_tex_2():
    dir_path = os.path.join(FIXTURE_DIR, "single_tex_2")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    # we do NOT check for 00README entries, so nothing is ignored
    assert len(pf.detected_toplevel_files) == 3
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""

def test_preflight_single_tex_3():
    """Test recursive inclusion."""
    dir_path = os.path.join(FIXTURE_DIR, "single_tex_3")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""
    for tf in pf.tex_files:
        if tf.filename == "fake-file-1.tex":
            assert tf.used_tex_files == ["fake-file-2.TEX", "fake-file-3.tex"]
        assert tf.language.value == "latex"

def test_preflight_single_tex_4():
    """Test recursive inclusion."""
    dir_path = os.path.join(FIXTURE_DIR, "single_tex_4")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 2
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""
    for tf in pf.tex_files:
        if tf.filename == "fake-file-1.tex":
            assert tf.used_tex_files == ["fake-file-2.TEX", "fake-file-3.tex"]
            assert tf.issues[0].info == "fake-package.sty"
            assert tf.issues[0].key.value == "file_not_found"
        assert tf.language.value == "latex"


def test_preflight_multi_tex_3():
    """Test multiple files, inclusions, plain tex."""
    dir_path = os.path.join(FIXTURE_DIR, "multi_tex_3")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 8
    found = False
    for tf in pf.detected_toplevel_files:
        if tf.filename == "main.tex":
            assert \
                tf.process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
                == \
                """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""
            found = True
            break
    assert found
    found = False
    for tf in pf.detected_toplevel_files:
        if tf.filename == "plain-main.tex":
            assert \
                tf.process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
                == \
                """{"engine":"tex","lang":"tex","output":"pdf","postp":"none"}"""
            found = True
            break
    assert found
    # make sure that we do not detect section3.tex as toplevel
    found = False
    for tf in pf.detected_toplevel_files:
        if tf.filename == "section3.tex":
            found = True
            break
    assert not found


def test_preflight_roundtrip():
    """Test roundtrip behavior from json response via PreFlightResponse to json."""
    dir_path = os.path.join(FIXTURE_DIR, "2311.03267")
    pf_json: str = generate_preflight_response(dir_path, json=True)
    pf_dict: dict = json.loads(pf_json)
    pf: PreflightResponse = PreflightResponse(**pf_dict)
    pf_json_roundtrip = pf.model_dump_json(exclude_none=True, exclude_defaults=True)
    assert pf_json, pf_json_roundtrip

def test_preflight_pre_postamble():
    """Test recursive inclusion."""
    dir_path = os.path.join(FIXTURE_DIR, "pre-postamble")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename, "main.tex"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""


def test_preflight_bye_no_newline():
    """Test recursive inclusion."""
    dir_path = os.path.join(FIXTURE_DIR, "bye-no-newline")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.tex"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"tex","output":"pdf","postp":"none"}"""


def test_preflight_pdf_only_submission():
    """Test PDF only submission."""
    dir_path = os.path.join(FIXTURE_DIR, "single-pdf")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "hello-world.pdf"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"unknown","lang":"pdf","output":"unknown","postp":"none"}"""
    assert pf.detected_toplevel_files[0].process.compiler.compiler_string == "pdf_submission"


def test_preflight_html_only_submission():
    """Test HTML only submission."""
    dir_path = os.path.join(FIXTURE_DIR, "html_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "paper.html"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"unknown","lang":"html","output":"unknown","postp":"none"}"""
    assert pf.detected_toplevel_files[0].process.compiler.compiler_string == "html_submission"


def test_anc_files_submission():
    """Test submission with ancillary files."""
    dir_path = os.path.join(FIXTURE_DIR, "anc_files_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""
    assert len(pf.ancillary_files) == 2


def test_index_biblio_1():
    """Test index and bibliographies."""
    dir_path = os.path.join(FIXTURE_DIR, "index_test_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""
    assert \
        pf.detected_toplevel_files[0].process.index.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"pre_generated":true,"can_be_generated":false}"""
    assert \
        pf.detected_toplevel_files[0].process.bibliography.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"pre_generated":true,"can_be_generated":true}"""
    for tf in pf.tex_files:
        if tf.filename == "ms.tex":
            assert tf.used_tex_files == ["the-rest.tex"]
            assert tf.used_idx_files == ["ms.adx", "ms.bdx"]
            assert tf.used_ind_files == ["ms.and", "ms.bnd"]
        if tf.filename == "the-rest.tex":
            assert tf.used_bib_files == ["biblio.bib"]


def test_index_biblio_2():
    """Test index and bibliographies - missing index definition."""
    dir_path = os.path.join(FIXTURE_DIR, "index_test_2")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    for tf in pf.detected_toplevel_files:
        if tf.filename == "ms.tex":
            assert len(tf.issues) == 1
            assert tf.issues[0].info == "index definition for tag-b not found"


def test_preflight_no_hyperref():
    dir_path = os.path.join(FIXTURE_DIR, "single_tex_1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value =="success"
    assert pf.detected_toplevel_files[0].hyperref_found == False

def test_preflight_with_hyperref():
    dir_path = os.path.join(FIXTURE_DIR, "use_hyperref")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert pf.detected_toplevel_files[0].hyperref_found == True

def test_eps_dvips():
    """Test dvips_ps2pdf selection when eps are included."""
    dir_path = os.path.join(FIXTURE_DIR, "eps-test")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.tex"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}"""

def test_eps_dvips_enable_pdfetex():
    """Test dvips_ps2pdf selection when eps are included."""
    dir_path = os.path.join(FIXTURE_DIR, "eps-test")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.tex"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}"""

def test_epsfig_dvips():
    """Test epsfig image extraction."""
    dir_path = os.path.join(FIXTURE_DIR, "epsfig-test")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.tex"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}"""
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            assert sorted(tf.used_other_files), ["bla.eps", "foo.eps"]


def test_mixed_images():
    """Test failure when mixing png and eps."""
    dir_path = os.path.join(FIXTURE_DIR, "mixed-images")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.tex"
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"xetex","lang":"latex","output":"pdf","postp":"none"}"""


def test_multi_include_cmds():
    """Test multiple consecutive include commands."""
    dir_path = os.path.join(FIXTURE_DIR, "multi-include-cmds")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    found_main = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_tex_files) == ["a.sty", "b.sty", "c.tex", "e.tex"]
            assert sorted(tf.used_other_files) == ["aa.jpg", "bb.jpg", "cc.jpg", "dd.png", "ee.jpg"]
    assert found_main

def test_no_final_newline():
    """Test whether detection of include command works with no final newline."""
    dir_path = os.path.join(FIXTURE_DIR, "last-line-no-newline")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.tex"
    found_foo_tex = False
    for tf in pf.tex_files:
        if tf.filename == "foo.tex":
            found_foo_tex = True
            assert tf.used_tex_files == ["bla.tex"]
    assert found_foo_tex

def test_biber_good_version_32():
    """Test bbl version matching arXiv TeX version."""
    dir_path = os.path.join(FIXTURE_DIR, "bbl_version_good")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert tf.process.bibliography.pre_generated == True
    assert tf.process.bibliography.can_be_generated == True
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 1
    assert tf.issues[0].key == IssueType.bbl_version_needs_previous_version

def test_biber_good_version_33():
    """Test bbl version not matching arXiv TeX version."""
    dir_path = os.path.join(FIXTURE_DIR, "bbl_version_good_33")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert tf.process.bibliography.pre_generated == True
    assert tf.process.bibliography.can_be_generated == True
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0

def test_biber_bad_version_31():
    """Test bbl version not matching arXiv TeX version."""
    dir_path = os.path.join(FIXTURE_DIR, "bbl_version_mismatch")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert tf.process.bibliography.pre_generated == True
    assert tf.process.bibliography.can_be_generated == True
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 1
    issue = tf.issues[0]
    assert issue.key == IssueType.bbl_version_mismatch
    assert issue.filename == "bla.bbl"

def test_multi_usepackage():
    """Test usepackage with multiple entries."""
    dir_path = os.path.join(FIXTURE_DIR, "multi-usepackage")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    found_main = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_tex_files) == ["a.sty", "b.sty", "c.sty"]
    assert found_main

def test_svg_compiler_detection():
    """Test correct compiler detection despite unsupported img extension."""
    dir_path = os.path.join(FIXTURE_DIR, "svg-include-compiler")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert \
        pf.detected_toplevel_files[0].process.compiler.model_dump_json(exclude_none=True, exclude_defaults=True) \
        == \
        """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""


def test_overlapping_filenames():
    """Test same filename for multiple file types."""
    dir_path = os.path.join(FIXTURE_DIR, "overlapping-filenames")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    found_main = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_tex_files) == ["article.tex"]
    assert found_main

def test_overpic_filenames():
    """Test overpic environment detection."""
    dir_path = os.path.join(FIXTURE_DIR, "overpic")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    found_main = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_other_files) == ["foo.jpg"]
    assert found_main

def test_addplot_filenames():
    """Test addplot environment detection."""
    dir_path = os.path.join(FIXTURE_DIR, "addplot")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    found_main = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_other_files) == ["data1.txt", "data2.txt"]
    assert found_main

def test_addplot_2():
    """Test addplot environment detection."""
    dir_path = os.path.join(FIXTURE_DIR, "addplot-2")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 1
    assert pf.tex_files[0].used_other_files == ['something.csv']

def test_quoted_arguments():
    """Test quoted arguments to commands."""
    dir_path = os.path.join(FIXTURE_DIR, "quoted-arguments")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    found_main = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_other_files) == ["bla bla.jpg", "foo.png"]
    assert found_main

def test_bbl_bib():
    """Test submission with bbl and bib present."""
    dir_path = os.path.join(FIXTURE_DIR, "bbl-bib")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert tf.process.bibliography.pre_generated == True
    assert tf.process.bibliography.can_be_generated == True
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    assert tf.used_bib_files == ["xxx.bib"]
    assert tf.used_other_files == []


def test_bbl_no_bib():
    """Test submission with bbl but without bib present."""
    dir_path = os.path.join(FIXTURE_DIR, "bbl-no-bib")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert tf.process.bibliography.pre_generated
    assert tf.process.bibliography.can_be_generated == False
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    assert tf.used_bib_files == []
    assert tf.used_other_files == ["main.bbl"]


def test_bib_no_bbl():
    """Test submission with bib but without bbl present."""
    dir_path = os.path.join(FIXTURE_DIR, "bib-no-bbl")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert tf.process.bibliography.pre_generated == False
    assert tf.process.bibliography.can_be_generated
    # bbl is missing, but we have bib around
    assert len(tf.issues) == 0
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    assert tf.used_bib_files == ["xxx.bib"]
    assert tf.used_other_files == []


def test_multi_bib_no_bbl():
    """Test submission with multiple bib, no bbl, one bib missing."""
    dir_path = os.path.join(FIXTURE_DIR, "multi-bib-no-bbl")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert not tf.process.bibliography.pre_generated
    assert not tf.process.bibliography.can_be_generated
    # bbl is missing, but we have bib around
    assert len(tf.issues) == 2
    assert \
        sorted([issue.key for issue in tf.issues]) \
        == \
        [IssueType.bbl_bib_file_missing, IssueType.issue_in_subfile]
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 1
    assert tf.issues[0].key == IssueType.file_not_found
    assert tf.issues[0].filename == "yyy.bib"
    assert tf.used_bib_files == ["xxx.bib"]
    assert tf.used_other_files == []


def test_no_bbl_no_bib():
    """Test submission with no bib nor bbl present."""
    dir_path = os.path.join(FIXTURE_DIR, "no-bbl-no-bib")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert not tf.process.bibliography.pre_generated
    assert len(tf.issues) == 2
    assert \
        sorted([issue.key for issue in tf.issues]) \
        == \
        [IssueType.bbl_bib_file_missing, IssueType.issue_in_subfile]
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 1
    assert tf.issues[0].key == IssueType.file_not_found
    assert tf.issues[0].filename == "xxx.bib"
    assert tf.used_bib_files == []
    assert tf.used_other_files == []


def test_biber_bibtex_mix():
    """Test submission with no bib nor bbl present."""
    dir_path = os.path.join(FIXTURE_DIR, "bibtex-and-biber")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert len(tf.issues) == 1
    assert tf.issues[0].key == IssueType.multiple_bibliography_types
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    assert tf.used_bib_files == ["xxx.bib", "xxx.bib"]
    assert tf.used_other_files == []

def test_biblatex_with_bibliography():
    """Test submission with using biblatex and \bibliography."""
    dir_path = os.path.join(FIXTURE_DIR, "biblatex-bibliography")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert len(tf.issues) == 0
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    assert tf.used_bib_files == ["xxx.bib"]
    assert tf.used_other_files == []

def test_double_slash_normalization():
    """Test double slash normalization present."""
    dir_path = os.path.join(FIXTURE_DIR, "double-slash-normalization")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    found_main = False
    found_sub = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_other_files) == ["subdir/img.png"]
            assert sorted(tf.used_tex_files) == ["subdir/bla.tex"]
        if tf.filename == "subdir/bla.tex":
            found_sub = True
    assert found_main
    assert found_sub

def test_plain_tex_sub():
    """Test plain tex files with sub files."""
    dir_path = os.path.join(FIXTURE_DIR, "plain-tex-sub")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    tf = pf.detected_toplevel_files[0]
    assert tf.process.compiler.engine == "tex"
    assert tf.process.compiler.lang == "tex"
    assert tf.process.compiler.output == "pdf"
    assert tf.process.compiler.postp == "none"

def test_plain_tex_sub_enable_pdfetex():
    """Test plain tex files with sub files."""
    dir_path = os.path.join(FIXTURE_DIR, "plain-tex-sub")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    tf = pf.detected_toplevel_files[0]
    assert tf.process.compiler.engine == "tex"
    assert tf.process.compiler.lang == "tex"
    assert tf.process.compiler.output == "pdf"
    assert tf.process.compiler.postp == "none"


def test_plain_no_bye():
    """Test plain tex files without \bye."""
    dir_path = os.path.join(FIXTURE_DIR, "plain-tex-no-bye")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    tf = pf.detected_toplevel_files[0]
    assert tf.process.compiler.engine == "tex"
    assert tf.process.compiler.lang == "tex"
    assert tf.process.compiler.output == "pdf"
    assert tf.process.compiler.postp == "none"

def test_tikz_pgf_library_0():
    """Test tikzlibrary loading system pgfarrow.meta."""
    dir_path = os.path.join(FIXTURE_DIR, "arrowmeta")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0

def test_tikz_pgf_library_1():
    """Test tikzlibrary loading tikzfoobar.code.tex."""
    dir_path = os.path.join(FIXTURE_DIR, "tikzlib-1")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    found_main = False
    found_tikz = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_tex_files) == ["tikzlibraryfoobar.code.tex"]
        if tf.filename == "tikzlibraryfoobar.code.tex":
            found_tikz = True
    assert found_main
    assert found_tikz

def test_tikz_pgf_library_2():
    """Test tikzlibrary loading pgffoobar.code.tex."""
    dir_path = os.path.join(FIXTURE_DIR, "tikzlib-2")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    found_main = False
    found_tikz = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_tex_files) == ["pgflibraryfoobar.code.tex"]
        if tf.filename == "pgflibraryfoobar.code.tex":
            found_tikz = True
    assert found_main
    assert found_tikz

def test_tikz_pgf_library_3():
    """Test tikzlibrary loading tikzfoobar.code.tex when both present."""
    dir_path = os.path.join(FIXTURE_DIR, "tikzlib-3")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 3
    tf = pf.tex_files[0]
    assert len(tf.issues) == 0
    found_main = False
    found_tikz = False
    found_pgf = False
    for tf in pf.tex_files:
        if tf.filename == "main.tex":
            found_main = True
            assert sorted(tf.used_tex_files) == ["tikzlibraryfoobar.code.tex"]
        if tf.filename == "pgflibraryfoobar.code.tex":
            found_pgf = True
        if tf.filename == "tikzlibraryfoobar.code.tex":
            found_tikz = True
    assert found_main
    assert found_tikz
    assert found_pgf

def test_latex209():
    """Test submission in latex209 format."""
    dir_path = os.path.join(FIXTURE_DIR, "latex209")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    tf = pf.detected_toplevel_files[0]
    assert len(tf.issues) == 1
    assert tf.issues[0].key == IssueType.unsupported_compiler_type_latex209


def test_amstex_documentstyle():
    """Test documentstyle from amstex."""
    dir_path = os.path.join(FIXTURE_DIR, "amstex-documentstyle")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    tf = pf.detected_toplevel_files[0]
    assert tf.process.compiler.engine == "tex"
    assert tf.process.compiler.lang == "tex"
    assert tf.process.compiler.output == "pdf"
    assert tf.process.compiler.postp == "none"

def test_unicode_tex_packages():
    """Test submission with unicode packages."""
    for pkg in UNICODE_TEX_PACKAGES:
        dir_path = os.path.join(FIXTURE_DIR, f"unicode-tex-{pkg}")
        pf: PreflightResponse = generate_preflight_response(dir_path)
        assert pf.status.key.value == "success"
        assert len(pf.detected_toplevel_files) == 1
        assert len(pf.tex_files) == 1
        tf = pf.detected_toplevel_files[0]
        assert tf.process.compiler.engine == "xetex"
        assert tf.process.compiler.lang == "latex"
        assert tf.process.compiler.output == "pdf"
        assert tf.process.compiler.postp == "none"


def test_img_in_cls():
    """Test detection of images loaded in cls files."""
    dir_path = os.path.join(FIXTURE_DIR, "img-in-cls")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    found_cls: bool = False
    for tf in pf.tex_files:
        if tf.filename == "rsproca_new.cls":
            found_cls = True
            assert \
                sorted(tf.used_other_files) \
                == \
                sorted([
                    "RS_Pubs_Logo_Line_CMYK.pdf", "RSTA_OpenAccesslogo_RGB.pdf",
                    "RS_crossmark_logo.pdf", "PROCEEDINGS_A_RGB.pdf"
                ])
    assert found_cls

def test_tcblibrary():
    """Test detection of tcblibrary loaded files."""
    dir_path = os.path.join(FIXTURE_DIR, "tcblibrary")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 1
    assert len(pf.tex_files[0].issues) == 0

def test_bst_included():
    """Test detection of bst files included in submission."""
    dir_path = os.path.join(FIXTURE_DIR, "bst-detection")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 1
    assert len(pf.tex_files[0].issues) == 0
    assert pf.tex_files[0].used_other_files == ["ieeetr.bst"]

def test_bst_system():
    """Test detection of bst files from system tree."""
    dir_path = os.path.join(FIXTURE_DIR, "bst-detection-system")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 1
    assert len(pf.tex_files[0].issues) == 0
    assert pf.tex_files[0].used_other_files == []

def test_pdf_with_javascript():
    """Test detection of PDF file with javascript embedded."""
    # ENABLE_JS_CHECKS is already imported into pdf_checks, so we need to monkeypatch it there!
    monkeypatch.setattr(tex2pdf_tools.preflight.pdf_checks, "ENABLE_JS_CHECKS", True)
    dir_path = os.path.join(FIXTURE_DIR, "pdf-with-javascript")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "error"
    assert len(pf.detected_toplevel_files) == 0
    assert len(pf.tex_files) == 0
    assert pf.status.info == "QA check failed: JavaScript code found in PDF"

def test_fontspec_font_detection():
    """Test detection of font files used by fontspec commands."""
    dir_path = os.path.join(FIXTURE_DIR, "fontspec-font-detection")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 1
    tf = pf.tex_files[0]
    assert tf.used_other_files == [ "texgyrepagella-bold-as-batman.otf" ]
    assert sorted([x.info for x in tf.issues]) == \
        sorted([
            "texgyrepagella-reverseitalic.ttf", "texgyrepagella-italic2.otf", "texgyrepagella-italic3.otf",
            "CharisSIL-notfound.ttf", "texgyrepagella-superregular.otf", "missing1.otf",
        ])

def test_exe_detection():
    """Test detection of exe files."""
    dir_path = os.path.join(FIXTURE_DIR, "detect-exe")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "error"
    assert pf.status.info == "QA check failed: EXE file found"
    assert len(pf.detected_toplevel_files) == 0
    assert len(pf.tex_files) == 0


def test_bye_after_endinput():
    """Test for \\bye after \\endinput."""
    dir_path = os.path.join(FIXTURE_DIR, "bye-after-endinput")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert len(pf.tex_files) == 2
    tf = pf.detected_toplevel_files[0]
    assert tf.process.compiler.engine == "tex"
    assert tf.process.compiler.lang == "latex"
    assert tf.process.compiler.output == "pdf"
    assert tf.process.compiler.postp == "none"
    assert tf.issues == []
