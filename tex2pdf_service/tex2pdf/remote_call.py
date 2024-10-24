"""Compile a tarball via the service URL to an outcome file."""

import json
import logging
import os
import tarfile
import time

import requests


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


def service_process_tarball(service: str, tarball: str, outcome_file: str, tex2pdf_timeout: int, post_timeout: int, auto_detect: bool = False) -> bool:
    """Submit tarball to compilation service and receive result."""
    if os.path.exists(outcome_file):
        raise FileExistsError(f"Outcome file {outcome_file} already exists!")
    os.makedirs(os.path.dirname(outcome_file), exist_ok=True)
    logging.info("File: %s", os.path.basename(tarball))
    meta = {}
    status_code = None

    with open(tarball, "rb") as data_fd:
        uploading = {"incoming": (os.path.basename(tarball), data_fd, "application/gzip")}
        while True:
            try:
                post_url = service + f"?timeout={tex2pdf_timeout}&auto_detect={auto_detect}"
                logging.debug("POST URL: %s", post_url)
                logging.debug("uploading = %s", uploading)
                res = requests.post(
                    post_url,
                    files=uploading,
                    timeout=post_timeout,
                    allow_redirects=False,
                )
                status_code = res.status_code
                if status_code == 504:
                    logging.warning("Got 504 for %s", service)
                    time.sleep(1)
                    continue

                if status_code == 200:
                    if res.content:
                        with open(outcome_file, "wb") as out:
                            out.write(res.content)
                        meta = get_outcome_meta(outcome_file)
            except TimeoutError:
                logging.warning("%s: Connection timed out", tarball)

            except Exception as exc:
                logging.warning("Exception submitting tarball: %s", exc)
                logging.warning("%s: %s", tarball, str(exc))
            break

    success = meta.get("status") == "success"
    logging.log(
        logging.INFO if success else logging.WARNING,
        "submit: %s (%s) %s",
        os.path.basename(tarball),
        str(status_code),
        success,
    )
    return success
