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

# switching from chardet to charset_normalizer
# from chardet import detect as charset_detect
from charset_normalizer import detect as charset_detect
from pydantic import BaseModel, Field

# tell ruff to not complain, I don't want to add __all__ entries
from .report import PreflightReport  # noqa

MODULE_PATH = os.path.dirname(__file__)

T = TypeVar("T")

PDF_SUBMISSION_STRING = "pdf_submission"
HTML_SUBMISSION_STRING = "html_submission"

# Version of the bbl file that is created by biber in the
# current version of arxiv tex
# TL2025
# ======
# biber 2.20
# biblatex: 3.20
# bbl format: 3.3
#
# TL2024
# ======
# biber 2.20
# biblatex: 3.20
# bbl format: 3.3
#
# arXiv TeX TL2023
# ================
# biber 2.19
# biblatex 3.19
# bbl format: 3.2
CURRENT_ARXIV_TEX_BBL_VERSION = "3.2"

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
    bib = "bib"  # source bibliography
    idx = "idx"  # source index, but can have arbitrary extensions!
    bbl = "bbl"  # generated bibliography
    ind = "ind"  # generated index, but can have arbitrary extensions!
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

    def ext_str(self) -> str:
        """Return the list of extensions as string."""
        exts: str = ""
        if isinstance(self.extensions, dict):
            exts = ALL_IMAGE_EXTS
        elif self.extensions is None:
            exts = ""
        else:
            exts = self.extensions
        return exts


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
        # further aliases:
        # tex -> etex+dvips_ps2pdf
        # latex -> latex+dvips_ps2pdf
        if compiler == "tex":
            self.lang = LanguageType.tex
            self.engine = EngineType.tex
            self.output = OutputType.dvi
            self.postp = PostProcessType.dvips_ps2pdf
            return
        if compiler == "latex":
            self.lang = LanguageType.latex
            self.engine = EngineType.tex
            self.output = OutputType.dvi
            self.postp = PostProcessType.dvips_ps2pdf
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
    index_definition_missing = "index_definition_missing"
    bbl_version_mismatch = "bbl_version_mismatch"
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
    _data: str = ""
    language: LanguageType = LanguageType.unknown
    contains_documentclass: bool = False
    contains_bye: bool = False
    contains_pdfoutput_true: bool = False
    contains_pdfoutput_false: bool = False
    hyperref_found: bool | None = None
    used_tex_files: list[str] = []
    used_bib_files: list[str] = []
    used_idx_files: list[str] = []
    used_bbl_files: list[str] = []
    used_ind_files: list[str] = []
    used_other_files: list[str] = []
    used_system_files: list[str] = Field(exclude=True, default=[])
    mentioned_files: dict[str, dict[str, IncludeSpec]] = Field(exclude=True, default={})
    issues: list[TeXFileIssue] = []
    children: list["ParsedTeXFile"] = Field(exclude=True, default=[])
    parents: list["ParsedTeXFile"] = Field(exclude=True, default=[])

    def detect_language(self) -> None:
        """Detect the language used in the given file (TeX, LaTeX, or unknown)."""
        # the default languages is UNKNOWN, but if we detect
        # certain values, switch to either TEX or LATEX only
        # we check for \bye first, so that if a file contains both
        # \documentclass and \bye (which is a syntax error!)
        self.language = LanguageType.unknown
        if self.filename.endswith(".sty"):
            self.language = LanguageType.latex
        if re.search(r"\\text(bf|it|sl)|\\section|\\chapter", self._data, re.MULTILINE):
            self.language = LanguageType.latex
        if re.search(r"^[^%\n]*\\bye(?![a-zA-Z])", self._data, re.MULTILINE):
            self.language = LanguageType.tex
            self.contains_bye = True
        if re.search(r"^[^%\n]*\\documentclass[^a-zA-Z]", self._data, re.MULTILINE):
            self.contains_documentclass = True
            if self.language == LanguageType.tex:
                self.issues.append(
                    TeXFileIssue(IssueType.conflicting_file_type, "containing both bye and documentclass")
                )
            self.language = LanguageType.latex

        if re.search(r"^[^%]*\\pdfoutput\s*=\s*1", self._data, re.MULTILINE):
            self.contains_pdfoutput_true = True
        if re.search(r"^[^%]*\\pdfoutput\s*=\s*0", self._data, re.MULTILINE):
            self.contains_pdfoutput_false = True

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

        # preprocess data to remove comments
        data = re.sub(re.compile(r"(?<!\\)%.*\n"), "", self._data)
        for f in re.findall(r"\\input\s+([-a-zA-Z0-9._]+)", data):
            self.mentioned_files[str(f)] = {"input": INCLUDE_COMMANDS_DICT["input"]}
        # check for the rest of include commands
        for i in re.findall(ARGS_INCLUDE_REGEX, data, re.MULTILINE | re.VERBOSE):
            logging.debug("%s regex found %s", self.filename, i)
            self.collect_included_files(i)
        logging.debug("%s found included files: %s", self.filename, self.mentioned_files)

    def collect_included_files(self, inc: list[str]) -> None:
        """Determine actually included files from the list of regex group captures."""
        # every inc has four matching groups
        # inc[0] ... command
        # inc[1] ... options (if present)
        # inc[2] ... first argument
        # inc[3] ... second argument (if present)
        # inc[4] ... third argument (if present)
        include_command = inc[0]
        # special cases for environment style commands
        if re.match(r"begin\s*{\s*overpic\s*}", include_command):
            include_command = "overpic"
        if inc[1]:
            include_options = inc[1]
        else:
            include_options = "[]"
        if inc[2]:
            include_argument = inc[2]
        else:
            include_argument = "{}"
        if inc[3]:
            include_extra_argument = inc[3]
        else:
            include_extra_argument = "{}"
        if inc[4]:
            include_extra2_argument = inc[4]
        else:
            include_extra2_argument = "{}"

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
        assert include_extra2_argument.startswith("{")
        assert include_extra2_argument.endswith("}")

        # drop [] and {} around options/arguments
        include_options = include_options[1:-1]
        include_argument = include_argument[1:-1]
        include_extra_argument = include_extra_argument[1:-1]
        include_extra2_argument = include_extra2_argument[1:-1]

        file_incspec: dict[str, dict[str, IncludeSpec]] = {}

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
            file_incspec[filearg.strip().strip('"')] = {incdef.cmd: incdef}
        elif incdef.cmd == "usetikzlibrary":
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for f in include_argument.split(","):
                file_incspec[f"""tikzlibrary{f.strip().strip('"')}.code.tex"""] = {incdef.cmd: incdef}
        elif incdef.cmd == "bibliography":
            # replace end of line comments with empty string
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for bf in include_argument.split(","):
                f = bf.strip().strip('"')
                f = f[2:] if f.startswith("./") else f
                if f.endswith(".bib"):
                    file_incspec[f] = {incdef.cmd: incdef}
                else:
                    file_incspec[f"{f}.bib"] = {incdef.cmd: incdef}
        elif incdef.cmd == "makeindex":  # \makeindex -> \newindex{default}{idx}{ind}{Index}
            logging.debug("makeindex found")
            # encode the information of index definition into the filename
            file_incspec["<MAIN>.<default>.<idx>.<ind>"] = {incdef.cmd: incdef}
        elif incdef.cmd == "newindex":  # \newindex{tag}{raw_extension}{compiled_extension}{Whatever title}
            logging.debug(f"newindex found with tag {include_extra_argument} and {include_extra2_argument}")
            # encode the information of index definition into the filename
            file_incspec[f"<MAIN>.<{include_argument}>.<{include_extra_argument}>.<{include_extra2_argument}>"] = {
                incdef.cmd: incdef
            }
        elif incdef.cmd == "printindex":  # \printindex[tag] (default is <default> for tag
            logging.debug(f"printindex found with tag {include_options}")
            if include_options == "":
                tag = "default"
            else:
                tag = include_options
            # encode the information of index usage tag into the filename
            file_incspec[f"<MAIN>.<{tag}>"] = {incdef.cmd: incdef}
        elif incdef.cmd == "usepackage" or incdef.cmd == "RequirePackage":
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for f in include_argument.split(","):
                fn = f.strip().strip('"')
                fn = fn if fn.endswith(".sty") else f"{fn}.sty"
                if fn == "hyperref.sty":
                    self.hyperref_found = True
                file_incspec[fn] = {incdef.cmd: incdef}
        else:
            if isinstance(incdef.file_argument, int):
                if incdef.file_argument == 1:
                    filearg = include_argument.strip().strip('"')
                elif incdef.file_argument == 2:
                    filearg = include_extra_argument.strip().strip('"')
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
                        file_incspec[fn.strip().strip('"')] = {incdef.cmd: incdef}
                else:
                    filearg = filearg[2:] if filearg.startswith("./") else filearg
                    file_incspec[filearg] = {incdef.cmd: incdef}

            else:
                raise PreflightException(f"Unexpected type of file_argument: {type(incdef.file_argument)}")

        logging.debug(file_incspec)
        # clean up the actual file argument
        # the filearg could be very strange stuff, like when \includegraphics is redefined
        # \def\includegraphics{....}
        # in the case of agutexSI2019.cls, the .... even includes a \n
        file_incspec_cleaned: dict[str, dict[str, IncludeSpec]] = {}
        for k, v in file_incspec.items():
            k_cleaned = k.encode("unicode_escape").decode("utf-8")
            file_incspec_cleaned[k_cleaned] = v
        for k, v in file_incspec_cleaned.items():
            if k in self.mentioned_files:
                self.mentioned_files[k] |= file_incspec_cleaned[k]
            else:
                self.mentioned_files[k] = file_incspec_cleaned[k]

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
    ) -> tuple[LanguageType, list[TeXFileIssue]]:
        """Walk a subgraph to search for properties."""
        return self._find_entry_in_subgraph({})

    def _find_entry_in_subgraph(self, visited: dict[str, bool]) -> tuple[LanguageType, list[TeXFileIssue]]:
        """Walk a subgraph to search for properties."""
        issues = []
        found_language: LanguageType = self.language
        logging.debug("find_entry_in_subgraph: %s", self.filename)
        for n in self.children:
            if n.filename in visited:
                logging.debug("find_entry_in_subgraph: revisiting %s", n.filename)
                continue
            logging.debug("find_entry_in_subgraph: recursively calling into %s", n.filename)
            visited[n.filename] = True
            kid_language, kid_issues = n._find_entry_in_subgraph(visited)
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

            issues.extend(kid_issues)

        return found_language, issues

    # TODO rewrite using _generic_walk_document_tree
    def recursive_collect_files(self, what: FileType | str) -> list[str]:
        """Recursively collect all tex/bib/other files."""
        return self._recursive_collect_files(what, {})

    def _recursive_collect_files(self, what: FileType | str, visited: dict[str, bool]) -> list[str]:
        """Recursively collect all tex/bib/other files."""
        if what == FileType.bib:
            idx = "used_bib_files"
        elif what == FileType.bbl:
            idx = "used_bbl_files"
        elif what == FileType.ind:
            idx = "used_ind_files"
        elif what == FileType.idx:
            idx = "used_idx_files"
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
    hyperref_found: bool | None = None
    issues: list[TeXFileIssue] = []


