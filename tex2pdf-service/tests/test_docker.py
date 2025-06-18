import json
import logging
import os
import shutil
import subprocess
import time
import urllib.parse

import pytest
import requests
from bin.compile_submissions import get_outcome_meta_and_files_info
from tex2pdf.converter_driver import RemoteConverterDriver

PORT_2023 = 33031
PORT_2025 = 33032
# default proxy is TL2024
# since we run --network host for tl2024 docker, the app listens on the internal port
PORT_DEFAULT = 8080
SELF_DIR = os.path.abspath(os.path.dirname(__file__))

TL2023_CUTOFF = 1748736000
TL2023_TS = TL2023_CUTOFF - 100


def submit_tarball(
    service: str,
    tarball: str,
    outcome_file: str,
    tex2pdf_timeout: int = 30,
    post_timeout: int = 10,
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
                print(f"POSTED TO {res.url}")
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
                            meta, lines, clsfiles, styfiles, pdfchecksum = get_outcome_meta_and_files_info(outcome_file)

                else:
                    logging.warning("%s: status code %d", url, status_code)

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
    image_name: str, container_name: str, external_port: int, extra_args: list[str] = [], internal_port: int = 8080
):
    """Start the docker container if it is not already running."""
    # Start the container
    args = [
        "docker",
        "run",
        "--security-opt",
        "no-new-privileges=true",
        "--cpus",
        "1",
        "--rm",
        "-d",
        "-p",
        f"{external_port}:{internal_port}",
        "-e",
        f"PORT={internal_port}",
        *extra_args,
        "--name",
        container_name,
        image_name,
    ]
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


