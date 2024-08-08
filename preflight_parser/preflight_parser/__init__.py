"""GenPDF preflight parser."""

import glob
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from itertools import zip_longest
from pprint import pformat

import chardet

MODULE_PATH = os.path.dirname(__file__)

#
# CLASSES AND TYPES
#
# This section contains the class definitions and compound types


class PreflightStatusValues(Enum):
    """Possible values of preflight's execution status."""

    SUCCESS = 1
    ERROR = 2
    SUSPICIOUS = 3

    def __str__(self) -> str:
        return self.name.lower()


@dataclass
class PreflightStatus:
    """Specification of Preflight status entry."""

    key: PreflightStatusValues
    info: str | None = None

    def asdict(self) -> dict:
        """Representation as dictionary for json response."""
        ret = self.__dict__.copy()
        ret["key"] = str(self.key)
        return prune_dir(ret)


class FileType(Enum):
    """Classification of files."""

    TEX = 1
    BIB = 2
    OTHER = 5

    def __str__(self) -> str:
        return self.name.lower()


@dataclass
class IncludeSpec:
    """Specification of an include statement in a TeX file."""

    cmd: str
    source: str
    type: FileType
    extensions: None | str | dict = None
    file_argument: int | list[int] = 1
    take_options: bool = True
    multi_args: bool = False


class LanguageType(Enum):
    r"""Possible language types of a submission/file.

    TEX does not allow compiling as latex, e.g., because it contains \bye
    LATEX does not allow compiling as plain tex, e.g., because it contains \documentclass
    UNKNOWN allows compilation as either TEX or LATEX.
    """

    TEX = 1
    LATEX = 2

    UNKNOWN = 100

    def __str__(self) -> str:
        return self.name.lower()


class EngineType(Enum):
    """Possible engines in use."""

    TEX = 1
    LUATEX = 2
    XETEX = 3
    PTEX = 4
    UPTEX = 5

    UNKNOWN = 100

    def __str__(self) -> str:
        return self.name.lower()


class OutputType(Enum):
    """Possible output types of the first run."""

    DVI = 1
    PDF = 2
    UNKNOWN = 100

    def __str__(self) -> str:
        return self.name.lower()


class IndexCompiler(Enum):
    """Possible index compiler."""

    MAKEINDEX = 1
    UNKNOWN = 100

    def __str__(self) -> str:
        return self.name.lower()


class BibCompiler(Enum):
    """Possible index compiler."""

    BIBTEX = 1
    BIBTEX8 = 2
    UBIBTEX = 3
    BIBER = 4
    UNKNOWN = 100

    def __str__(self) -> str:
        return self.name.lower()


class PostProcessType(Enum):
    """Possible conversion types from dvi to pdf."""

    NOT_NECESSARY = 1
    DVIPS_PS2PDF = 2
    DVIPDFMX = 3

    UNKNOWN = 100

    def __str__(self) -> str:
        return self.name.lower()


@dataclass
class IndexProcessSpec:
    """Specification of the indexing process."""

    processor: IndexCompiler = IndexCompiler.UNKNOWN
    pre_generated: bool = False

    def asdict(self) -> dict:
        """Representation as dictionary for json response."""
        ret = self.__dict__.copy()
        ret["processor"] = str(self.processor)
        return prune_dir(ret)


@dataclass
class BibProcessSpec:
    """Specification of the bibliography process."""

    processor: BibCompiler = BibCompiler.UNKNOWN
    pre_generated: bool = False

    def asdict(self) -> dict:
        """Representation as dictionary for json response."""
        ret = self.__dict__.copy()
        ret["processor"] = str(self.processor)
        return prune_dir(ret)


@dataclass
class MainProcessSpec:
    """Specification of the main process to compile a document."""

    compiler: str = "unknown"
    bibliography: BibProcessSpec | None = None
    index: IndexProcessSpec | None = None
    options: dict | None = None

    def asdict(self) -> dict:
        """Representation as dictionary for json response."""
        ret = self.__dict__.copy()
        if self.bibliography:
            ret["bibliography"] = self.bibliography.asdict()
        if self.index:
            ret["index"] = self.index.asdict()
        return prune_dir(ret)


