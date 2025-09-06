"""Compile a tarball via the service URL to an outcome file."""

import json
import logging
import os
import tarfile
import time
import traceback
import typing

import requests

from .service_logger import get_logger


def get_outcome_meta(outcome_file: str) -> dict:
    """Open a compressed outcome tar archive and get the metadata."""
    meta = {}
    with tarfile.open(outcome_file, "r:gz") as outcome:
        for name in outcome.getnames():
            if name.startswith("outcome-") and name.endswith(".json"):
                meta_contents = outcome.extractfile(name)
                if meta_contents:
                    meta.update(json.load(meta_contents))
    return meta


def convert_pdf_remote(
    compile_service: str,
    arxivid: str | None,
    tempdir: str,
    tag: str,
    source: str,
    use_addon_tree: bool,
    timeout: float | None,
    max_tex_files: int | None,
    max_appending_files: int | None,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
    log_extra: dict[str, typing.Any] = {},
) -> tuple[int, str]:
    logger = get_logger()
    tarball = os.path.join(tempdir, source)
    # make sure we have a trailing slash
    compile_service = compile_service.rstrip("/") + "/"
    with open(tarball, "rb") as data_fd:
        uploading = {"incoming": (source, data_fd, "application/gzip")}
        retries = 2
        for attempt in range(1 + retries):
            try:
                if compile_service.endswith("convert/"):
                    args_dict = {
                        "timeout": timeout,
                        "use_addon_tree": use_addon_tree,
                        "max_tex_files": max_tex_files,
                        "max_appending_files": max_appending_files,
                        "watermark_text": watermark_text,
                        "watermark_link": watermark_link,
                        "auto_detect": auto_detect,
                        "hide_anc_dir": hide_anc_dir,
                    }
                else:
                    args_dict = {
                        "timeout": timeout,
                        "arxivid": arxivid,
                    }
                logger.debug("POST URL: %s, args = %s", compile_service, args_dict, extra=log_extra)
                logger.debug("uploading = %s", uploading, extra=log_extra)
                try:
                    res = requests.post(
                        compile_service,
                        files=uploading,
                        timeout=timeout,
                        allow_redirects=False,
                        params=args_dict,
                    )
                except ConnectionError as e:
                    logger.warning(
                        "Failed to submit tarball %s to %s, connection error: %s",
                        tarball,
                        compile_service,
                        e,
                        extra=log_extra,
                    )
                    return 422, "Failed to submit tarball: connection error"
                status_code = res.status_code
                logger.debug("Received status code %d from POST to %s", status_code, res.url, extra=log_extra)
                if status_code == 504:
                    # This is the only place we retry, and at most 3 times in total.
                    logger.warning("Got 504 for %s", compile_service, extra=log_extra)
                    time.sleep(1)
                    # we need to rewind the data_fd otherwise the next request will send
                    # an empty file.
                    data_fd.seek(0)
                    continue

                # Deal with failures
                if status_code == 400 or status_code == 422 or status_code == 500:
                    logger.warning(
                        "Failed to submit tarball %s to %s, status code: %d, %s",
                        tarball,
                        compile_service,
                        status_code,
                        res.text,
                        extra=log_extra,
                    )
                    return status_code, f"Failed to submit tarball: {res.text}"

                elif status_code == 200:
                    # it would be better to forward the streaming response directly to the caller
                    # one approach is explained here: https://stackoverflow.com/a/73299661
                    if res.content:
                        out_filename = f"{tag}-outcome.tar.gz"
                        out_path = os.path.join(tempdir, out_filename)
                        with open(out_path, "wb") as out_file:
                            out_file.write(res.content)
                        return status_code, out_path
                    else:
                        logger.warning(
                            "Failed to submit tarball %s to %s, status code: %d, %s",
                            tarball,
                            compile_service,
                            status_code,
                            res.text,
                            extra=log_extra,
                        )
                        return status_code, "Failed to submit tarball: {res.text}"
                else:
                    logger.warning(
                        "Unexpected status code %d from %s: %s",
                        status_code,
                        compile_service,
                        res.text,
                        extra=log_extra,
                    )
                    return status_code, f"Unexpected status code: {status_code}"

            except TimeoutError:
                logger.warning("%s: Connection to %s timed out", tarball, compile_service, extra=log_extra)
                return 500, "Timeout contacting remote service"
            except Exception as exc:
                logger.warning("Exception submitting tarball: %s", exc, exc_info=True, extra=log_extra)
                logger.warning("%s: %s", tarball, str(exc), extra=log_extra)
                return 500, "General exception: " + traceback.format_exc()
        logger.error(
            "Failed to submit tarball %s to %s after %d attempts", tarball, compile_service, retries, extra=log_extra
        )
        return 500, "Failed to submit tarball after multiple attempts"


def service_process_tarball(
    service: str,
    tempdir: str,
    tarball: str,
    outcome_file: str,
    tex2pdf_timeout: int,
    post_timeout: int,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
    log_extra: dict[str, typing.Any] = {},
) -> bool:
    """Submit tarball to compilation service and receive result."""
    if os.path.exists(outcome_file):
        raise FileExistsError(f"Outcome file {outcome_file} already exists!")
    os.makedirs(os.path.dirname(outcome_file), exist_ok=True)
    logging.info("File: %s", os.path.basename(tarball))
    meta = {}
    status_code = None

    status_code, msg = convert_pdf_remote(
        service,
        None,
        tempdir,
        os.path.basename(tarball),
        tarball,
        False,
        post_timeout,
        auto_detect=auto_detect,
        hide_anc_dir=hide_anc_dir,
        log_extra=log_extra,
    )

    if status_code == 200:
        meta = get_outcome_meta(msg)

    success = meta.get("status") == "success"
    logging.log(
        logging.INFO if success else logging.WARNING,
        "submit: %s (%s) %s",
        os.path.basename(tarball),
        str(status_code),
        success,
    )
    return success
