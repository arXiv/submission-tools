"""GenPDF preflight parser."""

import glob
import logging
import os
import re
import subprocess
import typing
from collections.abc import Callable
from enum import Enum
from itertools import zip_longest
from pprint import pformat
from typing import TypeVar

import chardet
from pydantic import BaseModel, Field, PrivateAttr

MODULE_PATH = os.path.dirname(__file__)

T = TypeVar("T")

PDF_SUBMISSION_STRING = "pdf_submission"
HTML_SUBMISSION_STRING = "html_submission"

#
# CLASSES AND TYPES
#
# This section contains the class definitions and compound types


class PreflightStatusValues(str, Enum):
    """Possible values of preflight's execution status."""

    success = "success"
    error = "error"
    suspicious = "suspicious"


class PreflightStatus(BaseModel):
    """Specification of Preflight status entry."""

    key: PreflightStatusValues
    info: str | None = None


class FileType(str, Enum):
    """Classification of files."""

    tex = "tex"
    bib = "bib"
    other = "other"


class IncludeSpec(BaseModel):
    """Specification of an include statement in a TeX file."""

    cmd: str
    source: str
    type: FileType
    extensions: None | str | dict = None
    file_argument: int | list[int] = 1
    take_options: bool = True
    multi_args: bool = False


class LanguageType(str, Enum):
    r"""Possible language types of a submission/file.

    TEX does not allow compiling as latex, e.g., because it contains \bye
    LATEX does not allow compiling as plain tex, e.g., because it contains \documentclass
    PDF is for PDF only submissions.
    HTML is for HTML only submissions.
    UNKNOWN allows compilation as either TEX or LATEX.
    """

    unknown = "unknown"
    tex = "tex"
    latex = "latex"
    pdf = "pdf"
    html = "html"


class EngineType(str, Enum):
    """Possible engines in use."""

    unknown = "unknown"
    tex = "tex"
    luatex = "luatex"
    xetex = "xetex"
    ptex = "ptex"
    uptex = "uptex"


class OutputType(str, Enum):
    """Possible output types of the first run."""

    unknown = "unknown"
    dvi = "dvi"
    pdf = "pdf"


class IndexCompiler(str, Enum):
    """Possible index compiler."""

    unknown = "unknown"
    makeindex = "makeindex"


class BibCompiler(str, Enum):
    """Possible index compiler."""

    unknown = "unknown"
    bibtex = "bibtex"
    bibtex8 = "bibtex8"
    ubibtex = "ubibtex"
    biber = "biber"


class PostProcessType(str, Enum):
    """Possible conversion types from dvi to pdf."""

    unknown = "unknown"
    none = "none"
    dvips_ps2pdf = "dvips_ps2pdf"
    dvipdfmx = "dvipdfmx"


class PreflightException(Exception):
    """General exception when parsing preflight."""

    pass


class ParseSyntaxError(PreflightException):
    """Syntax error when parsing a dict to an object."""

    pass


class IndexProcessSpec(BaseModel):
    """Specification of the indexing process."""

    processor: IndexCompiler = IndexCompiler.unknown
    pre_generated: bool


class BibProcessSpec(BaseModel):
    """Specification of the bibliography process."""

    processor: BibCompiler = BibCompiler.unknown
    pre_generated: bool


class CompilerSpec(BaseModel):
    """Specification of the compiler (engine+postprocess)."""

    engine: EngineType
    lang: LanguageType
    output: OutputType
    postp: PostProcessType | None

    _COMPILER_SELECTION = {
        LanguageType.tex: {
            OutputType.dvi: {
                EngineType.tex: "etex",
                EngineType.luatex: "dviluatex",
                # not easy to do: EngineType.XETEX: "xetex",
                EngineType.ptex: "ptex",
                EngineType.uptex: "uptex",
            },
            OutputType.pdf: {
                EngineType.tex: "pdfetex",
                EngineType.luatex: "luatex",
                EngineType.xetex: "xetex",
                # EngineType.PTEX: "ptex",
                # EngineType.UPTEX: "uptex",
            },
        },
        LanguageType.latex: {
            OutputType.dvi: {
                EngineType.tex: "latex",
                EngineType.luatex: "dvilualatex",
                # not easy to do: EngineType.XETEX: "xetex",
                EngineType.ptex: "platex",
                EngineType.uptex: "uplatex",
            },
            OutputType.pdf: {
                EngineType.tex: "pdflatex",
                EngineType.luatex: "lualatex",
                EngineType.xetex: "xelatex",
                # EngineType.PTEX: "ptex",
                # EngineType.UPTEX: "uptex",
            },
        },
    }

    def __init__(self, **kwargs: typing.Any) -> None:
        """Adjust __init__ function to allow for CompilerSpec(compiler="...")."""
        if len(kwargs) == 1 and "compiler" in kwargs:
            compiler = kwargs["compiler"]
            super().__init__(
                engine=EngineType.unknown,
                lang=LanguageType.unknown,
                output=OutputType.unknown,
                postp=PostProcessType.unknown,
            )
            self.from_compiler_string(compiler)
        else:
            super().__init__(**kwargs)

    @property
    def is_determined(self) -> bool:
        """Check whether a compiler spec is completely determined (no unknowns)."""
        if self.engine == EngineType.unknown or self.lang == LanguageType.unknown or self.output == OutputType.unknown:
            return False
        return True

    @property
    def compiler_string(self) -> str | None:
        """Convert Language/Output/Engine/PostProcess to compiler string."""
        # first deal with PDF only submissions:
        if self.lang.value == "pdf":
            return PDF_SUBMISSION_STRING
        if self.lang.value == "html":
            return HTML_SUBMISSION_STRING
        if self.lang in self._COMPILER_SELECTION:
            if self.output in self._COMPILER_SELECTION[self.lang]:
                if self.engine in self._COMPILER_SELECTION[self.lang][self.output]:
                    ret = self._COMPILER_SELECTION[self.lang][self.output][self.engine]
                    if self.postp is not None and not self.postp == PostProcessType.none:
                        # TODO should we check whether output == DVI ?
                        # we might have other non-dvi2pdf related postprocessing later on?
                        ret += f"+{self.postp.value}"
                    return ret
        # if we are still here, something was wrong ....
        return None

    @property
    def tex_compiler(self) -> str | None:
        """Return the TeX compiler to be used."""
        # first deal with PDF only submissions:
        if self.lang.value == "pdf":
            return PDF_SUBMISSION_STRING
        if self.lang.value == "html":
            return HTML_SUBMISSION_STRING
        if self.lang in self._COMPILER_SELECTION:
            if self.output in self._COMPILER_SELECTION[self.lang]:
                if self.engine in self._COMPILER_SELECTION[self.lang][self.output]:
                    return self._COMPILER_SELECTION[self.lang][self.output][self.engine]
        return None

    def from_compiler_string(self, compiler: str) -> None:
        """Convert compiler string to Language/Output/Engine/PostProcess types."""
        if compiler == PDF_SUBMISSION_STRING:
            self.lang = LanguageType.pdf
            self.engine = EngineType.unknown
            self.output = OutputType.unknown
            self.postp = PostProcessType.none
            return
        if compiler == HTML_SUBMISSION_STRING:
            self.lang = LanguageType.html
            self.engine = EngineType.unknown
            self.output = OutputType.unknown
            self.postp = PostProcessType.none
            return
        parts = compiler.split("+", 1)
        comp: str = ""
        if len(parts) == 2:
            comp, postp = parts
            for pp in PostProcessType:
                if pp.value == postp:
                    self.postp = pp
                    break
        else:
            comp = parts[0]
            self.postp = PostProcessType.none
        for lang in self._COMPILER_SELECTION:
            for outp in self._COMPILER_SELECTION[lang]:
                for eng in self._COMPILER_SELECTION[lang][outp]:
                    if comp == self._COMPILER_SELECTION[lang][outp][eng]:
                        self.lang = lang
                        self.output = outp
                        self.engine = eng
                        break