class IssueType(Enum):
    """Possible issues we detect."""

    FILE_NOT_FOUND = 1
    CONFLICTING_FILE_TYPE = 2
    CONFLICTING_OUTPUT_TYPE = 3
    CONFLICTING_ENGINE_TYPE = 4
    CONFLICTING_POSTPROCESS_TYPE = 5
    UNSUPPORTED_COMPILER_TYPE = 6
    CONFLICTING_IMAGE_TYPES = 7
    INCLUDE_COMMAND_WITH_MACRO = 8
    CONTENTS_DECODE_ERROR = 9
    ISSUE_IN_SUBFILE = 99
    OTHER = 100

    def __str__(self) -> str:
        return self.name.lower()


@dataclass
class TeXFileIssue:
    """Specification of Issue in a file."""

    key: IssueType
    info: str
    # line: int
    filename: str | None = None

    def asdict(self) -> dict:
        """Representation as dictionary for json response."""
        ret = self.__dict__.copy()
        ret["key"] = str(self.key)
        return prune_dir(ret)


@dataclass
class ParsedTeXFile:
    """Result of parsing a TeX file."""

    filename: str
    data: str
    output_type: OutputType = OutputType.UNKNOWN
    language: LanguageType = LanguageType.UNKNOWN
    engine: EngineType = EngineType.UNKNOWN
    postprocess: PostProcessType = PostProcessType.UNKNOWN
    used_tex_files: list[str] = field(default_factory=list)
    used_bib_files: list[str] = field(default_factory=list)
    used_other_files: list[str] = field(default_factory=list)
    used_system_files: list[str] = field(default_factory=list)
    mentioned_files: dict[str, IncludeSpec] = field(default_factory=dict)
    issues: list[TeXFileIssue] = field(default_factory=list)
    children: list["ParsedTeXFile"] = field(default_factory=list)
    parents: list["ParsedTeXFile"] = field(default_factory=list)

    def asdict(self) -> dict:
        """Representation as dictionary for json response."""
        ret = self.__dict__.copy()
        ret["output_type"] = str(self.output_type)
        ret["language"] = str(self.language)
        ret["engine"] = str(self.engine)
        ret["postprocess"] = str(self.postprocess)
        del ret["mentioned_files"]
        del ret["used_system_files"]
        ret["issues"] = [li.asdict() for li in self.issues]
        del ret["children"]
        del ret["parents"]
        del ret["data"]
        return prune_dir(ret)

    def __repr__(self):
        return f"""ParsedTeXFile(
  filename = {self.filename},
  output_type = {self.output_type},
  language = {self.language},
  engine = {self.engine},
  postprocess = {self.postprocess},
  used_tex_files = {self.used_tex_files},
  used_bib_files = {self.used_bib_files},
  used_other_files = {self.used_other_files},
  mentioned_files = {self.mentioned_files},
  used_system_files = {self.used_system_files},
  issues = {self.issues},
  children = {[n.filename for n in self.children]},
  parents = {[n.filename for n in self.parents]}
)"""

    def detect_language(self) -> None:
        """Detect the language used in the given file (TeX, LaTeX, or unknown)."""
        # the default languages is UNKNOWN, but if we detect
        # certain values, switch to either TEX or LATEX only
        # we check for \bye first, so that if a file contains both
        # \documentclass and \bye (which is a syntax error!)
        language = LanguageType.UNKNOWN
        if self.filename.endswith(".sty"):
            language = LanguageType.LATEX
        if re.search(r"\\text(bf|it|sl)|\\section|\\chapter", self.data, re.MULTILINE):
            language = LanguageType.LATEX
        if re.search(r"^[^%\n]*\\bye[^a-zA-Z0-9_\n]", self.data, re.MULTILINE):
            language = LanguageType.TEX
        if re.search(r"^[^%\n]*\\documentclass", self.data, re.MULTILINE):
            if language == LanguageType.TEX:
                self.issues.append(
                    TeXFileIssue(IssueType.CONFLICTING_FILE_TYPE, "containing both bye and documentclass")
                )
            language = LanguageType.LATEX
        self.language = language

    def detect_engine(self) -> None:
        """If possible, update the engine type based on the content of the file."""
        self.engine = EngineType.UNKNOWN

    def detect_postprocess(self) -> None:
        """If possible, update the postprocess type based on the content of the file."""
        if self.output_type == OutputType.DVI:
            self.postprocess = PostProcessType.DVIPS_PS2PDF
        elif self.output_type == OutputType.PDF:
            self.postprocess = PostProcessType.NOT_NECESSARY
        elif self.output_type == OutputType.UNKNOWN:
            self.postprocess = PostProcessType.UNKNOWN
        else:
            raise ValueError(f"unknown output type {self.output_type}")

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
                or (self.output_type == OutputType.PDF and found_eps)
                or (self.output_type == OutputType.DVI and found_pdf)
            ):
                self.output_type = OutputType.UNKNOWN
                self.issues.append(
                    TeXFileIssue(
                        IssueType.CONFLICTING_IMAGE_TYPES, "images of formats that cannot be loaded at the same time"
                    )
                )
            else:
                if found_pdf:
                    self.output_type = OutputType.PDF
                elif found_eps:
                    self.output_type = OutputType.DVI
                else:
                    self.output_type = OutputType.UNKNOWN

    def update_engine_based_on_system_files(self) -> None:
        """Check in the list of used systemfiles for indications a specific compiler needs to be used."""
        for f in self.used_system_files:
            if "/luatex/" in f or "/lualatex/" in f:
                self.engine = EngineType.LUATEX

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
        for f in re.findall(r"\\input\s+([-a-zA-Z0-9._]+)", self.data):
            self.mentioned_files[str(f)] = INCLUDE_COMMANDS_DICT["input"]
        # check for the rest of include commands
        for i in re.findall(ARGS_INCLUDE_REGEX, self.data, re.MULTILINE | re.VERBOSE):
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
                    IssueType.INCLUDE_COMMAND_WITH_MACRO, info=f"command {include_command} used with macro parameter #"
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
                    raise ValueError
                if incdef.multi_args:
                    for f in filearg.split(","):
                        fn = f[2:] if f.startswith("./") else f
                        file_incspec[fn.strip()] = incdef
                else:
                    filearg = filearg[2:] if filearg.startswith("./") else filearg
                    file_incspec[filearg] = incdef

            else:
                raise ValueError

        logging.debug(file_incspec)
        self.mentioned_files |= file_incspec

    def walk_document_tree(self, func: Callable[["ParsedTeXFile"], list[any]]) -> list[any]:
        """Call a function on any node of a document tree."""
        return self._walk_document_tree(func, {})

    def _walk_document_tree(self, func: Callable[["ParsedTeXFile"], list[any]], visited: dict[str, bool]) -> list[any]:
        """Call a function on any node of a document tree - internal helper."""
        ret = func(self)
        visited[self.filename] = True
        for n in self.children:
            if n.filename not in visited:
                ret_kid = n._walk_document_tree(func, visited)
                ret.extend(ret_kid)
        return ret

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
            if found_language == LanguageType.UNKNOWN:
                found_language = kid_language
            elif found_language == LanguageType.TEX:
                if kid_language == LanguageType.LATEX:
                    issues.append(
                        TeXFileIssue(IssueType.CONFLICTING_FILE_TYPE, "conflicting lang types of main and subfiles")
                    )
                # always upgrade to LaTeX
                found_language = LanguageType.LATEX
            elif found_language == LanguageType.LATEX:
                if kid_language == LanguageType.TEX:
                    issues.append(
                        TeXFileIssue(IssueType.CONFLICTING_FILE_TYPE, "conflicting lang types of main and subfiles")
                    )
                # keep found_language as LATEX
            else:
                raise ValueError(f"Unknown LanguageType {found_language}")

            if found_output == OutputType.UNKNOWN:
                found_output = kid_output
            elif kid_output == OutputType.UNKNOWN:
                # keep found_output
                pass
            elif kid_output != found_output:
                issues.append(
                    TeXFileIssue(IssueType.CONFLICTING_OUTPUT_TYPE, "conflicting output types of main and subfiles")
                )

            if found_engine == EngineType.UNKNOWN:
                found_engine = kid_engine
            elif kid_engine == EngineType.UNKNOWN:
                # keep found_compiler
                pass
            elif kid_engine != found_engine:
                # TODO maybe order engines? tex < luatex ???
                issues.append(
                    TeXFileIssue(IssueType.CONFLICTING_ENGINE_TYPE, "conflicting engine types of main and subfiles")
                )

            if found_postprocess == PostProcessType.UNKNOWN:
                found_postprocess = kid_postprocess
            elif kid_postprocess == PostProcessType.UNKNOWN:
                # keep found_compiler
                pass
            elif kid_postprocess != found_postprocess:
                # TODO maybe order engines? tex < luatex ???
                issues.append(
                    TeXFileIssue(
                        IssueType.CONFLICTING_POSTPROCESS_TYPE, "conflicting postprocess types of main and subfiles"
                    )
                )

            issues.extend(kid_issues)

        return found_language, found_output, found_engine, found_postprocess, issues

    def recursive_collect_files(self, what: FileType | str) -> list[str]:
        """Recursively collect all tex/bib/other files."""
        return self._recursive_collect_files(what, {})

    def _recursive_collect_files(self, what: FileType | str, visited: dict[str, bool]) -> list[str]:
        """Recursively collect all tex/bib/other files."""
        if what == FileType.BIB:
            idx = "used_bib_files"
        elif what == FileType.TEX:
            idx = "used_tex_files"
        elif what == FileType.OTHER:
            idx = "used_other_files"
        elif what == "issues":
            idx = "issues"
        else:
            raise ValueError(f"no such file type: {what}")
        found = getattr(self, idx)
        visited[self.filename] = True
        for n in self.children:
            if n.filename in visited:
                logging.debug("recursive_collect_files: revisiting %s", n.filename)
                continue
            found.extend(n._recursive_collect_files(what, visited))
        return found