@pytest.fixture(scope="module")
def docker_container(request):
    global PORT_2023  # noqa: PLW0603
    global PORT_2025  # noqa: PLW0603
    PORT_2023 = request.config.getoption("--docker-port-2023")
    PORT_2025 = request.config.getoption("--docker-port-2025")

    image_2023_name = "public-tex2pdf-app-2023-2023-05-21"
    image_2024_name = "public-tex2pdf-app-2024-2024-12-29"
    image_2025_name = "public-tex2pdf-app-2025-2025-05-11"
    container_2023_name = "test-arxiv-tex2pdf-2023"
    container_2024_name = "test-arxiv-tex2pdf-2024"
    container_2025_name = "test-arxiv-tex2pdf-2025"

    if not request.config.getoption("--no-docker-setup"):
        subprocess.call(["docker", "kill", container_2023_name])
        subprocess.call(["docker", "kill", container_2024_name])
        subprocess.call(["docker", "kill", container_2025_name])

        # Make sure the container is the latest
        args = ["make", "app.docker"]
        make = subprocess.run(args, encoding="utf-8", capture_output=True, check=False)
        if make.returncode != 0:
            print(make.stdout)
            print(make.stderr)
            pass

        _start_docker_container(image_2023_name, container_2023_name, PORT_2023)
        _start_docker_container(image_2025_name, container_2025_name, PORT_2025)
        # fmt: off
        _start_docker_container(
            image_2024_name, container_2024_name, PORT_DEFAULT,
            [
                "--network", "host",
                "--env",     "TEX2PDF_PROXY_RELEASE=1",
                "--env",     f"TEX2PDF_SCOPES=tl2023:{TL2023_CUTOFF}",
                "--env",     f"TEX2PDF_KEYS_TO_URLS_tl2023=http://localhost:{PORT_2023}/convert/",
                "--env",     f"TEX2PDF_KEYS_TO_URLS_tl2025=http://localhost:{PORT_2025}/convert/",
            ],
        )
        # fmt: on

    _check_docker_api_ready(container_2023_name, PORT_2023)
    _check_docker_api_ready(container_2024_name, PORT_DEFAULT)
    _check_docker_api_ready(container_2025_name, PORT_2025)

    # we test with 2024 as default entry point, and 2023 as fallback
    yield f"http://localhost:{PORT_DEFAULT}"

    if not request.config.getoption("--no-docker-setup") and not request.config.getoption("--keep-docker-running"):
        # Stop the container after tests
        with open(f"{container_2023_name}.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_2023_name], stdout=log, stderr=log)
        with open(f"{container_2024_name}.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_2024_name], stdout=log, stderr=log)
        with open(f"{container_2025_name}.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_2025_name], stdout=log, stderr=log)
        subprocess.call(["docker", "kill", container_2023_name])
        subprocess.call(["docker", "kill", container_2024_name])
        subprocess.call(["docker", "kill", container_2025_name])


@pytest.mark.integration
def test_api_hello(docker_container):
    url = docker_container
    response = requests.get(url)
    if response.status_code != 200:
        print(response.content)
        pass
    assert response.status_code == 200
    pass


# this test doesn't work with the remote compilation since the status changes from 500 to 400 ???
@pytest.mark.integration
def test_api_smoke(docker_container):
    """00README.XXX is bad, so make sure it does not die or anything."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test1/test1.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test1.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is None
    assert status == 500


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_git_hash(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2/test2.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("version_info") is not None
    assert meta.get("version_info") != ""
    assert meta.get("version_info") != "tex2pdf:(unknown)"
    assert meta.get("version_info").startswith("tex2pdf:")


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_test2(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2/test2.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "test2.pdf"
    assert meta.get("tex_files") == ["fake-file-2.tex"]
    # autotex says that the documents are combined alphabetically
    assert meta.get("documents") == ["out/fake-file-2.pdf"]


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_test3(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test3/test3.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test3.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "test3.pdf"
    assert meta.get("tex_files") == ["fake-file-2.tex", "fake-file-1.tex", "fake-file-3.tex"]
    assert meta.get("pdf_files") == ["fake-file-2.pdf", "fake-file-1.pdf", "fake-file-3.pdf"]
    # v2 keeps the order which is what we'd expect
    assert meta.get("documents") == ["out/fake-file-2.pdf", "out/fake-file-1.pdf", "out/fake-file-3.pdf"]


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_test4(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test4/test4.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test4.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "test4.pdf"
    assert meta.get("tex_files") == ["main.tex", "gdp.tex"]
    assert len(meta.get("converters", [])) == 2
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvi2ps, ps2pdf


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_test_anc_ignore(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-anc-ignore/test-anc-ignore.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-anc-ignore.outcome.tar.gz")
    meta, status = submit_tarball(
        url, tarball, outcome, api_args={"auto_detect": "true", "hide_anc_dir": "true", "ts": ts}
    )
    assert meta is not None
    assert meta.get("status") == "fail"


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_test_anc_ignore_no_ancfiles(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test4/test4.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test4.outcome.tar.gz")
    meta, status = submit_tarball(
        url, tarball, outcome, api_args={"auto_detect": "true", "hide_anc_dir": "true", "ts": ts}
    )
    assert meta is not None
    assert meta.get("pdf_file") == "test4.pdf"
    assert meta.get("tex_files") == ["main.tex", "gdp.tex"]
    assert len(meta.get("converters", [])) == 2
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvi2ps, ps2pdf


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_preflight(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test3/test3.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test3.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, json_response=True, api_args={"preflight": "v2", "ts": ts})
    assert meta is not None
    assert meta.get("status").get("key") == "success"
    assert len(meta.get("detected_toplevel_files")) == 3
    assert [f["filename"] for f in meta.get("detected_toplevel_files")] == [
        "fake-file-1.tex",
        "fake-file-2.tex",
        "fake-file-3.tex",
    ]


@pytest.mark.integration
def test_remote2023(docker_container) -> None:
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2/test2.tar.gz")
    out_dir = os.path.join(SELF_DIR, "output/test2-remote")
    url = docker_container + "/convert/"
    tag = os.path.basename(tarball)

    logging.debug("Before instantiating the RemoteConverterDriver")

    shutil.rmtree(out_dir, ignore_errors=True)

    converter = RemoteConverterDriver(url, 600, out_dir, tarball, use_addon_tree=False, tag=tag, auto_detect=True)
    logging.debug("Calling generate_pdf")
    pdf = converter.generate_pdf()
    assert os.path.isfile(f"{out_dir}/outcome-test2.json")
    assert os.path.isfile(f"{out_dir}/out/test2.pdf")
    assert pdf == "test2.pdf"


@pytest.mark.integration
def test_remote2023_anc_ignore(docker_container) -> None:
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-anc-ignore/test-anc-ignore.tar.gz")
    out_dir = os.path.join(SELF_DIR, "output/test-anc-ignore-remote")
    url = docker_container + "/convert/"
    tag = os.path.basename(tarball)
    shutil.rmtree(out_dir, ignore_errors=True)
    converter = RemoteConverterDriver(
        url, 600, out_dir, tarball, use_addon_tree=False, tag=tag, auto_detect=True, hide_anc_dir=True
    )
    pdf = converter.generate_pdf()
    assert pdf is None
    assert os.path.isfile(f"{out_dir}/test-anc-ignore.tar.gz-outcome.tar.gz")


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_missing_graphics(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-missing-img/test-missing-img.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-missing-img.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    # compilation must fail on missing files
    assert meta.get("status") == "fail"


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_missing_glo(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-missing-glo/test-missing-glo.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-missing-glo.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    # compilation must succeed
    assert meta.get("status") == "success"
    # we need two runs, the first one creates the glossary entry
    assert len(meta.get("converters")[0].get("runs")) == 2
    # the first run should have exit code 1, since it misses the not-available glo entry
    assert meta.get("converters")[0].get("runs")[0].get("return_code") == 1


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_api_broken_tex(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-broken-tex/test-broken-tex.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-broken-tex.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    # compilation must succeed
    assert meta.get("status") == "fail"
    # we need two runs, the first one creates the glossary entry
    assert len(meta.get("converters")[0].get("runs")) == 2
    # the first run should have exit code 1, since it misses the not-available glo entry
    assert meta.get("converters")[0].get("runs")[0].get("return_code") == 1
    assert meta.get("converters")[0].get("runs")[1].get("return_code") == 1


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_bbl_32(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-bbl-32/test-bbl-32.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-bbl-32.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "test-bbl-32.pdf"
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 3
    assert "/usr/local/texlive/texmf-biblatex-33" not in meta["converters"][0]["runs"][2].get("log")


@pytest.mark.integration
def test_bbl_33(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-bbl-33/test-bbl-33.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-bbl-33.outcome.tar.gz")
    # need to send this tl tl2023 container, thus give timestamp according to TEX2PDF_SCOPES
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": TL2023_TS})
    assert meta is not None
    assert meta.get("pdf_file") == "test-bbl-33.pdf"
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 3
    assert "/usr/local/texlive/texmf-biblatex-33" in meta["converters"][0]["runs"][2].get("log")


@pytest.mark.integration
def test_stamp_good(docker_container):
    url = docker_container + "/stamp"
    infile = os.path.join(SELF_DIR, "fixture/tarballs/stamp-good/good.pdf")
    outcome = os.path.join(SELF_DIR, "output/stamp-good.pdf")
    status = submit_file(url, infile, outcome, api_args={"watermark_text": "Hello World"})
    assert status == 200


@pytest.mark.integration
def test_stamp_missing_watermark_text(docker_container):
    url = docker_container + "/stamp"
    infile = os.path.join(SELF_DIR, "fixture/tarballs/stamp-good/good.pdf")
    outcome = os.path.join(SELF_DIR, "output/stamp-good.pdf")
    status = submit_file(url, infile, outcome)
    assert status == 400


@pytest.mark.integration
def test_stamp_not_rec_file(docker_container):
    url = docker_container + "/stamp"
    infile = os.path.join(SELF_DIR, "fixture/tarballs/stamp-not-rec-file/random.pdf")
    outcome = os.path.join(SELF_DIR, "output/stamp-random.pdf")
    status = submit_file(url, infile, outcome)
    assert status == 400


@pytest.mark.integration
def test_stamp_pdfa(docker_container):
    url = docker_container + "/stamp"
    infile = os.path.join(SELF_DIR, "fixture/tarballs/stamp-pdfa/main.pdf")
    outcome = os.path.join(SELF_DIR, "output/stamp-pdfa.pdf")
    status = submit_file(url, infile, outcome)
    assert status == 400


@pytest.mark.integration
def test_always_changing_labels(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-always-changing-labels/test-always-changing-labels.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-always-changing-labels.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    assert meta.get("pdf_file") == "test-always-changing-labels.pdf"
    assert meta.get("tex_files") == ["main.tex"]
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 7  # latex, latex, latex, latex, latex, dvi2ps, ps2pdf


@pytest.mark.integration
@pytest.mark.parametrize("ts", [None, TL2023_TS])
def test_latex_as_tex_fails(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/latex-as-tex-fails/latex-as-tex-fails.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-latex-as-tex-fails.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false", "ts": TL2023_TS})
    assert meta is not None
    # compilation must succeed
    assert meta.get("status") == "fail"
    assert len(meta.get("converters")[0].get("runs")) == 1
    # the first run should have exit code 1, since it misses the not-available glo entry
    assert meta.get("converters")[0].get("runs")[0].get("return_code") == 1


@pytest.mark.integration
def test_api_texlive_version(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-texlive-version/test-texlive-version.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-texlive-version.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    # since the default proxy is TL2024, and we explicitely request TL2025 in the ZZRM here,
    # check that a 2025 TeX Live is actually used
    assert "TeX Live 2025" in meta["converters"][0]["runs"][1].get("log")
