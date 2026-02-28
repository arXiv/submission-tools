import os

from tex2pdf_tools.preflight import PreflightResponse, generate_preflight_response
from tex2pdf_tools.preflight.models import TYPST_SUBMISSION_STRING
from tex2pdf_tools.preflight.typst import (
    _strip_typst_comments,
    compute_typst_document_graph,
    compute_typst_toplevel_files,
    parse_typst_file,
)

_DIR = os.path.abspath(os.path.dirname(__file__))
FIXTURE_DIR = os.path.join(_DIR, "fixture")


def test_typst_simple():
    """Single toplevel with includes and images."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_simple")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.typ"
    assert pf.detected_toplevel_files[0].process.compiler.compiler_string == TYPST_SUBMISSION_STRING
    assert len(pf.typst_files) == 2
    # main.typ should reference chapter.typ and fig.png
    main_node = next(tf for tf in pf.typst_files if tf.filename == "main.typ")
    assert "chapter.typ" in main_node.used_typ_files
    assert "fig.png" in main_node.used_other_files
    # tex_files should be empty for typst submissions
    assert len(pf.tex_files) == 0


def test_typst_no_includes():
    """Single standalone Typst file with no includes."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_no_includes")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 1
    assert pf.detected_toplevel_files[0].filename == "main.typ"
    assert pf.detected_toplevel_files[0].process.compiler.compiler_string == TYPST_SUBMISSION_STRING
    assert len(pf.typst_files) == 1
    main_node = pf.typst_files[0]
    assert main_node.used_typ_files == []
    assert main_node.used_other_files == []


def test_typst_multi_root():
    """Multiple independent toplevel Typst files."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_multi_root")
    pf: PreflightResponse = generate_preflight_response(dir_path)
    assert pf.status.key.value == "success"
    assert len(pf.detected_toplevel_files) == 2
    filenames = {tl.filename for tl in pf.detected_toplevel_files}
    assert filenames == {"paper.typ", "slides.typ"}
    for tl in pf.detected_toplevel_files:
        assert tl.process.compiler.compiler_string == TYPST_SUBMISSION_STRING


def test_typst_comment_stripping():
    """Verify commented-out imports are ignored."""
    data = b"""
// #import "ignored.typ"
/* #import "also_ignored.typ" */
#import "real.typ"
/* multi
   line
   #include "nope.typ"
*/
#image("pic.png")
// #image("nope.png")
"""
    stripped = _strip_typst_comments(data)
    assert b"ignored.typ" not in stripped
    assert b"also_ignored.typ" not in stripped
    assert b"nope.typ" not in stripped
    assert b"nope.png" not in stripped
    assert b'#import "real.typ"' in stripped
    assert b'#image("pic.png")' in stripped


def test_parse_typst_file_imports():
    """Unit test for regex parsing of imports/includes/images/reads."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_simple")
    n = parse_typst_file(dir_path, "main.typ")
    assert "chapter.typ" in n.used_typ_files
    assert "fig.png" in n.used_other_files
    assert n.issues == []


def test_parse_typst_file_read():
    """Unit test for #read() detection."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_multi_root")
    n = parse_typst_file(dir_path, "slides.typ")
    assert "data.csv" in n.used_other_files


def test_typst_document_graph():
    """Test document graph building."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_simple")
    main = parse_typst_file(dir_path, "main.typ")
    chapter = parse_typst_file(dir_path, "chapter.typ")
    nodes = {"main.typ": main, "chapter.typ": chapter}
    roots, nodes = compute_typst_document_graph(nodes)
    assert "main.typ" in roots
    assert "chapter.typ" not in roots
    assert chapter in main.children
    assert main in chapter.parents


def test_typst_toplevel_files():
    """Test toplevel file detection."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_simple")
    main = parse_typst_file(dir_path, "main.typ")
    chapter = parse_typst_file(dir_path, "chapter.typ")
    nodes = {"main.typ": main, "chapter.typ": chapter}
    roots, nodes = compute_typst_document_graph(nodes)
    toplevel = compute_typst_toplevel_files(roots, nodes)
    assert len(toplevel) == 1
    assert "main.typ" in toplevel
    assert toplevel["main.typ"].process.compiler.compiler_string == TYPST_SUBMISSION_STRING


def test_typst_json_serialization():
    """Verify JSON serialization works for typst submissions."""
    dir_path = os.path.join(FIXTURE_DIR, "typst_simple")
    result = generate_preflight_response(dir_path, json=True)
    assert isinstance(result, str)
    # compiler_string is a property, JSON contains the raw lang/output fields
    assert '"lang":"typst"' in result
    assert "typst_files" in result
    assert "main.typ" in result