@dataclass
class ToplevelFile:
    """Toplevel file and how to compile it."""

    filename: str
    process: MainProcessSpec = field(default_factory=MainProcessSpec)
    issues: list[TeXFileIssue] = field(default_factory=list)

    def asdict(self) -> dict:
        """Representation as dictionary for json response."""
        ret = self.__dict__.copy()
        ret["issues"] = [li.asdict() for li in self.issues]
        ret["process"] = self.process.asdict()
        return prune_dir(ret)


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
PARSED_FILE_EXTENSIONS = [".tex", ".sty", ".cls", ".clo"]

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
    IncludeSpec("input", "core", FileType.TEX, TEX_EXTENSIONS, take_options=False),
    IncludeSpec("include", "core", FileType.TEX, TEX_EXTENSIONS, take_options=False),
    IncludeSpec("InputIfFileExists", "core", FileType.TEX, TEX_EXTENSIONS, take_options=False),
    IncludeSpec("documentstyle", "core", FileType.TEX, "cls"),
    IncludeSpec("documentclass", "core", FileType.TEX, "cls"),
    IncludeSpec("LoadClass", "core", FileType.TEX, "cls"),
    IncludeSpec("LoadClassWithOptions", "core", FileType.TEX, "cls", take_options=False),
    IncludeSpec("usepackage", "core", FileType.TEX, "sty", take_options=True, multi_args=True),
    IncludeSpec(
        "RequirePackage",
        "core",
        FileType.TEX,
        "sty",
        take_options=True,
        multi_args=True,
    ),
    IncludeSpec(
        "RequirePackageWithOptions",
        "core",
        FileType.TEX,
        "sty",
        take_options=False,
        multi_args=False,
    ),
    IncludeSpec("bibliography", "core", FileType.BIB, "bib", take_options=False),
    IncludeSpec("includegraphics", "graphics", FileType.OTHER, IMAGE_EXTENSIONS),
    IncludeSpec("psfig", "epsfig", FileType.OTHER, EPS_EXTENSIONS),
    IncludeSpec(
        "subfile",
        "subfiles",
        FileType.TEX,
        TEX_EXTENSIONS,
        take_options=False,
        multi_args=False,
    ),
    IncludeSpec(
        "subfileinclude",
        "subfiles",
        FileType.TEX,
        TEX_EXTENSIONS,
        take_options=False,
        multi_args=False,
    ),
    IncludeSpec("includesvg", "svg", FileType.OTHER, "svg"),
    IncludeSpec("includepdf", "pdfpages", FileType.OTHER, "pdf"),
    IncludeSpec("epsfbox", "epsf", FileType.OTHER, EPS_EXTENSIONS),
    IncludeSpec("epsfig", "epsfig", FileType.OTHER, EPS_EXTENSIONS),
    IncludeSpec("loadglsentries", "glossaries", FileType.OTHER, "gls"),  # TODO check extensions!!!
    IncludeSpec(
        "DTLloaddb", "datatool", FileType.OTHER, None, file_argument=2
    ),  # \DTLloaddb[hoptionsi]{hdb namei}{hfilenamei}
    IncludeSpec(
        "DTLloadrawdb", "datatool", FileType.OTHER, None, file_argument=2
    ),  # \DTLloaddb[hoptionsi]{hdb namei}{hfilenamei}
    IncludeSpec("import", "import", FileType.TEX, TEX_EXTENSIONS, file_argument=[1, 2]),  # \import{prefix}{file}
    IncludeSpec(
        "usetikzlibrary",
        "tikz",
        FileType.TEX,
        TEX_EXTENSIONS,
        take_options=False,
        multi_args=True,
    ),
    IncludeSpec(
        "usepgflibrary",
        "tikz",
        FileType.TEX,
        TEX_EXTENSIONS,
        take_options=False,
        multi_args=True,
    ),
    IncludeSpec(
        "lstinputlisting", "listings", FileType.TEX, TEX_EXTENSIONS
    ),  # \lstinputlisting[lastline=4]{listings.sty}
    IncludeSpec("tcbuselibrary", "tcolorbox", FileType.TEX, "code.tex"),
    IncludeSpec("tcbincludegraphics", "tcolorbos", FileType.OTHER, IMAGE_EXTENSIONS),
    IncludeSpec("asyinclude", "asy", FileType.OTHER, "asy"),
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


