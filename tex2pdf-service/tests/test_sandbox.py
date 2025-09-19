import os
import subprocess

import pytest
from conftest import _check_docker_api_ready, _start_docker_container, submit_tarball

PORT_DEFAULT = 8080
SELF_DIR = os.path.abspath(os.path.dirname(__file__))


@pytest.fixture(scope="module")
def docker_container(request):
    image_2025_name = "public-tex2pdf-app-2025-2025-08-03"
    container_2025_name = "test-arxiv-tex2pdf-2025-sandbox"

    if not request.config.getoption("--no-docker-setup"):
        subprocess.call(["docker", "kill", container_2025_name])

        # Make sure the container is the latest
        args = ["make", "app2025.docker"]
        make = subprocess.run(args, encoding="utf-8", capture_output=True, check=False)
        if make.returncode != 0:
            print(make.stdout)
            print(make.stderr)
            pass

        # for sandboxing support we need gvisor runtime
        _start_docker_container(image_2025_name, container_2025_name, PORT_DEFAULT)

    _check_docker_api_ready(container_2025_name, PORT_DEFAULT)

    # we test with 2024 as default entry point, and 2023 as fallback
    yield f"http://localhost:{PORT_DEFAULT}"

    if not request.config.getoption("--no-docker-setup") and not request.config.getoption("--keep-docker-running"):
        # Stop the container after tests
        with open(f"{container_2025_name}.log", "w", encoding="utf-8") as log:
            subprocess.call(["docker", "logs", container_2025_name], stdout=log, stderr=log)
        subprocess.call(["docker", "kill", container_2025_name])


@pytest.mark.integration
def test_api_bwrap_pdflatex(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test2/test2.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test2.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    # First assertions are that we can produce a PDF file
    assert meta is not None
    assert meta.get("pdf_file") == "test2.pdf"
    assert meta.get("tex_files") == ["fake-file-2.tex"]
    # autotex says that the documents are combined alphabetically
    assert meta.get("documents") == ["out/fake-file-2.pdf"]
    # make sure we did run bubblewrap!
    assert "bubblewrapping call /usr/local/texlive/2025/bin/x86_64-linux/pdflatex" in meta["converters"][0]["runs"][
        1
    ].get("stderr")


@pytest.mark.integration
def test_api_latex_dvips_ps2pdf(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test4/test4.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test4.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "true"})
    assert meta is not None
    assert meta.get("pdf_file") == "test4.pdf"
    assert meta.get("tex_files") == ["main.tex", "gdp.tex"]
    assert len(meta.get("converters", [])) == 2
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvi2ps, ps2pdf
    # fmt: off
    assert "bubblewrapping call /usr/local/texlive/2025/bin/x86_64-linux/latex" \
           in meta["converters"][0]["runs"][1].get("stderr")
    assert "bubblewrapping call /usr/local/texlive/2025/bin/x86_64-linux/dvips" \
           in meta["converters"][0]["runs"][2].get("stderr")
    assert "bubblewrapping call /usr/bin/ps2pdf" \
           in meta["converters"][0]["runs"][3].get("stderr")
    # fmt: on
