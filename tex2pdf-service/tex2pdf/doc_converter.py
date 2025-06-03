"""Turn multiple documents into one PDF."""

import os
import shlex
import shutil
import subprocess
import threading
import time
from typing import IO

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


def read_stream_continuously(stream: IO[str], output_list: list[str], stop_event: threading.Event) -> None:
    """Read a given stream (stdout or stderr) continuously and appends lines to a list."""
    logger = get_logger()
    for line in iter(stream.readline, ""):
        if stop_event.is_set():
            break
        logger.debug(line)
        output_list.append(line.strip())
    stream.close()


def run_subprocess_with_timeout(command: list[str], timeout_seconds: int = 60) -> tuple[list[str], list[str], int]:
    """
    Start a subprocess with a timeout, read and report stdout/stderr continously.

    Starts a subprocess, reads its stdout and stderr continuously,
    ensures it does not run longer than the specified timeout, and
    returns all collected stdout and stderr.
    """
    logger = get_logger()
    logger.info(f"Attempting to run command: {' '.join(command)}")
    logger.info(f"Timeout set to: {timeout_seconds} seconds")

    process = None
    stdout_thread = None
    stderr_thread = None
    stop_event = threading.Event()

    collected_stdout: list[str] = []
    collected_stderr: list[str] = []
    return_code = None

    try:
        # Start the subprocess
        # stderr=subprocess.PIPE to capture stderr separately
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,  # Capture stderr separately
            text=True,
        )

        # Start a thread to read stdout continuously
        stdout_thread = threading.Thread(
            target=read_stream_continuously, args=(process.stdout, collected_stdout, stop_event)
        )
        stdout_thread.daemon = True
        stdout_thread.start()

        # Start a thread to read stderr continuously
        stderr_thread = threading.Thread(
            target=read_stream_continuously, args=(process.stderr, collected_stderr, stop_event)
        )
        stderr_thread.daemon = True
        stderr_thread.start()

        start_time = time.time()
        while process.poll() is None:
            if time.time() - start_time > timeout_seconds:
                print(f"\nTimeout of {timeout_seconds} seconds reached. Terminating subprocess.")
                process.terminate()
                time.sleep(0.1)
                if process.poll() is None:
                    print("Subprocess did not terminate gracefully, killing it.")
                    process.kill()
                break
            time.sleep(0.1)

        # Signal threads to stop and wait for them to finish reading
        stop_event.set()
        if stdout_thread.is_alive():
            stdout_thread.join(timeout=5)
        if stderr_thread.is_alive():
            stderr_thread.join(timeout=5)

        # Wait for the subprocess to officially terminate and get its return code
        return_code = process.wait()
        print(f"\nSubprocess finished with return code: {return_code}")

    except FileNotFoundError:
        logger.error(f"Error: Command '{command[0]}' not found. Please ensure it's in your PATH.")
        return_code = 127  # Common exit code for command not found
        collected_stderr.append(f"Error: Command '{command[0]}' not found.")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        collected_stderr.append(f"An unexpected error occurred: {e}")
        return_code = 1  # Generic error code
    finally:
        if process and process.poll() is None:
            logger.warning("Ensuring subprocess is terminated in finally block.")
            process.terminate()
            process.wait(timeout=5)
            if process.poll() is None:
                process.kill()

    return collected_stdout, collected_stderr, return_code


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
    gs_cmd = [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        f"-sOutputFile={output_path}",
        *effective_pdf_list,
    ]
    pdftk_cmd = [
        "pdftk",
        *effective_pdf_list,
        "cat",
        "output",
        output_path,
        "verbose",
    ]
    logger.debug("Running gs to combine pdfs: %s", shlex.join(gs_cmd), extra=log_extra)
    out, err, ret = run_subprocess_with_timeout(gs_cmd, timeout_seconds=60)
    if ret != 0:
        logger.error("gs command failed with return code %d", ret, extra=log_extra)
        # if gs fails, we try pdftk
        logger.warning("Trying pdftk to combine pdfs as gs failed.", extra=log_extra)
        logger.debug("Running pdftk to combine pdfs: %s", shlex.join(pdftk_cmd), extra=log_extra)
        out, err, ret = run_subprocess_with_timeout(pdftk_cmd, timeout_seconds=60)
        if ret != 0:
            logger.error("pdftk command failed with return code %d", ret, extra=log_extra)
            raise Exception(f"Failed to combine documents: {err}")
    addon_outcome["gs"] = {}
    addon_outcome["gs"]["stdout"] = out
    addon_outcome["gs"]["stderr"] = err
    addon_outcome["gs"]["return_code"] = ret
    return out_filename, strip_to_basename(converted_docs), strip_to_basename(failed_docs), addon_outcome
