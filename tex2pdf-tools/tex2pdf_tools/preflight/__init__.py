"""GenPDF preflight parser."""

# TODO for graphicspath
# it seems that an image file that is included via a sub-tex files
# is still mentioned as used other file in the toplevel file
# THIS IS STRANGE and I have no idea why this happens (as of now)
# BUT !!! THIS ALSO HAPPENS on master branch - are we supposed to have this?

import glob
import logging
import os
import re
import subprocess
import typing
from collections.abc import Callable
from itertools import zip_longest
from pprint import pformat

from pydantic import BaseModel, Field

from .feature_flags import ENABLE_LUALATEX
from .file_checks import run_checks as run_file_checks
from .images import collect_image_info
from .models import (
    EPS_EXTENSIONS,
    FONT_EXTENSIONS,
    HTML_SUBMISSION_STRING,
    IMAGE_EXTENSIONS,
    PDF_SUBMISSION_STRING,
    TEX_EXTENSIONS,
    BblType,
    BibCompiler,
    BibProcessSpec,
    CheckPreflightException,
    CompilerSpec,
    EngineType,
    FileType,
    ImageInfo,
    IncludeSpec,
    IndexCompiler,
    IndexProcessSpec,
    IssueType,
    LanguageType,
    MainProcessSpec,
    OutputType,
    ParseSyntaxError,
    PostProcessType,
    PreflightException,
    PreflightStatus,
    PreflightStatusValues,
    T,
    TeXFileIssue,
    ToplevelFile,
    logger,
)
from .pdf_checks import run_checks as run_pdf_checks

# tell ruff to not complain, I don't want to add __all__ entries
from .report import PreflightReport  # noqa

MODULE_PATH = os.path.dirname(__file__)


#
# packages that require unicode tex (xetex, luatex)
UNICODE_TEX_PACKAGES = ["fontspec", "polyglossia", "unicode-math"]

# Pre-compiled regex patterns for performance optimization
# These patterns are used frequently during TeX file parsing
_RE_BYE = re.compile(rb"^[^%\n]*\\bye(?![a-zA-Z])", re.MULTILINE)
_RE_DOCUMENTCLASS = re.compile(rb"^[^%\n]*\\documentclass[^a-zA-Z]", re.MULTILINE)
_RE_DOCUMENTSTYLE = re.compile(rb"^[^%\n]*\\documentstyle[^a-zA-Z]", re.MULTILINE)
_RE_PDFOUTPUT_1 = re.compile(rb"^[^%\n]*\\pdfoutput\s*=\s*1", re.MULTILINE)
_RE_PDFOUTPUT_0 = re.compile(rb"^[^%\n]*\\pdfoutput\s*=\s*0", re.MULTILINE)
_RE_COMMENT = re.compile(rb"(?<!\\)%.*\n")
_RE_INPUT = re.compile(rb"\\input\s+([-a-zA-Z0-9._]+)")
_RE_GRAPHICSPATH = re.compile(rb"\\graphicspath\s*{((\s*{([^}]*)}\s*)+)}", re.MULTILINE)
_RE_BRACE_GROUP = re.compile(rb"{([^}]*)}")
_RE_ADDPLOT = re.compile(rb"(addplot)(?:\+?)\s*(\[[^]]*\])?\s*table\s*(?:\[[^]]*\])?\s*({[^}]+})", re.MULTILINE)
_RE_OVERPIC = re.compile(r"begin\s*{\s*overpic\s*}")
_RE_MACRO_ARG = re.compile(r"#[1-9]")
_RE_COMMENT_STR = re.compile(r"%.*$", re.MULTILINE)
_RE_LINE_ENDING = re.compile(rb"\r\n|\r|\n")
_RE_FONTSPEC_SET_CMDS = re.compile(
    rb"\\((?:new|set|renew|provide)font(?:family|face))\s*(?:%.*\n)?\\[^{]*({[^}]*})", re.MULTILINE
)

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

# we only support 3.2 and 3.3 via the extra tree
# this needs to be bytes since we read files in byte mode!
# We only support two TeX Live versions at each time during submission
CURRENT_ARXIV_TEX_BBL_VERSIONS = {
    "2023": [b"3.2", b"3.3"],
    "2025": [b"3.3"],
}
CURRENT_TEXLIVE_VERSION = "2025"
PREVIOUS_TEXLIVE_VERSION = "2023"

#
# CLASSES AND TYPES
#
# This section contains the class definitions and compound types