COMPILER_SELECTION = {
    LanguageType.TEX: {
        OutputType.DVI: {
            EngineType.TEX: "etex",
            EngineType.LUATEX: "dviluatex",
            # not eaasy to do: EngineType.XETEX: "xetex",
            EngineType.PTEX: "ptex",
            EngineType.UPTEX: "uptex",
        },
        OutputType.PDF: {
            EngineType.TEX: "pdfetex",
            EngineType.LUATEX: "luatex",
            EngineType.XETEX: "xetex",
            # EngineType.PTEX: "ptex",
            # EngineType.UPTEX: "uptex",
        },
    },
    LanguageType.LATEX: {
        OutputType.DVI: {
            EngineType.TEX: "latex",
            EngineType.LUATEX: "dvilualatex",
            # not eaasy to do: EngineType.XETEX: "xetex",
            EngineType.PTEX: "platex",
            EngineType.UPTEX: "uplatex",
        },
        OutputType.PDF: {
            EngineType.TEX: "pdflatex",
            EngineType.LUATEX: "lualatex",
            EngineType.XETEX: "xelatex",
            # EngineType.PTEX: "ptex",
            # EngineType.UPTEX: "uptex",
        },
    },
}


SUPPORTED_PIPELINES: list[str] = ["etex+dvips_ps2pdf", "latex+dvips_ps2pdf", "pdflatex"]