class MainProcessSpec(BaseModel):
    """Specification of the main process to compile a document."""

    compiler: CompilerSpec | None = None
    bibliography: BibProcessSpec | None = None
    index: IndexProcessSpec | None = None
    fontmaps: list[str] | None = None

    def __init__(self, **kwargs: typing.Any) -> None:
        """Adjust __init__ function to allow for CompilerSpec(compiler="...")."""
        if "compiler" in kwargs and isinstance(kwargs["compiler"], str):
            compiler = kwargs["compiler"]
            del kwargs["compiler"]
            super().__init__(compiler=CompilerSpec(compiler=compiler), **kwargs)
        else:
            super().__init__(**kwargs)


class IssueType(str, Enum):
    """Possible issues we detect."""

    file_not_found = "file_not_found"
    conflicting_file_type = "conflicting_file_type"
    conflicting_output_type = "conflicting_output_type"
    conflicting_engine_type = "conflicting_engine_type"
    conflicting_postprocess_type = "conflicting_postprocess_type"
    unsupported_compiler_type = "unsupported_compiler_type"
    conflicting_image_types = "conflicting_image_types"
    include_command_with_macro = "include_command_with_macro"
    contents_decode_error = "contents_decode_error"
    issue_in_subfile = "issue_in_subfile"
    other = "other"


class TeXFileIssue(BaseModel):
    """Specification of Issue in a file."""

    key: IssueType
    info: str
    # line: int
    filename: str | None = None

    def __init__(self, key: IssueType, info: str, filename: str | None = None, **kwargs: typing.Any) -> None:
        """Override __init__ to be able to use positional parameters."""
        super().__init__(key=key, info=info, filename=filename, **kwargs)


