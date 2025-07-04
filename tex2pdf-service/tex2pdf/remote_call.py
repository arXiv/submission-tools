"""Compile a tarball via the service URL to an outcome file."""

import json
import os
import tarfile
import time
import traceback
import typing

import requests

from . import (
    TEX2PDF_KEYS_TO_URLS,
    TEX2PDF_SCOPES,
    TEXLIVE_BASE_RELEASE,
)
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


def determine_compilation_system(ts: int | None, texlive_version: int | None) -> str:
    """Determine the compilation system based on TEX2PDF_SCOPES and the given arXiv ID."""
    logger = get_logger()
    # texlive_version takes priority:
    if texlive_version is not None:
        if str(texlive_version) == TEXLIVE_BASE_RELEASE:
            # the requested version is the one included in the current docker image
            logger.debug("Detected tex system via ZZRM: current (%s)", TEXLIVE_BASE_RELEASE)
            return "current"
        # if we have a texlive version, we can use it to determine the
        # compilation system.
        # We assume that our keys are called "tl2025" etc
        tlver = f"tl{texlive_version}"
        logger.debug("Using texlive version %s to determine compilation system", texlive_version)
        if tlver in TEX2PDF_KEYS_TO_URLS:
            logger.debug("Detected tex system via ZZRM: %s", tlver)
            return TEX2PDF_KEYS_TO_URLS[tlver]
        else:
            raise ValueError(f"Undefined TeX Live version requested in ZZRM: {tlver}")
    # we need to look into identifier
    # and select either local _generate_pdf or remote depending on the
    # time frame
    # Input comes from an environment variable
    # TEX2PDF_DATE_SCOPES="tetex2:CUTOF1:tetex3:CUTOF1:tl2009:...:CUTOFN:tl2023"
    # with the interpretations:
    # - submission date < CUTOF1 -> use tetex2
    # - CUTOF1 <= submission date < CUTOF2 -> use tetex3
    # ...
    # - CUTOFEND <= submission date -> use tl2023
    # Format of CUTOVERXXX: epoch seconds!
    # all of the following is only necessary if we actually have multiple
    # TeX systems running
    if ts is None:
        tex_system_key = "current"
    elif TEX2PDF_SCOPES != "":
        scope_list: list[str] = TEX2PDF_SCOPES.split(":")
        if len(scope_list) % 2:
            # uneven length is not good
            raise ValueError(f"Invalid scope definition: {scope_list}")
        # check for correct format and ordering!
        last_date: float = 0
        for tex_key, cut_of_day in [scope_list[i : i + 2] for i in range(len(scope_list))[::2]]:
            if tex_key not in TEX2PDF_KEYS_TO_URLS.keys():
                raise ValueError(f"Invalid tex key: {tex_key}")
            curr_date: float = float(cut_of_day)
            if curr_date < last_date:
                raise ValueError(f"Invalid scope definition, not increasing time stamps: {scope_list}")
            last_date = curr_date
        tex_system_key: str | None = None
        for tex_key, cut_of_day in [scope_list[i : i + 2] for i in range(len(scope_list))[::2]]:
            logger.debug("Checking submission date against curdate: %s", cut_of_day)
            curr_date = float(cut_of_day)
            if ts < curr_date:
                tex_system_key = tex_key
                break
        if tex_system_key is None:
            tex_system_key = "current"
    else:
        # no compilation services defined, we always use current
        tex_system_key = "current"
    logger.debug("Detected tex system: %s", tex_system_key)
    if tex_system_key == "current":
        compile_service = tex_system_key
    else:
        # we already checked above that all entries in the scope list are
        # available in the GEN_PDF_KEYS_TO_URLS hash.
        compile_service = TEX2PDF_KEYS_TO_URLS[tex_system_key]
    return compile_service


def submit_tarball(
    compile_service: str,
    tempdir: str,
    tag: str,
    source: str,
    use_addon_tree: bool,
    timeout: float,
    max_tex_files: int | None,
    max_appending_files: int | None,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
    log_extra: dict[str, typing.Any] | None = None,
    api_args: dict | None = None,
    outcome_file: str | None = None,
) -> tuple[int, str | dict | None]:
    logger = get_logger()
    if api_args is None:
        api_args = {}
    if log_extra is None:
        log_extra = {}
    tarball = os.path.join(tempdir, source)
    with open(tarball, "rb") as data_fd:
        uploading = {"incoming": (source, data_fd, "application/gzip")}
        retries = 2
        for attempt in range(1 + retries):
            try:
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
                args_dict.update(api_args)
                logger.debug("POST URL: %s, args = %s", compile_service, args_dict, extra=log_extra)
                logger.debug("uploading = %s", uploading, extra=log_extra)
                res = requests.post(
                    compile_service,
                    files=uploading,
                    timeout=timeout,
                    allow_redirects=False,
                    params=args_dict,
                )
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
                    data = res.json()
                    return status_code, f"Failed to submit tarball: {data['message']}"

                elif status_code == 200:
                    # it would be better to forward the streaming response directly to the caller
                    # one approach is explained here: https://stackoverflow.com/a/73299661
                    if res.content:
                        if "application/json" in res.headers.get("Content-Type", ""):
                            return 200, json.loads(res.content)
                        if outcome_file:
                            out_path = outcome_file
                        else:
                            out_filename = f"{tag}-outcome.tar.gz"
                            out_path = os.path.join(tempdir, out_filename)
                        with open(out_path, "wb") as out_file:
                            out_file.write(res.content)
                        return 200, out_path
                    else:
                        logger.warning(
                            "Failed to submit tarball %s to %s, status code: %d, %s",
                            tarball,
                            compile_service,
                            status_code,
                            res.text,
                            extra=log_extra,
                        )
                        return status_code, f"Failed to submit tarball: {res.text}"
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
