"""This module is the core of the PDF generation. It takes a tarball, unpack it, and generate PDF."""

import io
import json
import os
import random
import shlex
import subprocess
import time
import typing

from tex2pdf_tools.preflight import PreflightStatusValues, generate_preflight_response
from tex2pdf_tools.tex_inspection import find_unused_toplevel_files, maybe_bbl
from tex2pdf_tools.zerozeroreadme import FileUsageType, ZeroZeroReadMe

from . import (
    GIT_COMMIT_HASH,
    ID_TAG,
    MAX_TIME_BUDGET,
    catalog_files,
    file_props,
    file_props_in_dir,
    graphics_exts,
    test_file_extent,
)
from .doc_converter import combine_documents
from .pdf_watermark import Watermark, WatermarkError, add_watermark_text_to_pdf
from .remote_call import service_process_tarball
from .service_logger import get_logger
from .tarball import ZZRMUnderspecified, ZZRMUnsupportedCompiler, unpack_tarball
from .tex_patching import fix_tex_sources
from .tex_to_pdf_converters import BaseConverter, CompilerNotSpecified, select_converter_class

unlikely_prefix = "WickedUnlkly-"  # prefix for the merged PDF - with intentional typo
winded_message = (
    "PDF %s not in t0. When this happens, there are multiple TeX sources that has "
    "the conflicting names. (eg, both main.tex and main.latex exist.) This should "
    "have been resolved by find_primary_tex()."
    " In any rate, the tarball needs clarification."
)


class AssemblingFileNotFound(Exception):
    """Designated file in assembling is not found."""

    pass