class ParsedTeXFile(BaseModel):
    """Result of parsing a TeX file."""

    filename: str
    _data: str = PrivateAttr(default="")
    output_type: OutputType = OutputType.unknown
    language: LanguageType = LanguageType.unknown
    engine: EngineType = EngineType.unknown
    postprocess: PostProcessType = PostProcessType.unknown
    contains_documentclass: bool = False
    contains_bye: bool = False
    used_tex_files: list[str] = []
    used_bib_files: list[str] = []
    used_other_files: list[str] = []
    used_system_files: list[str] = Field(exclude=True, default=[])
    mentioned_files: dict[str, IncludeSpec] = Field(exclude=True, default={})
    issues: list[TeXFileIssue] = []
    children: list["ParsedTeXFile"] = Field(exclude=True, default=[])
    parents: list["ParsedTeXFile"] = Field(exclude=True, default=[])

    def detect_language(self) -> None:
        """Detect the language used in the given file (TeX, LaTeX, or unknown)."""
        # the default languages is UNKNOWN, but if we detect
        # certain values, switch to either TEX or LATEX only
        # we check for \bye first, so that if a file contains both
        # \documentclass and \bye (which is a syntax error!)
        language = LanguageType.unknown
        if self.filename.endswith(".sty"):
            language = LanguageType.latex
        if re.search(r"\\text(bf|it|sl)|\\section|\\chapter", self._data, re.MULTILINE):
            language = LanguageType.latex
        if re.search(r"^[^%\n]*\\bye(?![a-zA-Z])", self._data, re.MULTILINE):
            language = LanguageType.tex
            self.contains_bye = True
        if re.search(r"^[^%\n]*\\documentclass[^a-zA-Z]", self._data, re.MULTILINE):
            self.contains_documentclass = True
            if language == LanguageType.tex:
                self.issues.append(
                    TeXFileIssue(IssueType.conflicting_file_type, "containing both bye and documentclass")
                )
            language = LanguageType.latex
        self.language = language

    def detect_engine(self) -> None:
        """If possible, update the engine type based on the content of the file."""
        self.engine = EngineType.unknown

    def detect_postprocess(self) -> None:
        """If possible, update the postprocess type based on the content of the file."""
        if self.output_type == OutputType.dvi:
            self.postprocess = PostProcessType.dvips_ps2pdf
        elif self.output_type == OutputType.pdf:
            self.postprocess = PostProcessType.none
        elif self.output_type == OutputType.unknown:
            self.postprocess = PostProcessType.unknown
        else:
            raise PreflightException(f"unknown output type {self.output_type}")

    def detect_output_type(self) -> None:
        """If possible, update the output type based on the content of the file."""
        pdftex_exts = IMAGE_EXTENSIONS["pdftex"].split()
        dvips_exts = IMAGE_EXTENSIONS["dvips"].split()
        for f in self.mentioned_files:
            _, ext = os.path.splitext(f)
            if ext.startswith("."):
                ext = ext[1:]
            found_pdf = ext in pdftex_exts
            found_eps = ext in dvips_exts
            if (
                (found_pdf and found_eps)
                or (self.output_type == OutputType.pdf and found_eps)
                or (self.output_type == OutputType.dvi and found_pdf)
            ):
                self.output_type = OutputType.unknown
                self.issues.append(
                    TeXFileIssue(
                        IssueType.conflicting_image_types, "images of formats that cannot be loaded at the same time"
                    )
                )
            else:
                if found_pdf:
                    self.output_type = OutputType.pdf
                elif found_eps:
                    self.output_type = OutputType.dvi
                else:
                    self.output_type = OutputType.unknown

    def update_engine_based_on_system_files(self) -> None:
        """Check in the list of used systemfiles for indications a specific compiler needs to be used."""
        for f in self.used_system_files:
            if "/luatex/" in f or "/lualatex/" in f:
                self.engine = EngineType.luatex

    def detect_included_files(self) -> None:
        """Detect and update included files."""
        # deal with
        #   \input foobar
        # which does not require braces!
        # Allow filenames with a-zA-Z0-9.-_ but nothing more for now
        # TODO review possibility of UTF8 filenames
        ##
        # TODO deal with order
        # the double search destroys the order that is then preserved
        # in the dict due to insertion order.
        # Later one we want to do depth first search for documentclass etc
        # (contemplate whether this is strictly necessary!)
        for f in re.findall(r"\\input\s+([-a-zA-Z0-9._]+)", self._data):
            self.mentioned_files[str(f)] = INCLUDE_COMMANDS_DICT["input"]
        # check for the rest of include commands
        for i in re.findall(ARGS_INCLUDE_REGEX, self._data, re.MULTILINE | re.VERBOSE):
            logging.debug("%s regex found %s", self.filename, i)
            self.collect_included_files(i)
        logging.debug("%s found included files: %s", self.filename, self.mentioned_files)

    def collect_included_files(self, inc: list[str]) -> None:
        """Determine actually included files from the list of regex group captures."""
        # every inc has four matching groups
        # inc[0] ... command
        # inc[1] ... options (if present)
        # inc[2] ... first argumetn
        # inc[3] ... second argument (if present)
        include_command = inc[0]
        if inc[1]:
            include_options = inc[1]
        else:
            include_options = "[]"
        include_argument = inc[2]
        if inc[3]:
            include_extra_argument = inc[3]
        else:
            include_extra_argument = "{}"

        # check for syntactic correctness of arguments/options
        assert (
            include_command in INCLUDE_COMMANDS_DICT.keys()
        ), f"{include_command} not in {INCLUDE_COMMANDS_DICT.keys()}"
        assert include_options.startswith("[")
        assert include_options.endswith("]")
        assert include_argument.startswith("{")
        assert include_argument.endswith("}")
        assert include_extra_argument.startswith("{")
        assert include_extra_argument.endswith("}")

        # drop [] and {} around options/arguments
        include_options = include_options[1:-1]
        include_argument = include_argument[1:-1]
        include_extra_argument = include_extra_argument[1:-1]

        file_incspec: dict[str, IncludeSpec] = {}

        # we ignore includes in self-defined macros
        if re.match(r"#[1-9]", include_argument):
            self.issues.append(
                TeXFileIssue(
                    IssueType.include_command_with_macro, f"command {include_command} used with macro parameter #"
                )
            )
            # logging.debug("Include command found with macro argument, we cannot deal with this!")
            return

        # checked for the key presence above
        incdef = INCLUDE_COMMANDS_DICT[include_command]

        # first deal with special cases
        if incdef.cmd == "import":  # \import{prefix}{file} searches prefix/file
            filearg = f"{include_argument}/{include_extra_argument}"
            # the first argument might contain a trailing /, so remove double //
            filearg = filearg.replace("//", "/")
            filearg = filearg[2:] if filearg.startswith("./") else filearg
            file_incspec[filearg.strip()] = incdef
        elif incdef.cmd == "usetikzlibrary":
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for f in include_argument.split(","):
                file_incspec[f"tikzlibrary{f.strip()}.code.tex"] = incdef
        elif incdef.cmd == "bibliography":
            # replace end of line comments with empty string
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for bf in include_argument.split(","):
                f = bf.strip()
                f = f[2:] if f.startswith("./") else f
                if f.endswith(".bib"):
                    file_incspec[f] = incdef
                else:
                    file_incspec[f"{f}.bib"] = incdef
        elif incdef.cmd == "usepackage" or incdef.cmd == "RequirePackage":
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for f in include_argument.split(","):
                fn = f.strip()
                fn = fn if fn.endswith(".sty") else f"{fn}.sty"
                file_incspec[fn] = incdef
        else:
            if isinstance(incdef.file_argument, int):
                if incdef.file_argument == 1:
                    filearg = include_argument.strip()
                elif incdef.file_argument == 2:
                    filearg = include_extra_argument.strip()
                else:
                    # logging.error("incdef.file_argument = %s", incdef.file_argument)
                    logging.error("incdef: %s", pformat(incdef))
                    logging.error(
                        "include command %s argument %s option %s extra %s",
                        include_command,
                        include_argument,
                        include_options,
                        include_extra_argument,
                    )
                    raise PreflightException(f"Unexpected number of file_argument value {incdef.file_argument}")
                if incdef.multi_args:
                    for f in filearg.split(","):
                        fn = f[2:] if f.startswith("./") else f
                        file_incspec[fn.strip()] = incdef
                else:
                    filearg = filearg[2:] if filearg.startswith("./") else filearg
                    file_incspec[filearg] = incdef

            else:
                raise PreflightException(f"Unexpected type of file_argument: {type(incdef.file_argument)}")

        logging.debug(file_incspec)
        self.mentioned_files |= file_incspec

    def generic_walk_document_tree(self, map: Callable[["ParsedTeXFile"], T], reduce: Callable[[T, T], T]) -> T:
        """Walk the document tree in map/reduce fashion."""
        return self._generic_walk_document_tree(map, reduce, {})

    def _generic_walk_document_tree(
        self,
        map: Callable[["ParsedTeXFile"], T],
        reduce: Callable[[T, T], T],
        visited: dict[str, bool],
    ) -> T:
        """Call a function on any node of a document tree - internal helper."""
        ret = map(self)
        visited[self.filename] = True
        for n in self.children:
            if n.filename not in visited:
                ret_kid = n._generic_walk_document_tree(map, reduce, visited)
                ret = reduce(ret, ret_kid)
        return ret

    # TODO rewrite using _generic_walk_document_tree - below code breaks with
    def walk_document_tree(self, func: Callable[["ParsedTeXFile"], list[typing.Any]]) -> list[typing.Any]:
        """Call a function on any node of a document tree."""
        # return self._generic_walk_document_tree(
        #     func,
        #     lambda x,y: x.extend(y),
        #     {}
        # )
        return self._walk_document_tree(func, {})

    def _walk_document_tree(
        self, func: Callable[["ParsedTeXFile"], list[typing.Any]], visited: dict[str, bool]
    ) -> list[typing.Any]:
        """Call a function on any node of a document tree - internal helper."""
        ret = func(self)
        visited[self.filename] = True
        for n in self.children:
            if n.filename not in visited:
                ret_kid = n._walk_document_tree(func, visited)
                ret.extend(ret_kid)
        return ret

    # TODO rewrite using _generic_walk_document_tree
    def find_entry_in_subgraph(
        self,
    ) -> tuple[LanguageType, OutputType, EngineType, PostProcessType, list[TeXFileIssue]]:
        """Walk a subgraph to search for properties."""
        return self._find_entry_in_subgraph({})

    def _find_entry_in_subgraph(
        self, visited: dict[str, bool]
    ) -> tuple[LanguageType, OutputType, EngineType, PostProcessType, list[TeXFileIssue]]:
        """Walk a subgraph to search for properties."""
        issues = []
        found_language: LanguageType = self.language
        found_output: OutputType = self.output_type
        found_engine: EngineType = self.engine
        found_postprocess: PostProcessType = self.postprocess
        logging.debug("find_entry_in_subgraph: %s", self.filename)
        for n in self.children:
            if n.filename in visited:
                logging.debug("find_entry_in_subgraph: revisiting %s", n.filename)
                continue
            logging.debug("find_entry_in_subgraph: recursively calling into %s", n.filename)
            visited[n.filename] = True
            kid_language, kid_output, kid_engine, kid_postprocess, kid_issues = n._find_entry_in_subgraph(visited)
            if found_language == LanguageType.unknown:
                found_language = kid_language
            elif found_language == LanguageType.tex:
                if kid_language == LanguageType.latex:
                    issues.append(
                        TeXFileIssue(IssueType.conflicting_file_type, "conflicting lang types of main and subfiles")
                    )
                # always upgrade to LaTeX
                found_language = LanguageType.latex
            elif found_language == LanguageType.latex:
                if kid_language == LanguageType.tex:
                    issues.append(
                        TeXFileIssue(IssueType.conflicting_file_type, "conflicting lang types of main and subfiles")
                    )
                # keep found_language as LATEX
            else:
                raise PreflightException(f"Unknown LanguageType {found_language}")

            if found_output == OutputType.unknown:
                found_output = kid_output
            elif kid_output == OutputType.unknown:
                # keep found_output
                pass
            elif kid_output != found_output:
                issues.append(
                    TeXFileIssue(IssueType.conflicting_output_type, "conflicting output types of main and subfiles")
                )

            if found_engine == EngineType.unknown:
                found_engine = kid_engine
            elif kid_engine == EngineType.unknown:
                # keep found_compiler
                pass
            elif kid_engine != found_engine:
                # TODO maybe order engines? tex < luatex ???
                issues.append(
                    TeXFileIssue(IssueType.conflicting_engine_type, "conflicting engine types of main and subfiles")
                )

            if found_postprocess == PostProcessType.unknown:
                found_postprocess = kid_postprocess
            elif kid_postprocess == PostProcessType.unknown:
                # keep found_compiler
                pass
            elif kid_postprocess != found_postprocess:
                # TODO maybe order engines? tex < luatex ???
                issues.append(
                    TeXFileIssue(
                        IssueType.conflicting_postprocess_type, "conflicting postprocess types of main and subfiles"
                    )
                )

            issues.extend(kid_issues)

        return found_language, found_output, found_engine, found_postprocess, issues

    # TODO rewrite using _generic_walk_document_tree
    def recursive_collect_files(self, what: FileType | str) -> list[str]:
        """Recursively collect all tex/bib/other files."""
        return self._recursive_collect_files(what, {})

    def _recursive_collect_files(self, what: FileType | str, visited: dict[str, bool]) -> list[str]:
        """Recursively collect all tex/bib/other files."""
        if what == FileType.bib:
            idx = "used_bib_files"
        elif what == FileType.tex:
            idx = "used_tex_files"
        elif what == FileType.other:
            idx = "used_other_files"
        elif what == "issues":
            idx = "issues"
        else:
            raise PreflightException(f"no such file type: {what}")
        found: list[str] = getattr(self, idx)
        visited[self.filename] = True
        for n in self.children:
            if n.filename in visited:
                logging.debug("recursive_collect_files: revisiting %s", n.filename)
                continue
            found.extend(n._recursive_collect_files(what, visited))
        return found


