"""00README file parsing and handling."""

import json
import os
import typing
from collections import OrderedDict
from enum import Enum

import toml
import tomli_w
from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML, MappingNode, ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter

from ..preflight import (
    CompilerSpec,
    EngineType,
    LanguageType,
    MainProcessSpec,
    OutputType,
    PostProcessType,
    PreflightResponse,
    ToplevelFile,
    string_to_bool,
)

# 00README extensions
ZZRM_V1_EXTS: list[str] = [".xxx"]
ZZRM_V2_EXTS: list[str] = [".yml", ".yaml", ".json", ".jsn", ".ndjson", ".toml"]
ZZRM_EXTS: list[str] = ZZRM_V2_EXTS + ZZRM_V1_EXTS
DEFAULT_EXT = ".json"
DEFAULT_FORMAT = "json"

# We default to pdflatex
DEFAULT_ENGINE_TYPE: EngineType = EngineType.tex
DEFAULT_LANGUAGE_TYPE: LanguageType = LanguageType.latex
DEFAULT_OUTPUT_TYPE: OutputType = OutputType.pdf
DEFAULT_POSTPROCESS_TYPE: PostProcessType = PostProcessType.none


def yaml_repr_str(dumper: RoundTripRepresenter, data: str) -> ScalarNode:
    """Convert string to yaml representation."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def yaml_repr_ordered_dict(dumper: RoundTripRepresenter, data: OrderedDict) -> MappingNode:
    """Convert ordered dict to yaml representation."""
    return dumper.represent_mapping("tag:yaml.org,2002:map", dict(data))


def strip_to_basename(path: str, extent: None | str = None) -> str:
    """Strip the path to the basename."""
    if extent is None:
        return os.path.basename(path)
    return os.path.splitext(os.path.basename(path))[0] + extent


class ZZRMException(Exception):
    """General exception when dealing with ZZRM files."""

    pass


class ZZRMFileNotFoundError(ZZRMException):
    """Error when a needed file is not found."""

    pass


class ZZRMUnsupportedFileError(ZZRMException):
    """Error when an unsupported files (name, extension) is detected."""

    pass


class ZZRMUnsupportedVersion(ZZRMException):
    """Error when an unsupported ZZRM version is detected."""

    pass


class ZZRMMultipleFilesError(ZZRMException):
    """Error when multiple ZZRM files of the same version are found."""

    pass


class ZZRMKeyError(ZZRMException):
    """Error when an unknown key is found in ZZRM v1."""

    pass


class ZZRMParseError(ZZRMException):
    """Error when parsing a ZZRM from a dictionary."""

    pass


class FileUsageType(str, Enum):
    """Classification of usage of files."""

    toplevel = "toplevel"
    ignore = "ignore"
    include = "include"
    append = "append"


class OrientationType(str, Enum):
    """Possible orientation types."""

    portrait = "portrait"
    landscape = "landscape"


class UserFile(BaseModel):
    """Representation of a file related information provided by users."""

    filename: str | None = None
    usage: FileUsageType | None = None
    orientation: OrientationType | None = None
    keep_comments: bool | None = None
    fontmaps: list[str] | None = None


class ZeroZeroReadMe:
    """Representation of 00README.json file."""

    def __init__(self, dir_or_file: str | None = None, version: int = 1):
        self.version: int = version  # classic 00README.XXX is v1, dict i/o is v2.
        self.readme_filename: str | None = None
        self.readme: list[str] | None = None
        self.process: MainProcessSpec = MainProcessSpec(compiler="pdflatex")
        self.sources: OrderedDict[str, UserFile] = OrderedDict()
        self.stamp: bool | None = True
        self.nohyperref: bool | None = None
        if dir_or_file is None:
            return
        elif os.path.isdir(dir_or_file):
            self.init_from_dir(dir_or_file)
        elif os.path.isfile(dir_or_file):
            self.init_from_file(dir_or_file)
        else:
            raise ZZRMFileNotFoundError(f"File {dir_or_file} not found")

    def to_dict(self) -> OrderedDict:
        """Representation of ZZRM as dictionary."""
        result: OrderedDict[str, typing.Any] = OrderedDict()
        result["process"] = self.process.model_dump(exclude_none=True, exclude_defaults=True)
        # the zzrm.process.compiler should be the compiler_string, not the actual object
        if self.process.compiler is not None:
            result["process"]["compiler"] = self.process.compiler.compiler_string
        if self.sources.keys():
            result["sources"] = []
            for k, v in self.sources.items():
                result["sources"].append(v.model_dump(exclude_none=True, exclude_defaults=True))
        if self.stamp is not None:
            result["stamp"] = self.stamp
        if self.nohyperref is not None:
            result["nohyperref"] = self.nohyperref
        return result

    def init_from_file(self, file: str) -> None:
        """
        Load a 00README file.

        POLICY:
        * only files named 00readme.EXT with EXT in either
          ZZRM_V1_EXTS or ZZRM_V2_EXTS are accepted.

        Raises:
            * ZZRMUnsupportedFileError if file name is not recognized.
        """
        stem, ext = os.path.splitext(os.path.basename(file))
        if stem.lower() != "00readme":
            raise ZZRMUnsupportedFileError(f"File {file} must start with 00readme (case-insensitive)")
        if ext.lower() in ZZRM_V1_EXTS:
            self._fetch_00readme_data(file, 1)
        elif ext.lower() in ZZRM_V2_EXTS:
            self._fetch_00readme_data(file, 2)
        else:
            raise ZZRMUnsupportedFileError(f"Unsupported file extension {ext}")

    def init_from_dir(self, in_dir: str) -> None:
        """
        Load the appropriate 00README file from a directory.

        POLICY:
        * only one ZZRM v2 is allowed, if multiple are detected, an exception will be raised.
        * only one ZZRM v1 is allowed, if multiple are detected, an exception will be raised.
        * if ZZRM v1 and ZZRM v2 is present, ZZRM v2 will be loaded.

        Arguments:
            in_dir {str} -- Directory to load the 00README file from.

        Raises:
            ZZRMMultipleFilesError: if multiple ZZRMs of the same level are detected.
        """
        files = sorted(os.listdir(in_dir))

        zzrms_v1: list[str] = []
        zzrms_v2: list[str] = []
        for filename in files:
            if filename[0] > "0":  # Should I use ord()?
                break
            (stem, ext) = os.path.splitext(filename)
            if stem.lower() != "00readme":
                continue
            if ext.lower() in ZZRM_V1_EXTS:
                zzrms_v1.append(filename)
            elif ext.lower() in ZZRM_V2_EXTS:
                zzrms_v2.append(filename)
            else:
                # ignore files that are named 00readme.SOMETHING but don't match
                # the correct extensions
                continue

        if len(zzrms_v2) > 1:
            raise ZZRMMultipleFilesError("Only one v2 00readme directives file is allowed.")
        elif len(zzrms_v2) > 0:
            self._fetch_00readme_data(os.path.join(in_dir, zzrms_v2[0]), 2)
            return

        if len(zzrms_v1) > 1:
            raise ZZRMMultipleFilesError("Only one v1 00readme directives file is allowed.")
        elif len(zzrms_v1) > 0:
            self._fetch_00readme_data(os.path.join(in_dir, zzrms_v1[0]), 1)
            return

    def _fetch_00readme_data(self, filename: str, version: int) -> None:
        read_data: str | None = None
        for enc in ["utf-8", "iso-8859-1"]:
            try:
                with open(filename, encoding=enc) as src:
                    read_data = src.read()
                    break
            except Exception:
                continue
        if read_data is None:
            return

        self.readme_filename = filename
        if version == 1:
            self._fetch_00readme_v1(read_data)
        elif version == 2:
            _, ext = os.path.splitext(filename)
            self._fetch_00readme_v2(read_data, ext)
        else:
            raise ZZRMUnsupportedVersion(f"Unknown version {version}")

    def _fetch_00readme_v1(self, data: str) -> None:
        """Read and parse 00README.XXX file."""
        self.readme = data.split("\n")

        self.version = 1
        for line in self.readme:
            idioms = [idiom for idiom in line.strip().split(" ") if idiom]
            if len(idioms) == 2:
                filename = idioms[0]
                keyword = idioms[1]
                userfile: UserFile = UserFile(filename=filename)
                # go over the possible entries in v1 00README files
                #   file toplevelfile
                #   file ignored
                #   file included
                #   file keepcomments
                #   file landscape
                #   file fontmap
                #   nostamp
                #   nohyperref
                if keyword == "ignore":
                    userfile.usage = FileUsageType.ignore
                elif keyword == "include":
                    # is this any different from "ignore" - I dont understand the difference on the explanation page
                    userfile.usage = FileUsageType.include
                elif keyword == "keepcomments":
                    userfile.keep_comments = True
                elif keyword == "landscape":
                    userfile.orientation = OrientationType.landscape
                elif keyword == "toplevelfile":
                    userfile.usage = FileUsageType.toplevel
                elif keyword == "append":
                    userfile.usage = FileUsageType.append
                elif keyword == "fontmap":
                    # fontmap in 00README.XXX is a global option
                    if self.process.fontmaps is None:
                        self.process.fontmaps = [filename]
                    else:
                        self.process.fontmaps.append(filename)
                    # make sure we don't add a userfile for a fontmap line
                    # since we added it to the global options
                    userfile = None  # type: ignore
                else:
                    raise ZZRMKeyError(keyword)
                if userfile is not None:
                    # no keys were set, the file is treated as a toplevel file
                    if (
                        userfile.keep_comments is None
                        and userfile.orientation is None
                        and userfile.usage is None
                        and userfile.fontmaps is None
                    ):
                        userfile.usage = FileUsageType.toplevel
                    self.sources[filename] = userfile

            elif len(idioms) == 1:
                if idioms[0] == "nostamp":
                    self.stamp = False
                elif idioms[0] == "nohyperref":
                    self.nohyperref = True

    def _fetch_00readme_v2(self, data: str, ext: str) -> None:
        """Read and parse 00README.XXX file, v2."""
        zzrm = None
        match ext:
            case ".yml" | ".yaml":
                loader = YAML()
                zzrm = loader.load(data)
            case ".json" | ".jsn" | ".ndjson":
                zzrm = json.loads(data)
            case ".toml":
                zzrm = toml.loads(data)
        if zzrm:
            self.version = 2
            self.from_dict(zzrm)

    def from_dict(self, zzrm: dict) -> None:
        """Initialize a ZZRM from a dictionary."""
        # print(zzrm)
        for k, v in zzrm.items():
            if k == "process":
                if isinstance(v, dict):
                    try:
                        self.process = MainProcessSpec(**v)
                    except ValidationError as e:
                        raise ZZRMParseError(f"Validation error on parsing: {e}")
                else:
                    raise ZZRMParseError("Value of process is not a dictionary")
            elif k == "sources":
                if isinstance(v, list):
                    self.sources = OrderedDict()
                    for vv in v:
                        try:
                            uf = UserFile(**vv)
                        except ValidationError as e:
                            raise ZZRMParseError(f"Validation error on parsing: {e}")
                        if uf.filename is None:
                            raise ZZRMParseError(f"Missing filename in UserFile: {vv}")
                        if (
                            uf.keep_comments is None
                            and uf.orientation is None
                            and uf.usage is None
                            and uf.fontmaps is None
                        ):
                            uf.usage = FileUsageType.toplevel
                        self.sources[uf.filename] = uf
                else:
                    raise ZZRMParseError(f"Value for sources is not a list[dict]: {type(v)}")
            elif k == "stamp":
                if isinstance(v, bool):
                    self.stamp = v
                else:
                    self.stamp = string_to_bool(v)
            else:
                raise ZZRMParseError(f"Invalid key for 00README: {k}")

    def find_metadata(self, filename: str) -> UserFile:
        """Get an instance of a SourceFileMeta from filename, and create one if it doesn't exist."""
        meta = self.sources.get(filename)
        if meta is None:
            meta = UserFile(filename=filename)
            self.sources[filename] = meta
        return meta

    def set_tex_compiler(self, tc: str) -> None:
        """Set TeX compiler."""
        self.process.compiler = CompilerSpec(compiler=tc)

    def is_landscape(self, testing: str) -> bool:
        """Landscape orientation - only cares the file stem unlike other predicates."""
        for filename, source in self.sources.items():
            if testing.lower() == filename.lower():
                return source.orientation == OrientationType.landscape
        return False

    def is_keep_comments(self, testing: str) -> bool:
        """Match the file stem for landscape orientation."""
        for filename, source in self.sources.items():
            if testing.lower() == filename.lower():
                if source.keep_comments:
                    return True
        return False

    def update_from_preflight(self, pf: PreflightResponse) -> bool:
        """Update ZZRM variables from Preflight response."""
        if not self.toplevels:
            for tlf in pf.detected_toplevel_files:
                if tlf.filename in self.sources:
                    # it cannot be a toplevel usage file, since we check
                    # for toplevel files above, so it must be either ignore etc
                    # Obey this indirection and ignore the PreFlight, we might
                    # have been wrong here
                    pass
                else:
                    uf = UserFile(filename=tlf.filename, usage=FileUsageType.toplevel)
                    self.sources[tlf.filename] = uf
        # if we still not have any toplevel files, because all files found by
        # Preflight have been marked as ignored/append etc, then bail out
        if not self.toplevels:
            return False
        # Now we are sure we have toplevel files set.
        # If no compiler is selected, select it based on the first toplevel file
        if self.process.compiler is None:
            self.process.compiler = CompilerSpec(
                engine=EngineType.unknown, lang=LanguageType.unknown, output=OutputType.unknown
            )
        if not self.process.compiler.is_determined:
            first_tex = self.toplevels[0]
            # search for first_tex in the detected toplevel files
            found_tlp: ToplevelFile | None = None
            for tlp in pf.detected_toplevel_files:
                if tlp.filename == first_tex:
                    found_tlp = tlp
                    break
            if not found_tlp:
                # Couldn't find selected file in list of toplevel files
                return False
            if self.process.compiler.engine == EngineType.unknown:
                if found_tlp.process.compiler is None or found_tlp.process.compiler.engine == EngineType.unknown:
                    self.process.compiler.engine = DEFAULT_ENGINE_TYPE
                else:
                    self.process.compiler.engine = found_tlp.process.compiler.engine
            if self.process.compiler.lang == LanguageType.unknown:
                if found_tlp.process.compiler is None or found_tlp.process.compiler.lang == LanguageType.unknown:
                    self.process.compiler.lang = DEFAULT_LANGUAGE_TYPE
                else:
                    self.process.compiler.lang = found_tlp.process.compiler.lang
            if self.process.compiler.output == OutputType.unknown:
                if found_tlp.process.compiler is None or found_tlp.process.compiler.output == OutputType.unknown:
                    self.process.compiler.output = DEFAULT_OUTPUT_TYPE
                else:
                    self.process.compiler.output = found_tlp.process.compiler.output
            if self.process.compiler.postp is None or self.process.compiler.postp == PostProcessType.unknown:
                if found_tlp.process.compiler is None or found_tlp.process.compiler.postp == PostProcessType.unknown:
                    self.process.compiler.postp = DEFAULT_POSTPROCESS_TYPE
                else:
                    self.process.compiler.postp = found_tlp.process.compiler.postp
        return True

    @property
    def is_ready_for_compilation(self) -> bool:
        """Check whether sufficient information is available for compilation."""
        if (
            self.toplevels  # at least one toplevel file
            and self.process.compiler  # compiler is defined
            and self.process.compiler.is_determined  # no unknown parts in engine/lang/output
        ):
            return True
        return False

    @property
    def is_supported_compiler(self) -> bool:
        """Check that we are ready for compilation and that the selected compiler is supported."""
        if (
            self.is_ready_for_compilation
            and self.process.compiler is not None
            and self.process.compiler.compiler_string is not None
        ):
            return True
        return False

    @property
    def toplevels(self) -> list[str]:
        """Returns the list of files marked as toplevel."""
        return [filename for filename, source in self.sources.items() if source.usage == FileUsageType.toplevel]

    @property
    def ignores(self) -> set[str]:
        """Returns the list of files marked as ignore."""
        return set([filename for filename, source in self.sources.items() if source.usage == FileUsageType.ignore])

    @property
    def includes(self) -> set[str]:
        """Returns the list of files marked as include."""
        return set([filename for filename, source in self.sources.items() if source.usage == FileUsageType.include])

    @property
    def fontmaps(self) -> list[str]:
        """Returns the list of fontmaps declared."""
        ret = [filename for filename, source in self.sources.items() if source.fontmaps]
        if self.process.fontmaps is not None:
            ret += self.process.fontmaps
        return sorted(ret)

    @property
    def nostamp(self) -> bool:
        """Returns whether stamping should not be done."""
        if self.stamp is None:
            return False
        else:
            return not self.stamp

    @property
    def landscapes(self) -> set[str]:
        """Returns a set of landscape designated files. Obsolete, do not use if possible. Use is_landscape instead."""
        return set(
            [filename for filename, source in self.sources.items() if source.orientation == OrientationType.landscape]
        )

    @property
    def keepcomments(self) -> set[str]:
        """Returns a set of keep_comments designated files. Obsolete, use is_keep_comments instead."""
        return set([filename for filename, source in self.sources.items() if source.keep_comments])

    @property
    def hyperref(self) -> bool:
        """Returns the value for hyperref setting (unsupported as of now)."""
        return not self.nohyperref

    @property
    def assembling_files(self) -> list[str]:
        """Compute list of assembling files."""
        assembly = []
        for fn, uf in self.sources.items():
            if uf.usage == FileUsageType.toplevel:
                # convert .tex to .pdf filename
                assembly.append(strip_to_basename(fn, ".pdf"))
            elif uf.usage == FileUsageType.include:
                assembly.append(fn)
        return assembly

    def to_yaml(self, output: typing.TextIO) -> typing.TextIO:
        """Provide YAML representation of ZZRM."""
        yaml = YAML()
        yaml.representer.add_representer(str, yaml_repr_str)
        yaml.representer.add_representer(OrderedDict, yaml_repr_ordered_dict)
        yaml.representer.add_representer(EngineType, yaml_repr_str)
        yaml.representer.add_representer(LanguageType, yaml_repr_str)
        yaml.representer.add_representer(OutputType, yaml_repr_str)
        yaml.representer.add_representer(PostProcessType, yaml_repr_str)
        yaml.representer.add_representer(FileUsageType, yaml_repr_str)
        yaml.representer.add_representer(OrientationType, yaml_repr_str)
        yaml.dump(self.to_dict(), output)
        return output

    def to_json(self, indent: int | None = 4) -> str:
        """Provide JSON representation of ZZRM."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_toml(self) -> str:
        """Provide TOML representation of ZZRM."""
        return tomli_w.dumps(self.to_dict())