class ConverterDriver:
    """Drives the Tex converter.

    - Drives to pick a converter class
    - Sets up the work dir
    - Picks TeX files to convert
    - Runs converter on the tex files
    """

    source: str
    in_dir: str
    out_dir: str
    runs: list[dict]
    work_dir: str
    converter: BaseConverter | None
    converters: list[type[BaseConverter]]
    tex_files: list[str]
    zzrm: ZeroZeroReadMe | None
    t0: float
    max_time_budget: float
    outcome: dict
    converter_logs: list[str]
    tag: str
    note: str
    use_addon_tree: bool
    max_tex_files: int
    max_appending_files: int
    water: Watermark
    ts: int | None
    auto_detect: bool = False
    hide_anc_dir: bool = False

    def __init__(
        self,
        work_dir: str,
        source: str,
        use_addon_tree: bool | None = None,
        tag: str | None = None,
        watermark: Watermark | None = None,
        max_time_budget: float | None = None,
        max_tex_files: int = 1,
        max_appending_files: int = 0,
        ts: int | None = None,
        auto_detect: bool = False,
        hide_anc_dir: bool = False,
    ):
        self.work_dir = work_dir
        self.in_dir = os.path.join(work_dir, "in")
        self.out_dir = os.path.join(work_dir, "out")
        self.source = source
        self.converters = []
        self.converter = None
        self.water = Watermark(None, None) if watermark is None else watermark
        self.outcome = {}
        self.log_extra = {ID_TAG: tag} if tag else {}
        self.note = ""
        self.converter_logs = []
        self.tex_files = []
        self.t0 = time.perf_counter()
        self.max_time_budget = MAX_TIME_BUDGET if max_time_budget is None else max_time_budget
        self.tag = tag if tag else "unknown driver"
        self.use_addon_tree = use_addon_tree if use_addon_tree else False
        self.max_tex_files = max_tex_files
        self.max_appending_files = max_appending_files
        self.ts = ts
        self.auto_detect = auto_detect
        self.hide_anc_dir = hide_anc_dir
        self.zzrm = None
        pass

    @property
    def driver_log(self) -> str:
        """The converter driver log."""
        return "\n".join(self.converter_logs) if self.converter_logs else self.note

    def _find_anc_rename_directory(self, ancdir: str) -> str | None:
        target: str | None = None
        if os.path.isdir(ancdir):
            target = f"{self.in_dir}/_anc"
            assert target is not None  # placate stupid mypy
            if os.path.isdir(target):
                # we need to find a way to rename it
                new_target = None
                for i in range(10):
                    try_target = f"{target}_{random.getrandbits(32)}"
                    if os.path.isdir(try_target):
                        continue
                    else:
                        new_target = try_target
                        break
                if not new_target:
                    # No way that this can happen, 10 times random strings
                    # and all those directories are present ...???
                    target = None
                else:
                    target = new_target
        return target

    def generate_pdf(self) -> str | None:
        """We have the beef."""
        logger = get_logger()
        self.t0 = time.perf_counter()

        # this might raise various exceptions, that should be reported to the API down the line
        self.zzrm = ZeroZeroReadMe(self.in_dir)

        self.outcome = {
            ID_TAG: self.tag,
            "status": None,
            "converters": [],
            "start_time": str(self.t0),
            "timeout": str(self.max_time_budget),
            "use_addon_tree": self.use_addon_tree,
            "max_tex_files": self.max_tex_files,
            "max_appending_files": self.max_appending_files,
        }
        if self.water.text:
            self.outcome["watermark"] = self.water
        # Find the starting point
        fix_tex_sources(self.in_dir)

        if not self.zzrm.is_ready_for_compilation:
            if not self.auto_detect:
                raise ZZRMUnderspecified("Not ready for compilation and auto-detect disabled")
            logger.debug("Running preflight for input since no 00README present")
            preflight_response = generate_preflight_response(self.in_dir)
            if isinstance(preflight_response, str):
                raise Exception("We didn't request a JSON object but received one?")
            self.outcome["preflight_v2"] = preflight_response.to_json()
            logger.debug("Got preflight response: %s", preflight_response)
            if preflight_response.status.key != PreflightStatusValues.success:
                # TODO what to do here?
                raise Exception("Preflight didn't succeed!")
            if not self.zzrm.update_from_preflight(preflight_response):
                raise ZZRMUnderspecified("Cannot determine compiler from preflight and sources")

        # we should now be ready to go
        if not self.zzrm.is_ready_for_compilation:
            raise ZZRMUnderspecified("Still not ready for compilation -- this is strange")

        if not self.zzrm.is_supported_compiler:
            raise ZZRMUnsupportedCompiler

        tex_files = self.zzrm.toplevels
        if self.zzrm.readme_filename is not None:
            # zzrm was provided
            max_tex_files = len(tex_files)
        else:
            # if no ZZRM was present, we default to only compile the
            # first self.max_tex_files files
            max_tex_files = self.max_tex_files

        self.tex_files = tex_files[:max_tex_files]  # Used tex files
        unused_tex_files = tex_files[max_tex_files:]
        self.outcome["possible_tex_files"] = tex_files
        self.outcome["tex_files"] = self.tex_files
        self.outcome["unused_tex_files"] = unused_tex_files
        for tex_file in self.tex_files:
            self.zzrm.find_metadata(tex_file).usage = FileUsageType.toplevel
        for tex_file in unused_tex_files:
            self.zzrm.find_metadata(tex_file).usage = FileUsageType.ignore

        if not self.tex_files:
            in_files = [f"""{in_file["name"]} ({in_file["size"]})""" for in_file in self.outcome.get("in_files", [])]
            self.note = "No tex file found. " + ", ".join(in_files)
            logger.error("Cannot find tex file for %s.", self.tag, extra=self.log_extra)
            self.outcome.update({"status": "fail", "tex_file": None, "in_files": file_props_in_dir(self.in_dir)})
            return None

        # Ignore nohyperref, we will not auto-add hyperref, so we don't need this option
        if self.zzrm.nohyperref:
            logger.warning("Ignoring nohyperref but continuing")
            # self.outcome["status"] = "fail"
            # self.outcome["reason"] = "nohyperref is not supported yet"
            # self.outcome["in_files"] = file_props_in_dir(self.in_dir)
        # Deal with ignoring of anc directory, if requested
        target: str | None = None
        if self.hide_anc_dir:
            ancdir = f"{self.in_dir}/anc"
            if os.path.isdir(ancdir):
                target = self._find_anc_rename_directory(ancdir)
                # we should have a target now that works
                if target is None:
                    logger.warning("Cannot find target to rename anc directory, strange!")
                else:
                    logger.debug("Renaming anc directory %s to %s", ancdir, target)
                    os.rename(ancdir, target)
        try:
            # run TeX under try and have a finally to rename the anc directory back
            # in case some exception happens in the TeX processing
            self._run_tex_commands()
        except CompilerNotSpecified as e:
            self.outcome["status"] = "fail"
            self.outcome["reason"] = str(e)
            self.outcome["in_files"] = file_props_in_dir(self.in_dir)
        finally:
            if self.hide_anc_dir and target is not None:
                logger.debug("Renaming backup anc directory %s back to %s", target, ancdir)
                os.rename(target, ancdir)
        pdf_files = self.outcome.get("pdf_files", [])
        if pdf_files:
            self._finalize_pdf()
            self.outcome["status"] = "success"
        else:
            self.outcome["status"] = "fail"
        return self.outcome.get("pdf_file")

    def _run_tex_commands(self) -> None:
        logger = get_logger()
        t0_files = catalog_files(self.in_dir)
        start_process_time = time.process_time()

        # select compiler based on ZZRM or preflight, don't guess
        converter_class = select_converter_class(self.zzrm)
        outcome = self.outcome  # just an alias

        ordered_tex_files = converter_class.order_tex_files(self.tex_files)
        outcome["pdf_files"] = []
        outcome["include_figures"] = converter_class.yes_pix()
        for tex_file in ordered_tex_files:
            self.converter = converter_class(
                self.tag,
                use_addon_tree=self.use_addon_tree,
                zzrm=self.zzrm,
                init_time=self.t0,
                max_time_budget=self.max_time_budget,
            )
            cpu_t0 = time.process_time()

            # If the tarball contains a PDF file, pretend it not exist.
            pdf_file = os.path.splitext(tex_file)[0] + ".pdf"
            made_pdf_file = os.path.join(self.in_dir, pdf_file)
            if os.path.exists(made_pdf_file):
                if pdf_file not in t0_files:
                    logger.warning(winded_message, made_pdf_file, extra=self.log_extra)
                    pass
                else:
                    del t0_files[pdf_file]
                pass

            # the converter returns the multiple runs of latex command, so it is named runs.
            runs = self.converter.produce_pdf(tex_file, self.work_dir, self.in_dir, self.out_dir)

            elapse_time = time.perf_counter() - self.t0
            cpu_t1 = time.process_time()
            cpu_time_per_run = cpu_t1 - cpu_t0

            pdf_file = runs.get("pdf_file", pdf_file)
            made_pdf_file = os.path.join(self.in_dir, pdf_file)
            # I'm not liking this part very much
            runs["tex_file"] = tex_file
            runs["bbl_file"] = maybe_bbl(tex_file, self.in_dir)
            runs["converter"] = self.converter.converter_name()
            runs["out_files"] = file_props_in_dir(self.out_dir)
            runs["elapse_time"] = elapse_time
            runs["cpu_time"] = cpu_time_per_run

            # Once the runs made, attach it to the converter
            outcome["converters"].append(runs)
            pdf_file_props = file_props(made_pdf_file)
            if pdf_file_props["size"]:
                outcome["pdf_files"].append(pdf_file)
            else:
                logger.warning("PDF file error: %s", repr(pdf_file_props), extra=self.log_extra)
                pass

            # truncate some latex logs for the HTTP replies. The full log file is in the
            # out_dir and you can download.
            conv_log = runs.get("runs", [{}])[-1].get("log")
            if conv_log and isinstance(conv_log, str):  # be cautious and not die for log
                conv_log = conv_log.splitlines()
                if len(conv_log) > 100:
                    desc = [f"TeX File: {tex_file}"]
                    l30 = conv_log[:30]
                    ll50 = conv_log[-50:]
                    conv_log = desc + l30 + ["", f"<{len(conv_log) - len(l30) - len(ll50)} lines removed>", ""] + ll50
                    pass
                self.converter_logs.append("\n".join(conv_log))
                pass
            pass

        t1_files = catalog_files(self.in_dir)

        artifacts = t1_files.keys() - t0_files.keys()
        pdf_files = outcome["pdf_files"]

        # If PDF files made, no need to run the next converter.
        if pdf_files:
            for artifact in artifacts:
                if artifact.endswith("-eps-converted-to.pdf"):
                    continue
                from_file = os.path.join(self.in_dir, artifact)
                to_file = os.path.join(self.out_dir, artifact)
                os.makedirs(os.path.dirname(to_file), exist_ok=True)
                os.rename(from_file, to_file)
                pass

        # Keep the all of converters' runs (except the files created)
        outcome["total_time"] = time.perf_counter() - self.t0
        outcome["total_cpu_time"] = time.process_time() - start_process_time

    def unused_pics(self) -> list[str]:
        """Return the list of unused pics.

        return the path, not the file name
        """
        return [
            maybe
            for maybe in find_unused_toplevel_files(self.in_dir, self.tex_files)
            if test_file_extent(maybe, graphics_exts)
        ]

    def _finalize_pdf(self) -> None:
        """TeX has done its work. It may still need some things added to the PDF.

        First, we say the top-level graphics files appended.
        Second, we want the PDF watermarked.

        Note that, 00README.XXX can suppress the graphics addition, and watermarking.

        https://info.arxiv.org/help/submit_tex.html#latex
        Note that adding a 00README.XXX with a toplevelfile directive will only effect the processing order
        and not the final assembly order of the pdf.

        This is true for V1. When using v2 00README, the doc order honors the order of compiled texs.
        """
        logger = get_logger()
        outcome = self.outcome
        # When the converter is successful, ship the pdf and the outcome.
        # oh - don't forget to watermark the PDF.
        pdf_files = outcome["pdf_files"]
        # add pics from 00README.XXX
        merged_pdf = f"{self.tag}.pdf"
        # generated PDF must be in out_dir, and outcome["pdf_file"] should only be the name
        # without dir. It's a bit of pain but mixing up is confusing
        outcome["pdf_file"] = merged_pdf  # init
        try:
            # artifact moving has moved the pdfs to out_dir while unused pics still in in_dir
            docs = [f"out/{pdf_file}" for pdf_file in pdf_files]
            pic_adds = self.unused_pics()[: self.max_appending_files]

            # Does the converter class support pic additions?
            if self.converter and self.converter.__class__.yes_pix():
                docs += [f"in/{pic}" for pic in pic_adds]

            # Note the available documents that can be combined.
            outcome["available_documents"] = docs

            # After all the trouble, if assembling_files is designated in post process, use it.
            # Here, instead of taking the raw, match the basenames and list the docs in the
            # order that appears in the assembling files. If it is missing in either, it is
            # ignored.
            if self.zzrm and self.zzrm.assembling_files:
                # Lay out the ingredients
                ingredients = {os.path.basename(doc): doc for doc in docs}
                cooked = []
                # Follow the recipe
                for ingredient in self.zzrm.assembling_files:
                    doc = ingredients.get(ingredient)
                    if doc:
                        cooked.append(doc)
                    else:
                        # If an ingredient is missing, error
                        raise AssemblingFileNotFound(f"File {ingredient} is not found in " + repr(ingredients.keys()))
                # Replace the docs to make with the cooked ingredients
                docs = cooked
                # When the assembling is designated, don't truncate
                self.max_appending_files = len(docs)

            # Docs decided
            outcome["documents"] = docs
            docs = [os.path.join(self.work_dir, doc) for doc in docs]
            final_pdf, used_gfx, unused_gfx, addon_outcome = combine_documents(
                docs, self.out_dir, merged_pdf, log_extra=self.log_extra
            )
            outcome |= addon_outcome
            # self.zzrm.set_assembling_files(used_gfx)
            outcome["pdf_file"] = final_pdf
            outcome["used_figures"] = used_gfx
            outcome["unused_figures"] = self.unused_pics()[self.max_appending_files :] + unused_gfx
        except AssemblingFileNotFound as exc:
            logger.warning("Failed combining PDFs: %s", exc, extra=self.log_extra)
            pass
        except Exception as exc:
            if isinstance(exc, subprocess.TimeoutExpired | subprocess.CalledProcessError):
                logger.warning(
                    "Failed combining PDFs: %s (stdout=%s, stderr=%s)",
                    exc,
                    exc.stdout,
                    exc.stderr,
                    extra=self.log_extra,
                )
                outcome["gs"] = {}
                if isinstance(exc, subprocess.CalledProcessError):
                    outcome["gs"]["return_code"] = exc.returncode
                outcome["gs"]["timeout"] = True
                # mypy believes that exc does not have stdout/stderr, but both
                # exceptions contain these values
                outcome["gs"]["stdout"] = exc.stdout
                outcome["gs"]["stderr"] = exc.stderr
            else:
                raise exc

        assert self.zzrm is not None

        if self.water.text and (not self.zzrm.nostamp):
            pdf_file = os.path.join(self.out_dir, outcome["pdf_file"])
            # the "combine documents" step may have failed, and the pdf_file may not exist
            if not os.path.exists(pdf_file):
                logger.warning("PDF file %s not found, cannot watermark", pdf_file, extra=self.log_extra)
                return
            temp_name = outcome["pdf_file"] + ".watermarked.pdf"
            watered = self._watermark(pdf_file, os.path.join(self.out_dir, temp_name))

            if os.path.exists(watered):
                outcome["watermark"] = self.water
                os.rename(watered, pdf_file)
                pass
            pass
        return

    def _watermark(self, pdf_file: str, watered: str | None = None) -> str:
        """Watermark the PDF file. Watered is the result filename."""
        output = pdf_file
        if self.water.text:
            logger = get_logger()
            if watered is None:
                watered = os.path.join(os.path.dirname(pdf_file), "watermarked-" + os.path.basename(pdf_file))
                pass
            try:
                add_watermark_text_to_pdf(self.water, pdf_file, watered)
                output = watered
            except WatermarkError as _exc:
                logger.warning("Failed watermarking %s", pdf_file, exc_info=True, extra=self.log_extra)
                output = pdf_file
            except Exception as _exc:
                logger.error("Exception in watermarking %s", pdf_file, exc_info=True, extra=self.log_extra)
                output = pdf_file
            pass
        return output

    pass


