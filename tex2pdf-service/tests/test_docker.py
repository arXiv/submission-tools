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

PORT = 33031
SELF_DIR = os.path.abspath(os.path.dirname(__file__))


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
    params = urllib.parse.urlencode(params_dict)
    url = f"{service}/?{params}"
    with open(tarball, "rb") as data_fd:
        uploading = {"incoming": (os.path.basename(tarball), data_fd, "application/gzip")}
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


@pytest.fixture(scope="module")
def docker_container(request):
    global PORT  # noqa: PLW0603
    PORT = request.config.getoption("--docker-port")
    url = f"http://localhost:{PORT}"

    if not request.config.getoption("--no-docker-setup"):
        image_name = "public-tex2pdf-app-2023-2023-05-21"
        container_name = "test-arxiv-tex2pdf"
        dockerport = "8080"

        subprocess.call(["docker", "kill", container_name])

        # Make sure the container is the latest
        args = ["make", "app.docker"]
        make = subprocess.run(args, encoding="utf-8", capture_output=True, check=False)
        if make.returncode != 0:
            print(make.stdout)
            print(make.stderr)
            pass

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
            f"{PORT}:{dockerport}",
            "-e",
            f"PORT={dockerport}",
            "--name",
            container_name,
            image_name,
        ]
        docker = subprocess.run(args, encoding="utf-8", capture_output=True, check=False)
        if docker.returncode != 0:
            logging.error("tex2pdf container did not start")
            pass

    # Wait for the API to be ready
    for _ in range(60):  # retries for 60 seconds
        try:
            response = requests.get(url)
            if response.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        time.sleep(1)
    else:
        with open("tex2pdf.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_name], stdout=log, stderr=log)
        raise RuntimeError("API did not start in time")

    yield url

    if not request.config.getoption("--no-docker-setup") and not request.config.getoption("--keep-docker-running"):
        # Stop the container after tests
        with open("tex2pdf.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_name], stdout=log, stderr=log)
        subprocess.call(["docker", "kill", container_name])


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
def test_api_smoke(docker_container):
    """00README.XXX is bad, so make sure it does not die or anything."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test1/test1.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test1.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is None
    assert status == 500

@pytest.mark.integration
def test_api_git_hash(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2/test2.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    assert meta.get("version_info") is not None
    assert meta.get("version_info") != ""
    assert meta.get("version_info") != "tex2pdf:(unknown)"
    assert meta.get("version_info").startswith("tex2pdf:")


@pytest.mark.integration
def test_api_test2(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2/test2.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    assert meta.get("pdf_file") == "test2.pdf"
    assert meta.get("tex_files") == ["fake-file-2.tex"]
    # autotex says that the documents are combined alphabetically
    assert meta.get("documents") == ["out/fake-file-2.pdf"]


@pytest.mark.integration
def test_api_test3(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test3/test3.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test3.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    assert meta.get("pdf_file") == "test3.pdf"
    assert meta.get("tex_files") == ["fake-file-2.tex", "fake-file-1.tex", "fake-file-3.tex"]
    assert meta.get("pdf_files") == ["fake-file-2.pdf", "fake-file-1.pdf", "fake-file-3.pdf"]
    # v2 keeps the order which is what we'd expect
    assert meta.get("documents") == ["out/fake-file-2.pdf", "out/fake-file-1.pdf", "out/fake-file-3.pdf"]


@pytest.mark.integration
def test_api_test4(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test4/test4.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test4.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    assert meta.get("pdf_file") == "test4.pdf"
    assert meta.get("tex_files") == ["main.tex", "gdp.tex"]
    assert len(meta.get("converters", [])) == 2
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvi2ps, ps2pdf

@pytest.mark.integration
def test_api_test_anc_ignore(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-anc-ignore/test-anc-ignore.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-anc-ignore.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "hide_anc_dir": "true"})
    assert meta is not None
    assert meta.get("status") == "fail"

@pytest.mark.integration
def test_api_test_anc_ignore_no_ancfiles(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test4/test4.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test4.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true", "hide_anc_dir": "true"})
    assert meta is not None
    assert meta.get("pdf_file") == "test4.pdf"
    assert meta.get("tex_files") == ["main.tex", "gdp.tex"]
    assert len(meta.get("converters", [])) == 2
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvi2ps, ps2pdf

@pytest.mark.integration
def test_api_preflight(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test3/test3.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test3.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, json_response=True, api_args={"preflight": "v2"})
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
    converter = RemoteConverterDriver(url, 600, out_dir, tarball, use_addon_tree=False, tag=tag, auto_detect=True, hide_anc_dir=True)
    pdf = converter.generate_pdf()
    assert pdf is None
    assert os.path.isfile(f"{out_dir}/test-anc-ignore.tar.gz-outcome.tar.gz")

@pytest.mark.integration
def test_api_missing_graphics(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-missing-img/test-missing-img.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-missing-img.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    # compilation must fail on missing files
    assert meta.get("status") == "fail"

@pytest.mark.integration
def test_api_missing_glo(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-missing-glo/test-missing-glo.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-missing-glo.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    # compilation must succeed
    assert meta.get("status") == "success"
    # we need two runs, the first one creates the glossary entry
    assert len(meta.get("converters")[0].get("runs")) == 2
    # the first run should have exit code 1, since it misses the not-available glo entry
    assert meta.get("converters")[0].get("runs")[0].get("return_code") == 1

@pytest.mark.integration
def test_api_broken_tex(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-broken-tex/test-broken-tex.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-broken-tex.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    # compilation must succeed
    assert meta.get("status") == "fail"
    # we need two runs, the first one creates the glossary entry
    assert len(meta.get("converters")[0].get("runs")) == 2
    # the first run should have exit code 1, since it misses the not-available glo entry
    assert meta.get("converters")[0].get("runs")[0].get("return_code") == 1
    assert meta.get("converters")[0].get("runs")[1].get("return_code") == 1
