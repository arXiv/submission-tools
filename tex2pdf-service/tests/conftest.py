"""Pytest configuration file."""

import json
import logging
import os
import subprocess
import time
import urllib

import requests
from bin.compile_submissions import get_outcome_meta_and_files_info

os.environ.setdefault("TEXLIVE_BASE_RELEASE", "2025")


def pytest_addoption(parser):
    """Add command line options to pytest."""
    parser.addoption("--keep-docker-running", action="store_true", help="keep docker image running")
    parser.addoption("--no-docker-setup", action="store_true", help="do not run docker setup, expect a running docker")
    parser.addoption(
        "--docker-port-2023", action="store", default="33031", help="outside docker port to use for TL2023"
    )


def submit_tarball(
    service: str,
    tarball: str,
    outcome_file: str,
    tex2pdf_timeout: int = 300,
    post_timeout: int = 300,
    json_response: bool = False,
    api_args: dict = {},
) -> tuple[None | dict, int]:
    meta = None
    params_dict = {"timeout": tex2pdf_timeout}
    params_dict.update(api_args)
    url = f"{service}/"
    logging.debug(f"Submitting {service} with params {params_dict} and tarball {tarball}")
    with open(tarball, "rb") as data_fd:
        uploading = {"incoming": (os.path.basename(tarball), data_fd, "application/gzip")}
        while True:
            try:
                res = requests.post(
                    url, files=uploading, timeout=post_timeout, allow_redirects=False, params=params_dict
                )
                logging.debug(f"Posted to {res.url}")
                status_code = res.status_code
                if status_code == 504:
                    logging.warning("Got 504 for %s", service)
                    time.sleep(1)
                    continue

                if status_code == 200:
                    if res.content:
                        if json_response:
                            return json.loads(res.content), 200
                        else:
                            os.makedirs(os.path.dirname(outcome_file), exist_ok=True)
                            with open(outcome_file, "wb") as out:
                                out.write(res.content)
                            meta, lines, clsfiles, styfiles, pdfchecksum, _ = get_outcome_meta_and_files_info(
                                outcome_file
                            )

                else:
                    logging.warning("%s: status code %d, %s", url, status_code, res.text)
                    # load "message" from response
                    data = res.json()
                    return data["message"], status_code

            except TimeoutError:
                logging.warning("%s: Connection timed out", tarball)
                status_code = 500

            except Exception as exc:
                logging.warning("%s: %s", tarball, str(exc))
                status_code = 500

            break

    return meta, status_code


def submit_file(
    service: str,
    fname: str,
    outcome_file: str,
    tex2pdf_timeout: int = 30,
    post_timeout: int = 10,
    json_response: bool = False,
    api_args: dict = {},
) -> int:
    params_dict = {}
    params_dict.update(api_args)
    params = urllib.parse.urlencode(params_dict)
    url = f"{service}/?{params}"
    with open(fname, "rb") as data_fd:
        uploading = {"incoming": (os.path.basename(fname), data_fd, "application/pdf")}
        while True:
            try:
                res = requests.post(url, files=uploading, timeout=post_timeout, allow_redirects=False)
                status_code = res.status_code
                if status_code == 504:
                    logging.warning("Got 504 for %s", service)
                    time.sleep(1)
                    continue

                if status_code == 200:
                    if res.content:
                        if json_response:
                            return json.loads(res.content), 200
                        else:
                            os.makedirs(os.path.dirname(outcome_file), exist_ok=True)
                            with open(outcome_file, "wb") as out:
                                out.write(res.content)

                else:
                    logging.warning("%s: status code %d", url, status_code)

            except TimeoutError:
                logging.warning("%s: Connection timed out", fname)
                status_code = 500

            except Exception as exc:
                logging.warning("%s: %s", fname, str(exc))
                status_code = 500

            break

    return status_code


def _start_docker_container(
    image_name: str,
    container_name: str,
    external_port: int,
    extra_args: list[str] = [],
    internal_port: int = 8080,
    gvisor: bool = True,
):
    """Start the docker container if it is not already running."""
    # Start the container
    GVISOR_ARGS = ["--runtime=runsc", "-e", "ENABLE_SANDBOX=1"] if gvisor else []
    # fmt: off
    args = [
        "docker", "run",
        *GVISOR_ARGS,
        "--security-opt", "no-new-privileges=true",
        "--cpus", "1",
        "--rm", "-d",
        "-p", f"{external_port}:{internal_port}",
        "-e", f"PORT={internal_port}",
        *extra_args,
        "--name", container_name,
        image_name,
    ]
    # fmt: on
    docker = subprocess.run(args, encoding="utf-8", capture_output=True, check=False)
    if docker.returncode != 0:
        logging.error(f"tex2pdf container {container_name} did not start")


def _check_docker_api_ready(container_name: str, external_port: int):
    url = f"http://localhost:{external_port}"
    for _ in range(60):  # retries for 60 seconds
        try:
            response = requests.get(url)
            if response.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(1)
    else:
        with open(f"{container_name}.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_name], stdout=log, stderr=log)
        raise RuntimeError(f"API at {container_name} did not start in time")
