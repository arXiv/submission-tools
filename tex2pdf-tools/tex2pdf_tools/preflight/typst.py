"""Typst file parser for preflight."""

import logging
import os
import re

from pydantic import BaseModel, Field

from .models import (
    TYPST_SUBMISSION_STRING,
    CompilerSpec,
    IssueType,
    MainProcessSpec,
    TeXFileIssue,
    ToplevelFile,
)

logger = logging.getLogger("[preflight]")

# Regex patterns for Typst parsing
_RE_TYPST_LINE_COMMENT = re.compile(rb"//[^\n]*")
_RE_TYPST_BLOCK_COMMENT = re.compile(rb"/\*.*?\*/", re.DOTALL)
_RE_TYPST_IMPORT = re.compile(rb'#import\s+"([^"]+)"')
_RE_TYPST_INCLUDE = re.compile(rb'#include\s+"([^"]+)"')
_RE_TYPST_IMAGE = re.compile(rb'#image\s*\(\s*"([^"]+)"')
_RE_TYPST_READ = re.compile(rb'#read\s*\(\s*"([^"]+)"')


def _strip_typst_comments(data: bytes) -> bytes:
    """Remove Typst comments from file data."""
    data = _RE_TYPST_BLOCK_COMMENT.sub(b"", data)
    data = _RE_TYPST_LINE_COMMENT.sub(b"", data)
    return data


class ParsedTypstFile(BaseModel):
    """Result of parsing a Typst file."""

    filename: str
    _data: bytes = b""
    used_typ_files: list[str] = []
    used_other_files: list[str] = []
    issues: list[TeXFileIssue] = []
    children: list["ParsedTypstFile"] = Field(exclude=True, default=[])
    parents: list["ParsedTypstFile"] = Field(exclude=True, default=[])


def parse_typst_file(basedir: str, filename: str) -> ParsedTypstFile:
    """Parse a single Typst file for imports, includes, images, and reads."""
    filepath = os.path.join(basedir, filename)
    n = ParsedTypstFile(filename=filename)

    try:
        with open(filepath, "rb") as fh:
            n._data = fh.read()
    except FileNotFoundError:
        n.issues.append(TeXFileIssue(IssueType.file_not_found, filename))
        return n
    except OSError as e:
        n.issues.append(TeXFileIssue(IssueType.other, f"Cannot read {filename}: {e}"))
        return n

    data = _strip_typst_comments(n._data)

    # Find imported/included .typ files
    for match in _RE_TYPST_IMPORT.findall(data):
        try:
            path = match.decode("utf-8")
        except UnicodeDecodeError:
            continue
        path = path[2:] if path.startswith("./") else path
        if path not in n.used_typ_files:
            n.used_typ_files.append(path)

    for match in _RE_TYPST_INCLUDE.findall(data):
        try:
            path = match.decode("utf-8")
        except UnicodeDecodeError:
            continue
        path = path[2:] if path.startswith("./") else path
        if path not in n.used_typ_files:
            n.used_typ_files.append(path)

    # Find images and read files
    for match in _RE_TYPST_IMAGE.findall(data):
        try:
            path = match.decode("utf-8")
        except UnicodeDecodeError:
            continue
        path = path[2:] if path.startswith("./") else path
        if path not in n.used_other_files:
            n.used_other_files.append(path)

    for match in _RE_TYPST_READ.findall(data):
        try:
            path = match.decode("utf-8")
        except UnicodeDecodeError:
            continue
        path = path[2:] if path.startswith("./") else path
        if path not in n.used_other_files:
            n.used_other_files.append(path)

    return n


def parse_typst_dir(files: list[str], rundir: str) -> dict[str, ParsedTypstFile]:
    """Parse all .typ files in a directory."""
    nodes: dict[str, ParsedTypstFile] = {}
    for f in files:
        nodes[f] = parse_typst_file(rundir, f)
    return nodes


def compute_typst_document_graph(
    nodes: dict[str, ParsedTypstFile],
) -> tuple[dict[str, ParsedTypstFile], dict[str, ParsedTypstFile]]:
    """Build parent/child relationships for Typst files."""
    for _, n in nodes.items():
        for sn in n.used_typ_files:
            if sn in nodes:
                n.children.append(nodes[sn])
                nodes[sn].parents.append(n)
    roots = {}
    for fn, n in nodes.items():
        if not n.parents:
            roots[fn] = n
    return roots, nodes


def compute_typst_toplevel_files(
    roots: dict[str, ParsedTypstFile], nodes: dict[str, ParsedTypstFile]
) -> dict[str, ToplevelFile]:
    """Determine toplevel Typst files.

    All root nodes (not imported by others) are considered toplevel files.
    """
    toplevel_files: dict[str, ToplevelFile] = {}
    for f, _n in roots.items():
        tl = ToplevelFile(
            filename=f,
            process=MainProcessSpec(compiler=CompilerSpec(compiler=TYPST_SUBMISSION_STRING)),
        )
        toplevel_files[f] = tl
    return toplevel_files
