"""
TeX file patching for the Tex to PDF generation.

The primary motivation of this is, using Pygmentize for code highlighting, the package option
for first and second run of latex command needs to be changed.
For first run, the package option needs to write out the render output, and the second run
uses it. It is similar to .aux file but for package, there is no built-in mechanism to do so.

As a result, the package option needs to be changed for the first run, and then revert back.
I do not know how the webnode is doing this but as long as the submissions use the frozencache,
I see it not possible to genpdf withont patching the package option.
"""
import os
import re
import typing

from tex_inspection import TEX_FILE_EXTS

graphicspath_re = re.compile(r"\\graphicspath\{((\{.+?\})+)\}")
paths_re = re.compile(r'\{(.+?)\}')


def correct_graphicspath(line: str) -> str:
    # Find the \graphicspath command in the given content
    if not line.startswith("\\graphicspath"):
        return line
    match = graphicspath_re.search(line)
    if not match:
        return line  # No \graphicspath found, return original content
    paths_str = match.group(1)
    paths = paths_re.findall(paths_str)

    corrected_paths = []
    for path in paths:
        normalized_path = path
        if normalized_path.startswith("./"):
            normalized_path = normalized_path[2:]
        if not normalized_path.endswith("/"):
            corrected = normalized_path + "/"
            if corrected not in paths and corrected not in corrected_paths:
                corrected_paths.append(corrected)
                pass
            pass
        pass
    corrected_paths_str = ''.join(f'{{{path}}}' for path in corrected_paths)
    return f"\\graphicspath{{{corrected_paths_str}}}" + "\n"


def remove_auto_pst_pdf(line: str) -> str:
    """Remove auto-pst-pdf from the given line. This package runs latex, dvips, and ps2pdf.
    Not only this is unnecessary, this only works with shell escape, which is not allowed.
    """
    if line.find("auto-pst-pdf") != -1:
        if re.match(r"\\usepackage(?:\[(.*?)\])?\{\s*auto-pst-pdf\s*\}", line):
            return "%" + line
    return line


def set_overleafhome_and_homepath(line: str) -> str:
    """If you find a tex line setting \overleafhome, set \homepath as well
    """
    if line.find("\def\overleafhome{") != -1:
        matched = re.search(r"\\overleafhome\{([^}]*)\}", line)
        if matched:
            home = matched.group(1)
            return line + f"\\def\\homepath{{{home}}}\n"
    return line


def fix_tex_sources(in_dir: str,
                    fixers: list[typing.Callable]|None = None,
                    toplevels: list[str]|None = None) -> None:
    """Fix the tex sources in the given directory."""
    if toplevels is None:
        toplevels = os.listdir(in_dir)

    if fixers is None:
        fixers = [correct_graphicspath, remove_auto_pst_pdf, set_overleafhome_and_homepath]

    def fix_line(line: str) -> str:
        """Apply fixers to the given line."""
        for fixer in fixers:
            line = fixer(line)
            pass
        return line

    for filename in toplevels:
        [stem, fext] = os.path.splitext(filename)
        # really stinky special case for the .tex.txt file
        # if you find foo.tex.txt, rename it to foo.tex
        # seriously, apparently AutoTex does this? or maybe latex allows this?
        # I think we need to talk.
        if fext.lower() == ".txt":
            [_real_stem, fext_2] = os.path.splitext(stem)
            if fext_2.lower() in TEX_FILE_EXTS:
                os.rename(os.path.join(in_dir, filename), os.path.join(in_dir, stem))


    for parent_dir, dirs, files in os.walk(in_dir):
        for filename in files:
            [_stem, fext] = os.path.splitext(filename)
            if fext.lower() not in TEX_FILE_EXTS:
                continue
            with open(os.path.join(parent_dir, filename), encoding="iso-8859-1") as fd:
                original = fd.readlines()
                pass

            fixed = [fix_line(line) for line in original]
            # Count the number of lines that are changed
            changed = sum([0 if original[i] == fixed[i] else 1 for i in range(len(original))], 0)
            if changed:
                with open(os.path.join(parent_dir, filename), "w", encoding="iso-8859-1") as fd:
                    fd.writelines(fixed)
