"""00README file parsing and handling."""

import json
import os
import typing
from collections import OrderedDict
from enum import Enum

import toml
import tomli_w
from preflight_parser import (
    CompilerSpec,
    EngineType,
    LanguageType,
    MainProcessSpec,
    OutputType,
    ParseSyntaxError,
    PostProcessType,
    string_to_bool,
)
from pydantic import BaseModel
from ruamel.yaml import YAML, MappingNode, ScalarNode
from ruamel.yaml.representer import RoundTripRepresenter

# 00README file extensions - earlier wins
ZZRM_EXTS = [".yml", ".yaml", ".json", ".jsn", ".ndjson", ".toml", ".xxx"]


def yaml_repr_str(dumper: RoundTripRepresenter, data: str) -> ScalarNode:
    """Convert string to yaml representation."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def yaml_repr_ordered_dict(dumper: RoundTripRepresenter, data: OrderedDict) -> MappingNode:
    """Convert ordered dict to yaml representation."""
    return dumper.represent_mapping("tag:yaml.org,2002:map", dict(data))


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

    readme: list[str] | None
    readme_filename: str | None
    version: int
    compilation: MainProcessSpec
    sources: OrderedDict[str, UserFile]
    stamp: bool | None
    nohyperref: bool | None

    def __init__(self, in_dir: str | None = None, version: int = 1):  # noqa: D107
        self.version = version  # classic 00README.XXX is v1, dict i/o is v2.
        self.readme_filename = None
        self.readme = None
        self.compilation = MainProcessSpec(compiler="pdflatex")
        self.sources = OrderedDict()
        self.stamp = True
        if in_dir:
            self.intern_00readme(in_dir)

    def to_dict(self) -> OrderedDict:
        """Representation of ZZRM as dictionary."""
        result = OrderedDict()
        result["compilation"] = self.compilation.model_dump(exclude_none=True, exclude_defaults=True)
        # the zzrm.compilation.compiler should be the compiler_string, not the actual object
        result["compilation"]["compiler"] = self.compilation.compiler.compiler_string
        if self.sources.keys():
            result["sources"] = []
            for k, v in self.sources.items():
                result["sources"].append(v.model_dump(exclude_none=True, exclude_defaults=True))
        if self.stamp is not None:
            result["stamp"] = self.stamp
        if self.nohyperref is not None:
            result["nohyperref"] = self.nohyperref
        return result

    def intern_00readme(self, in_dir: str) -> None:
        """Read 00README.XXX v1 format and populate values."""
        # If there are 00README.XXX and 00readme.xxx, 00README.XXX is used.
        files = sorted(os.listdir(in_dir))

        zzrms: list[tuple[str, str, str]] = []
        for filename in files:
            if filename[0] > "0":  # Should I use ord()?
                break
            (stem, ext) = os.path.splitext(filename)
            if stem.lower() != "00readme":
                continue
            zzrms.append((stem, ext, filename))

        def ext_order(zz: tuple[str, str, str]) -> int:
            try:
                return ZZRM_EXTS.index(zz[1])
            except ValueError:
                pass
            return len(ZZRM_EXTS) + 1000  # Any positive integer would work

        if len(zzrms) > 0:
            if len(zzrms) > 1:
                zzrm = sorted([zz for zz in zzrms if zz[1] in ZZRM_EXTS], key=ext_order)[0]
            else:
                zzrm = zzrms[0]
            stem, ext, filename = zzrm
            match ext.lower():
                case ".xxx":
                    self.fetch_00readme(os.path.join(in_dir, filename))
                case ".yml" | ".yaml" | ".json" | ".jsn" | ".ndjson" | ".toml":
                    self.fetch_00readme_v2(os.path.join(in_dir, filename))

            # TODO determine compilation defaults
            # this is by now not possible, since we cannot do the AutoTeX thing
            # it needs the change that compiling old submissions are sent
            # to the autotex/tex2pdf container

    def fetch_00readme(self, filename: str) -> None:
        """Read and parse 00README.XXX file."""
        self.readme_filename = filename
        for enc in ["utf-8", "iso-8859-1"]:
            try:
                with open(filename, encoding=enc) as src:
                    self.readme = src.readlines()
                break
            except Exception:
                continue
        if self.readme is None:
            return

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
                    if self.compilation.fontmaps is None:
                        self.compilation.fontmaps = [filename]
                    else:
                        self.compilation.fontmaps.append(filename)
                    # make sure we don't add a userfile for a fontmap line
                    # since we added it to the global options
                    userfile = None  # type: ignore
                else:
                    raise KeyError(keyword)
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

    def fetch_00readme_v2(self, filename: str) -> None:
        """Read and parse 00README.XXX file, v2."""
        stem, ext = os.path.splitext(filename)
        zzrm = None
        match ext:
            case ".yml" | ".yaml":
                loader = YAML()
                with open(filename, "rb") as fd:
                    zzrm = loader.load(fd)
            case ".json" | ".jsn" | ".ndjson":
                with open(filename, "rb") as fd:
                    zzrm = json.load(fd)
            case ".toml":
                zzrm = toml.load(filename)
        if zzrm:
            # print(zzrm)
            self.readme_filename = filename
            self.version = 2
            for k, v in zzrm.items():
                if k == "compilation":
                    if isinstance(v, dict):
                        self.compilation = MainProcessSpec(**v)
                    else:
                        raise ParseSyntaxError("Value of compilation is not a dictionary")
                elif k == "sources":
                    if isinstance(v, list):
                        self.sources: OrderedDict[str, UserFile] = OrderedDict()
                        for vv in v:
                            uf = UserFile(**vv)
                            if uf.filename is None:
                                raise ParseSyntaxError(f"Missing filename in UserFile: {vv}")
                            if (
                                uf.keep_comments is None
                                and uf.orientation is None
                                and uf.usage is None
                                and uf.fontmaps is None
                            ):
                                uf.usage = FileUsageType.toplevel
                            self.sources[uf.filename] = uf
                    else:
                        raise ParseSyntaxError(f"Value for sources is not a list[dict]: {type(v)}")
                elif k == "stamp":
                    if isinstance(v, bool):
                        self.stamp = v
                    else:
                        self.stamp = string_to_bool(v)
                else:
                    raise ParseSyntaxError(f"Invalid key for 00README: {k}")

    def find_metadata(self, filename: str) -> UserFile:
        """Get an instance of a SourceFileMeta from filename, and create one if it doesn't exist."""
        meta = self.sources.get(filename)
        if meta is None:
            meta = UserFile(filename=filename)
            self.sources[filename] = meta
        return meta

    def set_tex_compiler(self, tc: str) -> None:
        """Set TeX compiler."""
        self.compilation.compiler = CompilerSpec(compiler=tc)

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
        if self.compilation.fontmaps is not None:
            ret += self.compilation.fontmaps
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
    def nohyperref(self) -> bool:
        """Returns the value for nohyperref setting (unsupported as of now)."""
        return self.nohyperref

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
                assembly.append(fn)
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