class PreflightResponse(BaseModel):
    """Preflight response model."""

    status: PreflightStatus
    detected_toplevel_files: list[ToplevelFile]
    tex_files: list[ParsedTeXFile]
    ancillary_files: list[str]

    def to_json(self, **kwargs: typing.Any) -> str:
        """Return a json representation."""
        return self.model_dump_json(exclude_none=True, exclude_defaults=True, **kwargs)


#
# GLOBAL CONSTANTS
#

TEX_EXTENSIONS = "tex"
EPS_EXTENSIONS = "eps ps eps.gz ps.gz mps"

# upper/lower case uses case folding!!!!
# TODO: check whether luatex actually support mps without shell-escape
IMAGE_EXTENSIONS = {
    "pdftex": "pdf png jpg mps jpeg jbig2 jb2",
    "luatex": "pdf png jpg mps jpeg jbig2 jb2",
    "dvips": "eps ps eps.gz ps.gz eps.Z mps",
    "dvipdfmx": "pdf ai png jpg jpeg jp2 jpf bmp ps eps mps",
}


def _merge(a: list[T], b: list[T]) -> list[T]:
    return a + [e_b for e_b in b if e_b not in a]


_extss: list[str] = IMAGE_EXTENSIONS["pdftex"].split()
_extss = _merge(_extss, IMAGE_EXTENSIONS["dvips"].split())
_extss = _merge(_extss, IMAGE_EXTENSIONS["dvipdfmx"].split())
_extss = _merge(_extss, IMAGE_EXTENSIONS["luatex"].split())
ALL_IMAGE_EXTS: str = " ".join(_extss)

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
    IncludeSpec(cmd="includestandalone", source="standalone", type=FileType.tex, extensions=TEX_EXTENSIONS),
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
    IncludeSpec(cmd="newindex", source="index", type=FileType.idx),
    IncludeSpec(cmd="makeindex", source="index", type=FileType.idx),
    IncludeSpec(cmd="printindex", source="index", type=FileType.ind),
    IncludeSpec(cmd="overpic", source="overpic", type=FileType.other, extensions=IMAGE_EXTENSIONS),
]
# make a dict with key is include command
INCLUDE_COMMANDS_DICT = {f.cmd: f for f in INCLUDE_COMMANDS}


