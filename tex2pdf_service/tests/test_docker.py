import os
import tempfile
import time
import requests
import subprocess
import pytest
from bin.compile_submissions import get_outcome_meta
import logging

PORT = 33031

def submit_tarball(service: str, tarball: str, outcome_file: str, tex2pdf_timeout: int = 30, post_timeout: int = 10) -> None | dict:
    meta = None
    url = service + f"/?timeout={tex2pdf_timeout}&auto_detect=true"
    with open(tarball, "rb") as data_fd:
        uploading = {'incoming': (os.path.basename(tarball), data_fd, 'application/gzip')}
        while True:
            try:
                res = requests.post(url, files=uploading,
                                    timeout=post_timeout, allow_redirects=False)
                status_code = res.status_code
                if status_code == 504:
                    logging.warning("Got 504 for %s", service)
                    time.sleep(1)
                    continue

                if status_code == 200:
                    if res.content:
                        with open(outcome_file, "wb") as out:
                            out.write(res.content)
                        meta, lines, clsfiles, styfiles, pdfchecksum = get_outcome_meta(
                            outcome_file)
                else:
                    logging.warning(f"%s: status code %d", url, status_code)

            except TimeoutError:
                logging.warning("%s: Connection timed out", tarball)

            except Exception as exc:
                logging.warning("%s: %s", tarball, str(exc))
            break

    return meta

@pytest.fixture(scope="module")
def docker_container(request):
    PORT = request.config.getoption('--docker-port')
    url = f"http://localhost:{PORT}"

    os.makedirs("tests/output", exist_ok=True)

    if not request.config.getoption('--no-docker-setup'):
        image_name = "public-tex2pdf-app-2024-2024-07-21"
        container_name = "test-arxiv-tex2pdf"
        dockerport = "8080"

        subprocess.call(["docker", "kill", container_name])

        # Make sure the container is the latest
        args = ["make", "app.docker"]
        make = subprocess.run(args, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if make.returncode != 0:
            print(make.stdout)
            print(make.stderr)
            pass

        # Start the container
        args = ["docker", "run", '--security-opt', "no-new-privileges=true", "--cpus", "1", "--rm",
                "-d",
                "-p", f"{PORT}:{dockerport}",
                "-e", f"PORT={dockerport}",
                "--name", container_name,
                image_name]
        docker = subprocess.run(args, encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
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
        raise RuntimeError("API did not start in time")

    yield url

    if not request.config.getoption('--no-docker-setup'):
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
    tarball = "tests/fixture/tarballs/test1/test1.tar.gz"
    outcome = "tests/output/test1.outcome.tar.gz"
    meta = submit_tarball(url, tarball, outcome)
    assert meta is not None


@pytest.mark.integration
def test_api_test2(docker_container):
    url = docker_container + "/convert"
    tarball = "tests/fixture/tarballs/test2/test2.tar.gz"
    outcome = "tests/output/test2.outcome.tar.gz"
    meta = submit_tarball(url, tarball, outcome)
    assert meta is not None
    assert meta.get("pdf_file") == "test2.pdf"
    assert meta.get("tex_files") == ['fake-file-2.tex']
    # autotex says that the documents are combined alphabetically
    assert meta.get("documents") == ['out/fake-file-2.pdf']

@pytest.mark.integration
def test_api_test3(docker_container):
    url = docker_container + "/convert"
    tarball = "tests/fixture/tarballs/test3/test3.tar.gz"
    outcome = "tests/output/test3.outcome.tar.gz"
    meta = submit_tarball(url, tarball, outcome)
    assert meta is not None
    assert meta.get("pdf_file") == "test3.pdf"
    assert meta.get("tex_files") == ['fake-file-2.tex', 'fake-file-1.tex', 'fake-file-3.tex']
    assert meta.get("pdf_files") == ['fake-file-2.pdf', 'fake-file-1.pdf', 'fake-file-3.pdf']
    # v2 keeps the order which is what we'd expect
    assert meta.get("documents") == ['out/fake-file-2.pdf', 'out/fake-file-1.pdf', 'out/fake-file-3.pdf']


@pytest.mark.integration
def test_api_test4(docker_container):
    url = docker_container + "/convert"
    tarball = "tests/fixture/tarballs/test4/test4.tar.gz"
    outcome = "tests/output/test4.outcome.tar.gz"
    meta = submit_tarball(url, tarball, outcome)
    assert meta is not None
    assert meta.get("pdf_file") == "test4.pdf"
    assert meta.get("tex_files") == ['main.tex', 'gdp.tex']
    assert len(meta.get("converters", [])) == 2
    assert len(meta["converters"][0]["runs"]) == 4  # latex, latex, dvi2ps, ps2pdf
