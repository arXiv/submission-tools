"""This module is the core of the PDF generation. It takes a tarball, unpack it, and generate PDF."""

import hashlib
import os
import shlex
import subprocess
import time
import typing
from abc import abstractmethod

from tex2pdf_tools.tex_inspection import find_pdfoutput_1
from tex2pdf_tools.zerozeroreadme import ZeroZeroReadMe

from . import ID_TAG, MAX_LATEX_RUNS, MAX_TIME_BUDGET, file_props, file_props_in_dir, local_exec
from .service_logger import get_logger

WITH_SHELL_ESCAPE = False

# common command line arguments to all tex/latex calls
# -interaction=batchmode supress most console output
# -recorder creates a .fls file that records all read/written files
# -halt-on-error ensures that if an included file is missing, then La(TeX) does not
#  continue to process the file and produce a PDF, but returns an error.
# -file-line-error changes the formatting of the error messages
COMMON_TEX_CMD_LINE_ARGS = ["-interaction=batchmode", "-recorder"]
# extra latex command line arguments
EXTRA_LATEX_CMD_LINE_ARGS = ["-file-line-error"]


class NoTexFile(Exception):
    """No tex file found in the tarball."""

    pass


class RunFail(Exception):
    """pdflatex/bibtex run failed."""

    pass


class CompilerNotSpecified(Exception):
    """cannot detect compiler."""

    pass


class ImplementationError(Exception):
    """General implementation error (or bug)."""

    pass