# TODO
# \openin2=data.txt ... \read2 to \myline ...

# TODO we should auto-generate this regex
ARGS_INCLUDE_REGEX = r"""
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
        includestandalone|               # standalone \includestandalone[〈options〉]{〈file〉}
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
        asyinclude|                      # asy
        newindex|                        # index
        makeindex|
        printindex|
        begin\s*{\s*overpic\s*}          # overpic
    )\s*(?:%.*\n)?
    \s*(\[[^]]*\])?\s*(?:%.*\n)?      # optional arguments
    \s*({[^}]*})?\s*(?:%.*\n)?        # actual argument with braces
    \s*({[^}]*})?\s*(?:%.*\n)?        # second argument with braces
    \s*({[^}]*})?                     # third argument with braces
    (?=\s*(\W|$))                         # any non-word character terminating the command
"""

# All possible CompilerSpecs
# tex / dvi
COMPILER: dict[str, CompilerSpec] = dict()
COMPILER["tex"] = CompilerSpec(
    engine=EngineType.tex, output=OutputType.dvi, postp=PostProcessType.dvips_ps2pdf, lang=LanguageType.tex
)
COMPILER["dviluatex"] = CompilerSpec(
    engine=EngineType.luatex, output=OutputType.dvi, postp=PostProcessType.dvips_ps2pdf, lang=LanguageType.tex
)
COMPILER["ptex"] = CompilerSpec(
    engine=EngineType.ptex, output=OutputType.dvi, postp=PostProcessType.dvipdfmx, lang=LanguageType.tex
)
COMPILER["uptex"] = CompilerSpec(
    engine=EngineType.uptex, output=OutputType.dvi, postp=PostProcessType.dvipdfmx, lang=LanguageType.tex
)

