import os
import subprocess

import pytest
from tex2pdf.tarball import unpack_tarball

FILES = ["main.tex", "ancillary.tex", "anc/deep/data.csv", "sub/anc/s.tex"]


@pytest.mark.parametrize("members", [["main.tex", "ancillary.tex", "anc", "sub"], ["."]])
@pytest.mark.parametrize("hide_anc_dir", [True, False])
def test_unpack_tarball_hide_anc_dir(tmp_path, members, hide_anc_dir):
    """Only the top-level anc/ is skipped, for bare ("anc/x") and "./anc/x" member names."""
    src = tmp_path / "src"
    for name in FILES:
        (src / name).parent.mkdir(parents=True, exist_ok=True)
        (src / name).write_text("x\n")
    tarball = str(tmp_path / "sub.tar.gz")
    subprocess.run(["tar", "czf", tarball, "-C", str(src), *members], check=True)
    in_dir = tmp_path / "in"
    in_dir.mkdir()

    unpack_tarball(str(in_dir), tarball, hide_anc_dir, {})

    unpacked = sorted(os.path.relpath(os.path.join(d, f), in_dir) for d, _, fs in os.walk(in_dir) for f in fs)
    expected = sorted(f for f in FILES if not (hide_anc_dir and f.startswith("anc/")))
    assert unpacked == expected
