"""
Inspect input tex files
"""
import os
import re
import stat
import typing
from ruamel.yaml import YAML

# Text file extensions
TEX_FILE_EXTS = [".tex", ".ltf", ".ltx", ".latex", ".txt"]

def file_props(filename: str) -> dict:
    """fstat the file and return the size and name."""
    if os.path.exists(filename):
        file_stat = os.stat(filename)
        file_mode = file_stat.st_mode
        base_name = os.path.basename(filename)
        if stat.S_ISREG(file_mode):
            return {"size": file_stat.st_size, "name": base_name}
        if stat.S_ISDIR(file_mode):
            return {"name": base_name, "is_dir": True}
        if stat.S_ISLNK(file_mode):
            return {"name": base_name, "is_link": True}
        return {"mode": repr(file_mode), "name": base_name}
    return {"size": None, "name": os.path.basename(filename)}


def file_props_in_dir(a_dir: str) -> list:
    """Runs the file prots to each file in a directory."""
    return [file_props(os.path.join(a_dir, filename)) for filename in os.listdir(a_dir)]


def catalog_files(root_dir: str) -> dict[str, typing.Any]:
    """
    catalog the files in the root_dir
    """
    catalog = {}
    for a_dir, _dirs, files in os.walk(root_dir):
        for filename in files:
            filepath = os.path.join(a_dir, filename)
            catalog[filepath[len(root_dir)+1:]] = file_props(filepath)
            pass
        pass
    return catalog



def test_file_extent(filename: str, exts: list | dict, no_ext: str | None = None) -> None | str:
    """Test if the filename ends with any of the extensions."""
    ext = os.path.splitext(filename)[1]
    if not ext and no_ext is not None:
        ext = no_ext
        filename = filename + no_ext
        pass
    return filename if ext.lower() in exts else None



class BadBib(Exception):
    """Cannot find bib file"""
    pass


class ZeroZeroReadMe:
    """Representation of 00README.XXX file"""

    readme: typing.List[str] | None
    ignores: set[str]
    includes: set[str]
    toplevels: list[str]
    landscapes: set[str]
    keepcomments: set[str]
    fontmaps: set[str]
    nohyperref: bool
    nostamp: bool

    def __init__(self, in_dir: str | None = None):
        self.readme = None
        self.ignores = set()
        self.includes = set()
        self.toplevels = []  # should preserve the order
        self.landscapes = set()
        self.keepcomments = set()
        self.fontmaps = set()
        self.nohyperref = False
        self.nostamp = False
        if in_dir:
            # If there are 00README.XXX and 00readme.xxx, 00README.XXX is used.
            for filename in sorted(os.listdir(in_dir)):
                if filename[0] > '0':  # Should I use ord()?
                    break
                if filename.upper() == "00README.XXX":
                    self.fetch_00readme(os.path.join(in_dir, filename))
                    break
                pass
            pass
        pass

    def __bool__(self) -> bool:
        """Return True if 00README.XXX is fetched"""
        return self.readme is not None

    def fetch_00readme(self, filename: str) -> None:
        """Read and parse 00README.XXX file"""

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
            idioms = [idiom for idiom in line.strip().split(' ') if idiom]
            if len(idioms) == 2:
                match idioms[1]:
                    case "ignore":
                        self.ignores.add(idioms[0])
                    case "include":
                        self.includes.add(idioms[0])
                    case "toplevelfile":
                        # may need to check the file extension
                        self.toplevels.append(idioms[0])
                    case "landscape":
                        self.landscapes.add(idioms[0])
                    case "keepcomments":
                        self.keepcomments.add(idioms[0])
                    case "fontmap":
                        name = idioms[0]
                        if name.endswith(".map"):
                            name = name[:-4]
                        if re.match(r"[A-Za-z]+", name):
                            self.fontmaps.add(idioms[0])
            elif len(idioms) == 1:
                if idioms[0] == "nostamp":
                    self.nostamp = True
                elif idioms[0] == "nohyperref":
                    self.nohyperref = True


def maybe_bbl(tex: str, in_dir: str) -> str | None:
    """Look for .bbl file"""
    maybe_bbl_file = os.path.splitext(tex)[0] + ".bbl"
    if os.path.exists(os.path.join(in_dir, maybe_bbl_file)):
        return maybe_bbl_file
    return None