# tex / pdf
COMPILER["pdftex"] = CompilerSpec(
    engine=EngineType.tex, output=OutputType.pdf, postp=PostProcessType.none, lang=LanguageType.tex
)
COMPILER["luatex"] = CompilerSpec(
    engine=EngineType.luatex, output=OutputType.pdf, postp=PostProcessType.none, lang=LanguageType.tex
)
COMPILER["xetex"] = CompilerSpec(
    engine=EngineType.xetex, output=OutputType.pdf, postp=PostProcessType.none, lang=LanguageType.tex
)

# latex / dvi
COMPILER["latex"] = CompilerSpec(
    engine=EngineType.tex, output=OutputType.dvi, postp=PostProcessType.dvips_ps2pdf, lang=LanguageType.latex
)
COMPILER["dvilualatex"] = CompilerSpec(
    engine=EngineType.luatex, output=OutputType.dvi, postp=PostProcessType.dvips_ps2pdf, lang=LanguageType.latex
)
COMPILER["platex"] = CompilerSpec(
    engine=EngineType.ptex, output=OutputType.dvi, postp=PostProcessType.dvipdfmx, lang=LanguageType.latex
)
COMPILER["uplatex"] = CompilerSpec(
    engine=EngineType.uptex, output=OutputType.dvi, postp=PostProcessType.dvipdfmx, lang=LanguageType.latex
)

# latex / pdf
COMPILER["pdflatex"] = CompilerSpec(
    engine=EngineType.tex, output=OutputType.pdf, postp=PostProcessType.none, lang=LanguageType.latex
)
COMPILER["lualatex"] = CompilerSpec(
    engine=EngineType.luatex, output=OutputType.pdf, postp=PostProcessType.none, lang=LanguageType.latex
)
COMPILER["xelatex"] = CompilerSpec(
    engine=EngineType.xetex, output=OutputType.pdf, postp=PostProcessType.none, lang=LanguageType.latex
)

ALL_COMPILERS = list(COMPILER.values())
ALL_COMPILERS_STR = [c.compiler_string for c in ALL_COMPILERS]
DVI_COMPILERS = [c for c in ALL_COMPILERS if c.output == OutputType.dvi]
DVI_COMPILERS_STR = [c.compiler_string for c in DVI_COMPILERS]
PDF_COMPILERS = [c for c in ALL_COMPILERS if c.output == OutputType.pdf]
PDF_COMPILERS_STR = [c.compiler_string for c in PDF_COMPILERS]
TEX_COMPILERS = [c for c in ALL_COMPILERS if c.lang == LanguageType.tex]
TEX_COMPILERS_STR = [c.compiler_string for c in TEX_COMPILERS]
LATEX_COMPILERS = [c for c in ALL_COMPILERS if c.lang == LanguageType.latex]
LATEX_COMPILERS_STR = [c.compiler_string for c in LATEX_COMPILERS]
FONTSPEC_ALLOWED_COMPILERS = [c for c in ALL_COMPILERS if c.engine == EngineType.luatex or c.engine == EngineType.xetex]
FONTSPEC_ALLOWED_COMPILERS_STR = [c.compiler_string for c in FONTSPEC_ALLOWED_COMPILERS]
# check that we can represent all defined compilers as strings
for c in ALL_COMPILERS:
    assert c.compiler_string is not None
