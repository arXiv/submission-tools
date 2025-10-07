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
    # fmt: off
    assert "bubblewrapping call /usr/local/texlive/2025/bin/x86_64-linux/pdflatex" \
           in meta["converters"][0]["runs"][1].get("stderr")
    # fmt: on


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


@pytest.mark.integration
@pytest.mark.parametrize("compiler", ["pdftex", "xelatex", "lualatex"])
def test_basic_compilers(docker_container, compiler):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, f"fixture/tarballs/{compiler}-basic/{compiler}-basic.tar.gz")
    outcome = os.path.join(SELF_DIR, f"output/{compiler}-basic.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome)
    if status != 200:
        print(meta)
    assert status == 200
    assert meta is not None
    assert meta.get("pdf_file") == f"{compiler}-basic.pdf"
    assert meta.get("tex_files") == ["main.tex"]
    bin_prog = "pdfetex" if compiler == "pdftex" else compiler
    assert meta.get("converter").startswith(bin_prog)
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 2  # compiler, compiler
    # fmt: off
    assert f"bubblewrapping call /usr/local/texlive/2025/bin/x86_64-linux/{bin_prog}" \
           in meta["converters"][0]["runs"][1].get("stderr")
    # fmt: on


@pytest.mark.integration
def test_mktextfm(docker_container):
    """Test that LaTeX compilation triggers mktextfm for custom font metrics."""
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/test-mktextfm/test-mktextfm.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/test-mktextfm.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert meta is not None
    assert status == 200
    assert meta.get("pdf_file") == "test-mktextfm.pdf"
    assert meta.get("status") == "success"
    # Check that mktextfm was called in the log
    assert len(meta.get("converters", [])) == 1
    assert len(meta["converters"][0]["runs"]) == 4
    log = meta["converters"][0]["runs"][0].get("stderr", "")
    # this fails, the LaTeX code does not force mf-tfm-pk generation
    # due to the presence of type1 fonts
    # we probably need some cyrillic font
    assert "mktextfm" in log


@pytest.mark.integration
def test_cmd_exec_luatex(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/cmd-exec-luatex/cmd-exec-luatex.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/cmd-exec-luatex.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert meta is not None
    assert meta.get("pdf_file") is None


@pytest.mark.integration
def test_cmd_exec_pdftex(docker_container):
    url = docker_container + "/convert"
    tarball = os.path.join(SELF_DIR, "fixture/tarballs/cmd-exec-pdftex/cmd-exec-pdftex.tar.gz")
    outcome = os.path.join(SELF_DIR, "output/cmd-exec-pdftex.outcome.tar.gz")
    meta, status = submit_tarball(url, tarball, outcome, api_args={"auto_detect": "false"})
    assert meta is not None
    assert meta.get("pdf_file") is None