class ConversionOutcomeMaker:
    """Conversion outcome packer/unpacker.

    This can be part of driver. It makes the class methods a touch longer. So, make this part
    done by a visitor class.
    """

    def __init__(self, work_dir: str, tag: str, outcome_file: str | None = None, gen_id: str = "tex2pdf"):
        self.work_dir = work_dir
        self.tag = tag
        self.outcome_file = f"{tag}.outcome.tar.gz" if outcome_file is None else outcome_file
        self.log_extra = {ID_TAG: self.tag}
        self.gen_id = gen_id
        pass

    def create_outcome(
        self,
        converter_driver: ConverterDriver,
        outcome: dict,
        conversion_meta: dict | None = None,
        outcome_files: list[str] | None = None,
        more_files: list[str] | None = None,
    ) -> None:
        """
        Work as the visitor to the converter to generate outcome and upload.

        work_dir/
            outcome-{tag}.json
            {converter.out_dir}/

        """
        logger = get_logger()
        in_dir = converter_driver.in_dir
        out_dir = converter_driver.out_dir

        out_dir_files = os.listdir(out_dir)
        if outcome_files is None:
            outcome_files = [fname for fname in out_dir_files if not fname.endswith(".pdf")]
            pass

        zzrm = converter_driver.zzrm
        assert zzrm is not None
        zzrm_generated = io.StringIO()
        zzrm.to_yaml(zzrm_generated)
        zzrm_generated.seek(0)
        zzrm_text = zzrm_generated.read()
        outcome_meta = {
            "version": 1,  # outcome format version
            "version_info": f"{self.gen_id}:{GIT_COMMIT_HASH}",
            "in_directory": os.path.basename(in_dir),
            "out_directory": os.path.basename(out_dir),
            "in_files": catalog_files(in_dir),
            "out_files": catalog_files(out_dir),
            "zzrm": {
                "input": zzrm.readme,
                "content": zzrm.to_dict(),
                "generated": zzrm_text,
            },
        }
        if conversion_meta:
            outcome_meta["conversion"] = conversion_meta
            pass

        if converter_driver.converter:
            outcome_meta["converter"] = converter_driver.converter.converter_name()
        if outcome:
            # outcome could come from a remote call and already contain a `version_info`
            complete_version_info: str = ""
            if "version_info" in outcome:
                complete_version_info = f"""{outcome_meta["version_info"]} {outcome["version_info"]}"""
            else:
                complete_version_info = str(outcome_meta["version_info"])
            outcome_meta.update(outcome)
            outcome_meta["version_info"] = complete_version_info
        outcome_meta_file = f"outcome-{self.tag}.json"
        with open(os.path.join(self.work_dir, outcome_meta_file), "w", encoding="utf-8") as fd:
            json.dump(outcome_meta, fd, indent=2)
            pass
        bod = os.path.basename(out_dir)
        if more_files is None:
            more_files = []
            pass
        taring = more_files + [f"{bod}/{fname}" for fname in outcome_files]
        # double-check the files exist
        taring = [ofile for ofile in taring if os.path.exists(os.path.join(self.work_dir, ofile))]
        tar_cmd = ["tar", "czf", self.outcome_file, outcome_meta_file, *taring]
        logger.debug(f"Creating outcome: {shlex.join(tar_cmd)}", extra=self.log_extra)
        subprocess.call(tar_cmd, cwd=self.work_dir)
        return

    def unpack_outcome(self) -> dict[str, str | int | float | dict] | None:
        """Corresponds to the packer above."""
        tar_cmd = ["tar", "xzf", self.outcome_file]
        logger = get_logger()
        logger.debug(f"Unpacking outcome: {shlex.join(tar_cmd)}", extra=self.log_extra)
        subprocess.call(tar_cmd, cwd=self.work_dir)
        # os.unlink(self.outcome_file)
        meta = None
        files = os.listdir(self.work_dir)
        logger.debug(f"Unpacked files of {self.outcome_file}: {files!r}", extra=self.log_extra)
        outcome_meta_file = f"outcome-{self.tag}.json"
        try:
            for filename in files:
                if filename == outcome_meta_file:
                    with open(os.path.join(self.work_dir, filename), encoding="utf-8") as fd:
                        meta = json.load(fd)
                        pass
                    pass
                pass
            pass
        except Exception as _exc:
            pass
        return meta


