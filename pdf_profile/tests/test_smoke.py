import os.path
from collections import OrderedDict

import pytest
import subprocess
from src.pdf_profile import PdfProfile, PdfTextSimilarity
from ruamel.yaml import YAML

@pytest.fixture
def arxiv_2401_00001():
    this_file = os.path.abspath(__file__)
    tests_dir = os.path.dirname(this_file)
    pdf_dir = os.path.join(tests_dir, "fixture", "pdf")
    test_pdf = os.path.join(pdf_dir, "2401.00001.pdf")
    subprocess.run(["curl", "-L", "https://arxiv.org/pdf/2401.00001", "-o", test_pdf, ])
    return test_pdf


def test_smoke_1(arxiv_2401_00001):
    profiler = PdfProfile()
    profiler.profile_pdf(arxiv_2401_00001)
    yaml = YAML()
    with open("fixture/pdf/digest.2401.00001.yaml") as digest_fd:
        digest = yaml.load(digest_fd)
    profile = profiler.as_dict()
    assert digest == profile


def test_smoke_2():
    a = PdfProfile()
    b = PdfProfile()
    a.profile_pdf("./investigation/2402/2402.02001v2/2402.02001v2.1.pdf")
    b.profile_pdf("./investigation/2402/2402.02001v2/2402.02001v2.2.pdf")
    sim = PdfTextSimilarity(a, b)
    print(sim.compare_texts())
    assert sim.compare_texts() > 0.95