class ParsedTeXFile(BaseModel):
    """Result of parsing a TeX file."""

    filename: str
    _data: bytes = b""  # content of files is read in bytes
    _graphicspath: list[list[str]] = []
    _uses_bibliography: bool = False
    _uses_bbl_file_type: set[BblType] = set()
    _missing_bib_files: set[str] = set()
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
        logger.debug("Detecting language for: %s", self.filename)
        if self.filename.endswith(".cls") or self.filename.endswith(".clo"):
            self.language = LanguageType.latex
            # don't do more parsing here, in particular for \pdfoutput etc
            # which is often \if...ed and then fails
            return
        self.language = LanguageType.unknown
        if self.filename.endswith(".sty"):
            logger.debug("Found .sty, setting language to latex")
            self.language = LanguageType.latex
        # this is too dangerous, several plain tex macro packages define \section or \chapter
        # if re.search(rb"^[^%\n]*(\\text(bf|it|sl)|\\section|\\chapter)", self._data, re.MULTILINE):
        #    self.language = LanguageType.latex
        if _RE_BYE.search(self._data):
            self.language = LanguageType.tex
            self.contains_bye = True
        if _RE_DOCUMENTCLASS.search(self._data):
            logger.debug("Found documentclass, setting language to latex")
            self.contains_documentclass = True
            if self.language == LanguageType.tex:
                self.issues.append(
                    TeXFileIssue(IssueType.conflicting_file_type, "containing both bye and documentclass")
                )
            self.language = LanguageType.latex
        if _RE_DOCUMENTSTYLE.search(self._data):
            logger.debug("Found documentstyle, setting language to latex209")
            self.contains_documentclass = True
            if self.language == LanguageType.tex:
                self.issues.append(
                    TeXFileIssue(IssueType.conflicting_file_type, "containing both bye and documentclass")
                )
            self.language = LanguageType.latex209
        if _RE_PDFOUTPUT_1.search(self._data):
            self.contains_pdfoutput_true = True
        if _RE_PDFOUTPUT_0.search(self._data):
            self.contains_pdfoutput_false = True

    def update_engine_based_on_system_files(self) -> None:
        """Check in the list of used systemfiles for indications a specific compiler needs to be used."""
        for f in self.used_system_files:
            if "/luatex/" in f or "/lualatex/" in f:
                self.engine = EngineType.luatex

    def detect_included_files(self, only_images: bool = False) -> None:
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
        data = _RE_COMMENT.sub(b"", self._data)
        if not only_images:
            for f in _RE_INPUT.findall(data):
                # f is a byte string, but corresponds to an input file.
                logger.debug("%s regex found %s", self.filename, f)
                try:
                    ff = f.decode("utf-8")
                    self.mentioned_files[ff] = {"input": INCLUDE_COMMANDS_DICT["input"]}
                except UnicodeDecodeError:
                    # TODO can we do more here?
                    logger.warning("Cannot decode argument to input: %s", f)
        # deal with finding \graphicspath{ ... }
        # which is required to detect grpahics files in other directories
        # format:
        #    \graphicspath{  {path1/} {path2/} ... }
        # list of paths in braces, must end in a forward /
        # The general regexp does not allow braces in braces like { {foobar} }
        # so we have to treat this differently
        # we cannot use re.findall or so because we need balanced braces search
        #
        # using regex module
        # data = "...\n\graphicspath{ {bla} }\n\\graphicspath{ {foo} { something/  } { bar } }\nsomerest"
        # m = regex.search(r"^[^%\n]*?\\graphicspath\s*{(\s*{([^}]*)}\s*)+}",
        #                  data, regex.MULTILINE | regex.REVERSE)
        # m.allcaptures()[2] gives the inner list in reverse -> [' bar ', ' something/  ', 'foo']
        # because this does a "reverse" search so the returned list is also in reverse!
        # this search the LAST occurrence!

        if not only_images:
            # doing it with plain re
            graphicspath_occurrences = _RE_GRAPHICSPATH.findall(data)
            logger.debug("Found the following graphicspath entries: %s", graphicspath_occurrences)
            gp_entries: list[list[str]] = []
            for gp in graphicspath_occurrences:
                inside_group = gp[0]  # this is the match inside the argument braces
                all_path = _RE_BRACE_GROUP.findall(inside_group)
                this_gp_entry: list[str] = []
                for d in all_path:
                    try:
                        this_gp_entry.append(d.strip().decode("utf-8"))
                    except UnicodeDecodeError:
                        # TODO can we do more here?
                        logger.warning("Cannot decode graphicspath entry: %s in %s", d, gp)
                # if we could parse an entry, append it
                if this_gp_entry:
                    gp_entries.append(this_gp_entry)
            if gp_entries:
                self._graphicspath = gp_entries
                logger.debug("Setting graphicspath to %s", self._graphicspath)

            # deal with some specially tricky commands
            for i in _RE_ADDPLOT.findall(data):
                logger.debug("%s regex found %s", self.filename, i)
                try:
                    ii = [x.decode("utf-8") for x in i]
                    self.collect_included_files(ii)
                except UnicodeDecodeError:
                    # TODO can we do more here?
                    logger.warning("Cannot decode argument: %s", i)

        if only_images:
            todore = ARGS_INCLUDE_REGEX_ONLY_IMAGES.encode("utf-8")
        else:
            todore = ARGS_INCLUDE_REGEX.encode("utf-8")

        # deal with fontspec commands that have a leading command name
        if not only_images:
            logger.debug("searching for fontspec commands expecting a command")
            for i in _RE_FONTSPEC_SET_CMDS.findall(data):
                logger.debug("%s regex found %s", self.filename, i)
                try:
                    # decode and insert empty options so that collect_included_files is happy
                    ii = [x.decode("utf-8") for x in i]
                    ii.insert(1, "[]")
                    self.collect_included_files(ii)
                    pass
                except UnicodeDecodeError:
                    # TODO can we do more here?
                    logger.warning("Cannot decode argument: %s", i)

        # check for the rest of include commands
        logger.debug(f"searching for {'only images' if only_images else 'all'} in {self.filename}")
        for i in re.findall(todore, data, re.MULTILINE | re.VERBOSE):
            logger.debug("%s regex found %s", self.filename, i)
            try:
                ii = [x.decode("utf-8") for x in i]
                self.collect_included_files(ii)
            except UnicodeDecodeError:
                # TODO can we do more here?
                logger.warning("Cannot decode argument: %s", i)
        logger.debug("%s found included files: %s", self.filename, self.mentioned_files)

    def collect_included_files(self, inc: list[str]) -> None:
        """Determine actually included files from the list of regex group captures."""
        logger.debug(f"collect_included_files: {inc}")
        inclen = len(inc)
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
        if inclen > 3 and inc[3]:
            include_extra_argument = inc[3]
        else:
            include_extra_argument = "{}"
        if inclen > 4 and inc[4]:
            include_extra2_argument = inc[4]
        else:
            include_extra2_argument = "{}"

        # check for syntactic correctness of arguments/options
        assert include_command in INCLUDE_COMMANDS_DICT.keys(), (
            f"{include_command} not in {INCLUDE_COMMANDS_DICT.keys()}"
        )
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
        if _RE_MACRO_ARG.match(include_argument):
            self.issues.append(
                TeXFileIssue(
                    IssueType.include_command_with_macro, f"command {include_command} used with macro parameter #"
                )
            )
            # logger.debug("Include command found with macro argument, we cannot deal with this!")
            return

        # checked for the key presence above
        incdef = INCLUDE_COMMANDS_DICT[include_command]

        no_arguments_commands = ["makeindex", "printindex"]
        if include_argument == "" and incdef.cmd not in no_arguments_commands:
            logger.debug(r"Skipping %s due to empty argument, maybe a \verb?", incdef.cmd)
            return

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
                file_incspec[f"""{{tikz,pgf}}library{f.strip().strip('"')}.code.tex"""] = {incdef.cmd: incdef}
        elif incdef.cmd == "tcbuselibrary":
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for f in include_argument.split(","):
                file_incspec[f"""tcb{f.strip().strip('"')}.code.tex"""] = {incdef.cmd: incdef}
        elif incdef.cmd == "bibliographystyle":
            logger.debug(f"Detected BblType.plain for {self.filename}")
            self._uses_bbl_file_type.add(BblType.plain)
            file_incspec[include_argument.strip().strip('"')] = {incdef.cmd: incdef}
        elif incdef.cmd == "bibliography" or incdef.cmd == "addbibresource":
            # TODO detect more possible add*resource commands of biblatex
            # replace end of line comments with empty string
            self._uses_bibliography = True
            if incdef.cmd == "addbibresource":
                self._uses_bbl_file_type.add(BblType.biblatex)
            include_argument = re.sub(r"%.*$", "", include_argument, flags=re.MULTILINE)
            for bf in include_argument.split(","):
                f = bf.strip().strip('"')
                f = f[2:] if f.startswith("./") else f
                if f.endswith(".bib"):
                    file_incspec[f] = {incdef.cmd: incdef}
                else:
                    file_incspec[f"{f}.bib"] = {incdef.cmd: incdef}
        elif incdef.cmd == "makeindex":  # \makeindex -> \newindex{default}{idx}{ind}{Index}
            logger.debug("makeindex found")
            # encode the information of index definition into the filename
            file_incspec["<MAIN>.<default>.<idx>.<ind>"] = {incdef.cmd: incdef}
        elif incdef.cmd == "newindex":  # \newindex{tag}{raw_extension}{compiled_extension}{Whatever title}
            logger.debug(f"newindex found with tag {include_extra_argument} and {include_extra2_argument}")
            # encode the information of index definition into the filename
            file_incspec[f"<MAIN>.<{include_argument}>.<{include_extra_argument}>.<{include_extra2_argument}>"] = {
                incdef.cmd: incdef
            }
        elif incdef.cmd == "printindex":  # \printindex[tag] (default is <default> for tag
            logger.debug(f"printindex found with tag {include_options}")
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
                # if biblatex is used, record that
                if fn == "biblatex.sty":
                    self._uses_bibliography = True
                    self._uses_bbl_file_type.add(BblType.biblatex)
        elif incdef.cmd == "psfig" or incdef.cmd == "epsfig":
            # Command syntax: \(e)psfig{file=xxxx, ...}
            # which is similar to \includegraphics[...]{xxxx}
            for f in include_argument.split(","):
                stanza = f.strip().strip('"')
                if stanza.startswith("file="):
                    file_incspec[stanza[5:]] = {incdef.cmd: incdef}
                elif stanza.startswith("figure="):
                    file_incspec[stanza[7:]] = {incdef.cmd: incdef}
        else:
            if isinstance(incdef.file_argument, int):
                if incdef.file_argument == 1:
                    filearg = include_argument.strip().strip('"')
                elif incdef.file_argument == 2:
                    filearg = include_extra_argument.strip().strip('"')
                else:
                    # logger.error("incdef.file_argument = %s", incdef.file_argument)
                    logger.error("incdef: %s", pformat(incdef))
                    logger.error(
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

        logger.debug("Detected inc spec: %s", file_incspec)
        # clean up the actual file argument
        # the filearg could be very strange stuff, like when \includegraphics is redefined
        # \def\includegraphics{....}
        # in the case of agutexSI2019.cls, the .... even includes a \n
        # also normalize // to / for keys
        file_incspec_cleaned: dict[str, dict[str, IncludeSpec]] = {}
        for k, v in file_incspec.items():
            k_cleaned = k.encode("unicode_escape").decode("utf-8").replace("//", "/")
            file_incspec_cleaned[k_cleaned] = v
        # clean mentioned files from double //
        new_mentioned_files: dict[str, dict[str, IncludeSpec]] = {}
        for k, v in self.mentioned_files.items():
            kk = k.replace("//", "/")
            new_mentioned_files[kk] = v
        self.mentioned_files = new_mentioned_files
        for k, v in file_incspec_cleaned.items():
            if k in self.mentioned_files:
                self.mentioned_files[k] |= file_incspec_cleaned[k]
            else:
                self.mentioned_files[k] = file_incspec_cleaned[k]

    def generic_walk_document_tree(
        self, map: Callable[["ParsedTeXFile"], T], reduce: Callable[[T, T], T], init: T | None = None
    ) -> T:
        """Walk the document tree in map/reduce fashion."""
        return self._generic_walk_document_tree(map, reduce, {}, init)

    def _generic_walk_document_tree(
        self,
        map: Callable[["ParsedTeXFile"], T],
        reduce: Callable[[T, T], T],
        visited: dict[str, bool],
        init: T | None = None,
    ) -> T:
        """Call a function on any node of a document tree - internal helper."""
        if init is None:
            logger.debug("generic_walk_document_tree: init is None")
            ret = map(self)
            logger.debug("generic_walk_document_tree: init ret to %s", ret)
        else:
            logger.debug("generic_walk_document_tree: init is %s", init)
            selfmap = map(self)
            logger.debug("generic_walk_document_tree: map self is %s", selfmap)
            ret = reduce(init, selfmap)
            logger.debug("generic_walk_document_tree: ret %s = reduce ( init %s , map self %s )", ret, init, selfmap)
        visited[self.filename] = True
        logger.debug("generic_walk_document_tree: children = %s", [f.filename for f in self.children])
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
    def compute_language_of_graph(
        self,
    ) -> tuple[LanguageType, list[TeXFileIssue]]:
        """Walk a subgraph to search for properties."""
        return self._compute_language_of_graph({})

    def _compute_language_of_graph(self, visited: dict[str, bool]) -> tuple[LanguageType, list[TeXFileIssue]]:
        """Walk a subgraph to search for properties."""
        issues = []
        found_language: LanguageType = self.language
        logger.debug("compute_language_of_graph: %s, start lang = %s", self.filename, found_language)
        for n in self.children:
            if n.filename in visited:
                logger.debug("compute_language_of_graph: revisiting %s", n.filename)
                continue
            logger.debug("compute_language_of_graph: recursively calling into %s", n.filename)
            visited[n.filename] = True
            kid_language, kid_issues = n._compute_language_of_graph(visited)
            if found_language == LanguageType.unknown:
                found_language = kid_language
            elif found_language == LanguageType.tex:
                if kid_language == LanguageType.latex:
                    issues.append(
                        TeXFileIssue(IssueType.conflicting_file_type, "conflicting lang types of main and subfiles")
                    )
                elif kid_language == LanguageType.unknown or kid_language == LanguageType.tex:
                    # don't change found_language which is tex
                    pass
                else:
                    raise PreflightException(f"Unknown kid LanguageType {kid_language}")
            elif found_language == LanguageType.latex:
                if kid_language == LanguageType.tex:
                    issues.append(
                        TeXFileIssue(IssueType.conflicting_file_type, "conflicting lang types of main and subfiles")
                    )
                # keep found_language as LATEX
            elif found_language == LanguageType.latex209:
                if kid_language == LanguageType.tex:
                    issues.append(
                        TeXFileIssue(IssueType.conflicting_file_type, "conflicting lang types of main and subfiles")
                    )
                # keep found_language as LATEX209
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
        logger.debug("_recursive_collect_files: fn = %s, type = %s", self.filename, what)
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
        elif what == FileType.bst:
            idx = "used_other_files"
        elif what == "issues":
            idx = "issues"
        else:
            raise PreflightException(f"no such file type: {what}")
        # we will extend this list, so we cannot use the attribute itself,
        # but need a copy of it
        found: list[str] = getattr(self, idx).copy()
        logger.debug("_recursive_collect_files: setting found to %s", found)
        visited[self.filename] = True
        for n in self.children:
            if n.filename in visited:
                logger.debug("recursive_collect_files: revisiting %s", n.filename)
                continue
            found.extend(n._recursive_collect_files(what, visited))
        return found


class PreflightResponse(BaseModel):
    """Preflight response model."""

    status: PreflightStatus
    detected_toplevel_files: list[ToplevelFile]
    tex_files: list[ParsedTeXFile]
    ancillary_files: list[str]
    maybe_used_files: list[str]
    image_files: list[ImageInfo] = []

    def to_json(self, **kwargs: typing.Any) -> str:
        """Return a json representation."""
        return self.model_dump_json(exclude_none=True, exclude_defaults=True, **kwargs)


# only parse file with these extensions
# .pdf_tex are generated tex files from the svg.sty packages
# .pdf_t are generated tex files from the ??? packages
# we do not parse .cls and .clo files because they at times contain
# calls to macros that we use to detect language or bib type (\documentstyle, \bibliographystyle, etc.)
# which leads to misdetection and errors
# Examples:
# - cup-journal.cls contains \bibliographystyle
# - revtex4-1.cls contains \documentstyle
PARSED_FILE_EXTENSIONS = [".tex", ".sty", ".ltx", ".pdf_tex", ".pdf_t"]
ONLY_IMAGE_PARSE_FILE_EXTENSIONS = [".cls", ".clo"]
# extensions of files we want to keep but cannot detect in preflight directly
MAYBE_USED_FILE_EXTENSIONS = [
    ".pygtex",  # frozen cache of minted/pygmentize
]

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
    IncludeSpec(cmd="documentstyle", source="core", type=FileType.tex, extensions="cls sty"),
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
    IncludeSpec(cmd="bibliographystyle", source="core", type=FileType.other, extensions="bst", take_options=False),
    IncludeSpec(cmd="addbibresource", source="biblatex", type=FileType.bib),
    IncludeSpec(cmd="includegraphics", source="graphics", type=FileType.other, extensions=IMAGE_EXTENSIONS),
    IncludeSpec(cmd="includegraphics*", source="graphics", type=FileType.other, extensions=IMAGE_EXTENSIONS),
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
    IncludeSpec(cmd="addplot", source="pgfplots", type=FileType.other),
    IncludeSpec(cmd="setmainfont", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="setsansfont", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="setmonofont", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="newfontfamily", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="setfontfamily", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="renewfontfamily", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="providefontfamily", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="newfontface", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="setfontface", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="renewfontface", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="providefontface", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
    IncludeSpec(cmd="fontspec", source="fontspec", type=FileType.other, extensions=FONT_EXTENSIONS),
]
# make a dict with key is include command
INCLUDE_COMMANDS_DICT = {f.cmd: f for f in INCLUDE_COMMANDS}


# TODO
# \openin2=data.txt ... \read2 to \myline ...

ARGS_INCLUDE_REGEX_ONLY_IMAGES = r"""
    \\(
        includegraphics\*|               # graphic[sx]
        includegraphics|                 # graphic[sx]
        epsfig|                          # epsfig
        psfig|
        includepdf|                      # pdfpages
        epsfbox                          # epsf
    )\s*(?:%.*\n)?
    \s*(\[[^]]*\])?\s*(?:%.*\n)?      # optional arguments
    \s*({[^}]*})?\s*(?:%.*\n)?        # actual argument with braces
    \s*({[^}]*})?\s*(?:%.*\n)?        # second argument with braces
    \s*({[^}]*})?                     # third argument with braces
    (?=\s*(\W|$))                         # any non-word character terminating the command
"""
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
        bibliographystyle|
        addbibresource|                  # biblatex
        includegraphics\*|               # graphic[sx]
        includegraphics|                 # graphic[sx]
        epsfig|                          # epsfig
        psfig|
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
        begin\s*{\s*overpic\s*}|         # overpic
        set(?:main|sans|mono)font|         # fontspec
        fontspec                         # extra fontspec via special treatment
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
ALL_COMPILERS_STR: list[str] = [c.compiler_string for c in ALL_COMPILERS if c.compiler_string is not None]
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


SUPPORTED_COMPILERS: list[CompilerSpec]
SUPPORTED_COMPILERS_STR: list[str | None]


def update_list_of_supported_compilers() -> None:
    """Update the list of supported compilers."""
    global SUPPORTED_COMPILERS, SUPPORTED_COMPILERS_STR  # noqa: PLW0603
    # the following order also gives the preference!
    # fmt: off
    SUPPORTED_COMPILERS = (
        [COMPILER["pdflatex"], COMPILER["latex"], COMPILER["pdftex"], COMPILER["tex"], COMPILER["xelatex"]]
        + ([COMPILER["lualatex"]] * ENABLE_LUALATEX)
    )
    # fmt:on
    SUPPORTED_COMPILERS_STR = [c.compiler_string for c in SUPPORTED_COMPILERS]


# actually set the values
update_list_of_supported_compilers()


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


def parse_file(basedir: str, filename: str, only_image: bool = False) -> ParsedTeXFile:
    """Parse a file for included commands."""
    with open(f"{basedir}/{filename}", "rb") as f:
        data = f.read()
    # standardize line endings
    data = _RE_LINE_ENDING.sub(b"\n", data)
    n = ParsedTeXFile(filename=filename)
    n._data = data
    logger.debug("parse_file: starting detect_included_files %s", n.filename)
    n.detect_included_files(only_images=only_image)
    logger.debug("parse_file: starting detect_language")
    n.detect_language()
    logger.debug("parse_file: finished parsing")

    return n


def parse_dir(
    rundir: str,
) -> tuple[dict[str, ParsedTeXFile] | ToplevelFile, list[str], list[str], list[ImageInfo], list[TeXFileIssue]]:
    """Parse all TeX files in a directory.

    Returns:
        Tuple of (nodes, anc_files, maybe_files, image_files, warning_issues)
    """
    glob_files = glob.glob(f"{rundir}/**/*", recursive=True)
    # strip rundir/ prefix
    n = len(rundir) + 1
    all_files = [f[n:] for f in glob_files if os.path.isfile(f)]
    # collect image sizes
    image_files: list[ImageInfo] = collect_image_info(all_files, rundir)
    # run checks on all files
    checks_succeeded, error_checks, warning_checks = run_file_checks(
        all_files, "all", rundir, extra={"image_files": image_files}
    )

    # Errors raise exception as before
    if not checks_succeeded:
        raise CheckPreflightException("\n".join([z.info for z in error_checks]))

    # Warnings are collected and will be added to issues
    warning_issues: list[TeXFileIssue] = []

    # Collect all warnings
    for warning in warning_checks:
        warning.issues.extend(warning.issues)

    # we will not analyze ancillary files
    files = [f for f in all_files if not f.startswith("anc/")]
    # ancillary files
    anc_files = [t for t in all_files if t.startswith("anc/")]
    #
    # maybe files
    maybe_files = [t for t in files if os.path.splitext(t)[1].lower() in MAYBE_USED_FILE_EXTENSIONS]
    # files = os.listdir(rundir)
    # needs more extensions that we support
    tex_files = [t for t in files if os.path.splitext(t)[1].lower() in PARSED_FILE_EXTENSIONS]
    logger.debug(f"Detected files for {rundir} = {tex_files}")
    if not tex_files:
        # we didn't find any tex file, check for a single PDF file
        if len(files) == 1 and files[0].lower().endswith(".pdf"):
            # PDF only submission, only one PDF file, nothing else
            # run checks that might reject the PDF
            checks_succeeded, failed_checks = run_pdf_checks(f"{rundir}/{files[0]}", "all")
            if not checks_succeeded:
                raise CheckPreflightException("\n".join([z.info for z in failed_checks]))
            return (
                ToplevelFile(
                    filename=files[0], process=MainProcessSpec(compiler=CompilerSpec(compiler=PDF_SUBMISSION_STRING))
                ),
                anc_files,
                maybe_files,
                image_files,
                warning_issues,
            )
        else:
            # check for HTML submissions
            for f in sorted(files):
                if f.lower().endswith(".html"):
                    return (
                        ToplevelFile(
                            filename=f, process=MainProcessSpec(compiler=CompilerSpec(compiler=HTML_SUBMISSION_STRING))
                        ),
                        anc_files,
                        maybe_files,
                        image_files,
                        warning_issues,
                    )
    only_image_files = [t for t in files if os.path.splitext(t)[1].lower() in ONLY_IMAGE_PARSE_FILE_EXTENSIONS]
    logger.debug(f"First round of tex file parsing: {tex_files}")
    nodes = {f: parse_file(rundir, f) for f in tex_files}
    logger.debug(f"Second round of tex file parsing (only_image=True): {only_image_files}")
    nodes_imgs = {f: parse_file(rundir, f, only_image=True) for f in only_image_files}
    nodes.update(nodes_imgs)
    # print(nodes)
    return nodes, anc_files, maybe_files, image_files, warning_issues


def kpse_search_files(
    basedir: str, nodes: dict[str, ParsedTeXFile], toplevel_node: ParsedTeXFile | None = None
) -> dict[str, dict[str, str]]:
    """Search for files using kpsearch, using the lua script kpse_search.lua.

    If toplevel_node is None, only search for TeX files, otherwise
    search for all non-TeX files included recursively in the document tree
    of toplevel_node.
    """
    logger.debug("DUMP A")
    _dump_nodes(nodes)
    kpse_find_input_data = ""
    kpse_find_input_data_prefix = ""
    if toplevel_node:
        # The following does NOT include the toplevel_node itself
        # we need to make a copy, otherwise, when we append the toplevel filename,
        # it will be appended to the original node list, since these are only pointers
        # to lists.
        all_used_nodes: list[str] = toplevel_node.recursive_collect_files(FileType.tex).copy()
        logger.debug("DUMP B")
        _dump_nodes(nodes)
        all_used_nodes.append(toplevel_node.filename)
        search_nodes = {}
        for f in all_used_nodes:
            if f in nodes:
                search_nodes[f] = nodes[f]
            else:
                logger.debug("TeX-like file included but not found, skipping: %s", f)
        logger.debug("DUMP C")
        _dump_nodes(nodes)
        logger.debug(
            "kpse_search_file: searching in document tree for %s - %s - %s",
            toplevel_node.filename,
            all_used_nodes,
            search_nodes.keys(),
        )
        # search for graphics path
        # if we find two or more, skip completely - this is not supported since we would need to know
        # the order, and which images are loaded at what time
        # Other option would be to make multiple graphicspath additive, which is not what
        # latex does, but might help?
        logger.debug("Bubbling up graphicspath to toplevel files")
        all_graphicspaths: list[list[str]] = toplevel_node.generic_walk_document_tree(
            lambda x: x._graphicspath,
            lambda x, y: [*x, *y] if y is not None else x,  # we cannot use append, needs to be functional!
            [],
        )  # Deal with the set of "normal" inclusions
        logger.debug("Bubbled up graphics path gives: %s", all_graphicspaths)
        if len(all_graphicspaths) > 1:
            logger.warning("Multiple graphicspath directive detected, skipping all of them!")
        elif len(all_graphicspaths) == 1:
            toplevel_node._graphicspath = all_graphicspaths
            logger.debug(
                "Set graphicspath of toplevel file %s to %s", toplevel_node.filename, toplevel_node._graphicspath
            )
        if toplevel_node and toplevel_node._graphicspath:
            # there can only be one entry
            kpse_find_input_data_prefix += f"""#graphicspath={":".join(toplevel_node._graphicspath[0])}\n"""
    else:
        search_nodes = nodes.copy()
        logger.debug("kpse_search_file: searching all nodes for TeX files")

    for _, n in search_nodes.items():
        for k, subv in n.mentioned_files.items():
            for cmd, v in subv.items():
                logger.debug("kpse_search: k = %s, cmd = %s, v = %s", k, cmd, v)
                # if we are in the first round (toplevel_files is empty) we only search
                # for TeX files, so skip everything else.
                if toplevel_node:
                    # search for all but TeX files within the toplevel_node
                    if v.type == FileType.tex:
                        continue
                else:
                    # search for TeX files only
                    if v.type != FileType.tex:
                        continue

                # we don't know the \jobname by now, so we cannot search for index files
                # (.idx/.ind/etc)
                if k.startswith("<MAIN>."):
                    continue
                exts = v.ext_str()
                kpse_find_input_data += f"{k}\n{exts}\n"
                logger.debug("... adding k/exts %s/%s to find input", k, exts)

    if not kpse_find_input_data:
        return {}

    logger.debug("kpse_find_input_data ===%s===", kpse_find_input_data)

    debug_args = ["-vv"] if logger.root.level == logging.DEBUG else []
    p = subprocess.run(
        ["texlua", f"{MODULE_PATH}/kpse_search.lua", *debug_args, "-mark-sys-files", basedir],
        input=kpse_find_input_data_prefix + kpse_find_input_data,
        capture_output=True,
        text=True,
        check=True,
    )

    logger.debug("kpse_found return: ===\n%s\n===", p.stdout)
    # lua script ships out debug output using DEBUG: header per line
    lines_stdout = p.stdout.splitlines()
    lines = [line for line in lines_stdout if line[:7] != "DEBUG: "]
    logger.debug("Return lines from kpse_find.lua: ===\n%s\n===", lines)
    for line in lines_stdout:
        if line[:7] == "DEBUG: ":
            logger.debug(f"kpse_find.lua {line}")

    # read back the output information
    kpse_found: dict[str, dict[str, str]] = {}
    for fname, exts, found in zip_longest(*[iter(lines)] * 3, fillvalue=""):
        logger.debug("zipping gives fname / exts / found = %s / %s / %s", fname, exts, found)
        if fname not in kpse_found:
            kpse_found[fname] = {}
        if found.startswith("./anc/"):
            # ignore ancillary files in the return, they should be marked
            # as not existing
            kpse_found[fname][exts] = ""
        else:
            kpse_found[fname][exts] = found[2:] if found.startswith("./") else found

    logger.debug("kpse_found return ====%s===", kpse_found)
    return kpse_found


def update_nodes_with_kpse_info(
    nodes: dict[str, ParsedTeXFile],
    kpse_found: dict[str, dict[str, str]],
    only_tex: bool,
    toplevel_node: ParsedTeXFile | None = None,
) -> dict[str, ParsedTeXFile]:
    """Update the parsed tex files with the location of used files.

    If toplevel_node is given, only update nodes below that node in the document forest.
    """
    selected_nodes: list[str] = []
    if toplevel_node:
        selected_nodes = toplevel_node.recursive_collect_files(FileType.tex).copy()
        selected_nodes.append(toplevel_node.filename)
    for _, n in nodes.items():
        # the check for toplevel_node is not necessary, but mypy cannot deduce that
        # it is set if selected_nodes is not []
        if toplevel_node and selected_nodes and n.filename not in selected_nodes:
            logger.debug("Skipping %s, not in document tree below toplevel %s", n.filename, toplevel_node.filename)
            continue
        logger.debug("update_nodes_with_kpse_info: working on %s only_tex = %s", n.filename, only_tex)
        for f, subv in n.mentioned_files.items():
            logger.debug("... got f = %s", f)
            for cmd, v in subv.items():
                v_exts = v.ext_str()
                logger.debug("...... got cmd = %s, vexts = %s, v type = %s", cmd, v_exts, v.type)
                if f in kpse_found and v_exts in kpse_found[f]:
                    found = kpse_found[f][v_exts]
                    logger.debug("...... found %s", found)
                elif f.startswith("<MAIN>."):
                    # deal with index idx/ind files that are based on jobname
                    # and aren't found.
                    logger.debug(r"keeping \jobname file %s", f)
                    found = f
                else:
                    # we search in two steps, so not all entries will ever be in the return value
                    logger.debug("kpse_found not containing =%s=", f)
                    continue
                if found.startswith("SYSTEM:"):
                    # record system files serparately
                    n.used_system_files.append(found[7:])
                    continue
                # if we don't find the file and
                # * it is not loaded via InputIfFileExists
                # * it is not a bib file
                # then record an issue
                # If it is a bib file, record it in internal field _missing_bib_files
                if found == "":
                    if v.cmd != "InputIfFileExists":
                        if v.type == FileType.bib:
                            n._missing_bib_files.add(f)
                        else:
                            n.issues.append(TeXFileIssue(IssueType.file_not_found, f))
                    continue
                if only_tex:
                    if v.type == FileType.tex:
                        n.used_tex_files.append(found)
                    else:
                        logger.debug("Ignoring anything else in only_tex=True mode")
                else:
                    if v.type == FileType.bib:
                        logger.debug("Adding for %s found %s to used_bib_files", n.filename, found)
                        n.used_bib_files.append(found)
                        logger.debug("Now used_bib_files = %s", n.used_bib_files)
                    elif v.type == FileType.bbl:
                        n.used_bbl_files.append(found)
                    elif v.type == FileType.ind:
                        n.used_ind_files.append(found)
                    elif v.type == FileType.idx:
                        n.used_idx_files.append(found)
                    elif v.type == FileType.other:
                        n.used_other_files.append(found)
                    elif v.type == FileType.tex:
                        logger.debug("Ignoring tex files in only_tex=False mode")
                    else:
                        raise PreflightException(f"Unknown file type {v.type} for file {f}")
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
                        logger.warning("Cannot find parsed node for used tex file %s", sn)
    for fn, n in nodes.items():
        # print(f"working on {n.filename} - parents = {n.parents}")
        if not n.parents:
            # print("n.parents is true")
            roots[fn] = n
    return roots, nodes


def compute_toplevel_files(roots: dict[str, ParsedTeXFile], nodes: dict[str, ParsedTeXFile]) -> dict[str, ToplevelFile]:
    """Determine the toplevel files."""
    toplevel_files = {}
    nr_root_items = len(roots)
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

        # special case: we didn't find any toplevel file, and there is only one tree (root)
        # If the tree has unknown LanguageType, we assume it is plain TeX since the end of input is equivalent to \bye
        # We don't do this if there are more than one root items, to not get some randomly uploaded file
        # listed as toplevel file.
        if (
            len(toplevel_files) == 0
            and nr_root_items == 1
            and tl_n.compute_language_of_graph()[0] == LanguageType.unknown
        ):
            logger.debug("compute_toplevel_files: assuming plain TeX due to graph being unknown for %s", f)
            tl_n.language = LanguageType.tex
            toplevel_files[f] = tl

    return toplevel_files


def guess_compilation_parameters(toplevel_files: dict[str, ToplevelFile], nodes: dict[str, ParsedTeXFile]) -> None:
    """Guess the compilation parameters from the accumulated information."""
    for f, tl in toplevel_files.items():
        tl_n = nodes[f]

        # CompilerSpec is not hashable, so we cannot directly use it as set elements
        candidate_compilers = set(ALL_COMPILERS_STR)

        logger.debug("guess_compilation_parameters: tl_n.used_tex_files = %s", tl_n.used_tex_files)
        logger.debug("guess_compilation_parameters: tl_n.used_system_files = %s", tl_n.used_system_files)

        found_language, issues = tl_n.compute_language_of_graph()
        if found_language == LanguageType.latex209:
            # we generally forbid latex209, but to support those who still write amstex plain tex documents
            # using \include amstex\documentstyle{amsppt} let them be helped!
            loads_amstex: bool = tl_n.generic_walk_document_tree(
                lambda x: bool([p for p in x.used_tex_files + x.used_system_files if p.endswith("/amstex.tex")]),
                lambda x, y: x or y,
            )
            if loads_amstex:
                logger.debug("guess_compilation_parameters: found amstex load, allowing for latex209")
                found_language = LanguageType.tex
            else:
                issues.append(
                    TeXFileIssue(IssueType.unsupported_compiler_type_latex209, "LaTeX 2.09 is not supported anymore")
                )

        logger.debug("guess_compilation_parameters: found language %s", found_language)

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
        is_unicode_tex = False
        for fn in tl_n.used_system_files + tl_n.used_tex_files:
            for ucfn in UNICODE_TEX_PACKAGES:
                if fn.endswith(f"/{ucfn}.sty"):
                    candidate_compilers.intersection_update(FONTSPEC_ALLOWED_COMPILERS_STR)
                    is_unicode_tex = True
                    break

        # check all other files
        all_other = tl_n.recursive_collect_files(FileType.other)
        logger.debug("Guess image types: files = %s", all_other)
        pdftex_exts = set(IMAGE_EXTENSIONS["pdftex"].split())
        dvips_exts = set(IMAGE_EXTENSIONS["dvips"].split())
        luatex_exts = set(IMAGE_EXTENSIONS["luatex"].split())
        dvipdfmx_exts = set(IMAGE_EXTENSIONS["dvipdfmx"].split())
        all_exts = pdftex_exts | dvips_exts | luatex_exts | dvipdfmx_exts
        driver_paths = {"pdftex", "dvips", "dvipdfmx", "luatex"}
        for fn in all_other:
            logger.debug("before discarding drivers, drive_paths = %s, fn = %s", driver_paths, fn)
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
            logger.debug("after discarding drivers, drive_paths = %s, fn = %s", driver_paths, fn)
        if not driver_paths:
            issues.append(TeXFileIssue(IssueType.conflicting_engine_type, "included images force conflicting engines"))

        logger.debug("Starting candidate_compiler updates: %s", candidate_compilers)
        if "luatex" not in driver_paths:
            candidate_compilers.difference_update(
                set([c.compiler_string for c in ALL_COMPILERS if c.engine == EngineType.luatex])
            )
        logger.debug("After luatex candidate_compiler updates: %s", candidate_compilers)
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
        logger.debug("After dvipdmx candidate_compiler updates: %s", candidate_compilers)
        if "dvips" not in driver_paths:
            candidate_compilers.difference_update(
                set([c.compiler_string for c in ALL_COMPILERS if c.postp == PostProcessType.dvips_ps2pdf])
            )
        logger.debug("After dvips candidate_compiler updates: %s", candidate_compilers)
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
        logger.debug("After pdftex (end) candidate_compiler updates: %s", candidate_compilers)

        lang: LanguageType = LanguageType.tex if found_language == LanguageType.unknown else found_language

        candidate_compilers.intersection_update(TEX_COMPILERS_STR if lang == LanguageType.tex else LATEX_COMPILERS_STR)

        possible_compiler_strings = list(candidate_compilers)
        supported_compiler_strings = candidate_compilers.intersection(set(SUPPORTED_COMPILERS_STR))

        if not possible_compiler_strings:
            issues.append(TeXFileIssue(IssueType.unsupported_compiler_type, "compiler cannot be determined"))
        elif not supported_compiler_strings:
            # try to give a good hint why this does not work:
            if is_unicode_tex:
                issues.append(
                    TeXFileIssue(
                        IssueType.unsupported_compiler_type_unicode,
                        "Unicode TeX engine (XeTeX or LuaTeX) is required, but currently not supported.",
                    )
                )
            else:
                issues.append(
                    TeXFileIssue(
                        IssueType.unsupported_compiler_type_image_mix,
                        "Probable mix of eps and png/jpg/pdf images, which is currently not supported.",
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

        tl.issues = issues


def update_toplevel_issues(toplevel_files: dict[str, ToplevelFile], nodes: dict[str, ParsedTeXFile]) -> None:
    """Add a toplevel issue if there are issues in subfiles."""
    for f, tl in toplevel_files.items():
        issues: list[TeXFileIssue] = tl.issues
        tl_n = nodes[f]
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
        bbl_file = tl_f.removesuffix(".tex").removesuffix(".TEX") + ".bbl"
        bbl_file_full_path = os.path.join(rundir, bbl_file)
        bbl_file_present = os.path.isfile(bbl_file_full_path)

        # if the bbl file is not present, go over all nodes and add issues if bib files are missing
        bib_file_issue_found: bool = False
        logger.debug("checking for bib files")
        selected_nodes = nodes[tl_f].recursive_collect_files(FileType.tex).copy()
        selected_nodes.append(tl_f)
        for _, n in nodes.items():
            if tl_n and selected_nodes and n.filename not in selected_nodes:
                logger.debug("Skipping %s, not in document tree below toplevel %s", n.filename, tl_n.filename)
                continue
            for bib_file in n._missing_bib_files:
                bib_file_issue_found = True
                if not bbl_file_present:
                    n.issues.append(TeXFileIssue(IssueType.file_not_found, "bib file missing", bib_file))

        node = nodes[tl_f]
        uses_bibliography: bool = node.generic_walk_document_tree(
            lambda x: x._uses_bibliography, lambda x, y: x or y, False
        )
        bbl_types_used: set = node.generic_walk_document_tree(
            lambda x: x._uses_bbl_file_type, lambda x, y: x.union(y), set()
        )
        logger.debug(f"bbl types used: {bbl_types_used}")
        if not uses_bibliography:
            logger.debug("no bibliography use detected!")
            # no bibliography used, skip
            continue
        if len(bbl_types_used) == 0:
            # we default to plain type
            logger.debug("no bibliography type used, defaulting to plain")
            bbl_types_used = set([BblType.plain])
        if len(bbl_types_used) > 1:
            logger.debug("multiple bbl types used, add issue")
            # multiple bibliography types used, skip
            tl_n.issues.append(
                TeXFileIssue(
                    IssueType.multiple_bibliography_types,
                    f"multiple bibliography types used: {[v.value for v in bbl_types_used]}",
                )
            )
            continue

        # we have only one bibliography type, check if it is biber or bibtex
        is_biblatex_bbl: bool = bbl_types_used.pop() == BblType.biblatex
        if bbl_file_present:
            # check version of bbl file
            # First three lines of .bbl file:
            #
            # % $ biblatex auxiliary file $
            # % $ biblatex bbl format version 3.3 $
            # % Do not modify the above lines!
            with open(bbl_file_full_path, "rb") as bblfn:
                # try to read up to three lines from the .bbl file
                # This ma fail for empty .bbl files or files containing less than three lines
                # in this case the next throws the StopIteration exception
                try:
                    head = [next(bblfn).strip() for _ in range(3)]
                except StopIteration:
                    head = [b""]
            if head[0] == b"% $ biblatex auxiliary file $":
                # only check files created by biblatex/biber
                if not is_biblatex_bbl:
                    node.issues.append(
                        TeXFileIssue(
                            IssueType.bbl_usage_mismatch,
                            "bbl file created by biber, but bibtex is used",
                            bbl_file,
                        )
                    )
                else:
                    if head[1].startswith(b"% $ biblatex bbl format version "):
                        bbl_version = head[1].removeprefix(b"% $ biblatex bbl format version ").removesuffix(b" $")
                        bbl_version_utf8 = bbl_version.decode("utf-8")
                        if bbl_version not in CURRENT_ARXIV_TEX_BBL_VERSIONS[CURRENT_TEXLIVE_VERSION]:
                            # try other releases
                            if bbl_version in CURRENT_ARXIV_TEX_BBL_VERSIONS[PREVIOUS_TEXLIVE_VERSION]:
                                node.issues.append(
                                    TeXFileIssue(
                                        IssueType.bbl_version_needs_previous_version,
                                        f"Used bbl version {bbl_version_utf8} is only supported in "
                                        f"TeX Live {PREVIOUS_TEXLIVE_VERSION}",
                                        bbl_file,
                                    )
                                )
                            else:
                                good_versions = [
                                    x.decode("ascii") for x in CURRENT_ARXIV_TEX_BBL_VERSIONS[CURRENT_TEXLIVE_VERSION]
                                ]
                                node.issues.append(
                                    TeXFileIssue(
                                        IssueType.bbl_version_mismatch,
                                        f"Expected one of {good_versions} but got {bbl_version_utf8}",
                                        bbl_file,
                                    )
                                )
            # toplevel filename .bbl is available -> precompiled bib, ignore if bib files is missing
            tl_n.process.bibliography = BibProcessSpec(
                processor=BibCompiler.biblatex if is_biblatex_bbl else BibCompiler.unknown,
                pre_generated=True,
                can_be_generated=not bib_file_issue_found,
            )
            # if we don't allow bib->bbl processing,
            # add bbl file to the list of used_other_files
            logger.debug(
                "bbl other files check: bib_file_issue_found = %s",
                bib_file_issue_found,
            )
            if bib_file_issue_found:
                nodes[tl_f].used_other_files.append(bbl_file)
            continue
        # we are still here, so bbl_file_present is False
        # toplevel filename .bbl is missing -> require .bib to be available,
        # TODO this should detect `backend=bibtex` in the biblatex options!
        tl_n.process.bibliography = BibProcessSpec(
            processor=BibCompiler.biblatex if is_biblatex_bbl else BibCompiler.unknown,
            pre_generated=False,
            can_be_generated=not bib_file_issue_found,
        )
        # we have activated bib->bbl generation, so no issue needs to be reported
        # we also already added issues to the single files if bib is missing and bbl not available
        # tl_n.issues.append(TeXFileIssue(IssueType.bbl_file_missing, "bbl file missing", bbl_file))
        logger.debug("bib_file_issue_found = %s, bbl_file_present = %s", bib_file_issue_found, bbl_file_present)
        if bib_file_issue_found and not bbl_file_present:
            tl_n.issues.append(TeXFileIssue(IssueType.bbl_bib_file_missing, "Both bbl and bib files are missing"))


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
        logger.debug("Got all_ind = %s", all_ind)
        logger.debug("Got all_idx = %s", all_idx)
        if not all_ind and not all_idx:
            logger.debug("no index use detected!")
            # no index used, skip
            continue
        defined_indices = {}
        for idxdef in all_idx:
            tag, idx_ext, ind_ext = idxdef.split(".")
            tag = tag[1:-1]
            idx_ext = idx_ext[1:-1]
            ind_ext = ind_ext[1:-1]
            defined_indices[tag] = (idx_ext, ind_ext)
        logger.debug("Found globally used indices: %s", all_ind)
        logger.debug("Found globally defined indices: %s", defined_indices)
        found_all_indices = True
        for tag in all_ind:
            # check that all used indices are defined
            if tag not in defined_indices:
                logger.error("Missing index definition for %s", tag)
                tl_n.issues.append(
                    TeXFileIssue(IssueType.index_definition_missing, f"index definition for {tag} not found")
                )
                continue
            else:
                logger.debug("Found index definition for %s: %s", tag, defined_indices[tag])
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
            tl_n.process.index = IndexProcessSpec(
                processor=IndexCompiler.unknown,
                pre_generated=True,
                can_be_generated=False,  # TODO this needs review!
            )
        else:
            tl_n.process.index = IndexProcessSpec(
                processor=IndexCompiler.unknown,
                pre_generated=False,
                can_be_generated=False,  # TODO this needs review!
            )


def _dump_nodes(nodes: dict[str, ParsedTeXFile]) -> None:
    logger.debug("DUMPING NODES")
    for k, n in nodes.items():
        logger.debug("... DUMP node k = %s", k)
        logger.debug("... ... used_tex_files = %s", n.used_tex_files)
        logger.debug("... ... used_other_files = %s", n.used_other_files)


def _generate_preflight_response_dict(rundir: str) -> PreflightResponse:
    """Parse submission and generated preflight response as dictionary."""
    # parse files
    n: dict[str, ParsedTeXFile] | ToplevelFile
    anc_files: list[str]
    maybe_files: list[str]
    nodes: dict[str, ParsedTeXFile]
    roots: dict[str, ParsedTeXFile]
    toplevel_files: dict[str, ToplevelFile]

    image_files: list[ImageInfo] = []
    warning_issues: list[TeXFileIssue] = []

    try:
        n, anc_files, maybe_files, image_files, warning_issues = parse_dir(rundir)
        tests_succeeded = True
        error_msg = ""
    except CheckPreflightException as e:
        tests_succeeded = False
        error_msg = f"QA check failed: {e!s}"
    if not tests_succeeded:
        nodes = {}
        toplevel_files = {}
        anc_files = []
        maybe_files = []
        status = PreflightStatus(key=PreflightStatusValues.error, info=error_msg)
    elif isinstance(n, ToplevelFile):
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
            logger.debug("generate preflight: initial nodes = %s", nodes)
            # search for TeX files only in a first round
            kpse_found = kpse_search_files(rundir, nodes)
            # update nodes with information of found kpse
            nodes = update_nodes_with_kpse_info(nodes, kpse_found, only_tex=True)
            logger.debug("found TeX file nodes: %s", nodes.keys())
            # create tree
            roots, nodes = compute_document_graph(nodes)
            logger.debug("found root nodes: %s", roots.keys())
            # determine toplevel files
            toplevel_files = compute_toplevel_files(roots, nodes)
            # search for all other files per toplevel file
            for tlf in toplevel_files.keys():
                tl_n = nodes[tlf]
                logger.debug(
                    "Working on toplevel file %s searching for other files %s", tl_n.filename, tl_n.used_other_files
                )
                kpse_found2 = kpse_search_files(rundir, nodes, tl_n)
                nodes = update_nodes_with_kpse_info(nodes, kpse_found2, only_tex=False, toplevel_node=tl_n)
                logger.debug(
                    "After working on toplevel file %s searching for other files - n.used_other_files = %s",
                    tl_n.filename,
                    nodes[tlf].used_other_files,
                )
            guess_compilation_parameters(toplevel_files, nodes)
            deal_with_bibliographies(rundir, toplevel_files, nodes)
            deal_with_indices(rundir, toplevel_files, nodes)
            update_toplevel_issues(toplevel_files, nodes)
            # Add warning issues to the first toplevel file (or create a dummy if none)
            if toplevel_files and warning_issues:
                first_tlf = next(iter(toplevel_files.values()))
                first_tlf.issues.extend(warning_issues)
            # TODO check for suspicious status!
            status = PreflightStatus(key=PreflightStatusValues.success)
    return PreflightResponse(
        status=status,
        detected_toplevel_files=[tl for tl in toplevel_files.values()],
        tex_files=[n for n in nodes.values()],
        ancillary_files=anc_files,
        maybe_used_files=maybe_files,
        image_files=image_files,
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
            maybe_used_files=[],
        )
    if json:
        return pfr.to_json(**kwargs)
    else:
        return pfr
