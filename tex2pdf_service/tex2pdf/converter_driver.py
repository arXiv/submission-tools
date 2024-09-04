"""
This module is the core of the PDF generation. It takes a tarball, unpack it, and generate PDF.
"""
import io
import json
import os
import shlex
import subprocess
import time
import typing
from enum import Enum

from pikepdf import PdfError

from tex2pdf import file_props, file_props_in_dir, catalog_files, \
    ID_TAG, graphics_exts, test_file_extent, MAX_TIME_BUDGET
from tex2pdf.doc_converter import combine_documents, strip_to_basename
from tex2pdf.service_logger import get_logger
from tex2pdf.tarball import unpack_tarball, chmod_775
from tex2pdf.tex_to_pdf_converters import BaseConverter
from tex2pdf.tex_patching import fix_tex_sources
from tex2pdf.pdf_watermark import add_watermark_text_to_pdf, Watermark
from tex_inspection import (find_primary_tex, maybe_bbl, ZeroZeroReadMe, find_unused_toplevel_files,
                            SubmissionFileType)
from tex2pdf.tex_to_pdf_converters import select_converter_classes
from preflight_parser import generate_preflight_response

unlikely_prefix = "WickedUnlkly-"  # prefix for the merged PDF - with intentional typo
winded_message = ("PDF %s not in t0. When this happens, there are multiple TeX sources that has "
                  "the conflicting names. (eg, both main.tex and main.latex exist.) This should "
                  "have been resolved by find_primary_tex()."
                  " In any rate, the tarball needs clarification.")

class PreflightVersion(Enum):
    """Possible values of preflight version."""

    NONE = 0
    V1 = 1
    V2 = 2