#
# FUNCTIONS
#


def prune_dir(a: dict) -> dict:
    """Remove entries with value None from dict."""
    return {k: v for k, v in a.items() if v is not None and v != [] and v != "unknown"}


def parse_file(basedir: str, filename: str) -> ParsedTeXFile:
    """Parse a file for included commands."""
    with open(f"{basedir}/{filename}", "rb") as f:
        rawdata = f.read()
    detected_encoding_data = chardet.detect(rawdata)
    encoding: str | None = detected_encoding_data.get("encoding")
    if encoding is None:
        encoding = "utf-8"
    try:
        data: str = str(rawdata.decode(encoding))
    except UnicodeDecodeError:
        logging.warning("Failed to decode %s in %s", filename, encoding)
        try:
            # try once more, this time with ascii
            data: str = str(rawdata.decode("ascii"))
        except UnicodeDecodeError:
            n = ParsedTeXFile(filename, "")
            n.issues.append(
                TeXFileIssue(IssueType.CONTENTS_DECODE_ERROR, f"cannot decode file, tried {encoding} and ascii")
            )
            return n
    # standardize line endings
    line_ending_re = re.compile(r"\r\n|\r|\n")
    data = re.sub(line_ending_re, "\n", data)
    n = ParsedTeXFile(filename, data)
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


