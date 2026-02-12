import logging
import typing
from dataclasses import dataclass, field
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel, Field

logger = logging.getLogger("[preflight]")

T = TypeVar("T")

#
# GLOBAL CONSTANTS
#
PDF_SUBMISSION_STRING = "pdf_submission"
HTML_SUBMISSION_STRING = "html_submission"


TEX_EXTENSIONS = "tex"
EPS_EXTENSIONS = "eps ps eps.gz ps.gz mps"
FONT_EXTENSIONS = "ttf otf"

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


#
# CLASSES AND TYPES
#
# This section contains the class definitions and compound types


class ImageInfo(BaseModel):
    """Information about an image file."""

    filename: str
    width: int | None = None
    height: int | None = None
    megapixels: float | None = None
    file_bytes: int | None = None
    is_oversized: bool = False
    pdftex_fast_copy: bool | None = Field(
        default=None, alias="pdftex-fast-copy", serialization_alias="pdftex-fast-copy"
    )

    @property
    def file_size_mb(self) -> float | None:
        """Return file size in megabytes."""
        if self.file_bytes is None:
            return None
        return self.file_bytes / (1024 * 1024)


class IssueType(str, Enum):
    """Possible issues we detect."""

    file_not_found = "file_not_found"
    conflicting_file_type = "conflicting_file_type"
    conflicting_output_type = "conflicting_output_type"
    conflicting_engine_type = "conflicting_engine_type"
    conflicting_postprocess_type = "conflicting_postprocess_type"
    unsupported_compiler_type = "unsupported_compiler_type"
    unsupported_compiler_type_unicode = "unsupported_compiler_type_unicode"
    unsupported_compiler_type_image_mix = "unsupported_compiler_type_image_mix"
    unsupported_compiler_type_latex209 = "unsupported_compiler_type_latex209"
    conflicting_image_types = "conflicting_image_types"
    include_command_with_macro = "include_command_with_macro"
    contents_decode_error = "contents_decode_error"
    issue_in_subfile = "issue_in_subfile"
    index_definition_missing = "index_definition_missing"
    bbl_version_mismatch = "bbl_version_mismatch"
    bbl_version_needs_previous_version = "bbl_version_needs_previous_version"
    bbl_file_missing = "bbl_file_missing"
    bbl_bib_file_missing = "bbl_bib_file_missing"
    multiple_bibliography_types = "multiple_bibliography_types"
    bbl_usage_mismatch = "bbl_usage_mismatch"
    oversized_image = "oversized_image"
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
    bst = "bst"  # bibliography style files
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
    LATEX209 is for old-style submissions, which we do not accept anymore, but detect
    PDF is for PDF only submissions.
    HTML is for HTML only submissions.
    UNKNOWN allows compilation as either TEX or LATEX.
    """

    unknown = "unknown"
    tex = "tex"
    latex = "latex"
    latex209 = "latex209"
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
    mendex = "mendex"


class BibCompiler(str, Enum):
    """Possible bib-bbl compiler."""

    unknown = "unknown"
    bibtex = "bibtex"
    bibtex8 = "bibtex8"
    bibtexu = "bibtexu"
    upbibtex = "upbibtex"
    biber = "biber"
    biblatex = "biblatex"  # biblatex has backend configuration, and we parse run.xml for the correct one


class BblType(str, Enum):
    """Possible values for bbl file type."""

    unknown = "unknown"
    plain = "plain"
    biblatex = "biblatex"


class PostProcessType(str, Enum):
    """Possible conversion types from dvi to pdf."""

    unknown = "unknown"
    none = "none"
    dvips_ps2pdf = "dvips_ps2pdf"
    dvipdfmx = "dvipdfmx"


class PreflightException(Exception):
    """General exception when parsing preflight."""

    pass


class CheckPreflightException(PreflightException):
    """Exception raised when PDF checks fail."""

    pass


class ParseSyntaxError(PreflightException):
    """Syntax error when parsing a dict to an object."""

    pass


class IndexProcessSpec(BaseModel):
    """Specification of the indexing process."""

    processor: IndexCompiler = IndexCompiler.unknown
    pre_generated: bool
    can_be_generated: bool


class BibProcessSpec(BaseModel):
    """Specification of the bibliography process."""

    processor: BibCompiler = BibCompiler.unknown
    pre_generated: bool
    can_be_generated: bool


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
                    # deal with the special case of pdfetex/pdftex
                    # we want return "pdftex" as compiler string
                    # otherwise we get "pdfetex" in 00README.json files showing up in "compiler: pdfetex"
                    # which is **correct** but the frontend fails to deal with that.
                    if ret == "pdfetex":
                        ret = "pdftex"
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
        # pdftex -> pdfetex (since this is the correct compiler name)
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
        if compiler == "pdftex":
            self.lang = LanguageType.tex
            self.engine = EngineType.tex
            self.output = OutputType.pdf
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


class ToplevelFile(BaseModel):
    """Toplevel file and how to compile it."""

    filename: str
    process: MainProcessSpec
    hyperref_found: bool | None = None
    issues: list[TeXFileIssue] = []


class CheckSeverity(str, Enum):
    """Severity level for check results."""

    error = "error"
    warning = "warning"


@dataclass
class CheckResult:
    check_passed: bool
    info: str
    long_info: str
    severity: CheckSeverity = CheckSeverity.error
    issues: list[TeXFileIssue] = field(default_factory=list)
