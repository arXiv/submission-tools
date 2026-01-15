"""Turn multiple documents into one PDF."""

import os
import shlex
import shutil
import subprocess

from PIL import Image, UnidentifiedImageError

from . import graphics_exts
from .service_logger import get_logger


def convert_image_to_pdf(image_path: str, pdf_path: str) -> str:
    """Convert an image to a PDF."""
    image: Image.Image = Image.open(image_path)
    try:
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(pdf_path, "PDF", resolution=100.0)
    finally:
        image.close()
        pass
    return pdf_path


def strip_to_basename(path_list: list[str], extent: None | str = None) -> list[str]:
    """Strip the path to the basename."""
    if extent is None:
        return [os.path.basename(path) for path in path_list]
    return [os.path.splitext(os.path.basename(path))[0] + extent for path in path_list]


def combine_documents(
    doc_list: list[str], out_dir: str, out_filename: str, log_extra: dict | None = None
) -> tuple[str, list, list, dict]:
    """Combine multiple PDFs and maybe some pictures, and images into one PDF.

    Args:
        doc_list (list): List of documents. (can be in any dir)
        out_dir (str): Output directory.
        out_filename (str): Name of output PDF.
        log_extra (dict): Extra logging information.
    """
    output_path = os.path.join(out_dir, out_filename)
    converted_docs: list[str] = []
    failed_docs: list[str] = []
    addon_outcome: dict[str, dict] = {}
    # if we have only one pdf document in the list, return it as is
    if len(doc_list) == 1 and doc_list[0].lower().endswith(".pdf"):
        if doc_list[0] != output_path:
            shutil.move(doc_list[0], output_path)
        converted_docs.append(os.path.basename(doc_list[0]))
        return out_filename, converted_docs, failed_docs, addon_outcome

    logger = get_logger()
    effective_pdf_list = []
    # first collection list of pdfs to be combined (normal and converted images)
    for doc_path in doc_list:
        [stem, ext] = os.path.splitext(doc_path)
        # This should exist but be safe.
        if not os.path.exists(doc_path):
            logger.warning("Document requested to be joined is not available: %s", doc_path, extra=log_extra)
            continue
        if ext.lower() == ".pdf":  # This should not need lower() but be safe. Should I assert?
            effective_pdf_list.append(doc_path)
        elif ext.lower() in graphics_exts:
            temp_pdf = os.path.join(out_dir, stem + ".pdf")
            try:
                pdf_filename = convert_image_to_pdf(doc_path, temp_pdf)
                if pdf_filename and os.path.exists(pdf_filename):
                    effective_pdf_list.append(temp_pdf)
                    converted_docs.append(doc_path)
            except UnidentifiedImageError:
                failed_docs.append(doc_path)
                logger.warning("Unsupported %s", doc_path, extra=log_extra)
            except Exception as _exc:
                failed_docs.append(doc_path)
                logger.warning("Unknown error %s", doc_path, extra=log_extra, exc_info=True)
    if len(effective_pdf_list) == 0:
        # this should not happen, we should have at least one pdf from the tex file
        raise Exception("No documents have been found.")
    if len(effective_pdf_list) == 1:
        # we didn't return above where we check for len(doc_list) == 1
        # so this is an image that has been converted to pdf.
        # Somehow surprising ... do we have such submissions?
        if effective_pdf_list[0] != output_path:
            shutil.move(effective_pdf_list[0], output_path)
        converted_docs.append(os.path.basename(effective_pdf_list[0]))
        return out_filename, strip_to_basename(converted_docs), strip_to_basename(failed_docs), addon_outcome

    # call gs to combine the pdf
    # we cannot use pikepdf (easily) here since it breaks annotations (links)
    combine_programs_priority_list = ["pdfcpu", "gs", "pdftk"]
    combine_programs = {
        "gs": [
            "gs",
            "-sDEVICE=pdfwrite",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            f"-sOutputFile={output_path}",
            *effective_pdf_list,
        ],
        "pdftk": ["pdftk", *effective_pdf_list, "cat", "output", output_path],
        "pdfcpu": ["pdfcpu", "merge", "-offline", output_path, *effective_pdf_list],
    }
    for prog in combine_programs_priority_list:
        cmds = combine_programs[prog]
        logger.debug("Running %s to combine pdfs: %s", prog, shlex.join(cmds), extra=log_extra)
        try:
            ret = subprocess.run(cmds, capture_output=True, timeout=60, check=True, text=True)
        except subprocess.TimeoutExpired as e:
            logger.warning("%s command timed out, trying next: %s", prog, e, extra=log_extra)
            continue
        except subprocess.CalledProcessError as e:
            logger.warning(
                "%s command failed, trying next. returncode: %s, output: %s",
                prog,
                e.returncode,
                e.output,
                extra=log_extra,
            )
            continue
        if not ret:
            raise Exception("Concatenation of PDF files failed with all programs, giving up.")
        addon_outcome["pdfconcat"] = {}
        addon_outcome["pdfconcat"]["prog"] = prog
        addon_outcome["pdfconcat"]["stdout"] = ret.stdout
        addon_outcome["pdfconcat"]["stderr"] = ret.stderr
        addon_outcome["pdfconcat"]["return_code"] = ret.returncode
        break
    return out_filename, strip_to_basename(converted_docs), strip_to_basename(failed_docs), addon_outcome