def parse_dir(rundir) -> dict[str, ParsedTeXFile] | ToplevelFile:
    """Parse all TeX files in a directory."""
    files = glob.glob(f"{rundir}/**/*", recursive=True)
    # strip rundir/ prefix
    n = len(rundir) + 1
    files = [f[n:] for f in files]
    # files = os.listdir(rundir)
    # needs more extensions that we support
    tex_files = [t for t in files if os.path.splitext(t)[1].lower() in PARSED_FILE_EXTENSIONS]
    if not tex_files:
        # we didn't find any tex file, check for a single PDF file
        if len(files) == 1 and files[0].lower().endswith(".pdf"):
            # PDF only submission, only one PDF file, nothing else
            return ToplevelFile(files[0], process=MainProcessSpec(compiler="pdf_submission"))
    nodes = {f: parse_file(rundir, f) for f in tex_files}
    # print(nodes)
    return nodes


def kpse_search_files(basedir: str, nodes: dict[str, ParsedTeXFile]) -> dict[str, str]:
    """Search for files using kpsearch, using the lua script kpse_search.lua."""
    kpse_find_input_data = ""
    for _, n in nodes.items():
        for k, v in n.mentioned_files.items():
            if isinstance(v.extensions, dict):
                if n.output_type == OutputType.DVI:  # TODO should we check for dvipdfmx?
                    if n.postprocess == PostProcessType.DVIPS_PS2PDF:
                        exts = v.extensions["dvips"]
                    elif n.postprocess == PostProcessType.DVIPDFMX:
                        exts = v.extensions["dvipdfmx"]
                    else:
                        exts = v.extensions["pdftex"]  # assume pdflatex as default
                elif n.output_type == OutputType.PDF or n.output_type == OutputType.UNKNOWN:  # TODO unify these cases?
                    if n.engine == EngineType.TEX:
                        exts = v.extensions["pdftex"]
                    elif n.engine == EngineType.XETEX or n.engine == EngineType.LUATEX:
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
                    n.issues.append(TeXFileIssue(IssueType.FILE_NOT_FOUND, f))
                continue
            if n.mentioned_files[f].type == FileType.TEX:
                n.used_tex_files.append(found)
            elif n.mentioned_files[f].type == FileType.BIB:
                n.used_bib_files.append(found)
            elif n.mentioned_files[f].type == FileType.OTHER:
                n.used_other_files.append(found)
            else:
                raise ValueError(f"Unknown file type {n.mentioned_files[f].type} for file {f}")
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


def compute_compiler(engine: EngineType, output: OutputType, lang: LanguageType, postprocess: PostProcessType) -> str:
    """Determine the actual compiler from engine/output/language."""
    if lang in COMPILER_SELECTION:
        if output in COMPILER_SELECTION[lang]:
            if engine in COMPILER_SELECTION[lang][output]:
                compiler = COMPILER_SELECTION[lang][output][engine]
    if not compiler:
        logging.warning("No compiler found for engine=%s, output=%s, lang=%s", engine, output, lang)
        return ""
    if postprocess == PostProcessType.NOT_NECESSARY:
        pass
    elif postprocess == PostProcessType.UNKNOWN:
        logging.warning("No postprocess type found")
    else:
        compiler += f"+{postprocess!s}"
    return compiler