class ToplevelFile(BaseModel):
    """Toplevel file and how to compile it."""

    filename: str
    process: MainProcessSpec
    issues: list[TeXFileIssue] = []


class PreflightResponse(BaseModel):
    """Preflight response model."""

    status: PreflightStatus
    detected_toplevel_files: list[ToplevelFile]
    tex_files: list[ParsedTeXFile]
    ancillary_files: list[str]

    def to_json(self, **kwargs: typing.Any) -> str:
        """Return a json representation."""
        return self.json(exclude_none=True, exclude_defaults=True, **kwargs)


#
# GLOBAL CONSTANTS
#

TEX_EXTENSIONS = "tex"
EPS_EXTENSIONS = "eps ps eps.gz ps.gz mps"

# upper/lower case uses case folding!!!!
IMAGE_EXTENSIONS = {
    "pdftex": "pdf png jpg mps jpeg jbig2 jb2",
    "dvips": "eps ps eps.gz ps.gz eps.Z mps",
    "xetex": "pdf ai png jpg jpeg jp2 jpf bmp ps eps mps",
    "dvipdfmx": "pdf ai png jpg jpeg jp2 jpf bmp ps eps mps",
}

# only parse file with these extensions
PARSED_FILE_EXTENSIONS = [".tex", ".sty", ".ltx", ".cls", ".clo"]

