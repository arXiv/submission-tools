"""Inspect input tex files."""

import os
import re
import typing

from ruamel.yaml import YAML

# Text file extensions
TEX_FILE_EXTS = [".tex", ".ltf", ".ltx", ".latex", ".txt"]


def maybe_bbl(tex: str, in_dir: str) -> str | None:
    """Look for .bbl file."""
    maybe_bbl_file = os.path.splitext(tex)[0] + ".bbl"
    if os.path.exists(os.path.join(in_dir, maybe_bbl_file)):
        return maybe_bbl_file
    return None


def find_tex_thing(tex_line: str, pattern: re.Pattern, needles: list[str]) -> str | None:
    """Find a thing in a tex file."""
    tex_line = tex_line.strip()
    if tex_line[0:1] == "%":
        return None
    for needle in needles:
        if tex_line.find(needle) >= 0:
            break
    else:
        return None
    maybe_thing = pattern.search(tex_line)
    return maybe_thing.group(1) if maybe_thing else None


package_name_picker_re = re.compile(r"\\(?:RequirePackage|usepackage)(?:\[.*?])?\{([^}]+)}")


includegraphics_re = re.compile(r"\\includegraphics(?:\[.*?])?\{([^}]+)}")


def find_include_graphics_filename(tex_line: str) -> str | None:
    """Find a file name in a tex line."""
    return find_tex_thing(tex_line, includegraphics_re, ["\\includegraphics"])


def read_ban_data(ban_list_file: str | None = None) -> typing.Any:
    """Read the ban data from the YAML file."""
    if ban_list_file is None:
        ban_list_file = os.path.join(os.path.dirname(__file__), "banned_tex.yaml")
    if os.path.exists(ban_list_file):
        yaml = YAML()
        with open(ban_list_file, encoding="utf-8") as fd:
            return yaml.load(fd)
    # Return a stub and don't die
    return {"ban_list": []}


def get_banned_tex_file_data() -> typing.Any:
    """Get the banned tex file data."""
    return globals().get("_banned_tex_file_data_", read_ban_data())


def decide_ban(condition: dict, target: str) -> bool:
    """Decide if the target string is banned.

    the condition can be one of the following:
    - startswith
    - endswith
    - contains
    - equals
    - regex
    """
    if condition.get("startswith"):
        return target.startswith(condition["startswith"])

    if condition.get("endswith"):
        return target.endswith(condition["endswith"])

    if condition.get("contains"):
        return condition["contains"] in target

    if condition.get("equals"):
        return bool(condition["equals"] == target)

    if condition.get("regex"):
        return re.match(condition["regex"], target) is not None

    return False


def maybe_banned_tex_file(filename: str) -> bool:
    """Test whether this TeX file is blacklisted."""
    ban_data = get_banned_tex_file_data()
    for ban in ban_data["ban_list"]:
        condition = ban["condition"].get("filename", {})
        if decide_ban(condition, filename):
            return True
        pass
    return False


def is_banned_tex_line(line: str) -> bool:
    """Test whether this TeX line is blacklisted? Use this only when maybe_banned_tex_file() returns True."""
    ban_data = get_banned_tex_file_data()
    for ban in ban_data["ban_list"]:
        condition = ban["condition"].get("line", {})
        if decide_ban(condition, line):
            return True
        pass
    return False


def is_banned_tex(filename: str, line: str) -> bool:
    """Test whether this TeX file is blacklisted.

    First, check if the filename is blacklisted. if yes, make sure the file contains
    the bad line. Return True if both conditions are met.
    """
    ban_data = get_banned_tex_file_data()
    for ban in ban_data["ban_list"]:
        if decide_ban(ban["condition"].get("filename", {}), filename) and decide_ban(
            ban["condition"].get("line", {}), line
        ):
            return True
        pass
    return False


def is_vanilla_tex_line(line: str) -> bool:
    """Check if the line is a vanilla tex line."""
    return line.find("\\special") >= 0


_tex_input_1 = re.compile(r"\\input\{([^}]+)}")
_tex_input_2 = re.compile(r"\\input\s+([^\x00-\x1F\x7F/\s\r\n]+)")


def find_tex_input(input_line: str) -> str | None:
    """Find a file name in a tex line."""
    if input_line.find("\\input") < 0:
        return None

    for tex_input_re in [_tex_input_1, _tex_input_2]:
        tex_input_match = tex_input_re.search(input_line)
        if tex_input_match:
            return tex_input_match.group(1).strip()
    return None


def find_used_files(tex_files: list[str]) -> set[str]:
    """Find used files in the given tex files."""
    used_files = set(tex_files)

    scoopers = [find_tex_input, find_include_graphics_filename]
    for tex_file in tex_files:
        with open(tex_file, encoding="iso-8859-1") as fd:
            lines = fd.readlines()
            pass

        for lineno, line in enumerate(lines):
            for scooper in scoopers:
                multiline = "".join([ln.strip() for ln in lines[lineno : lineno + 2]])
                used = scooper(multiline)
                if used:
                    used_files.add(used)
                    break
    return used_files


def find_unused_toplevel_files(in_dir: str, tex_files: list[str]) -> set[str]:
    """Find unused files in the given tex files."""
    in_dir_files = set(os.listdir(in_dir))
    used_files = find_used_files([os.path.join(in_dir, tex_file) for tex_file in tex_files])
    unused_files = in_dir_files - used_files
    return unused_files


def find_pdfoutput_1(tex_file: str, in_dir: str) -> bool:
    r"""Find the \pdfoutput=1 marker."""
    sources = [tex_file]
    checked = set()
    while sources:
        source = sources.pop(0)
        if source in checked:
            continue
        checked.add(source)
        tex_file = os.path.join(in_dir, source)
        if not os.path.exists(tex_file):
            continue
        try:
            with open(tex_file, encoding="iso-8859-1") as src:
                for line in src.readlines():
                    if line.strip()[0:1] == "%":
                        continue
                    if line.find("\\pdfoutput") >= 0:
                        if re.search(r"\\pdfoutput\s*=\s*1", line):
                            return True
                    related_input = find_tex_input(line)
                    if related_input:
                        r_stem, r_ext = os.path.splitext(related_input)
                        if r_ext == "":
                            related_input = related_input + ".tex"
                            pass
                        if source not in checked:
                            sources.append(related_input)
                            pass
                        pass
                    pass
                pass
        except Exception as _exc:
            pass
        pass
    return False