def find_primary_tex(in_dir: str, zzrm: ZeroZeroReadMe) -> typing.List[str]:
    """Find the document tex file in the directory

    - If there is only one .tex file, it is the main tex file.
    - If there are multiple .tex files, look for the first \\documentclass line in it.

    If none of the above, return None.

    The order of tex file is alphabetical order, and then treated with zzr top-levels.
    """

    losers = zzrm.ignores | zzrm.includes
    #loser_re_1 = re.compile(r'\\input\{([^}]+)}')
    #loser_re_2 = re.compile(r'\\input\s+(.+)')

    round_0: typing.Set[str] = set()
    round_1: typing.Set[str] = set()

    for filename in os.listdir(in_dir):
        # Make sure it is a file
        if not os.path.isfile(os.path.join(in_dir, filename)):
            continue
        if test_file_extent(filename, TEX_FILE_EXTS):
            round_0.add(filename)

    if len(round_0) <= 1:
        return list(round_0)

    normalized_texs = {os.path.splitext(filename)[0].lower(): filename for filename in round_0}

    for tex_file in round_0:
        maybe_banned = maybe_banned_tex_file(tex_file)
        with open(os.path.join(in_dir, tex_file), encoding='iso-8859-1') as srcfd:
            lines = srcfd.readlines()
        maybe_losers: typing.Set[str] = set()
        for line_no, line in enumerate(lines):
            if maybe_banned:
                if is_banned_tex(tex_file, line):
                    if tex_file in round_1:
                        round_1.remove(tex_file)  # I am banned!
                    losers.add(tex_file)
                    maybe_losers.clear()  # no loger losers
                    break
            stripped = line.strip()
            if stripped.startswith(r"\begin{document}"):
                round_1.add(tex_file)

            if stripped.startswith(r'\input'):
                # ln.strip()+" " - replace the \r or \n with space so that it delimits the \input.
                loser = find_tex_input("".join([ln.strip()+" " for ln in lines[line_no:line_no+3]]))
                if loser:
                    round_1.add(tex_file)  # I'm the winner!
                    [loser_stem, loser_ext] = os.path.splitext(loser)
                    # getting the loser file from normalized_texs should find one always but
                    # since I can guess it easily, I'll give it as a default just in case.
                    if loser_ext == "" or loser_ext in TEX_FILE_EXTS:
                        loser = normalized_texs.get(loser_stem.lower(),
                            test_file_extent(loser, TEX_FILE_EXTS, no_ext=".tex"))
                        if loser:
                            maybe_losers.add(loser)
            if stripped.startswith(r"\usepackage"):
                for pname in pick_package_names(stripped):
                    normalized_pkg = normalized_texs.get(pname.lower(),
                        test_file_extent(pname, TEX_FILE_EXTS, no_ext=".tex"))
                    if normalized_pkg:
                        maybe_losers.add(normalized_pkg)
        losers |= maybe_losers
    # End of round 1

    round_2 = sorted([tex_file for tex_file in round_1 if tex_file not in losers],
                     key=lambda x: x.lower())

    # If it manages to include multiple tex files with conflicting names, let TEX_FILE_EXTS
    # decide the winner.
    round_3: typing.Set[str] = set()
    stem_dupes: typing.Dict[str, typing.List[str]]  = {}
    for tex_file in round_2:
        [stem, _ext] = os.path.splitext(tex_file.lower())
        if stem not in stem_dupes:
            stem_dupes[stem] = []
        stem_dupes[stem].append(tex_file)

    for conflicts in stem_dupes.values():
        texs = sorted(conflicts,
                      key=lambda x: TEX_FILE_EXTS.index(os.path.splitext(x.lower())[1]),
                      reverse=True)
        round_3.add(texs[0])

    #
    round_3s = sorted([tex_file for tex_file in round_3], key=lambda x: x.lower())

    return [tex_file for tex_file in zzrm.toplevels if tex_file in round_3s] + \
        [tex_file for tex_file in round_3s if not tex_file in zzrm.toplevels]


def is_bib(tex_filename: str) -> bool:
    """Check if the tex file is a bib file"""
    bib_line_re = re.compile(r"\s*\\(bib\s*\(\s*\w+\s*\)|bibitem\s*{[^}]+})")
    try:
        with open(tex_filename, encoding='iso-8859-1') as src:
            for line in src.readlines():
                if line and line[0] == "%":
                    continue
                if line.find("\\bib") >= 0:  # faster than regex
                    if bib_line_re.search(line):
                        break
            else:
                return False
            pass
        pass
    except Exception as exc:
        raise BadBib(f"Failed to read {os.path.basename(tex_filename)} due to {str(exc)}") from exc
    return True


def find_tex_thing(tex_line: str, pattern: re.Pattern, needles: typing.List[str]) -> str | None:
    """Find a thing in a tex file"""
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


def pick_package_names(tex_line: str) -> typing.List[str]:
    """Pick up a package name from a tex line"""
    using = find_tex_thing(tex_line, package_name_picker_re, ["\\RequirePackage", "\\usepackage"])
    if using:
        return [package.strip() for package in using.split(",") if package.strip()]
    return []