single_argument_include_commands = [
    "include",
    "InputIfFileExists",
    "documentclass",
    "LoadClass",
    "LoadClassWithOptions",
    "includegraphics",
    "epsfile",
    "subfile",
    "subfileinclude",
]
multiple_argument_include_commands = [
    "usepackage",
    "RequirePackage",
    "RequirePackageWithOptions",
]
special_argument_include_commands = ["psfig"]

#
CONDITIONALLY_INCLUDED_FILES = [
    "svglov3.clo",
]

# hash command name -> [ take_options, multi_args, possible_extensions ]
INCLUDE_COMMANDS = [
    IncludeSpec(cmd="input", source="core", type=FileType.tex, extensions=TEX_EXTENSIONS, take_options=False),
    IncludeSpec(cmd="include", source="core", type=FileType.tex, extensions=TEX_EXTENSIONS, take_options=False),
    IncludeSpec(
        cmd="InputIfFileExists", source="core", type=FileType.tex, extensions=TEX_EXTENSIONS, take_options=False
    ),
    IncludeSpec(cmd="documentstyle", source="core", type=FileType.tex, extensions="cls"),
    IncludeSpec(cmd="documentclass", source="core", type=FileType.tex, extensions="cls"),
    IncludeSpec(cmd="LoadClass", source="core", type=FileType.tex, extensions="cls"),
    IncludeSpec(cmd="LoadClassWithOptions", source="core", type=FileType.tex, extensions="cls", take_options=False),
    IncludeSpec(
        cmd="usepackage", source="core", type=FileType.tex, extensions="sty", take_options=True, multi_args=True
    ),
    IncludeSpec(
        cmd="RequirePackage",
        source="core",
        type=FileType.tex,
        extensions="sty",
        take_options=True,
        multi_args=True,
    ),
    IncludeSpec(
        cmd="RequirePackageWithOptions",
        source="core",
        type=FileType.tex,
        extensions="sty",
        take_options=False,
        multi_args=False,
    ),
    IncludeSpec(cmd="bibliography", source="core", type=FileType.bib, extensions="bib", take_options=False),
    IncludeSpec(cmd="includegraphics", source="graphics", type=FileType.other, extensions=IMAGE_EXTENSIONS),
    IncludeSpec(cmd="psfig", source="epsfig", type=FileType.other, extensions=EPS_EXTENSIONS),
    IncludeSpec(
        cmd="subfile",
        source="subfiles",
        type=FileType.tex,
        extensions=TEX_EXTENSIONS,
        take_options=False,
        multi_args=False,
    ),
    IncludeSpec(
        cmd="subfileinclude",
        source="subfiles",
        type=FileType.tex,
        extensions=TEX_EXTENSIONS,
        take_options=False,
        multi_args=False,
    ),
    IncludeSpec(cmd="includesvg", source="svg", type=FileType.other, extensions="svg"),
    IncludeSpec(cmd="includepdf", source="pdfpages", type=FileType.other, extensions="pdf"),
    IncludeSpec(cmd="epsfbox", source="epsf", type=FileType.other, extensions=EPS_EXTENSIONS),
    IncludeSpec(cmd="epsfig", source="epsfig", type=FileType.other, extensions=EPS_EXTENSIONS),
    IncludeSpec(
        cmd="loadglsentries", source="glossaries", type=FileType.other, extensions="gls"
    ),  # TODO check extensions!!!
    IncludeSpec(
        cmd="DTLloaddb", source="datatool", type=FileType.other, extensions=None, file_argument=2
    ),  # \DTLloaddb[hoptionsi]{hdb namei}{hfilenamei}
    IncludeSpec(
        cmd="DTLloadrawdb", source="datatool", type=FileType.other, extensions=None, file_argument=2
    ),  # \DTLloaddb[hoptionsi]{hdb namei}{hfilenamei}
    IncludeSpec(
        cmd="import", source="import", type=FileType.tex, extensions=TEX_EXTENSIONS, file_argument=[1, 2]
    ),  # \import{prefix}{file}
    IncludeSpec(
        cmd="usetikzlibrary",
        source="tikz",
        type=FileType.tex,
        extensions=TEX_EXTENSIONS,
        take_options=False,
        multi_args=True,
    ),
    IncludeSpec(
        cmd="usepgflibrary",
        source="tikz",
        type=FileType.tex,
        extensions=TEX_EXTENSIONS,
        take_options=False,
        multi_args=True,
    ),
    IncludeSpec(
        cmd="lstinputlisting", source="listings", type=FileType.tex, extensions=TEX_EXTENSIONS
    ),  # \lstinputlisting[lastline=4]{listings.sty}
    IncludeSpec(cmd="tcbuselibrary", source="tcolorbox", type=FileType.tex, extensions="code.tex"),
    IncludeSpec(cmd="tcbincludegraphics", source="tcolorbos", type=FileType.other, extensions=IMAGE_EXTENSIONS),
    IncludeSpec(cmd="asyinclude", source="asy", type=FileType.other, extensions="asy"),
]
# make a dict with key is include command
INCLUDE_COMMANDS_DICT = {f.cmd: f for f in INCLUDE_COMMANDS}


