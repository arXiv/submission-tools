"""A timed-out run must not leave the worker waiting on a grandchild's pipe."""

import os
import subprocess
import time
import unittest

from tex2pdf import kill_and_collect

SELF_DIR = os.path.abspath(os.path.dirname(__file__))


class TestKillAndCollect(unittest.TestCase):
    def test_grandchild_holding_the_pipe_does_not_block_forever(self) -> None:
        """The shell is killed, its child keeps stdout/stderr open.

        communicate() waits for EOF, which never comes while the grandchild lives,
        so without the bound this call never returns and the worker is gone.
        """
        child = subprocess.Popen(
            ["bash", "-c", "sleep 120 & echo ready; wait"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="iso-8859-1",
        )
        assert child.stdout is not None
        self.assertEqual(child.stdout.readline(), "ready\n")  # grandchild is up, holding the pipe

        t0 = time.perf_counter()
        _out, err = kill_and_collect(child, grace=1.0)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 5.0, f"kill_and_collect blocked for {elapsed:.1f}s")
        self.assertIn("did not release its pipes", err)
        self.assertIsNotNone(child.returncode)

    def test_sandbox_dies_with_its_parent(self) -> None:
        """Bwrap must carry --die-with-parent, or a killed run leaves TeX running.

        --new-session puts the sandbox in its own session, out of reach of a kill on
        the wrapper and of killpg on its group, so this flag is the only thing that
        takes the TeX process down with a timed-out run.
        """
        script = os.path.join(os.path.dirname(SELF_DIR), "bin", "bwrap-tex.sh")
        with open(script, encoding="utf-8") as fd:
            self.assertIn("--die-with-parent", fd.read())


if __name__ == "__main__":
    unittest.main()