def compute_toplevel_files(roots: dict[str, ParsedTeXFile], nodes: dict[str, ParsedTeXFile]) -> dict[str, ToplevelFile]:
    """Determine the toplevel files."""
    toplevel_files = {}
    for f, n in roots.items():
        # don't consider sty/cls/clo as toplevel, even if they are not used
        if f.endswith(".sty") or f.endswith(".cls") or f.endswith(".clo"):
            continue
        found_language, found_output, found_engine, found_postprocess, issues = n.find_entry_in_subgraph()
        tl = ToplevelFile(filename=n.filename)
        engine: EngineType = EngineType.TEX if found_engine == EngineType.UNKNOWN else found_engine
        lang: LanguageType = LanguageType.TEX if found_language == LanguageType.UNKNOWN else found_language
        output: OutputType
        if lang == LanguageType.TEX:
            output = OutputType.DVI if found_output == OutputType.UNKNOWN else found_output
        elif lang == LanguageType.LATEX:
            output = OutputType.PDF if found_output == OutputType.UNKNOWN else found_output
        else:
            raise ValueError(f"Unsupported language type {lang}")
        postprocess: PostProcessType
        if output == OutputType.DVI:
            postprocess = (
                PostProcessType.DVIPS_PS2PDF if found_postprocess == PostProcessType.UNKNOWN else found_postprocess
            )
        elif output == OutputType.PDF:
            postprocess = (
                PostProcessType.NOT_NECESSARY if found_postprocess == PostProcessType.UNKNOWN else found_postprocess
            )
        compiler: str = compute_compiler(engine, output, lang, postprocess)
        if compiler not in SUPPORTED_PIPELINES:
            issues.append(TeXFileIssue(IssueType.UNSUPPORTED_COMPILER_TYPE, f"compiler {compiler} not supported"))
        tl.process = MainProcessSpec(compiler)

        # count issues in sub files
        tl_n = nodes[f]
        for fn, nr_issues in tl_n.walk_document_tree(lambda n: [tuple((n.filename, len(n.issues)))]):
            if nr_issues > 0:
                issues.append(TeXFileIssue(IssueType.ISSUE_IN_SUBFILE, str(nr_issues), filename=fn))
        tl.issues = issues
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
            tl_n.process.bibliography = BibProcessSpec(BibCompiler.UNKNOWN, pre_generated=True)
            # TODO, maybe remove issues with missing .bib files?
            continue
        # toplevel filename .bbl is missing -> require .bib to be available,
        top_node = nodes[tl_f]
        all_bib = top_node.recursive_collect_files(FileType.BIB)
        if all_bib:
            # TODO detect biber usage!
            tl_n.process.bibliography = BibProcessSpec(BibCompiler.UNKNOWN, pre_generated=False)


def format_json_response(
    toplevel_files: dict[str, ToplevelFile], nodes: dict[str, ParsedTeXFile], ret_status: PreflightStatus
) -> str:
    """Format json object for API preflight return."""
    ret = {}
    ret["detected_toplevel_files"] = [tl.asdict() for tl in toplevel_files.values()]
    ret["tex_files"] = [n.asdict() for n in nodes.values()]
    ret["status"] = ret_status.asdict()
    # pprint(ret)
    return json.dumps(ret)


def generate_preflight_response(rundir: str) -> str:
    """Parse submission and generated preflight response."""
    # parse files
    n: dict[str, ParsedTeXFile] | ToplevelFile = parse_dir(rundir)
    nodes: dict[str, ParsedTeXFile]
    roots: dict[str, ParsedTeXFile]
    toplevel_files: dict[str, ToplevelFile]
    if isinstance(n, ToplevelFile):
        # pdf only submission, we received the toplevel file already
        toplevel_files = {n.filename: n}
        nodes = {}
        status = PreflightStatus(PreflightStatusValues.SUCCESS)
    else:
        nodes = n
        if nodes == {}:
            roots = {}
            toplevel_files = {}
            status = PreflightStatus(PreflightStatusValues.ERROR, info="No TeX files found")
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
            status = PreflightStatus(PreflightStatusValues.SUCCESS)
    return format_json_response(toplevel_files, nodes, status)