# TODO
# \openin2=data.txt ... \read2 to \myline ...

# TODO we should auto-generate this regex
ARGS_INCLUDE_REGEX = r"""^[^%\n]*?   # check that line is not a comment
    \\(
        input|
        include|                         # command from the core format
        InputIfFileExists|
        documentstyle|
        documentclass|
        LoadClass|
        LoadClassWithOptions|
        usepackage|
        RequirePackage|
        RequirePackageWithOptions|
        bibliography|
        includegraphics|                 # graphic[sx]
        epsfig|                          # epsfig
        import|                          # import \import{prefix}{file} searches prefix/file
        # includestandalone|               # standalone TODO complicated!
        subfile|                         # subfiles
        subfileinclude|
        includesvg|                      # svg
        includepdf|                      # pdfpages
        epsfbox|                         # epsf
        loadglsentries|                  # glossaries
        DTLloaddb|                       # datatool
        DTLloadrawdb|
        lstinputlisting|                 # listings
        usetikzlibrary|                  # tikz
        usepgflibrary|
        tcbuselibrary|                   # tcolorbox
        tcbincludegraphics|
        asyinclude                       # asy
    )\s*(?:%.*\n)?
    (\[[^]]*\])?\s*(?:%.*\n)?    # optional arguments
    ({[^}]*})\s*(?:%.*\n)?         # actual argument with braces
    ({[^}]*})?                           # second argument with braces
"""


SUPPORTED_PIPELINES: list[str] = ["etex+dvips_ps2pdf", "latex+dvips_ps2pdf", "pdflatex"]


#
# FUNCTIONS
#
def string_to_bool(value: str) -> bool:
    """Convert a string to a bool."""
    if value.lower() in ["true", "yes", "on", "1"]:
        return True
    if value.lower() in ["false", "no", "off", "0"]:
        return False
    raise ParseSyntaxError(f"Cannot parse value to boolean: {value}")


def parse_file(basedir: str, filename: str) -> ParsedTeXFile:
    """Parse a file for included commands."""
    with open(f"{basedir}/{filename}", "rb") as f:
        rawdata = f.read()
    detected_encoding_data = chardet.detect(rawdata)
    encoding: str | None = detected_encoding_data.get("encoding")
    data: str
    if encoding is None:
        encoding = "utf-8"
    try:
        data = str(rawdata.decode(encoding))
    except UnicodeDecodeError:
        logging.warning("Failed to decode %s in %s", filename, encoding)
        try:
            # try once more, this time with ascii
            data = str(rawdata.decode("ascii"))
        except UnicodeDecodeError:
            n = ParsedTeXFile(filename=filename)
            n._data = ""
            n.issues.append(
                TeXFileIssue(IssueType.contents_decode_error, f"cannot decode file, tried {encoding} and ascii")
            )
            return n
    # standardize line endings
    line_ending_re = re.compile(r"\r\n|\r|\n")
    data = re.sub(line_ending_re, "\n", data)
    n = ParsedTeXFile(filename=filename)
    n._data = data
    logging.debug("parse_file: starting detect_included_files %s", n.filename)
    n.detect_included_files()
    logging.debug("parse_file: starting detect_language")
    n.detect_language()
    logging.debug("parse_file: starting detect_engine")
    n.detect_engine()
    logging.debug("parse_file: starting detect_postprocess")
    n.detect_postprocess()
    logging.debug("parse_file: starting detect_output_type")
    n.detect_output_type()
    logging.debug("parse_file: finished parsing")

    # if re.search(r"^[^%]*\\pdfoutput\s*=\s*1", data, re.MULTILINE):
    #    n.process.compiler = TODO

    return n