includegraphics_re = re.compile(r'\\includegraphics(?:\[.*?])?\{([^}]+)}')


def find_include_graphics_filename(tex_line: str) -> str | None:
    """Find a file name in a tex line"""
    return find_tex_thing(tex_line, includegraphics_re, ["\\includegraphics"])


def read_ban_data(ban_list_file: str | None = None) -> typing.Any:
    """Read the ban data from the YAML file."""
    if ban_list_file is None:
        ban_list_file = os.path.join(os.path.dirname(__file__), "banned_tex.yaml")
    if os.path.exists(ban_list_file):
        yaml = YAML()
        with open(ban_list_file, "r", encoding="utf-8") as fd:
            return yaml.load(fd)
    # Return a stub and don't die
    return {"ban_list": []}


def get_banned_tex_file_data() -> typing.Any:
    """Get the banned tex file data"""
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
    """Is this TeX file blacklisted?"""
    ban_data = get_banned_tex_file_data()
    for ban in ban_data["ban_list"]:
        condition = ban["condition"].get("filename", {})
        if decide_ban(condition, filename):
            return True
        pass
    return False

def is_banned_tex_line(line: str) -> bool:
    """Is this TeX line blacklisted? Use this only when maybe_banned_tex_file() returns True. """
    ban_data = get_banned_tex_file_data()
    for ban in ban_data["ban_list"]:
        condition = ban["condition"].get("line", {})
        if decide_ban(condition, line):
            return True
        pass
    return False


def is_banned_tex(filename: str, line: str) -> bool:
    """Is this TeX file blacklisted?
    First, check if the filename is blacklisted. if yes, make sure the file contains
    the bad line. Return True if both conditions are met.
    """
    ban_data = get_banned_tex_file_data()
    for ban in ban_data["ban_list"]:
        if decide_ban(ban["condition"].get("filename", {}), filename) and \
            decide_ban(ban["condition"].get("line", {}), line):
            return True
        pass
    return False


def is_vanilla_tex_line(line: str)-> bool:
    """Check if the line is a vanilla tex line"""
    return line.find('\\special') >= 0


def is_pdftex_line(line: str)-> bool:
    """Check if the line is a pdftex line"""
    # return line.startswith('\\def\\') or line.startswith('\\pageno=')
    return line.startswith('\\pageno=')


def is_pdflatex_line(line: str)-> bool:
    """Check if the line is a pdftex line"""
    # Do not check for \usepackage since etex allows
    # \beginpackages
    #    \usepackage{...}
    # \endpackages
    # return line.startswith('\\documentclass') or line.startswith('\\usepackage')
    return line.startswith('\\documentclass')


_tex_input_1 = re.compile(r'\\input\{([^}]+)}')
_tex_input_2 = re.compile(r'\\input\s+([^\x00-\x1F\x7F/\s\r\n]+)')


def find_tex_input(input_line: str) -> str | None:
    """Find a file name in a tex line"""
    if input_line.find("\\input") < 0:
        return None

    for tex_input_re in [_tex_input_1, _tex_input_2]:
        tex_input_match = tex_input_re.search(input_line)
        if tex_input_match:
            return tex_input_match.group(1).strip()
    return None


def find_used_files(tex_files: typing.List[str]) -> set[str]:
    """Find used files in the given tex files"""
    used_files = set(tex_files)

    scoopers = [find_tex_input, find_include_graphics_filename]
    for tex_file in tex_files:
        with open(tex_file, "r", encoding="iso-8859-1") as fd:
            lines = fd.readlines()
            pass

        for lineno, line in enumerate(lines):
            for scooper in scoopers:
                multiline = "".join([ln.strip() for ln in lines[lineno:lineno+2]])
                used = scooper(multiline)
                if used:
                    used_files.add(used)
                    break
    return used_files


def find_unused_toplevel_files(in_dir: str, tex_files: typing.List[str]) -> typing.Set[str]:
    """Find unused files in the given tex files"""
    in_dir_files = set(os.listdir(in_dir))
    used_files = find_used_files([os.path.join(in_dir, tex_file) for tex_file in tex_files])
    unused_files = in_dir_files - used_files
    return unused_files


def find_pdfoutput_1(tex_file: str, in_dir: str) -> bool:
    """Find the \pdfoutput=1 marker"""
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
            with open(tex_file, encoding='iso-8859-1') as src:
                for line in src.readlines():
                    if line.strip()[0:1] == "%":
                        continue
                    if line.find("\\pdfoutput") >= 0:
                        if re.search(r'\\pdfoutput\s*=\s*1', line):
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