class BaseConverter:
    """Base class for tex-to-pdf converters."""

    conversion_tag: str
    runs: list[dict]  # Each run generates an output
    log: str
    log_extra: dict
    supp_file_hashes: dict[str, list[str]]
    use_addon_tree: bool
    zzrm: ZeroZeroReadMe | None
    init_time: float
    max_time_budget: float
    stem: str

    def __init__(
        self,
        conversion_tag: str,
        use_addon_tree: bool = False,
        zzrm: ZeroZeroReadMe | None = None,
        max_time_budget: float | None = None,
        init_time: float | None = None,
    ):
        self.conversion_tag = conversion_tag
        self.use_addon_tree = use_addon_tree
        self.zzrm = zzrm
        self.runs = []
        self.log = ""
        self.log_extra = {ID_TAG: self.conversion_tag}
        self.supp_file_hashes = {"aux": [], "out": []}
        self.init_time = time.perf_counter() if init_time is None else init_time
        try:
            default_max = float(MAX_TIME_BUDGET)
        except Exception:
            default_max = 595
            pass
        self.max_time_budget = default_max if max_time_budget is None else max_time_budget
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler."""
        return "Unknown"

    def time_left(self) -> float:
        """Return the time left before the timeout."""
        return self.max_time_budget - (time.perf_counter() - self.init_time)

    def is_internal_converter(self) -> bool:
        """If the converter is internal, the work dir needs cleanup."""
        return True

    @abstractmethod
    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF from the given tex file. Return the outcome dict."""
        pass

    @abstractmethod
    def _latexen_run(self, step: str, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Run the base engine of the converter."""
        pass

    def _run_base_engine_necessary_times(
        self, tex_file: str, work_dir: str, in_dir: str, out_dir: str, base_format: str
    ) -> dict:
        logger = get_logger()
        # Stem: the filename of the tex file without the extension
        # we need to ensure that if the tex_file is called subdir/foobar.tex
        # then the stem is only "foobar" since compilation runs in the root
        # and the generated pdf/dvi/log files are NOT generated in the subdir
        stem = os.path.splitext(os.path.basename(tex_file))[0]
        self.stem = stem
        stem_pdf = f"{stem}.pdf"
        outcome: dict[str, typing.Any] = {"pdf_file": f"{stem_pdf}"}
        # first run
        step = "first_run"
        logger.debug("Starting first compile run")
        run = self._latexen_run(step, tex_file, work_dir, in_dir, out_dir)
        logger.debug("First run finished with %s", run)
        output_size = run[base_format]["size"]
        if output_size is None:
            logger.debug("output size is None, failing")
            outcome.update(
                {"status": "fail", "step": step, "reason": f"failed to create {base_format}", "runs": self.runs}
            )
            return outcome

        # if DVI/PDF is generated, rerun for TOC and references
        # We had already one run, run it at most MAX_LATEX_RUNS - 1 times again
        iteration_list = range(MAX_LATEX_RUNS - 1)
        for iteration in iteration_list:
            logger.debug("Starting %s run", iteration + 1)
            step = f"second_run:{iteration}"
            run = self._latexen_run(step, tex_file, work_dir, in_dir, out_dir)
            # maybe PDF/DVI creating fails on second run, so check output size again
            output_size = run[base_format]["size"]
            if output_size is None:
                logger.debug("second run output size is None, failing")
                outcome.update(
                    {"status": "fail", "step": step, "reason": f"failed to create {base_format}", "runs": self.runs}
                )
                return outcome
            if run["return_code"] != 0:
                logger.debug("Second or later run has error exit code, failing")
                name = run[base_format]["name"]
                artifact_file = os.path.join(in_dir, name)
                if os.path.exists(artifact_file):
                    logger.debug("Output %s deleted due to failed run", name)
                    os.unlink(artifact_file)
                    run[base_format] = file_props(artifact_file)
                outcome.update(
                    {"status": "fail", "step": step, "reason": "compiler run returned error code", "runs": self.runs}
                )
                return outcome
            status = "success"
            # check for hash differences of supp files (currently aux and out)
            for k in self.supp_file_hashes.keys():
                if len(self.supp_file_hashes[k]) > 1:
                    # the last aux/out/.. hash added is from the current run
                    # if the checksum hasn't changed, this is promising
                    if self.supp_file_hashes[k][-1] != self.supp_file_hashes[k][-2]:
                        logger.debug(f"{k} file size changed, need to rerun")
                        if iteration == iteration_list[-1]:
                            # we are in the last iteration, and labels are still changing
                            # In line with autotex, let us accept this as a success.
                            logger.warning("Last run had changing labels, but we exhausted the MAX_LATEX_RUNS limit.")
                        else:
                            status = "fail"
            for line in run["log"].splitlines():
                if line.find(rerun_needle) >= 0:
                    # Need retry
                    logger.debug("Found rerun needle")
                    if iteration == iteration_list[-1]:
                        # we are in the last iteration, and labels are still changing
                        # In line with autotex, let us accept this as a success.
                        logger.warning("Last run had changing labels, but we exhausted the MAX_LATEX_RUNS limit.")
                        # don't break here so that we get to a successful outcome
                    else:
                        status = "fail"
            run["iteration"] = iteration
            outcome.update({"runs": self.runs, "status": status, "step": step})
            if status == "success":
                break

        return outcome

    def _exec_cmd(
        self, args: list[str], stem: str, child_dir: str, work_dir: str, extra: dict | None = None
    ) -> tuple[dict[str, typing.Any], str, str]:
        """Run the command and return the result."""
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
        cmdenv = {
            "WORKDIR": work_dir,
            "SECRETS": "?",
            "GOOGLE_APPLICATION_CREDENTIALS": "?",
            "PATH": PATH,
            "HOME": homedir,
            "max_print_line": "4096",
            "error_line": "254",
            "half_error_line": "238",
        }
        # support SOURCE_DATE_EPOCH and FORCE_SOURCE_DATE set in the environment
        for senv in ["SOURCE_DATE_EPOCH", "FORCE_SOURCE_DATE"]:
            if os.getenv(senv):
                cmdenv[senv] = os.getenv(senv, "")  # the "" is only here to placate mypy :-(
        # try detecting incompatible bbl version and adjust TEXMFAUXTREES to make it compile
        bbl_file_full_path = os.path.join(child_dir, f"{stem}.bbl")
        if os.path.exists(bbl_file_full_path):
            with open(bbl_file_full_path, "rb") as bblfn:
                # try to read up to three lines from the .bbl file
                # This may fail for empty .bbl files or files containing less than three lines
                # in this case the next throws the StopIteration exception
                try:
                    head = [next(bblfn).strip() for _ in range(3)]
                except StopIteration:
                    head = [b""]
            if head[0] == b"% $ biblatex auxiliary file $":
                if head[1].startswith(b"% $ biblatex bbl format version "):
                    bbl_version = head[1].removeprefix(b"% $ biblatex bbl format version ").removesuffix(b" $")
                    if bbl_version == b"3.3":
                        logger.debug("bbl version 3.3 found, activating biblatex extra tree", extra=extra)
                        cmdenv["TEXMFAUXTREES"] = "/usr/local/texlive/texmf-biblatex-33,"  # we need a final comma!
        # get location of addon trees
        if self.use_addon_tree:
            kpsewhich = self.decorate_args(["/usr/bin/kpsewhich", "-var-value", "SELFAUTOPARENT"])
            sap = subprocess.run(kpsewhich, capture_output=True, text=True, check=False).stdout.rstrip()
            addon_tree = os.path.join(sap, "texmf-arxiv")
            if "TEXMFAUXTREES" in cmdenv:
                # if TEXMFAUXTREES is already set, append the addon tree to it
                cmdenv["TEXMFAUXTREES"] += f"{addon_tree},"  # we need a final comma!
            else:
                # if TEXMFAUXTREES is not set, create it
                cmdenv["TEXMFAUXTREES"] = f"{addon_tree},"  # we need a final comma!
        with subprocess.Popen(
            worker_args,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=child_dir,
            encoding="iso-8859-1",
            env=cmdenv,
        ) as child:
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
            run = {
                "args": args,
                "stdout": out,
                "stderr": err,
                "return_code": child.returncode,
                "run_env": cmdenv,
                "start_time": timestamp0,
                "end_time": timestamp1,
                "elapse_time": elapse_time,
                "process_completion": process_completion,
                "PATH": PATH,
            }
            pass
        extra.update({"run": run})
        logger.debug(f"Exec result: return code: {run['return_code']}", extra=extra)
        return run, out, err

    def _report_run(
        self, run: dict, out: str, err: str, step: str, in_dir: str, out_dir: str, output_tag: str, output_file: str
    ) -> None:
        """Report a standard command run to the run-dict, and append it to the runs."""
        logger = get_logger()
        out_stat = file_props(output_file)
        out_size = out_stat["size"]
        run.update(
            {
                "step": step,
                ID_TAG: self.conversion_tag,
                "in_files": file_props_in_dir(in_dir),
                "out_files": file_props_in_dir(out_dir),
                output_tag: out_stat,
            }
        )
        self.runs.append(run)
        logger.debug(
            f"{step} result: return code: {run['return_code']}",
            extra={ID_TAG: self.conversion_tag, "step": step, "run": run},
        )
        err_lines = err.splitlines()
        err_lines_not_ignored = []
        for el in err_lines:
            if el.startswith("libxpdf: Syntax Warning: Bad annotation destination"):
                # ignore this warning, it is not important
                continue
            if not el.strip():
                # ignore empty lines
                continue
            if el.startswith("kpathsea: Running mktex"):
                # ignore tfm or pk builds
                continue
            err_lines_not_ignored.append(el)
        if err_lines_not_ignored or out_size is None:
            logger.warning(
                f"{step}: {output_tag} size = {out_size!s} - {err_lines_not_ignored!s}",
                extra={ID_TAG: self.conversion_tag, "step": step, "stdout": out, "stderr": err},
            )
            pass

        pass

    def fetch_log(self, log_file: str) -> None:
        if os.path.exists(log_file):
            with open(log_file, encoding="iso-8859-1") as fd:
                self.log = f"# {self.converter_name()}\n" + fd.read()
                pass
            pass
        pass

    def fetch_supp_hashes(self, stem_file: str) -> None:
        for k in self.supp_file_hashes:
            supp_file = f"{stem_file}.{k}"
            if os.path.exists(supp_file):
                with open(supp_file, "rb") as fd:
                    self.supp_file_hashes[k].append(hashlib.sha256(fd.read()).hexdigest())

    def decorate_args(self, args: list[str]) -> list[str]:
        """Adjust the command args for TexLive commands.

        When running TexLive command in PyCharm, prepend the command that runs TL command
        in docker.
        """
        if local_exec:
            return ["/usr/local/bin/docker_pdflatex.sh", *args]
        return args

    @abstractmethod
    def converter_name(self) -> str:
        """Brief descripton of the converter."""
        pass

    def is_fallback(self) -> bool:
        """Check whether the converter is used for fallback.

        (obsolete, but you can dig out the fallback converter from the repo if you need.)
        """
        return False

    @classmethod
    def order_tex_files(cls, tex_files: list[str]) -> list[str]:
        """Order the tex files so that the main tex file comes first."""
        return tex_files

    @classmethod
    def yes_pix(cls) -> bool:
        """Append the extra pics in included submission. Default is False.

        This corresponds to "Separate figures with LaTeX submissions"
        https://info.arxiv.org/help/submit_tex.html#separate-figures-with-latex-submissions
        """
        return False

    def _check_cmd_run(self, run: dict, artifact: str) -> None:
        """Check the tex command run and kill the artifact when the tex command failed."""
        return_code = run.get("return_code")
        logger = get_logger()
        if return_code is None or return_code == -9:
            if artifact:
                if os.path.exists(artifact):
                    os.unlink(artifact)
                    logger.debug(f"'{artifact}' deleted. Return code: {return_code!s}")
                else:
                    logger.debug(f"'{artifact}' does not exist. Return code: {return_code!s}")
            else:
                logger.debug(f"Return code: {return_code!s}")

    def _to_pdf_run(
        self, args: list[str], stem: str, step: str, work_dir: str, in_dir: str, out_dir: str, log_file: str
    ) -> dict:
        """Run a command to generate a pdf."""
        run, out, err = self._exec_cmd(args, stem, in_dir, work_dir, extra={"step": step})
        pdf_filename = os.path.join(in_dir, f"{stem}.pdf")
        stem_filename = os.path.join(in_dir, stem)
        self._check_cmd_run(run, pdf_filename)
        self._report_run(run, out, err, step, in_dir, out_dir, "pdf", pdf_filename)
        self.fetch_supp_hashes(stem_filename)
        if log_file:
            self.fetch_log(log_file)
            if self.log:
                run["log"] = self.log
        return run

    pass


def select_converter_class(zzrm: ZeroZeroReadMe | None) -> type[BaseConverter]:
    """Select converter based on ZZRM."""
    if zzrm is None:
        raise CompilerNotSpecified("Compiler is not defined.")
    if zzrm.process.compiler is None:
        raise CompilerNotSpecified("Compiler is not defined.")
    process_spec = zzrm.process.compiler.compiler_string
    if process_spec == "etex+dvips_ps2pdf" or process_spec == "tex":
        return VanillaTexConverter
    elif process_spec == "latex+dvips_ps2pdf" or process_spec == "latex":
        return LatexConverter
    elif process_spec == "pdflatex":
        return PdfLatexConverter
    else:
        raise CompilerNotSpecified("Unknown compiler, cannot select converter: %s", process_spec)


# bad_for_latex_file_exts = {ext: True for ext in [".png", ".jpg", ".jpeg"]}
# bad_for_latex_file_exts = {ext: True for ext in []}

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
    """A base+ converter that does dvi, ps to pdf."""

    def _two_try_dvi_to_ps_run(
        self, outcome: dict[str, typing.Any], stem: str, work_dir: str, in_dir: str, out_dir: str
    ) -> tuple[dict[str, typing.Any], dict[str, typing.Any]]:
        """Run dvips twice. The first run with hyperdvi. If success, it stops. If not, the 2nd run without hyperdvi."""
        run = {}
        for hyperdvi in [True, False]:
            run = self._base_dvi_to_ps_run(stem, work_dir, in_dir, out_dir, hyperdvi=hyperdvi)
            if run["return_code"] == 0:
                outcome.update({"runs": self.runs, "status": "success", "step": "dvips", "hyperdvi": hyperdvi})
                return outcome, run
            pass
        outcome.update({"runs": self.runs, "status": "fail", "step": "dvips"})
        return outcome, run

    def _base_dvi_to_ps_run(self, stem: str, work_dir: str, in_dir: str, _out_dir: str, hyperdvi: bool = False) -> dict:
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
        args = ["/usr/bin/dvips", *dvi_options, "-o", f"{stem}.ps", dvi_file]

        run, out, err = self._exec_cmd(args, stem, in_dir, work_dir, extra={"step": tag})
        ps_filename = os.path.join(in_dir, f"{stem}.ps")
        self._check_cmd_run(run, ps_filename)
        self._report_run(run, out, err, tag, in_dir, work_dir, "ps", ps_filename)
        return run

    def _base_to_dvi_run(self, step: str, stem: str, args: list[str], work_dir: str, in_dir: str) -> dict:
        """Run the given command to generate dvi file and returns the run result."""
        run, out, err = self._exec_cmd(args, stem, in_dir, work_dir, extra={"step": step})
        dvi_filename = os.path.join(in_dir, f"{stem}.dvi")
        stem_filename = os.path.join(in_dir, stem)
        self._check_cmd_run(run, dvi_filename)
        latex_log_file = os.path.join(in_dir, f"{stem}.log")
        self.fetch_supp_hashes(stem_filename)
        self.fetch_log(latex_log_file)
        if self.log:
            run["log"] = self.log
        artifact = "dvi"
        self._report_run(run, out, err, step, in_dir, work_dir, artifact, dvi_filename)
        return run

    def _base_ps_to_pdf_run(self, stem: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Run ps2pdf command."""
        step = "ps_to_pdf"
        args = ["/usr/bin/ps2pdf", f"{stem}.ps", f"./{stem}.pdf"]
        return self._to_pdf_run(args, stem, step, work_dir, in_dir, out_dir, "")


class LatexConverter(BaseDviConverter):
    """Runs latex (not pdflatex) command."""

    def __init__(self, conversion_tag: str, **kwargs: typing.Any):
        super().__init__(conversion_tag, **kwargs)
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler."""
        return "latex"

    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF.

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
        outcome.update(
            {"runs": self.runs, "step": "ps2pdf", "status": "success" if run["return_code"] == 0 else "fail"}
        )

        logger.debug("latex.produce_pdf", extra={ID_TAG: self.conversion_tag, "outcome": outcome})
        return outcome

    def _latexen_run(self, step: str, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        # breaks many packages... f"-output-directory=../{bod}"
        args = ["/usr/bin/latex", *COMMON_TEX_CMD_LINE_ARGS, *EXTRA_LATEX_CMD_LINE_ARGS]
        if WITH_SHELL_ESCAPE:
            args.append("-shell-escape")
        args.append(tex_file)
        return self._base_to_dvi_run(step, self.stem, args, work_dir, in_dir)

    def _ps_to_pdf_run(self, work_dir: str, in_dir: str, out_dir: str) -> dict:
        return super()._base_ps_to_pdf_run(self.stem, work_dir, in_dir, out_dir)

    def converter_name(self) -> str:
        return "latex-dvi-ps-pdf"

    @classmethod
    def order_tex_files(cls, tex_files: list[str]) -> list[str]:
        """Order the tex files so that the main tex file comes first."""
        if "ms.tex" in tex_files:
            tex_files.remove("ms.tex")
            tex_files.insert(0, "ms.tex")
            pass
        return tex_files

    @classmethod
    def yes_pix(cls) -> bool:
        """Append the extra pics in included submission."""
        return True

    pass


class PdfLatexConverter(BaseConverter):
    """Runs pdflatex command."""

    to_pdf_args: list[str]
    pdfoutput_1_seen: bool

    def __init__(self, conversion_tag: str, **kwargs: typing.Any):
        self.pdfoutput_1_seen = kwargs.pop("pdfoutput_1_seen", False)
        super().__init__(conversion_tag, **kwargs)
        self.to_pdf_args = []
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler."""
        return "pdflatex"

    def _get_pdflatex_args(self, tex_file: str) -> list[str]:
        """Return the pdflatex command line arguments."""
        args = ["/usr/bin/pdflatex", *COMMON_TEX_CMD_LINE_ARGS, *EXTRA_LATEX_CMD_LINE_ARGS]
        # You need this sometimes, and harmful sometimes.
        if not self.pdfoutput_1_seen:
            args.append("-output-format=pdf")
        if WITH_SHELL_ESCAPE:
            args.append("-shell-escape")
        args.append(tex_file)
        return args

    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF.

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
        run = self._to_pdf_run(self.to_pdf_args, self.stem, step, work_dir, in_dir, out_dir, cmd_log)
        return run

    def converter_name(self) -> str:
        return f"{self.tex_compiler_name()}: {shlex.join(self.to_pdf_args)}"

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
#         args = ["/usr/bin/pdftex",  *COMMON_TEX_CMD_LINE_ARGS]
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
    """Runs tex command."""

    _args: list[str]

    def __init__(self, conversion_tag: str, **kwargs: typing.Any):
        super().__init__(conversion_tag, **kwargs)
        self._args = []
        pass

    @classmethod
    def tex_compiler_name(cls) -> str:
        """TeX Compiler."""
        return "tex"

    def produce_pdf(self, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Produce PDF.

        NOTE: It is important to return the outcome so that you can troubleshoot.
        Do not exception out.
        """
        logger = get_logger()

        # Stem: the filename of the tex file without the extension
        # we need to ensure that if the tex_file is called subdir/foobar.tex
        # then the stem is only "foobar" since compilation runs in the root
        # and the generated pdf/dvi/log files are NOT generated in the subdir
        stem = os.path.splitext(os.path.basename(tex_file))[0]
        self.stem = stem
        stem_pdf = f"{stem}.pdf"
        # pdf_filename = os.path.join(in_dir, stem_pdf)
        outcome: dict[str, typing.Any] = {"pdf_file": f"{stem_pdf}", "tex_file": tex_file}

        args = ["/usr/bin/etex", *COMMON_TEX_CMD_LINE_ARGS]
        if WITH_SHELL_ESCAPE:
            args.append("-shell-escape")
        args.append(tex_file)
        self._args = args

        # run two times
        for i in range(1, 3):
            step = f"tex_to_dvi_run_{i}"
            run = self._base_to_dvi_run(step, self.stem, args, work_dir, in_dir)
            dvi_size = run["dvi"]["size"]
            if not dvi_size or run["return_code"] != 0:
                msg = "failed to create dvi" if not dvi_size else "compiler run returned error code"
                outcome.update({"status": "fail", "step": step, "reason": msg, "runs": self.runs})
                dvi_file = os.path.join(in_dir, f"{self.stem}.dvi")
                if os.path.exists(dvi_file):
                    os.unlink(dvi_file)
                run["dvi"] = file_props(dvi_file)
                return outcome

        # dvi run
        step = "dvi_to_ps_run"
        outcome, run = self._two_try_dvi_to_ps_run(outcome, stem, work_dir, in_dir, out_dir)
        if outcome["status"] == "fail":
            return outcome
        ps_size = run["ps"]["size"]
        if not ps_size:
            outcome.update({"status": "fail", "step": step, "reason": "failed to create ps", "runs": self.runs})
            return outcome

        # ps-to-pdf
        run = self._ps_to_pdf_run(work_dir, in_dir, out_dir)
        outcome.update(
            {"runs": self.runs, "step": "ps2pdf", "status": "success" if run["return_code"] == 0 else "fail"}
        )
        logger.debug("tex.ps_to_pdf", extra={ID_TAG: self.conversion_tag, "outcome": outcome})
        return outcome

    def _dvi_to_ps_run(self, work_dir: str, in_dir: str, _out_dir: str, hyperdvi: bool = False) -> dict:
        """Run dvips to produce ps."""
        return self._base_dvi_to_ps_run(self.stem, work_dir, in_dir, _out_dir, hyperdvi=hyperdvi)

    def _ps_to_pdf_run(self, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Run ps2pdf command."""
        return super()._base_ps_to_pdf_run(self.stem, work_dir, in_dir, out_dir)

    def converter_name(self) -> str:
        return f"tex: {shlex.join(self._args)}"

    def _latexen_run(self, step: str, tex_file: str, work_dir: str, in_dir: str, out_dir: str) -> dict:
        """Plain tex is not latex."""
        raise ImplementationError("_latexen_run() not implemented")