def parse_dir(rundir: str) -> tuple[dict[str, ParsedTeXFile] | ToplevelFile, list[str]]:
    """Parse all TeX files in a directory."""
    files = glob.glob(f"{rundir}/**/*", recursive=True)
    # strip rundir/ prefix
    n = len(rundir) + 1
    files = [f[n:] for f in files if os.path.isfile(f)]
    # ancillary files
    anc_files = [t for t in files if t.startswith("anc/")]
    # files = os.listdir(rundir)
    # needs more extensions that we support
    tex_files = [t for t in files if os.path.splitext(t)[1].lower() in PARSED_FILE_EXTENSIONS]
    if not tex_files:
        # we didn't find any tex file, check for a single PDF file
        if len(files) == 1 and files[0].lower().endswith(".pdf"):
            # PDF only submission, only one PDF file, nothing else
            return ToplevelFile(
                filename=files[0], process=MainProcessSpec(compiler=CompilerSpec(compiler=PDF_SUBMISSION_STRING))
            ), anc_files
        else:
            # check for HTML submissions
            for f in sorted(files):
                if f.lower().endswith(".html"):
                    return ToplevelFile(
                        filename=f, process=MainProcessSpec(compiler=CompilerSpec(compiler=HTML_SUBMISSION_STRING))
                    ), anc_files
    nodes = {f: parse_file(rundir, f) for f in tex_files}
    # print(nodes)
    return nodes, anc_files


def kpse_search_files(basedir: str, nodes: dict[str, ParsedTeXFile]) -> dict[str, str]:
    """Search for files using kpsearch, using the lua script kpse_search.lua."""
    kpse_find_input_data = ""
    for _, n in nodes.items():
        for k, v in n.mentioned_files.items():
            if isinstance(v.extensions, dict):
                if n.output_type == OutputType.dvi:  # TODO should we check for dvipdfmx?
                    if n.postprocess == PostProcessType.dvips_ps2pdf:
                        exts = v.extensions["dvips"]
                    elif n.postprocess == PostProcessType.dvipdfmx:
                        exts = v.extensions["dvipdfmx"]
                    else:
                        exts = v.extensions["pdftex"]  # assume pdflatex as default
                elif n.output_type == OutputType.pdf or n.output_type == OutputType.unknown:  # TODO unify these cases?
                    if n.engine == EngineType.tex:
                        exts = v.extensions["pdftex"]
                    elif n.engine == EngineType.xetex or n.engine == EngineType.luatex:
                        exts = v.extensions["xetex"]
                    else:
                        exts = v.extensions["pdftex"]
            else:
                exts = v.extensions
            kpse_find_input_data += f"{k}\n{exts}\n"
    logging.debug("kpse_find_input_data ===%s===", kpse_find_input_data)

    if not kpse_find_input_data:
        return {}

    p = subprocess.run(
        ["texlua", f"{MODULE_PATH}/kpse_search.lua", "-mark-sys-files", basedir],
        input=kpse_find_input_data,
        capture_output=True,
        text=True,
        check=True,
    )

    # read back the output information
    kpse_found = {}
    for fname, found in zip_longest(*[iter(p.stdout.splitlines())] * 2, fillvalue=""):
        kpse_found[fname] = found[2:] if found.startswith("./") else found

    return kpse_found


def update_nodes_with_kpse_info(
    nodes: dict[str, ParsedTeXFile], kpse_found: dict[str, str]
) -> dict[str, ParsedTeXFile]:
    """Update the parsed tex files with the location of used files."""
    for _, n in nodes.items():
        for f in n.mentioned_files:
            if f in kpse_found:
                found = kpse_found[f]
            else:
                logging.error("kpse_found not containing =%s=", f)
                break
            if found.startswith("SYSTEM:"):
                # record system files serparately
                n.used_system_files.append(found[7:])
                continue
            # if we don't find the file, and it is not loaded optionally, record it as issue
            if found == "":
                if n.mentioned_files[f].cmd != "InputIfFileExists":
                    n.issues.append(TeXFileIssue(IssueType.file_not_found, f))
                continue
            if n.mentioned_files[f].type == FileType.tex:
                n.used_tex_files.append(found)
            elif n.mentioned_files[f].type == FileType.bib:
                n.used_bib_files.append(found)
            elif n.mentioned_files[f].type == FileType.other:
                n.used_other_files.append(found)
            else:
                raise PreflightException(f"Unknown file type {n.mentioned_files[f].type} for file {f}")
        n.update_engine_based_on_system_files()
    return nodes


def compute_document_graph(
    nodes: dict[str, ParsedTeXFile],
) -> tuple[dict[str, ParsedTeXFile], dict[str, ParsedTeXFile]]:
    """Create the file graph from the included files information."""
    roots = {}
    for _, n in nodes.items():
        for sn in n.used_tex_files:
            if sn in nodes:
                n.children.append(nodes[sn])
                nodes[sn].parents.append(n)
            else:
                # only log a warning when the parsed node has an extension that we
                # are supposed to parse
                if any([sn.endswith(x) for x in PARSED_FILE_EXTENSIONS]):
                    # exclude some files that are conditionally loaded but usually not present
                    if sn not in CONDITIONALLY_INCLUDED_FILES:
                        logging.warning("Cannot find parsed node for used tex file %s", sn)
    for fn, n in nodes.items():
        # print(f"working on {n.filename} - parents = {n.parents}")
        if not n.parents:
            # print("n.parents is true")
            roots[fn] = n
    return roots, nodes