# the following order also gives the preference!
SUPPORTED_COMPILERS: list[CompilerSpec] = [COMPILER["pdflatex"], COMPILER["latex"], COMPILER["tex"]]
SUPPORTED_COMPILERS_STR: list[str | None] = [c.compiler_string for c in SUPPORTED_COMPILERS]


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
    detected_encoding_data = charset_detect(rawdata)
    encoding: str | None = detected_encoding_data.get("encoding")
    data: str
    if encoding is None:
        encoding = "utf-8"
    # order of encodings we try:
    # - utf-8 (which includes ascii!)
    # - detected encoding
    try_encodings: list[str] = []
    if encoding != "utf-8":
        try_encodings.append("utf-8")
    try_encodings.append(encoding)
    logging.debug("Trying the following encodings in order: %s", try_encodings)
    found_encoding: str | None = None
    for enc in try_encodings:
        try:
            data = str(rawdata.decode(enc))
            found_encoding = enc
            logging.debug("Detected encoding %s", enc)
            break
        except UnicodeDecodeError:
            logging.debug("Failed to decode %s in %s", filename, enc)
    if not found_encoding:
        n = ParsedTeXFile(filename=filename)
        n._data = ""
        n.issues.append(TeXFileIssue(IssueType.contents_decode_error, f"cannot decode file, tried {try_encodings}"))
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
    logging.debug("parse_file: finished parsing")

    return n


def parse_dir(rundir: str) -> tuple[dict[str, ParsedTeXFile] | ToplevelFile, list[str]]:
    """Parse all TeX files in a directory."""
    glob_files = glob.glob(f"{rundir}/**/*", recursive=True)
    # strip rundir/ prefix
    n = len(rundir) + 1
    all_files = [f[n:] for f in glob_files if os.path.isfile(f)]
    # we will not analyze ancillary files
    files = [f for f in all_files if not f.startswith("anc/")]
    # ancillary files
    anc_files = [t for t in all_files if t.startswith("anc/")]
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


def kpse_search_files(basedir: str, nodes: dict[str, ParsedTeXFile]) -> dict[str, dict[str, str]]:
    """Search for files using kpsearch, using the lua script kpse_search.lua."""
    kpse_find_input_data = ""
    for _, n in nodes.items():
        for k, subv in n.mentioned_files.items():
            for cmd, v in subv.items():
                # we don't know the \jobname by now, so we cannot search for index files
                # (.idx/.ind/etc)
                if k.startswith("<MAIN>."):
                    continue
                exts = v.ext_str()
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

    logging.debug("kpse_found return: ===\n%s\n===", p.stdout)

    # read back the output information
    kpse_found: dict[str, dict[str, str]] = {}
    for fname, exts, found in zip_longest(*[iter(p.stdout.splitlines())] * 3, fillvalue=""):
        logging.debug("zipping gives fname / exts / found = %s / %s / %s", fname, exts, found)
        if fname not in kpse_found:
            kpse_found[fname] = {}
        if found.startswith("./anc/"):
            # ignore ancillary files in the return, they should be marked
            # as not existing
            kpse_found[fname][exts] = ""
        else:
            kpse_found[fname][exts] = found[2:] if found.startswith("./") else found

    logging.debug("kpse_found return ====%s===", kpse_found)
    return kpse_found