class AssemblingFileNotFound(Exception):
    """Designated file in assembling is not found"""
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
    runs: typing.List[dict]
    work_dir: str
    converter: BaseConverter | None
    converters: typing.List[type[BaseConverter]]
    tex_files: typing.List[str]
    zzrm: ZeroZeroReadMe
    t0: float
    max_time_budget: float
    outcome: dict
    converter_logs: typing.List[str]
    tag: str
    note: str
    use_addon_tree: bool
    max_tex_files: int
    max_appending_files: int
    artifact_order: dict
    today: str | None
    water: Watermark
    preflight: PreflightVersion

    def __init__(self, work_dir: str, source: str, use_addon_tree: bool | None = None,
                 tag: str | None = None, watermark: Watermark | None = None,
                 max_time_budget: float | None = None,
                 max_tex_files: int = 1,  max_appending_files: int = 0,
                 preflight: PreflightVersion = PreflightVersion.NONE
                 ):
        self.work_dir = work_dir
        self.in_dir = os.path.join(work_dir, "in")
        self.out_dir = os.path.join(work_dir, "out")
        self.source = source
        self.converters = []
        self.converter = None
        self.water = Watermark(None,None) if watermark is None else watermark
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
        self.today = None
        self.preflight = preflight
        pass

    @property
    def driver_log(self) -> str:
        """The converter driver log"""
        return "\n".join(self.converter_logs) if self.converter_logs else self.note


    def generate_pdf(self) -> str|None:
        """We have the beef"""
        logger = get_logger()
        self.t0 = time.perf_counter()

        self._unpack_tarball()
        try:
            self.zzrm = ZeroZeroReadMe(self.in_dir)
        except KeyError:
            self.zzrm = ZeroZeroReadMe(None)
            logger.warning("Input directory %s contains an invalid 00README file, and ignored", self.in_dir)
            pass
        self.outcome = {ID_TAG: self.tag, "status": None, "converters": [],
                        "start_time": str(self.t0),
                        "timeout": str(self.max_time_budget),
                        "use_addon_tree": self.use_addon_tree,
                        "max_tex_files": self.max_tex_files,
                        "max_appending_files": self.max_appending_files
                        }
        if self.water.text:
            self.outcome["watermark"] = self.water
        # Find the starting point
        fix_tex_sources(self.in_dir)
        tex_files = find_primary_tex(self.in_dir, self.zzrm)
        # If 00README input exists, obey the designation
        max_tex_files = len(tex_files) if self.zzrm.readme or self.zzrm.version > 1 else self.max_tex_files
        self.tex_files = tex_files[:max_tex_files]  # Used tex files
        unused_tex_files = tex_files[max_tex_files:]
        self.outcome["possible_tex_files"] = tex_files
        self.outcome["tex_files"] = self.tex_files
        self.outcome["unused_tex_files"] = unused_tex_files
        for tex_file in self.tex_files:
            self.zzrm.find_metadata(tex_file).set_file_type(SubmissionFileType.toplevel)
        for tex_file in unused_tex_files:
            self.zzrm.find_metadata(tex_file).set_file_type(SubmissionFileType.ignored)

        if not self.tex_files:
            in_file: dict
            in_files = ["%s (%s)" % (in_file["name"], str(in_file["size"]))
                        for in_file in self.outcome.get("in_files", [])]
            self.note = "No tex file found. " + ", ".join(in_files)
            logger.error("Cannot find tex file for %s.", self.tag,
                         extra=self.log_extra)
            self.outcome.update({"status": "fail", "tex_file": None,
                                 "in_files": file_props_in_dir(self.in_dir)})
            return None

        if self.preflight is not PreflightVersion.NONE:
            logger.debug("[ConverterDriver.generate_pdf] running preflight version %s", self.preflight)
            self.report_preflight()
            return None

        # Once no-hyperref is implemented, change here - future fixme
        if self.zzrm.nohyperref:
            self.outcome["status"] = "fail"
            self.outcome["reason"] = "nohyperref is not supported yet"
            self.outcome["in_files"] = file_props_in_dir(self.in_dir)
        else:
            self._run_tex_commands()
            pdf_files = self.outcome.get("pdf_files", [])
            if pdf_files:
                self._finalize_pdf()
                self.outcome["status"] = "success"
            else:
                self.outcome["status"] = "fail"
                pass
            pass
        return self.outcome.get("pdf_file")

    def report_preflight(self) -> None:
        """Set the values to zzrm"""
        if self.preflight == PreflightVersion.V1:
            converters, reasons = select_converter_classes(self.in_dir, zzrm=self.zzrm)
            self.outcome["converters"] = [converter.tex_compiler_name() for converter in converters]
            self.outcome["reasons"] = reasons
            self.outcome["pdf_files"] = strip_to_basename(self.tex_files, extent=".pdf")
            self.zzrm.register_primary_tex_files(self.tex_files)
            if len(self.converters) == 1:
                self.zzrm.set_tex_compiler(self.converters[0].tex_compiler_name())
            # Generally, the assembling files are the compiled tex files and the unused graphics
            self.zzrm.set_assembling_files(self.outcome["pdf_files"] + strip_to_basename(self.unused_pics()))
        elif self.preflight == PreflightVersion.V2:
            self.outcome["preflight_v2"] = generate_preflight_response(self.in_dir, json=True)
        else:
            # Should not happen, we check this already on entrance of API call
            raise ValueError(f"Invalid PreflightVersion: {self.preflight}")

    def _run_tex_commands(self) -> None:
        logger = get_logger()
        t0_files = catalog_files(self.in_dir)
        start_process_time = time.process_time()

        self.converters, reasons = select_converter_classes(self.in_dir, zzrm=self.zzrm)
        outcome = self.outcome # just an alias
        outcome["reasons"] = reasons

        for index, converter_class in enumerate(self.converters):
            # Note that, self.tex_files is alraedy ordered with zzr in mind
            ordered_tex_files = converter_class.order_tex_files(self.tex_files)
            outcome["pdf_files"] = []
            outcome["include_figures"] = converter_class.yes_pix()
            for tex_file in ordered_tex_files:
                self.converter = converter_class(self.tag, use_addon_tree=self.use_addon_tree,
                                                 zzrm=self.zzrm, init_time=self.t0,
                                                 max_time_budget=self.max_time_budget)
                cpu_t0 = time.process_time()

                # If the tarball contains a PDF file, pretend it not exist.
                pdf_file = os.path.splitext(tex_file)[0] + ".pdf"
                made_pdf_file = os.path.join(self.in_dir, pdf_file)
                if os.path.exists(made_pdf_file):
                    if pdf_file not in t0_files:
                        logger.warning(winded_message,made_pdf_file, extra=self.log_extra)
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
                runs["index"] = index
                runs["converter"] = self.converter.converter_name()
                runs["out_files"] = file_props_in_dir(self.out_dir)
                runs["elapse_time"] = elapse_time
                runs["cpu_time"] = cpu_time_per_run

                # Once the runs made, attach it to the converter
                outcome["converters"].append(runs)
                pdf_file_props = file_props(made_pdf_file)
                if pdf_file_props["size"]:
                    outcome["pdf_files"].append(pdf_file)
                    # Remember the compiler if it's not set
                    if self.zzrm.compilation.get("compiler") is None:
                        self.zzrm.set_tex_compiler(self.converter.tex_compiler_name())
                    pass
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
                        conv_log = desc + l30 + ["",
                                          f"<{len(conv_log) - len(l30) - len(ll50)} lines removed>",
                                          ""] + ll50
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
                break

            # For next iteration, clean up the in-dir
            for artifact in artifacts:
                from_file = os.path.join(self.in_dir, artifact)
                os.remove(from_file)
                pass
            pass

        # Keep the all of converters' runs (except the files created)
        outcome["total_time"] = time.perf_counter() - self.t0
        outcome["total_cpu_time"] = time.process_time() - start_process_time


    def unused_pics(self) -> list[str]:
        """Returns the list of unused pics
        return the path, not the file name
        """
        return [maybe for maybe in find_unused_toplevel_files(self.in_dir, self.tex_files) \
                if test_file_extent(maybe, graphics_exts)]

    def _finalize_pdf(self) -> None:
        """TeX has done its work. It may still need some things added to the PDF.
        First, we say the top-level graphics files appended.
        Second, we want the PDF watermarked.

        Note that, 00README.XXX can suppress the graphics addition, and watermarking.

https://info.arxiv.org/help/submit_tex.html#latex
Note that adding a 00README.XXX with a toplevelfile directive will only effect the processing order and not the final assembly order of the pdf.

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

            # Docs v2 does not change the compiled order
            docs_v2 = [f"out/{pdf_file}" for pdf_file in pdf_files]
            if self.zzrm and self.zzrm.version == 1:
                docs = sorted(docs_v2)
                pic_adds = self.unused_pics()[:self.max_appending_files]
            else:
                docs = docs_v2
                pic_adds = self.unused_pics()[:self.max_appending_files]

            # Does the converter class support pic additions?
            if self.converter and self.converter.__class__.yes_pix():
                docs += [f"in/{pic}" for pic in pic_adds]

            # Note the available documents that can be bombined.
            outcome["available_documents"] = docs

            # After all the trouble, if assembling_files is designated in post process, use it.
            # Here, instead of taking the raw, match the basenames and list the docs in the
            # order that appears in the assembling files. If it is missing in either, it is
            # ignored.
            if self.zzrm and self.zzrm.version > 1 and self.zzrm.assembling_files:
                # Lay out the ingredients
                ingredients = {os.path.basename(doc) : doc for doc in docs}
                cooked = []
                # Follow the recipe
                for ingredient in self.zzrm.assembling_files:
                    doc = ingredients.get(ingredient)
                    if doc:
                        cooked.append(doc)
                    else:
                        # If an ingredient is missing, error
                        raise AssemblingFileNotFound(f'File {ingredient} is not found in ' + repr(ingredients.keys()))
                # Replace the docs to make with the cooked ingredients
                docs = cooked
                # When the assembling is designated, don't truncate
                self.max_appending_files = len(docs)

            # Docs decided
            outcome["documents"] = docs
            docs = [os.path.join(self.work_dir, doc) for doc in docs]
            final_pdf, used_gfx, unused_gfx, addon_outcome = \
                combine_documents(docs, self.out_dir, merged_pdf, log_extra=self.log_extra)
            outcome |= addon_outcome
            self.zzrm.set_assembling_files(used_gfx)
            outcome["pdf_file"] = final_pdf
            outcome["used_figures"] = used_gfx
            outcome["unused_figures"] = self.unused_pics()[self.max_appending_files:] + unused_gfx
        except PdfError as exc:
            logger.warning("Failed combining PDFs: %s", exc, extra=self.log_extra)
            pass
        except AssemblingFileNotFound as exc:
            logger.warning("Failed combining PDFs: %s", exc, extra=self.log_extra)
            pass
        except Exception as exc:
            if isinstance(exc, (subprocess.TimeoutExpired, subprocess.CalledProcessError)):
                logger.warning("Failed combining PDFs: %s", exc, extra=self.log_extra)
                outcome["gs"] = {}
                if isinstance(exc, subprocess.CalledProcessError):
                    outcome["gs"]["return_code"] = exc.returncode
                outcome["gs"]["timeout"] =  True
                # mypy believes that exc does not have stdout/stderr, but both
                # exceptions contain these values
                outcome["gs"]["stdout"] = exc.stdout # type: ignore
                outcome["gs"]["stderr"] = exc.stderr # type: ignore
            else:
                raise exc

        if self.water.text and (not self.zzrm.nostamp):
            pdf_file = os.path.join(self.out_dir, outcome["pdf_file"])
            temp_name = outcome["pdf_file"] + ".watermarked.pdf"
            watered = self._watermark(pdf_file, os.path.join(self.out_dir, temp_name))

            if os.path.exists(watered):
                outcome["watermark"] = self.water
                os.rename(watered, pdf_file)
                pass
            pass
        return


    def _unpack_tarball(self) -> None:
        """Unpack the tarballs. Make sure the permissions - tar can set nasty perms."""
        local_tarball = os.path.join(self.in_dir, self.source)
        unpack_tarball(self.in_dir, local_tarball, self.log_extra)
        chmod_775(self.work_dir)
        pass

    def _watermark(self, pdf_file: str, watered: str | None = None) -> str:
        """Watermark the PDF file. Watered is the result filename."""
        output = pdf_file
        if self.water.text:
            logger = get_logger()
            if watered is None:
                watered = os.path.join(os.path.dirname(pdf_file),
                                       "watermarked-" + os.path.basename(pdf_file))
                pass
            try:
                add_watermark_text_to_pdf(self.water, pdf_file, watered)
                output = watered
            except Exception as _exc:
                logger.warning("Failed creating %s", watered, exc_info=True,
                               extra=self.log_extra)
                pass
            pass
        return output

    pass


class ConversionOutcomeMaker:
    """Conversion outcome packer/unpacker.

    This can be part of driver. It makes the class methods a touch longer. So, make this part
    done by a visitor class.
    """

    def __init__(self, work_dir: str, tag: str, outcome_file: str|None=None):
        self.work_dir = work_dir
        self.tag = tag
        self.outcome_file = f"{tag}.outcome.tar.gz" if outcome_file is None else outcome_file
        self.log_extra = {ID_TAG: self.tag}
        pass

    def create_outcome(self, converter_driver: ConverterDriver, outcome: dict,
                       conversion_meta: dict | None=None,
                       outcome_files: list[str] | None=None,
                       more_files: list[str] | None=None) -> None:
        """
        works as the visitor to the converter to generate outcome and upload.
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
        zzrm_generated = io.StringIO()
        zzrm.to_yaml(zzrm_generated)
        zzrm_generated.seek(0)
        zzrm_text = zzrm_generated.read()
        outcome_meta = {
            "version": 1,  # outcome format version
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
            outcome_meta.update(outcome)
        outcome_meta_file = f"outcome-{self.tag}.json"
        with open(os.path.join(self.work_dir, outcome_meta_file), "w", encoding='utf-8') as fd:
            json.dump(outcome_meta, fd, indent=2)
            pass
        bod = os.path.basename(out_dir)
        if more_files is None:
            more_files = []
            pass
        taring = more_files + [f"{bod}/{fname}" for fname in outcome_files]
        # double-check the files exist
        taring = [ofile for ofile in taring if os.path.exists(os.path.join(self.work_dir, ofile))]
        tar_cmd = ["tar", "czf", self.outcome_file, outcome_meta_file] + taring
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
        logger.debug(f"Unpacked files of {self.outcome_file}: {repr(files)}", extra=self.log_extra)
        outcome_meta_file = f"outcome-{self.tag}.json"
        try:
            for filename in files:
                if filename == outcome_meta_file:
                    with open(os.path.join(self.work_dir, filename), encoding='utf-8') as fd:
                        meta = json.load(fd)
                        pass
                    pass
                pass
            pass
        except Exception as _exc:
            pass
        return meta