def compute_toplevel_files(roots: dict[str, ParsedTeXFile], nodes: dict[str, ParsedTeXFile]) -> dict[str, ToplevelFile]:
    """Determine the toplevel files."""
    toplevel_files = {}
    for f, n in roots.items():
        # don't consider sty/cls/clo as toplevel, even if they are not used
        if f.endswith(".sty") or f.endswith(".cls") or f.endswith(".clo"):
            continue
        found_language, found_output, found_engine, found_postprocess, issues = n.find_entry_in_subgraph()
        engine: EngineType = EngineType.tex if found_engine == EngineType.unknown else found_engine
        lang: LanguageType = LanguageType.tex if found_language == LanguageType.unknown else found_language
        output: OutputType
        if lang == LanguageType.tex:
            output = OutputType.dvi if found_output == OutputType.unknown else found_output
        elif lang == LanguageType.latex:
            output = OutputType.pdf if found_output == OutputType.unknown else found_output
        else:
            raise PreflightException(f"Unsupported language type {lang}")
        postprocess: PostProcessType
        if output == OutputType.dvi:
            postprocess = (
                PostProcessType.dvips_ps2pdf if found_postprocess == PostProcessType.unknown else found_postprocess
            )
        elif output == OutputType.pdf:
            postprocess = PostProcessType.none if found_postprocess == PostProcessType.unknown else found_postprocess
        tl = ToplevelFile(
            filename=n.filename,
            process=MainProcessSpec(compiler=CompilerSpec(engine=engine, output=output, lang=lang, postp=postprocess)),
        )
        compiler: str | None = None if tl.process.compiler is None else tl.process.compiler.compiler_string
        if compiler is None:
            issues.append(TeXFileIssue(IssueType.unsupported_compiler_type, "compiler cannot be determined"))
        elif compiler not in SUPPORTED_PIPELINES:
            issues.append(TeXFileIssue(IssueType.unsupported_compiler_type, f"compiler {compiler} not supported"))

        # count issues in sub files
        tl_n = nodes[f]
        for fn, nr_issues in tl_n.walk_document_tree(lambda n: [tuple((n.filename, len(n.issues)))]):
            if nr_issues > 0:
                issues.append(TeXFileIssue(IssueType.issue_in_subfile, str(nr_issues), filename=fn))
        tl.issues = issues
        # it is not enough to be a latex file and a root file to be a toplevel file
        # we need to have documentclass being found in one of the include files
        contains_documentclass_somewhere = tl_n.generic_walk_document_tree(
            lambda x: x.contains_documentclass, lambda x, y: x or y
        )
        contains_bye_somewhere = tl_n.generic_walk_document_tree(lambda x: x.contains_bye, lambda x, y: x or y)
        if contains_documentclass_somewhere or contains_bye_somewhere:
            toplevel_files[f] = tl

    return toplevel_files


def deal_with_bibliographies(
    rundir: str, toplevel_files: dict[str, ToplevelFile], nodes: dict[str, ParsedTeXFile]
) -> None:
    """Check for inclusion of bib files and presence .bbl files."""
    for tl_f, tl_n in toplevel_files.items():
        bbl_file = tl_f.rstrip(".tex").rstrip(".TEX") + ".bbl"
        bbl_file_present = os.path.isfile(f"{rundir}/{bbl_file}")
        if bbl_file_present:
            # toplevel filename .bbl is available -> precompiled bib, ignore if bib files is missing
            tl_n.process.bibliography = BibProcessSpec(processor=BibCompiler.unknown, pre_generated=True)
            # add bbl file to the list of used_other_files
            nodes[tl_f].used_other_files.append(bbl_file)
            # TODO, maybe remove issues with missing .bib files?
            continue
        # toplevel filename .bbl is missing -> require .bib to be available,
        top_node = nodes[tl_f]
        all_bib = top_node.recursive_collect_files(FileType.bib)
        if all_bib:
            # TODO detect biber usage!
            tl_n.process.bibliography = BibProcessSpec(processor=BibCompiler.unknown, pre_generated=False)


def _generate_preflight_response_dict(rundir: str) -> PreflightResponse:
    """Parse submission and generated preflight response as dictionary."""
    # parse files
    n: dict[str, ParsedTeXFile] | ToplevelFile
    anc_files: list[str]
    nodes: dict[str, ParsedTeXFile]
    roots: dict[str, ParsedTeXFile]
    toplevel_files: dict[str, ToplevelFile]

    n, anc_files = parse_dir(rundir)
    if isinstance(n, ToplevelFile):
        # pdf only submission, we received the toplevel file already
        toplevel_files = {n.filename: n}
        nodes = {}
        status = PreflightStatus(key=PreflightStatusValues.success)
    else:
        nodes = n
        if nodes == {}:
            roots = {}
            toplevel_files = {}
            status = PreflightStatus(key=PreflightStatusValues.error, info="No TeX files found")
        else:
            # search for files with kpse
            kpse_found = kpse_search_files(rundir, nodes)
            # update nodes with information of found kpse
            nodes = update_nodes_with_kpse_info(nodes, kpse_found)
            logging.debug("found TeX file nodes: %s", nodes.keys())
            # create tree
            roots, nodes = compute_document_graph(nodes)
            logging.debug("found root nodes: %s", roots.keys())
            # determine toplevel files
            toplevel_files = compute_toplevel_files(roots, nodes)
            # deal with bibliographies, which is painful
            deal_with_bibliographies(rundir, toplevel_files, nodes)
            # TODO check for suspicious status!
            status = PreflightStatus(key=PreflightStatusValues.success)
    return PreflightResponse(
        status=status,
        detected_toplevel_files=[tl for tl in toplevel_files.values()],
        tex_files=[n for n in nodes.values()],
        ancillary_files=anc_files,
    )


def generate_preflight_response(rundir: str, json: bool = False, **kwargs: typing.Any) -> PreflightResponse | str:
    """Parse submission and generated preflight response as dictionary or json."""
    try:
        pfr: PreflightResponse = _generate_preflight_response_dict(rundir)
    except PreflightException as e:
        pfr = PreflightResponse(
            status=PreflightStatus(key=PreflightStatusValues.error, info=str(e)),
            detected_toplevel_files=[],
            tex_files=[],
            ancillary_files=[],
        )
    if json:
        return pfr.to_json(**kwargs)
    else:
        return pfr