def update_nodes_with_kpse_info(
    nodes: dict[str, ParsedTeXFile], kpse_found: dict[str, dict[str, str]]
) -> dict[str, ParsedTeXFile]:
    """Update the parsed tex files with the location of used files."""
    for _, n in nodes.items():
        for f, subv in n.mentioned_files.items():
            for cmd, v in subv.items():
                v_exts = v.ext_str()
                if f in kpse_found and v_exts in kpse_found[f]:
                    found = kpse_found[f][v_exts]
                elif f.startswith("<MAIN>."):
                    # deal with index idx/ind files that are based on jobname
                    # and aren't found.
                    logging.debug(r"keeping \jobname file %s", f)
                    found = f
                else:
                    logging.error("kpse_found not containing =%s=", f)
                    break
                if found.startswith("SYSTEM:"):
                    # record system files serparately
                    n.used_system_files.append(found[7:])
                    continue
                # if we don't find the file, and it is not loaded optionally, record it as issue
                if found == "":
                    if v.cmd != "InputIfFileExists":
                        n.issues.append(TeXFileIssue(IssueType.file_not_found, f))
                    continue
                if v.type == FileType.tex:
                    n.used_tex_files.append(found)
                elif v.type == FileType.bib:
                    n.used_bib_files.append(found)
                elif v.type == FileType.bbl:
                    n.used_bbl_files.append(found)
                elif v.type == FileType.ind:
                    n.used_ind_files.append(found)
                elif v.type == FileType.idx:
                    n.used_idx_files.append(found)
                elif v.type == FileType.other:
                    n.used_other_files.append(found)
                else:
                    raise PreflightException(f"Unknown file type {v.type} for file {f}")
            # n.update_engine_based_on_system_files()
            # n.update_compiler_data()
            # logging.debug("update_nodes_with_kpse_info: %s engine set to %s", n.filename, n.engine)
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
        tl = ToplevelFile(filename=n.filename, process=MainProcessSpec())
        tl_n = nodes[f]
        # check for hyperref
        hyperref_found = tl_n.generic_walk_document_tree(lambda x: x.hyperref_found, lambda x, y: x or y)
        # we want True/False, but hyperref_found could contain None
        tl.hyperref_found = True if hyperref_found else False
        # it is not enough to be a latex file and a root file to be a toplevel file
        # we need to have documentclass being found in one of the include files
        contains_documentclass_somewhere = tl_n.generic_walk_document_tree(
            lambda x: x.contains_documentclass, lambda x, y: x or y
        )
        contains_bye_somewhere = tl_n.generic_walk_document_tree(lambda x: x.contains_bye, lambda x, y: x or y)
        if contains_documentclass_somewhere or contains_bye_somewhere:
            toplevel_files[f] = tl

    return toplevel_files


