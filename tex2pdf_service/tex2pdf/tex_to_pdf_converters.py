"""
This module is the core of the PDF generation. It takes a tarball, unpack it, and generate PDF.
"""
import copy
import os
import subprocess
import shlex
import time
import typing
from abc import abstractmethod
from tex2pdf import file_props, local_exec, file_props_in_dir, \
    MAX_LATEX_RUNS, ID_TAG, test_file_extent, MAX_TIME_BUDGET
from tex2pdf.service_logger import get_logger
from tex_inspection import (pick_package_names, ZeroZeroReadMe, is_pdftex_line,
                            is_pdflatex_line, find_pdfoutput_1, TEX_FILE_EXTS)
from .log_inspection import inspect_log

WITH_SHELL_ESCAPE = False


class NoTexFile(Exception):
    """No tex file found in the tarball"""
    pass


class RunFail(Exception):
    """pdflatex/bibtex run failed"""
    pass


class ImplementationError(Exception):
    """Bug!?"""
    pass


class BaseConverter:
    """Base class for tex-to-pdf converters.
    """
    conversion_tag: str
    runs: typing.List[dict]  # Each run generates an output
    log: str
    log_extra: dict
    use_addon_tree: bool
    zzrm: ZeroZeroReadMe | None
    init_time: float
    max_time_budget: float
    stem: str

    def __init__(self, conversion_tag: str, use_addon_tree: bool = False, zzrm: ZeroZeroReadMe | None = None,
                 max_time_budget: float | None = None, init_time: float | None = None):
        self.conversion_tag = conversion_tag
        self.use_addon_tree = use_addon_tree
        self.zzrm = zzrm
        self.runs = []
        self.log = ""
        self.log_extra = {ID_TAG: self.conversion_tag}
        self.init_time = time.perf_counter() if init_time is None else init_time
        try:
            default_max = float(MAX_TIME_BUDGET)
        except:
            default_max = 595
            pass
        self.max_time_budget = default_max if max_time_budget is None else max_time_budget
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler """
        return "Unknown"


    def time_left(self) -> float:
        """Returns the time left before the timeout"""
        return self.max_time_budget - (time.perf_counter() - self.init_time)

    @classmethod
    def decline_file(cls, _tex_file: str, _parent_dir: str) -> typing.Tuple[bool, str]:
        """Decline the file if the converter cannot handle it"""
        return True, "The base class has no capability to handle any file"

    @classmethod
    def decline_tex(cls, _tex_line: str, _line_number: int) -> typing.Tuple[bool, str]:
        """Decline the tex line if the converter cannot handle it"""
        return True, "The base class has no capability to handle any file"

    def is_internal_converter(self) -> bool:
        """If the converter is internal, the work dir needs cleanup."""
        return True

    @abstractmethod
    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF from the given tex file. Return the outcome dict."""
        pass

    @abstractmethod
    def _latexen_run(self, step: str, tex_file:str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Run the base engine of the converter."""
        pass

    def _run_base_engine_necessary_times(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str, base_format: str) -> dict:
        stem = os.path.splitext(tex_file)[0]
        self.stem = stem
        stem_pdf = f"{stem}.pdf"
        outcome: dict[str, typing.Any] = {"pdf_file": f"{stem_pdf}"}
        # first run
        step = "first_run"
        run = self._latexen_run(step, tex_file, work_dir, in_dir, out_dir)
        output_size = run[base_format]["size"]
        if output_size is None:
            outcome.update({"status": "fail", "step": step,
                            "reason": f"failed to create {base_format}", "runs": self.runs})
            return outcome

        # if DVI/PDF is generated, rerun for TOC and references
        # We had already one run, run it at most MAX_LATEX_RUNS - 1 times again
        for iteration in range(MAX_LATEX_RUNS - 1):
            step = f"second_run:{iteration}"
            run = self._latexen_run(step, tex_file, work_dir, in_dir, out_dir)
            # maybe PDF/DVI creating fails on second run, so check output size again
            output_size = run[base_format]["size"]
            if output_size is None:
                outcome.update({"status": "fail", "step": step,
                                "reason": f"failed to create {base_format}", "runs": self.runs})
                return outcome
            # return code is not a good indication, unfortunately.
            # status = "success" if run["return_code"] == 0 else "fail"
            for line in run["log"].splitlines():
                if line.find(rerun_needle) >= 0:
                    # Need retry
                    status = "fail"
                    break
            else:
                status = "success"
            run["iteration"] = iteration
            outcome.update({"runs": self.runs, "status": status, "step": step})
            if status == "success":
                break

        return outcome


    def _exec_cmd(self, args: typing.List[str], child_dir: str, work_dir: str,
                  extra: dict | None = None) -> typing.Tuple[dict[str, typing.Any], str, str]:
        """Run the command and return the result"""
        logger = get_logger()
        worker_args = self.decorate_args(args)
        extra = self.log_extra if extra is None else self.log_extra | extra
        homedir = os.environ["HOME"]
        # I think it is a bad idea to be able to sudo.
        # if become_worker:
        #     worker_args = ["sudo", "-H", "-u", "worker", "--chdir", work_dir,
        #                    "--chroot", "/workroot", "-n",  "--"] + args
        #     homedir = "/home/worker"
        #     pass
        args_str = shlex.join(worker_args)
        timestamp0 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        extra["timestamp"] = timestamp0
        logger.debug("Process args: %s", args_str, extra=extra)
        t0 = time.perf_counter()
        # noinspection PyPep8Naming
        # pylint: disable=PyPep8Naming
        PATH = f"{homedir}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin:/sbin"
        # SECRETS or GOOGLE_APPLICATION_CREDENTIALS is not defined at all at this point but
        # be defensive and squish it anyway.
        #
        # These variables make the tex logging to line-fold at very long positions.
        # "max_print_line": "4096"
        # "error_line": "254"
        # "half_error_line": "238"
        cmdenv = {"WORKDIR": work_dir, "SECRETS": "?", "GOOGLE_APPLICATION_CREDENTIALS": "?",
                  "PATH": PATH, "HOME": homedir,
                  "max_print_line": "4096", "error_line": "254", "half_error_line": "238"}
        # support SOURCE_DATE_EPOCH and FORCE_SOURCE_DATE set in the environment
        for senv in ["SOURCE_DATE_EPOCH", "FORCE_SOURCE_DATE"]:
            if os.getenv(senv):
                cmdenv[senv] = os.getenv(senv, "") # the "" is only here to placate mypy :-(
        # get location of addon trees
        if self.use_addon_tree:
            kpsewhich = self.decorate_args(["/usr/bin/kpsewhich", "-var-value", "SELFAUTOPARENT"])
            sap = subprocess.run(kpsewhich, capture_output=True, text=True).stdout.rstrip()
            addon_tree = os.path.join(sap, "texmf-arxiv")
            cmdenv["TEXMFAUXTREES"] = addon_tree + "," # we need a final comma!
        with subprocess.Popen(worker_args, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                              cwd=child_dir, encoding='iso-8859-1', env=cmdenv) as child:
            process_completion = False
            try:
                timeout_value = self.time_left()
                (out, err) = child.communicate(timeout=timeout_value)
                process_completion = True
            except subprocess.TimeoutExpired:
                logger.warning("Process timeout %s", shlex.join(worker_args), extra=extra)
                child.kill()
                (out, err) = child.communicate()
                pass
            elapse_time = time.perf_counter() - t0
            timestamp1 = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            run = {"args": args, "stdout": out, "stderr": err,
                   "return_code": child.returncode,
                   "run_env": cmdenv,
                   "start_time": timestamp0, "end_time": timestamp1,
                   "elapse_time": elapse_time,
                   "process_completion": process_completion,
                   "PATH": PATH}
            pass
        extra.update({"run": run})
        logger.debug(f"Exec result: return code: {run['return_code']}", extra=extra)
        return run, out, err

    def _report_run(self, run: dict, out: str, err: str, step: str, in_dir: str, out_dir: str,
                    output_tag: str, output_file: str) -> None:
        """standard command run reporting to the run-dict, and append it to the runs."""
        logger = get_logger()
        out_stat = file_props(output_file)
        out_size = out_stat["size"]
        run.update({"step": step, ID_TAG: self.conversion_tag,
                    "in_files": file_props_in_dir(in_dir),
                    "out_files": file_props_in_dir(out_dir),
                    output_tag: out_stat})
        self.runs.append(run)
        logger.debug(f"{step} result: return code: {run['return_code']}",
                     extra={ID_TAG: self.conversion_tag, "step": step, "run": run})

        if err or out_size is None:
            logger.warning(f"{step}: {output_tag} size = {str(out_size)} - {str(err)}",
                           extra={ID_TAG: self.conversion_tag, "step": step,
                                  "stdout": out, "stderr": err})
            pass

        pass

    def fetch_log(self, log_file: str) -> None:
        if os.path.exists(log_file):
            with open(log_file, encoding='iso-8859-1') as fd:
                self.log = f"# {self.converter_name()}\n" + fd.read()
                pass
            pass
        pass

    def decorate_args(self, args: typing.List[str]) -> typing.List[str]:
        """Adjust the command args for TexLive commands.

        When running TexLive command in PyCharm, prepend the command that runs TL command
        in docker."""
        if local_exec:
            return ["/usr/local/bin/docker_pdflatex.sh"] + args
        return args

    @abstractmethod
    def converter_name(self) -> str:
        """Brief descripton of the converter"""
        pass

    def is_fallback(self) -> bool:
        """Is the converter used for fallback? (obsolete, but you can dig out the fallbach
        converter from the repo if you need.)"""
        return False

    @classmethod
    def order_tex_files(cls, tex_files: typing.List[str]) -> typing.List[str]:
        """Order the tex files so that the main tex file comes first"""
        return tex_files

    @classmethod
    def yes_pix(cls) -> bool:
        """Append the extra pics in included submission. Default is False.
        This corresponds to "Separate figures with LaTeX submissions"
        https://info.arxiv.org/help/submit_tex.html#separate-figures-with-latex-submissions
        """
        return False

    def _check_cmd_run(self, run: dict, artifact: str) -> None:
        """check the tex command run and kill the artifact when the tex command failed"""
        return_code = run.get("return_code")
        logger = get_logger()
        if return_code is None or return_code == -9:
            if artifact:
                if os.path.exists(artifact):
                    os.unlink(artifact)
                    logger.debug(f"'{artifact}' deleted. Return code: {str(return_code)}")
                else:
                    logger.debug(f"'{artifact}' does not exist. Return code: {str(return_code)}")
            else:
                logger.debug(f"Return code: {str(return_code)}")

    def _to_pdf_run(self, args: list[str], stem: str,
                    step: str, work_dir: str, in_dir: str, out_dir: str,
                    log_file: str
                    ) -> dict:
        """Run a command to generate a pdf"""
        run, out, err = self._exec_cmd(args, in_dir, work_dir, extra={"step": step})
        pdf_filename = os.path.join(in_dir, f"{stem}.pdf")
        self._check_cmd_run(run, pdf_filename)
        self._report_run(run, out, err, step, in_dir, out_dir, "pdf", pdf_filename)
        if log_file:
            self.fetch_log(log_file)
            if self.log:
                run["log"] = self.log
        return run

    def check_missing(self, in_dir: str, run: dict, artifact: str) -> dict:
        """Scoop up the missing files from the tex command log"""
        name = run[artifact]["name"]
        artifact_file = os.path.join(in_dir, name)
        if os.path.exists(artifact_file) and (missings := inspect_log(run["log"], break_on_found=False)):
            run["missings"] = missings
            get_logger().debug(f"Output {name} deleted due to incomplete run.")
            os.unlink(artifact_file)
            run[artifact] = file_props(artifact_file)
            pass
        return run
    pass

#
def select_converter_classes(in_dir: str, zzrm: ZeroZeroReadMe | None = None) \
        -> typing.Tuple[typing.List[type[BaseConverter]], typing.List[str]]:
    """Create a converter based on the tex file"""
    # candidates = [VanillaTexConverter, PdfTexConverter, PdfLatexConverter, LatexConverter]
    # https://info.arxiv.org/help/submit_tex.html
    # arXiv does not presently support PDFTeX.
    # since this seems to do more harm than good, at least for now, remove PDFTex.
    # We may revise this if we can come up with better method.
    candidates: typing.List[typing.Type[BaseConverter]] = [VanillaTexConverter, PdfLatexConverter, LatexConverter]
    if zzrm is not None and zzrm.version > 1:
        # If zzrm designates
        comp = "compiler"
        compiler: str = zzrm.compilation.get(comp, "auto")
        # not sure this is a good idea to have "auto", seems like having an escape hatch is okay.
        if compiler != "auto":
            cc_list: dict[str, typing.Type[BaseConverter]] = {cc.tex_compiler_name(): cc for cc in candidates}
            if compiler in cc_list:
                candidates = [cc_list[compiler]]
                pass
            else:
                raise ValueError(f"compiler {compiler} is not in " + repr(cc_list.keys()))
            # Just return the designated class and give no reason since there were no judgement
            return copy.copy(candidates), []

    classes = candidates.copy()
    tex_files = []
    reasons = []
    for rootdir, _dirs, files in os.walk(in_dir, topdown=True):
        for filename in files:
            declined = []
            for cc in classes:
                answer, reason = cc.decline_file(filename, rootdir)
                if answer:
                    declined.append((cc, reason))
                    break
                pass
            for cc, reason in declined:
                if cc in classes:
                    classes.remove(cc)
                    reasons.append(reason)
                    pass
                pass
            # find all the tex files in root dir
            if test_file_extent(filename, TEX_FILE_EXTS):
                tex_files.append(os.path.join(rootdir, filename))
                pass
            pass
        pass

    if len(classes) > 1:
        for tex_file in tex_files:
            with open(tex_file, encoding='iso-8859-1') as src:
                for line_no, line in enumerate(src.readlines()):
                    if not line:
                        continue
                    if line.strip()[0:1] == "%":
                        continue
                    declined = []
                    for cc in classes:
                        answer, reason = cc.decline_tex(line, line_no+1)
                        if answer:
                            declined.append((cc, reason))
                            break
                        pass
                    for cc, reason in declined:
                        if cc in classes:
                            reasons.append(reason)
                            classes.remove(cc)
                            pass
                        pass
                    if len(classes) < 2:
                        break
                else:
                    continue
                break
            pass
        pass
    return classes, reasons


#bad_for_latex_file_exts = {ext: True for ext in [".png", ".jpg", ".jpeg"]}
#bad_for_latex_file_exts = {ext: True for ext in []}

bad_for_latex_packages = {pname: True for pname in ["mmap", "fontspec"]}

bad_for_pdflatex_packages = {pname: True for pname in ["fontspec"]}
#     "pstricks",
#     "pst-node",
#     "pst-pdf",
#     "auto-pst-pdf",
#     "pst-eps",

# 2024-02-19 ntai
# it appears not all .ps or .eps fails with pdflatex so you have to give it a try.
# as a result, the list has become empty.
# bad_for_pdflatex_file_exts = [".ps", ".eps]

bad_for_pdftex_file_exts = [".ps", ".eps"]

bad_for_pdftex_packages = {pname: True for pname in ["fontspec"]}
bad_for_tex_packages = {pname: True for pname in ["fontspec"]}

rerun_needle = "Rerun to get cross-references right."


class BaseDviConverter(BaseConverter):
    """A base+ converter that does dvi, ps to pdf. """

    def _two_try_dvi_to_ps_run(self, outcome: dict[str, typing.Any], stem: str, work_dir: str,
                               in_dir: str, out_dir: str) \
            -> typing.Tuple[dict[str, typing.Any], dict[str, typing.Any]]:
        """Run dvips twice. The first run with hyperdvi. If success, it stops. If not, the
        2nd run without hyperdvi."""
        run = {}
        for hyperdvi in [True, False]:
            run = self._base_dvi_to_ps_run(stem, work_dir, in_dir, out_dir, hyperdvi=hyperdvi)
            if run["return_code"] == 0:
                outcome.update({"runs": self.runs, "status": "success",
                                "step": "dvips", "hyperdvi": hyperdvi})
                return outcome, run
            pass
        else:
            outcome.update({"runs": self.runs, "status": "fail", "step": "dvips"})
            return outcome, run

    def _base_dvi_to_ps_run(self, stem: str, work_dir: str, in_dir: str, _out_dir: str,
                            hyperdvi: bool=False) -> dict:
        """Run dvips to produce ps. This is driven by the _two_try_dvi_to_ps_run."""
        dvi_file = f"{stem}.dvi"
        tag = "dvi_to_ps"
        # -R2: Run securely. -R2 disables both shell command execution in \special'{} (via
        # backticks ' ) and config files (via the E option), and opening of any absolute filenames.
        # -z: Pass html hyperdvi specials through to the output for eventual distillation into PDF
        dvi_options = ["-R2"]
        if self.zzrm and self.zzrm.is_landscape(stem):
            dvi_options.append("-t")
            dvi_options.append("landscape")
            pass

        if self.zzrm and self.zzrm.is_keep_comments(stem):
            dvi_options.append("-K")
            pass

        if self.zzrm and self.zzrm.fontmaps:
            # Multiple -u options are allowed.
            for fontmap in self.zzrm.fontmaps:
                dvi_options.append("-u")
                dvi_options.append(fontmap)
                pass
            pass

        if hyperdvi:
            dvi_options.append("-z")
            pass
        args = ["/usr/bin/dvips"] + dvi_options + ["-o", f"{stem}.ps", dvi_file]

        run, out, err = self._exec_cmd(args, in_dir, work_dir, extra={"step": tag})
        ps_filename = os.path.join(in_dir, f"{stem}.ps")
        self._check_cmd_run(run, ps_filename)
        self._report_run(run, out, err, tag, in_dir, work_dir, "ps", ps_filename)
        return run

    def _base_to_dvi_run(self, step: str, stem: str, args: typing.List[str],
                         work_dir: str, in_dir: str) -> dict:
        """Runs the given command to generate dvi file and returns the run result."""
        run, out, err = self._exec_cmd(args, in_dir, work_dir, extra={"step": step})
        dvi_filename = os.path.join(in_dir, f"{stem}.dvi")
        self._check_cmd_run(run, dvi_filename)
        latex_log_file = os.path.join(in_dir, f"{stem}.log")
        self.fetch_log(latex_log_file)
        if self.log:
            run["log"] = self.log
        artifact = "dvi"
        self._report_run(run, out, err, step, in_dir, work_dir, artifact, dvi_filename)
        run = self.check_missing(in_dir, run, artifact)
        return run

    def _base_ps_to_pdf_run(self, stem: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Runs ps2pdf command"""
        step = "ps_to_pdf"
        args = ["/usr/bin/ps2pdf", f"{stem}.ps", f"./{stem}.pdf"]
        return self._to_pdf_run(args, stem, step, work_dir, in_dir, out_dir, "")


class LatexConverter(BaseDviConverter):
    """Runs latex (not pdflatex) command"""

    def __init__(self, conversion_tag: str, **kwargs: typing.Any):
        super().__init__(conversion_tag, **kwargs)
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler """
        return "latex"

    @classmethod
    def decline_file(cls, any_file: str, _parent_dir: str) -> typing.Tuple[bool, str]:
        # Cannot handle files other than .ps and .eps
        # if test_file_extent(any_file, bad_for_latex_file_exts):
        #     return True, f"LatexConverter cannot handle {any_file}." + \
        #         "See the list of excluded extensions."
        return False, ""

    @classmethod
    def decline_tex(cls, tex_line: str, line_number: int) -> typing.Tuple[bool, str]:
        if is_pdftex_line(tex_line):
            return True, f"LatexConverter cannot handle pdftex at line {line_number}"
        # if is_vanilla_tex _line(tex_line):
        #     return True, f"LatexConverter cannot handle pdftex at line {line_number}"
        if (line_number < 6) and (tex_line.find("\\pdfoutput=1") >= 0):
            return True, f"LatexConverter cannot handle \\pdfoutput=1 at line {line_number}"
        for package_name in pick_package_names(tex_line):
            if package_name in bad_for_latex_packages:
                # if a package is explicitli asking for dvi, it is ok.
                if tex_line.find("[dvipdfmx]") >= 0:
                    continue
                return True, f"LatexConverter cannot handle {package_name} at line {line_number}"
        return False, ""

    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF

        NOTE: It is important to return the outcome so that you can troubleshoot.
        Do not exception out.
        """
        logger = get_logger()

        outcome = self._run_base_engine_necessary_times(tex_file, work_dir, in_dir, out_dir, "dvi")
        if outcome["status"] == "fail":
            return outcome

        # Third - run dvips
        outcome, run = self._two_try_dvi_to_ps_run(outcome, self.stem, work_dir, in_dir, out_dir)
        if outcome["status"] == "fail":
            return outcome

        # Fourth - run ps2pdf
        run = self._ps_to_pdf_run(work_dir, in_dir, out_dir)
        outcome.update({"runs": self.runs, "step": "ps2pdf",
                        "status": "success" if run["return_code"] == 0 else "fail"})

        logger.debug("latex.produce_pdf", extra={ID_TAG: self.conversion_tag, "outcome": outcome})
        return outcome

    def _latexen_run(self, step: str, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        # breaks many packages... f"-output-directory=../{bod}"
        args = ["/usr/bin/latex", "-interaction=batchmode", "-file-line-error", "-recorder"]
        if WITH_SHELL_ESCAPE:
            args.append("-shell-escape")
        args.append(tex_file)
        return self._base_to_dvi_run(step, self.stem, args, work_dir, in_dir)
    
    def _ps_to_pdf_run(self, work_dir: str, in_dir: str, out_dir: str) -> dict:
        return super()._base_ps_to_pdf_run(self.stem, work_dir, in_dir, out_dir)

    def converter_name(self) -> str:
        return "latex-dvi-ps-pdf"

    @classmethod
    def order_tex_files(cls, tex_files: typing.List[str]) -> typing.List[str]:
        """Order the tex files so that the main tex file comes first"""
        if "ms.tex" in tex_files:
            tex_files.remove("ms.tex")
            tex_files.insert(0, "ms.tex")
            pass
        return tex_files

    @classmethod
    def yes_pix(cls) -> bool:
        """Append the extra pics in included submission"""
        return True
    pass


class PdfLatexConverter(BaseConverter):
    """Runs pdflatex command"""
    to_pdf_args: typing.List[str]
    pdfoutput_1_seen: bool

    def __init__(self, conversion_tag: str, **kwargs: typing.Any):
        self.pdfoutput_1_seen = kwargs.pop("pdfoutput_1_seen", False)
        super().__init__(conversion_tag, **kwargs)
        self.to_pdf_args = []
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler """
        return "pdflatex"


    @classmethod
    def decline_file(cls, _any_file: str, _parent_dir: str) -> typing.Tuple[bool, str]:
        # if any_file == ms_dot_tex:
        #     return True

        # Just having .ps file does not mean that it is bad for pdflatex.
        #
        # it = os.path.splitext(any_file)
        # # Cannot handle .ps file but alt may exist.
        # if it[1] in bad_for_pdflatex_file_exts:
        #     for alt_ext in bad_for_latex_file_exts:
        #         if os.path.exists(os.path.join(parent_dir, it[0] + alt_ext)):
        #             return False
        #     return True
        return False, ""

    @classmethod
    def decline_tex(cls, tex_line: str, line_number: int) -> typing.Tuple[bool, str]:
        if is_pdftex_line(tex_line):
            return True, f"PdfLatexConverter cannot handle pdftex at line {line_number}"
        # filename = find_include_graphics_filename(tex_line)
        # if filename:
        #     if test_file_extent(filename, bad_for_pdflatex_file_exts):
        #         return True, f"PdfLatexConverter cannot handle {filename} at {line_number}."
        #     pass
        for package_name in pick_package_names(tex_line):
            if package_name in bad_for_pdflatex_packages:
                return True, f"PdfLatexConverter cannot handle {package_name} at line {line_number}"

        return False, ""

    def _get_pdflatex_args(self, tex_file: str) -> typing.List[str]:
        """Return the pdflatex command line arguments"""
        args = ["/usr/bin/pdflatex"] + [
            "-interaction=batchmode",
            "-recorder",
            "-file-line-error"]
        # You need this sometimes, and harmful sometimes.
        if not self.pdfoutput_1_seen:
            args.append("-output-format=pdf")
        if WITH_SHELL_ESCAPE:
            args.append("-shell-escape")
        args.append(tex_file)
        return args

    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF

        NOTE: It is important to return the outcome so that you can troubleshoot.
        Do not exception out.
        """
        logger = get_logger()

        # find \pdfoutput=1
        self.pdfoutput_1_seen = find_pdfoutput_1(tex_file, in_dir)

        # This breaks many packages... f"-output-directory=../{bod}"
        self.to_pdf_args = self._get_pdflatex_args(tex_file)
        
        outcome = self._run_base_engine_necessary_times(tex_file, work_dir, in_dir, out_dir, "pdf")
        logger.debug("pdflatex.produce_pdf", extra={ID_TAG: self.conversion_tag, "outcome": outcome})
        return outcome

    def _latexen_run(self, step: str, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        cmd_log = os.path.join(in_dir, f"{self.stem}.log")
        run = self._to_pdf_run(self.to_pdf_args, self.stem,
                               step, work_dir, in_dir, out_dir, cmd_log)
        run = self.check_missing(in_dir, run, "pdf")
        return run


    def converter_name(self) -> str:
        return "%s: %s" % (self.tex_compiler_name(), shlex.join(self.to_pdf_args))

    pass


# class PdfTexConverter(BaseConverter):
#     """Runs pdftex command"""
#     to_pdf_args: typing.List[str]
#
#     def __init__(self, conversion_tag: str, **kwargs: typing.Any):
#         super().__init__(conversion_tag, **kwargs)
#         self.to_pdf_args = []
#         pass
#
#    @classmethod
#    def tex_compiler_name(cls) -> str:
#        """TeX Compiler name"""
#        return "pdftex"
#
#     @classmethod
#     def decline_file(cls, any_file: str, parent_dir: str) -> typing.Tuple[bool, str]:
#         if test_file_extent(any_file, bad_for_pdftex_file_exts):
#             return True, f"PdfTexConverter cannot handle {any_file}." + \
#                 "See the list of excluded extensions."
#         return False, ""
#
#     @classmethod
#     def decline_tex(cls, tex_line: str, line_number: int) -> typing.Tuple[bool, str]:
#         if is_pdflatex_line(tex_line) or is_vanilla_tex_line(tex_line) or is_usepackage_line(tex_line):
#             return True, f"PdfTexConverter cannot handle line {line_number}"
#         for package_name in pick_package_names(tex_line):
#             if package_name in bad_for_pdftex_packages:
#                 return True, f"PdfTexConverter cannot handle {package_name} at line {line_number}"
#         return False, ""
#
#     def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
#         """Produce PDF
#
#         NOTE: It is important to return the outcome so that you can troubleshoot.
#         Do not exception out.
#         """
#
#         # Stem: the filename of the tex file without the extension
#         stem = os.path.splitext(tex_file)[0]
#         self.stem = stem
#         stem_pdf = f"{stem}.pdf"
#         # pdf_filename = os.path.join(in_dir, stem_pdf)
#         outcome: dict[str, typing.Any] = {"pdf_file": f"{stem_pdf}"}
#
#         args = ["/usr/bin/pdftex", "-interaction=batchmode", "-recorder"]
#         if WITH_SHELL_ESCAPE:
#             args.append("-shell-escape")
#         args.append(tex_file)
#         self.to_pdf_args = args
#
#         #  pdftex run
#         step = "only_run"
#         run = self._pdftex_run(step, work_dir, in_dir, out_dir)
#         pdf_size = run["pdf"]["size"]
#         if not pdf_size:
#             outcome.update({"status": "fail", "step": step,
#                             "reason": "failed to create pdf", "runs": self.runs})
#             return outcome
#         return outcome
#
#     def _pdftex_run(self, step: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
#         log = os.path.join(in_dir, f"{self.stem}.log")
#         return self._to_pdf_run(self.to_pdf_args, self.stem, step, work_dir, in_dir, out_dir, log)
#
#     def converter_name(self) -> str:
#         return "pdftex: %s" % (shlex.join(self.to_pdf_args))
#
#     pass


class VanillaTexConverter(BaseDviConverter):
    """Runs tex command"""

    _args: typing.List[str]

    def __init__(self, conversion_tag: str, **kwargs: typing.Any):
        super().__init__(conversion_tag, **kwargs)
        self._args = []
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler """
        return "tex"

    @classmethod
    def decline_file(cls, any_file: str, parent_dir: str) -> typing.Tuple[bool, str]:
        return False, ""

    @classmethod
    def decline_tex(cls, tex_line: str, line_number: int) -> typing.Tuple[bool, str]:
        if is_pdflatex_line(tex_line):
            return True, f"VanillaTexConverter cannot handle line {line_number}"
        for package_name in pick_package_names(tex_line):
            if package_name in bad_for_tex_packages:
                return True, f"TexConverter cannot handle {package_name} at line {line_number}"
        return False, ""

    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF

        NOTE: It is important to return the outcome so that you can troubleshoot.
        Do not exception out.
        """
        logger = get_logger()

        # Stem: the filename of the tex file without the extension
        stem = os.path.splitext(tex_file)[0]
        self.stem = stem
        stem_pdf = f"{stem}.pdf"
        # pdf_filename = os.path.join(in_dir, stem_pdf)
        outcome: dict[str, typing.Any] = {"pdf_file": f"{stem_pdf}", "tex_file": tex_file}

        args = ["/usr/bin/etex", "-interaction=batchmode", "-recorder"]
        if WITH_SHELL_ESCAPE:
            args.append("-shell-escape")
        args.append(tex_file)
        self._args = args

        # tex run
        step = "tex_to_dvi_run"
        run = self._base_to_dvi_run(step, self.stem, args, work_dir, in_dir)
        dvi_size = run["dvi"]["size"]
        if not dvi_size:
            outcome.update({"status": "fail", "step": step,
                            "reason": "failed to create pdf", "runs": self.runs})
            return outcome

        # dvi run
        step = "dvi_to_ps_run"
        outcome, run = self._two_try_dvi_to_ps_run(outcome, stem, work_dir, in_dir, out_dir)
        if outcome["status"] == "fail":
            return outcome
        ps_size = run["ps"]["size"]
        if not ps_size:
            outcome.update({"status": "fail", "step": step,
                            "reason": "failed to create ps", "runs": self.runs})
            return outcome

        # ps-to-pdf
        run = self._ps_to_pdf_run(work_dir, in_dir, out_dir)
        outcome.update({"runs": self.runs, "step": "ps2pdf",
                        "status": "success" if run["return_code"] == 0 else "fail"})
        logger.debug("tex.ps_to_pdf", extra={ID_TAG: self.conversion_tag, "outcome": outcome})
        return outcome

    def _dvi_to_ps_run(self, work_dir: str, in_dir: str, _out_dir: str, hyperdvi: bool=False) -> dict:
        """Run dvips to produce ps."""
        return self._base_dvi_to_ps_run(self.stem, work_dir, in_dir, _out_dir, hyperdvi=hyperdvi)

    def _ps_to_pdf_run(self, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Runs ps2pdf command"""
        return super()._base_ps_to_pdf_run(self.stem, work_dir, in_dir, out_dir)

    def converter_name(self) -> str:
        return "tex: %s" % (shlex.join(self._args))

    def _latexen_run(self, step: str, tex_file: str, work_dir: str, in_dir: str,
                     out_dir: str) -> dict:
        """plain tex is not latex."""
        raise ImplementationError("_latexen_run() not implemented")
