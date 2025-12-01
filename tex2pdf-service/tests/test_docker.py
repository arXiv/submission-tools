import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.parse

import pymupdf
import pytest
import requests
from bin.compile_submissions import get_outcome_meta_and_files_info
from tex2pdf.converter_driver import RemoteConverterDriver
from tex2pdf.tarball import unpack_tarball
from tex2pdf_tools.zerozeroreadme import ZZRM_CURRENT_VERSION

PORT_2023 = 33031
# default proxy is TL2025
# since we run --network host for tl2025 docker, the app listens on the internal port
PORT_DEFAULT = 8080
SELF_DIR = os.path.abspath(os.path.dirname(__file__))

TL2023_CUTOFF = 1748736000
TL2023_TS = TL2023_CUTOFF - 100


def submit_tarball(
    service: str,
    tarball_dir: str,
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
    logging.debug(f"Submitting {service} with params {params_dict} and tarball dir {tarball_dir}")
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as f:
        with tarfile.open(f.name, mode="w:gz") as tar:
            tar.add(tarball_dir, arcname=".")
        uploading = {"incoming": (f"{os.path.basename(tarball_dir)}.tar.gz", f, "application/gzip")}
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
                logging.warning("%s: Connection timed out", tarball_dir)
                status_code = 500

            except Exception as exc:
                logging.warning("%s: %s", tarball_dir, str(exc))
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
    # fmt: off
    args = [
        "docker", "run",
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


@pytest.fixture(params=[None, TL2023_TS])
def ts(request):
    return request.param


@pytest.fixture(scope="module")
def docker_container(request):
    global PORT_2023  # noqa: PLW0603
    PORT_2023 = request.config.getoption("--docker-port-2023")

    image_2023_name = "public-tex2pdf-app-2023-2023-05-21"
    image_2025_name = "public-tex2pdf-app-2025-2025-08-03"
    container_2023_name = "test-arxiv-tex2pdf-2023"
    container_2025_name = "test-arxiv-tex2pdf-2025"

    if not request.config.getoption("--no-docker-setup"):
        subprocess.call(["docker", "kill", container_2023_name])
        subprocess.call(["docker", "kill", container_2025_name])

        # Make sure the container is the latest
        args = ["make", "app2023.docker", "app2025.docker"]
        make = subprocess.run(args, encoding="utf-8", capture_output=True, check=False)
        if make.returncode != 0:
            print(make.stdout)
            print(make.stderr)
            pass

        _start_docker_container(image_2023_name, container_2023_name, PORT_2023)
        # fmt: off
        _start_docker_container(
            image_2025_name, container_2025_name, PORT_DEFAULT,
            [
                "--network", "host",
                "--env",     "TEX2PDF_PROXY_RELEASE=1",
                "--env",     f"TEX2PDF_SCOPES=tl2023,autotex-tl2023:{TL2023_CUTOFF}",
                "--env",     f"TEX2PDF_KEYS_TO_URLS_tl2023=http://localhost:{PORT_2023}/convert/",
                "--env",     "TEX2PDF_KEYS_TO_URLS_autotex-tl2023=http://localhost:9999/no-such-autotex/",
            ],
        )
        # fmt: on

    _check_docker_api_ready(container_2023_name, PORT_2023)
    _check_docker_api_ready(container_2025_name, PORT_DEFAULT)

    # we test with 2024 as default entry point, and 2023 as fallback
    yield f"http://localhost:{PORT_DEFAULT}"

    if not request.config.getoption("--no-docker-setup") and not request.config.getoption("--keep-docker-running"):
        # Stop the container after tests
        with open(f"{container_2023_name}.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_2023_name], stdout=log, stderr=log)
        with open(f"{container_2025_name}.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_2025_name], stdout=log, stderr=log)
        subprocess.call(["docker", "kill", container_2023_name])
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


@pytest.mark.integration
def test_api_texlive_version_info(docker_container):
    url = docker_container
    response = requests.get(f"{url}/texlive/version")
    if response.status_code != 200:
        print(response.content)
    assert response.status_code == 200
    ret = response.json()
    assert ret["version"] == "2025"
    assert sorted(ret["proxy_version"]) == ["autotex-tl2023", "tl2023"]


# this test doesn't work with the remote compilation since the status changes from 500 to 400 ???
@pytest.mark.integration
def test_api_smoke(docker_container):
    """00README.XXX is bad, so make sure it does not die or anything."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test1")
    outcome = os.path.join(SELF_DIR, "output/test1.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta == "ZZRM cannot be loaded: Q"
    assert status == 422


@pytest.mark.integration
def test_api_git_hash(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2")
    outcome = os.path.join(SELF_DIR, "output/test2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("version_info") is not None
    assert meta.get("version_info") != ""
    assert meta.get("version_info") != "tex2pdf:(unknown)"
    assert meta.get("version_info").startswith("tex2pdf:")


@pytest.mark.integration
def test_api_test2(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2")
    outcome = os.path.join(SELF_DIR, "output/test2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "test2.pdf"
    assert meta.get("tex_files") == ["fake-file-2.tex"]
    # autotex says that the documents are combined alphabetically
    assert meta.get("documents") == ["out/fake-file-2.pdf"]


@pytest.mark.integration
def test_api_test3(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test3")
    outcome = os.path.join(SELF_DIR, "output/test3.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "test3.pdf"
    assert meta.get("tex_files") == ["fake-file-2.tex", "fake-file-1.tex", "fake-file-3.tex"]
    assert meta.get("pdf_files") == ["fake-file-2.pdf", "fake-file-1.pdf", "fake-file-3.pdf"]
    # v2 keeps the order which is what we'd expect
    assert meta.get("documents") == ["out/fake-file-2.pdf", "out/fake-file-1.pdf", "out/fake-file-3.pdf"]


@pytest.mark.integration
def test_api_test4(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test4")
    outcome = os.path.join(SELF_DIR, "output/test4.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "test4.pdf"
    assert meta.get("tex_files") == ["main.tex", "gdp.tex"]
    assert len(meta.get("converters", [])) == 2
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvi2ps, ps2pdf


@pytest.mark.integration
def test_api_test_anc_ignore(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-anc-ignore")
    outcome = os.path.join(SELF_DIR, "output/test-anc-ignore.outcome.tar.gz")
    meta, status = submit_tarball(
        url, tarball, outcome, api_args={"auto_detect": "true", "hide_anc_dir": "true", "ts": ts}
    )
    assert meta is not None
    assert meta.get("status") == "fail"


@pytest.mark.integration
def test_api_test_anc_ignore_no_ancfiles(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test4")
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
def test_api_preflight(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test3")
    outcome = os.path.join(SELF_DIR, "output/test3.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, json_response=True, api_args={"preflight": "v2", "ts": ts})
    assert meta is not None
    assert meta.get("status").get("key") == "success"
    assert len(meta.get("detected_toplevel_files")) == 3
    assert sorted([f["filename"] for f in meta.get("detected_toplevel_files")]) == [
        "fake-file-1.tex",
        "fake-file-2.tex",
        "fake-file-3.tex",
    ]


@pytest.mark.integration
def test_remote2023(docker_container) -> None:
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2")
    out_dir = os.path.join(SELF_DIR, "output/test2-remote")
    url = docker_container + "/convert/"
    tag = os.path.basename(tarball)

    logging.debug("Before instantiating the RemoteConverterDriver")

    shutil.rmtree(out_dir, ignore_errors=True)

    tarname = f"{tarball}/test2.tar.gz"
    print(f"tarname = {tarname}")
    with tarfile.open(tarname, mode="w:gz") as tar:
        tar.add(tarball, arcname=".")
    converter = RemoteConverterDriver(url, 600, out_dir, tarname, use_addon_tree=False, tag=tag, auto_detect=True)
    # os.unlink(tarname)
    logging.debug("Calling generate_pdf")
    pdf = converter.generate_pdf()
    assert os.path.isfile(f"{out_dir}/outcome-test2.json")
    assert os.path.isfile(f"{out_dir}/out/test2.pdf")
    assert pdf == "test2.pdf"


@pytest.mark.integration
def test_remote2023_anc_ignore(docker_container) -> None:
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-anc-ignore")
    out_dir = os.path.join(SELF_DIR, "output/test-anc-ignore-remote")
    url = docker_container + "/convert/"
    tag = os.path.basename(tarball)
    shutil.rmtree(out_dir, ignore_errors=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as f:
        with tarfile.open(f.name, mode="w:gz") as tar:
            tar.add(tarball, arcname=".")
        converter = RemoteConverterDriver(
            url, 600, out_dir, f.name, use_addon_tree=False, tag=tag, auto_detect=True, hide_anc_dir=True
        )
        pdf = converter.generate_pdf()
        assert pdf is None
        assert os.path.isfile(f"{out_dir}/test-anc-ignore-outcome.tar.gz")


@pytest.mark.integration
def test_api_missing_graphics(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-missing-img")
    outcome = os.path.join(SELF_DIR, "output/test-missing-img.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    # compilation must fail on missing files
    assert meta.get("status") == "fail"


@pytest.mark.integration
def test_api_missing_glo(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-missing-glo")
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
def test_api_broken_tex(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-broken-tex")
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
def test_bbl_32_2023(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-bbl-32")
    outcome = os.path.join(SELF_DIR, "output/test-bbl-32.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": TL2023_TS})
    assert meta is not None
    assert meta.get("pdf_file") == "test-bbl-32.pdf"
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 3
    assert "/usr/local/texlive/texmf-biblatex-33" not in meta["converters"][0]["runs"][2].get("log")


@pytest.mark.integration
def test_bbl_33(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-bbl-33")
    outcome = os.path.join(SELF_DIR, "output/test-bbl-33.outcome.tar.gz")
    # need to send this tl tl2023 container, thus give timestamp according to TEX2PDF_SCOPES
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": TL2023_TS})
    assert meta is not None
    assert meta.get("pdf_file") == "test-bbl-33.pdf"
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 3
    assert "/usr/local/texlive/texmf-biblatex-33" in meta["converters"][0]["runs"][2].get("log")


@pytest.mark.integration
def test_bbl_32_2025(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-bbl-32")
    outcome = os.path.join(SELF_DIR, "output/test-bbl-32-2025.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    # generation should fail because a bbl file vers 3.2 is uploaded, which should trigger an error
    if type(meta) is str:
        print(f"submit_tarball returned string {meta}")
        assert meta == ""
    assert type(meta) is dict
    assert meta.get("pdf_file") is None
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 2  # we fail in the second run


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
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-always-changing-labels")
    outcome = os.path.join(SELF_DIR, "output/test-always-changing-labels.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    assert meta.get("pdf_file") == "test-always-changing-labels.pdf"
    assert meta.get("tex_files") == ["main.tex"]
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 7  # latex, latex, latex, latex, latex, dvi2ps, ps2pdf


@pytest.mark.integration
def test_latex_as_tex_fails(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/latex-as-tex-fails")
    outcome = os.path.join(SELF_DIR, "output/test-latex-as-tex-fails.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false", "ts": ts})
    assert meta is not None
    # compilation must succeed
    assert meta.get("status") == "fail"
    assert len(meta.get("converters")[0].get("runs")) == 1
    # the first run should have exit code 1, since it misses the not-available glo entry
    assert meta.get("converters")[0].get("runs")[0].get("return_code") == 1


@pytest.mark.integration
def test_api_texlive_version(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-texlive-version")
    outcome = os.path.join(SELF_DIR, "output/test-texlive-version.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert meta is not None
    # check that a 2025 TeX Live is actually used
    assert "TeX Live 2025" in meta["converters"][0]["runs"][1].get("log")


@pytest.mark.integration
def test_api_version_1(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/version-1")
    outcome = os.path.join(SELF_DIR, "output/version-1.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200


@pytest.mark.integration
def test_api_version_2(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/version-2")
    outcome = os.path.join(SELF_DIR, "output/version-2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200


@pytest.mark.integration
def test_api_version_100(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/version-100")
    outcome = os.path.join(SELF_DIR, "output/version-100.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 422
    assert meta == f"ZZRM cannot be loaded: Version number out of range (1-{ZZRM_CURRENT_VERSION}): 100"


@pytest.mark.integration
def test_api_version_2_texlive_version(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/version-2-texlive-version")
    outcome = os.path.join(SELF_DIR, "output/version-2-texlive-version.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200


@pytest.mark.integration
def test_api_version_2_texlive_version_current(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/version-2-texlive-version-current")
    outcome = os.path.join(SELF_DIR, "output/version-2-texlive-version-current.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200


@pytest.mark.integration
def test_api_version_2_texlive_version_unknown(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/version-2-texlive-version-unknown")
    outcome = os.path.join(SELF_DIR, "output/version-2-texlive-version-unknown.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 422
    assert meta == "Invalid configuration: Undefined TeX Live version requested in ZZRM: tl2045"


@pytest.mark.integration
def test_api_bookmark_out_file(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/bookmark-out-file")
    outcome = os.path.join(SELF_DIR, "output/bookmark-out-file.outcome.tar.gz")
    outcome_dir = os.path.join(SELF_DIR, "output/bookmark-out-file")
    shutil.rmtree(outcome_dir, ignore_errors=True)
    os.makedirs(outcome_dir)
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    unpack_tarball(outcome_dir, outcome, {})
    with pymupdf.open(os.path.join(outcome_dir, "out", "bookmark-out-file.pdf")) as pdf:
        assert pdf.get_toc()[0] == [1, "Proof of Lemma 1", 1]


@pytest.mark.integration
@pytest.mark.parametrize("compiler", ["pdftex", "xelatex", "lualatex"])
def test_basic_compilers(docker_container, compiler):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, f"fixture/tarballs/{compiler}-basic")
    outcome = os.path.join(SELF_DIR, f"output/{compiler}-basic.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome)
    if status != 200:
        print(meta)
    assert status == 200
    assert meta is not None
    assert meta.get("pdf_file") == f"{compiler}-basic.pdf"
    assert meta.get("tex_files") == ["main.tex"]
    if compiler == "pdftex":
        # pdftex is an alias for pdfetex
        assert meta.get("converter").startswith("pdfetex")
    else:
        assert meta.get("converter").startswith(compiler)
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 2  # compiler, compiler


@pytest.mark.integration
def test_bibtex(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-bibtex")
    outcome = os.path.join(SELF_DIR, "output/test-bibtex.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 4  # pdflatex, bibtex, pdflatex, pdflatex
    assert meta["converters"][0]["runs"][1]["step"] == "bibtex_run"


@pytest.mark.integration
def test_biblatex_biber(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/biblatex-biber")
    outcome = os.path.join(SELF_DIR, "output/biblatex-biber.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 4  # pdflatex, biber, pdflatex, pdflatex
    assert meta["converters"][0]["runs"][1]["step"] == "biber_run"


@pytest.mark.integration
def test_biblatex_bibtex(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/biblatex-bibtex")
    outcome = os.path.join(SELF_DIR, "output/biblatex-bibtex.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 4  # pdflatex, bibtex, pdflatex, pdflatex
    assert meta["converters"][0]["runs"][1]["step"] == "bibtex_run"


@pytest.mark.integration
def test_biblatex_bibtex8(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/biblatex-bibtex8")
    outcome = os.path.join(SELF_DIR, "output/biblatex-bibtex8.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 4  # pdflatex, bibtex8, pdflatex, pdflatex
    assert meta["converters"][0]["runs"][1]["step"] == "bibtex8_run"


@pytest.mark.integration
def test_bibtex_not_used(docker_container):
    """Test a submission with built-in bibliography."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/bibtex-not-used")
    outcome = os.path.join(SELF_DIR, "output/bibtex-not-used.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 2  # pdflatex, pdflatex
    assert meta["converters"][0]["runs"][0]["step"] == "first_run"
    assert meta["converters"][0]["runs"][1]["step"] == "second_run:0"


@pytest.mark.integration
def test_bibtex_not_used_revtex(docker_container):
    """Test a submission with built-in bibliography, but revtex generating .bib files."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/bibtex-not-used-revtex")
    outcome = os.path.join(SELF_DIR, "output/bibtex-not-used-revtex.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 2  # pdflatex, pdflatex
    assert meta["converters"][0]["runs"][0]["step"] == "first_run"
    assert meta["converters"][0]["runs"][1]["step"] == "second_run:0"


@pytest.mark.integration
def test_no_bib_processor(docker_container):
    """Test that if the bib processor is not set, that we use bibtex as default."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-no-bib-processor")
    outcome = os.path.join(SELF_DIR, "output/test-no-bib-processor.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 4  # pdflatex, bibtex, pdflatex, pdflatex
    assert meta["converters"][0]["runs"][1]["step"] == "bibtex_run"


def test_tl2023_on_zzrm_without_texlive_version(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/tl2023-zzrm-without-texlive-version")
    outcome = os.path.join(SELF_DIR, "output/test-tl2023-zzrm-without-texlive-version.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    # since the default proxy is 2024, but we have a ZZRM with no texlive version set
    # we treat it as TL2023!
    assert "TeX Live 2023" in meta["converters"][0]["runs"][1].get("log")


@pytest.mark.integration
def test_first_line(docker_container, ts):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/first-line")
    outcome = os.path.join(SELF_DIR, "output/first-line.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta.get("pdf_file") == "first-line.pdf"


@pytest.mark.integration
def test_dvi_pdfoutput(docker_container, ts):
    """Test submission with latex selected and pdfoutput=1 in the source code, must fail."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/dvi-pdfoutput")
    outcome = os.path.join(SELF_DIR, "output/dvi-pdfoutput.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "ts": ts})
    assert meta is not None
    assert meta["status"] == "fail"
    assert meta.get("pdf_file") is None


@pytest.mark.integration
def test_failing_ps2pdf(docker_container, ts):
    """Test submission where ps2pdf fails.."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/failing-ps2pdf")
    outcome = os.path.join(SELF_DIR, "output/failing-ps2pdf.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false", "ts": ts})
    assert meta is not None
    assert meta["status"] == "fail"
    assert meta.get("pdf_file") is None
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvips, ps2pdf


@pytest.mark.integration
def test_check_js_detection(docker_container, ts):
    """Test submission with embedded Javascript fails.."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/check-js-detection")
    outcome = os.path.join(SELF_DIR, "output/check-js-detection.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false", "ts": ts})
    assert meta is not None
    assert meta.get("status") == "fail"
    assert meta.get("pdf_file") is None
    assert meta.get("reason", "") == "PDF QA check failed."


@pytest.mark.integration
def test_bibtex_fail(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/bibtex-fail")
    outcome = os.path.join(SELF_DIR, "output/bibtex-fail.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 2  # pdflatex, bibtex
    assert meta["converters"][0]["runs"][1]["step"] == "bibtex_run"
    assert meta["converters"][0]["runs"][0]["pdf"]["size"] is None
    assert meta["converters"][0]["runs"][1]["log"].startswith("This is BibTeX, Version")
    assert "I couldn't open style file" in meta["converters"][0]["runs"][1]["log"]


@pytest.mark.integration
def test_biber_fail(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/biber-fail")
    outcome = os.path.join(SELF_DIR, "output/biber-fail.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert status == 200
    assert meta is not None
    assert len(meta["converters"][0]["runs"]) == 2  # pdflatex, bibtex
    assert meta["converters"][0]["runs"][1]["step"] == "biber_run"
    assert meta["converters"][0]["runs"][0]["pdf"]["size"] is None
    assert meta["converters"][0]["runs"][1]["log"].startswith("INFO - This is Biber")
    assert "ERROR - Cannot find" in meta["converters"][0]["runs"][1]["log"]