def guess_compilation_parameters(toplevel_files: dict[str, ToplevelFile], nodes: dict[str, ParsedTeXFile]) -> None:
    """Guess the compilation parameters from the accumulated information."""
    for f, tl in toplevel_files.items():
        tl_n = nodes[f]

        # CompilerSpec is not hashable, so we cannot directly use it as set elements
        candidate_compilers = set(ALL_COMPILERS_STR)

        found_language, issues = tl_n.find_entry_in_subgraph()

        contains_pdfoutput_true = tl_n.generic_walk_document_tree(
            lambda x: x.contains_pdfoutput_true, lambda x, y: x or y
        )
        contains_pdfoutput_false = tl_n.generic_walk_document_tree(
            lambda x: x.contains_pdfoutput_false, lambda x, y: x or y
        )

        if contains_pdfoutput_true and contains_pdfoutput_false:
            tl.issues.append(TeXFileIssue(IssueType.conflicting_output_type, "pdfoutput set to 0 and 1"))
            # we assume by default pdf output
            candidate_compilers.difference_update(DVI_COMPILERS_STR)
        elif contains_pdfoutput_true:
            candidate_compilers.difference_update(DVI_COMPILERS_STR)
        elif contains_pdfoutput_false:
            candidate_compilers.difference_update(PDF_COMPILERS_STR)

        # check for fontspec.sty to determine xetex/luatex
        for fn in tl_n.used_system_files + tl_n.used_tex_files:
            if fn.endswith("/fontspec.sty"):
                candidate_compilers.intersection_update(FONTSPEC_ALLOWED_COMPILERS_STR)

        # check all other files
        all_other = tl_n.recursive_collect_files(FileType.other)
        pdftex_exts = set(IMAGE_EXTENSIONS["pdftex"].split())
        dvips_exts = set(IMAGE_EXTENSIONS["dvips"].split())
        luatex_exts = set(IMAGE_EXTENSIONS["luatex"].split())
        dvipdfmx_exts = set(IMAGE_EXTENSIONS["dvipdfmx"].split())
        all_exts = pdftex_exts | dvips_exts | luatex_exts | dvipdfmx_exts
        driver_paths = {"pdftex", "dvips", "dvipdfmx", "luatex"}
        for fn in all_other:
            _, ext = os.path.splitext(fn)
            f_ext = ext[1:].lower()
            # if an extension is not supported by at least one engine,
            # do not remove unsupported engines since we will end up
            # with an empty set of supported engines.
            if f_ext not in all_exts:
                continue
            if f_ext not in pdftex_exts:
                driver_paths.discard("pdftex")
            if f_ext not in dvips_exts:
                driver_paths.discard("dvips")
            if f_ext not in dvipdfmx_exts:
                driver_paths.discard("dvipdfmx")
            if f_ext not in luatex_exts:
                driver_paths.discard("luatex")
        if not driver_paths:
            issues.append(TeXFileIssue(IssueType.conflicting_engine_type, "included images force conflicting engines"))

        if "luatex" not in driver_paths:
            candidate_compilers.difference_update(
                set([c.compiler_string for c in ALL_COMPILERS if c.engine == EngineType.luatex])
            )
        if "dvipdfmx" not in driver_paths:
            candidate_compilers.difference_update(
                set(
                    [
                        c.compiler_string
                        for c in ALL_COMPILERS
                        if c.postp == PostProcessType.dvipdfmx or c.engine == EngineType.xetex
                    ]
                )
            )
        if "dvips" not in driver_paths:
            candidate_compilers.difference_update(
                set([c.compiler_string for c in ALL_COMPILERS if c.postp == PostProcessType.dvips_ps2pdf])
            )
        if "pdftex" not in driver_paths:
            candidate_compilers.difference_update(
                set(
                    [
                        c.compiler_string
                        for c in ALL_COMPILERS
                        if c.engine == EngineType.tex and c.output == OutputType.pdf
                    ]
                )
            )

        lang: LanguageType = LanguageType.tex if found_language == LanguageType.unknown else found_language

        candidate_compilers.intersection_update(TEX_COMPILERS_STR if lang == LanguageType.tex else LATEX_COMPILERS_STR)

        possible_compiler_strings = list(candidate_compilers)
        supported_compiler_strings = candidate_compilers.intersection(set(SUPPORTED_COMPILERS_STR))

        if not possible_compiler_strings:
            issues.append(TeXFileIssue(IssueType.unsupported_compiler_type, "compiler cannot be determined"))
        elif not supported_compiler_strings:
            issues.append(
                TeXFileIssue(
                    IssueType.unsupported_compiler_type, f"compiler(s) {possible_compiler_strings} not supported"
                )
            )

        # if there are multiple supported compilers, search for the first
        # according to the order in SUPPORTED_COMPILERS
        selected_compiler_string: str = ""
        for cs in SUPPORTED_COMPILERS_STR:
            if cs in supported_compiler_strings and cs is not None:
                selected_compiler_string = cs
                break

        if selected_compiler_string:
            tl.process.compiler = CompilerSpec(compiler=selected_compiler_string)

        # count issues in sub files
        for fn, nr_issues in tl_n.walk_document_tree(lambda n: [tuple((n.filename, len(n.issues)))]):
            if nr_issues > 0:
                issues.append(TeXFileIssue(IssueType.issue_in_subfile, str(nr_issues), filename=fn))
        tl.issues = issues


def deal_with_bibliographies(
    rundir: str, toplevel_files: dict[str, ToplevelFile], nodes: dict[str, ParsedTeXFile]
) -> None:
    """Check for inclusion of bib files and presence .bbl files."""
    for tl_f, tl_n in toplevel_files.items():
        node = nodes[tl_f]
        bbl_file = tl_f.removesuffix(".tex").removesuffix(".TEX") + ".bbl"
        bbl_file_full_path = os.path.join(rundir, bbl_file)
        bbl_file_present = os.path.isfile(bbl_file_full_path)
        is_biber: bool = False
        if bbl_file_present:
            # check version of bbl file
            # First three lines of .bbl file:
            #
            # % $ biblatex auxiliary file $
            # % $ biblatex bbl format version 3.3 $
            # % Do not modify the above lines!
            with open(bbl_file_full_path) as bblfn:
                # try to read up to three lines from the .bbl file
                # This ma fail for empty .bbl files or files containing less than three lines
                # in this case the next throws the StopIteration exception
                try:
                    head = [next(bblfn).strip() for _ in range(3)]
                except StopIteration:
                    head = [""]
            if head[0] == "% $ biblatex auxiliary file $":
                # only check files created by biblatex/biber
                is_biber = True
                if head[1].startswith("% $ biblatex bbl format version "):
                    bbl_version = head[1].removeprefix("% $ biblatex bbl format version ").removesuffix(" $")
                    if bbl_version != CURRENT_ARXIV_TEX_BBL_VERSION:
                        node.issues.append(
                            TeXFileIssue(
                                IssueType.bbl_version_mismatch,
                                f"Expected {CURRENT_ARXIV_TEX_BBL_VERSION} but got {bbl_version}",
                                bbl_file,
                            )
                        )
            # toplevel filename .bbl is available -> precompiled bib, ignore if bib files is missing
            tl_n.process.bibliography = BibProcessSpec(
                processor=BibCompiler.biber if is_biber else BibCompiler.unknown, pre_generated=True
            )
            # add bbl file to the list of used_other_files
            nodes[tl_f].used_other_files.append(bbl_file)
            # TODO, maybe remove issues with missing .bib files?
            continue
        # toplevel filename .bbl is missing -> require .bib to be available,
        all_bib = node.recursive_collect_files(FileType.bib)
        if all_bib:
            # TODO detect biber usage from source files (done when .bbl is available above)
            tl_n.process.bibliography = BibProcessSpec(processor=BibCompiler.unknown, pre_generated=False)