class RemoteConverterDriver(ConverterDriver):
    """Uses compilation service for conversion."""

    service: str
    timeout: int

    def __init__(self, service: str, timeout: int, work_dir: str, source: str, **kwargs: typing.Any):
        super().__init__(work_dir, source, **kwargs)
        self.service = service
        self.timeout = timeout

    def generate_pdf(self) -> str | None:
        """We have the beef."""
        logger = get_logger()
        self.t0 = time.perf_counter()

        tag = self.tag or os.path.basename(self.source)

        logger.warning("workdir = %s, tag = %s, source = %s", self.work_dir, tag, self.source)
        status_code, msg_file = service_process_tarball(
            compile_service=self.service,
            input_path=self.source,
            tag=tag,
            use_addon_tree=self.use_addon_tree,
            timeout=self.timeout,
            max_tex_files=self.max_tex_files,
            max_appending_files=self.max_appending_files,
            watermark_text=self.water.text,
            watermark_link=self.water.link,
            auto_detect=self.auto_detect,
            hide_anc_dir=self.hide_anc_dir,
            log_extra=self.log_extra,
            output_path=os.path.join(self.out_dir, f"{tag}-outcome.tar.gz"),
        )

        if status_code != 200:
            logger.warning(f"Couldn't generate PDF: {msg_file}")
            # ensure we have a zzrm file!
            self.zzrm = ZeroZeroReadMe()
            return None

        # unpack the tarball for further processing
        logger.debug("Unpacking to workdir %s", self.work_dir)
        os.makedirs(self.work_dir, exist_ok=True)
        assert isinstance(msg_file, str)
        unpack_tarball(self.work_dir, msg_file, {})
        logger.debug("Unpacking done")

        logger.debug("Getting outcome json")
        meta = {}
        for f in os.listdir(self.work_dir):
            if f.startswith("outcome-") and f.endswith(".json"):
                with open(os.path.join(self.work_dir, f)) as json_file:
                    meta.update(json.load(json_file))
                break
        self.outcome = meta
        # logger.debug("Dumping meta %s", meta)
        logger.debug("Checking for ZZRM")

        # we need to get ZZRM
        if self.zzrm is None:
            zzrm_content = meta["zzrm"]["content"]
            logger.debug("Got zzrm content: %s", zzrm_content)
            self.zzrm = ZeroZeroReadMe()
            self.zzrm.from_dict(zzrm_content)
        else:
            logger.debug("self.zzrm = %s", self.zzrm)

        logger.debug("Directory listing of %s is: %s", self.work_dir, os.listdir(self.work_dir))

        return self.outcome.get("pdf_file")