def deal_with_indices(rundir: str, toplevel_files: dict[str, ToplevelFile], nodes: dict[str, ParsedTeXFile]) -> None:
    """Check for inclusion of idx files and presence .ind files."""
    for tl_f, tl_n in toplevel_files.items():
        node = nodes[tl_f]
        # first collect the *defined* indices which contain the tag name:
        #          "used_ind_files" : [
        #             "<MAIN>.<tag1>",
        #             "<MAIN>.<tag2>"
        #          ],
        #          "used_idx_files": [
        #             "<MAIN>.<tag1>.<idx_ext>.<ind_ext>",
        #             ....
        #          ]
        all_ind = [fn[8:-1] for fn in node.recursive_collect_files(FileType.ind)]
        all_idx = [fn[7:] for fn in node.recursive_collect_files(FileType.idx)]
        defined_indices = {}
        for idxdef in all_idx:
            tag, idx_ext, ind_ext = idxdef.split(".")
            tag = tag[1:-1]
            idx_ext = idx_ext[1:-1]
            ind_ext = ind_ext[1:-1]
            defined_indices[tag] = (idx_ext, ind_ext)
        logging.debug("Found globally used indices: %s", all_ind)
        logging.debug("Found globally defined indices: %s", defined_indices)
        found_all_indices = True
        for tag in all_ind:
            # check that all used indices are defined
            if tag not in defined_indices:
                logging.error("Missing index definition for %s", tag)
                tl_n.issues.append(
                    TeXFileIssue(IssueType.index_definition_missing, f"index definition for {tag} not found")
                )
                continue
            else:
                logging.debug("Found index definition for %s: %s", tag, defined_indices[tag])
            idx_ext, ind_ext = defined_indices[tag]
            jobname = tl_f.removesuffix(".tex").removesuffix(".TEX")
            idx_file = jobname + "." + idx_ext
            ind_file = jobname + "." + ind_ext
            # remove the <MAIN>.... entry from this node, see below for more comments
            idx_file_pattern = f"<MAIN>.<{tag}>.<{idx_ext}>.<{ind_ext}>"
            if idx_file_pattern in nodes[tl_f].used_idx_files:
                nodes[tl_f].used_idx_files.remove(idx_file_pattern)
            nodes[tl_f].used_idx_files.append(idx_file)
            ind_file_present = os.path.isfile(f"{rundir}/{ind_file}")
            if ind_file_present:
                found_all_indices &= True
                # try to remove the <MAIN>.<tag> entry from this node, but
                # we do NOT remove it if it appears in some included file, too much work
                if f"<MAIN>.<{tag}>" in nodes[tl_f].used_ind_files:
                    nodes[tl_f].used_ind_files.remove(f"<MAIN>.<{tag}>")
                nodes[tl_f].used_ind_files.append(ind_file)
            else:
                found_all_indices &= False

        # remove unused index entries
        for tag, val in defined_indices.items():
            if tag not in all_ind:
                idx_ext, ind_ext = val
                idx_file_pattern = f"<MAIN>.<{tag}>.<{idx_ext}>.<{ind_ext}>"
                if idx_file_pattern in nodes[tl_f].used_idx_files:
                    nodes[tl_f].used_idx_files.remove(idx_file_pattern)

        if found_all_indices:
            tl_n.process.index = IndexProcessSpec(processor=IndexCompiler.unknown, pre_generated=True)
        else:
            tl_n.process.index = IndexProcessSpec(processor=IndexCompiler.unknown, pre_generated=False)


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
            # determine compilation settings
            guess_compilation_parameters(toplevel_files, nodes)
            # deal with bibliographies, which is painful
            deal_with_bibliographies(rundir, toplevel_files, nodes)
            deal_with_indices(rundir, toplevel_files, nodes)
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
