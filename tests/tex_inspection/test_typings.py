"""Tests using mypy."""

import os
import shutil
import subprocess
import unittest
from unittest import TestCase


class MyPyTest(TestCase):
    """Class for testing modules with mypy."""

    def test_run_mypy_module(self) -> None:
        """Run mypy on all module sources."""
        mypy = shutil.which("mypy")
        if mypy is None:
            raise OSError("mypy not found in PATH")
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        result: int = subprocess.call([mypy, "tex2pdf/tex_inspection"], env=os.environ, cwd=root_dir)
        self.assertEqual(result, 0, "Expect 0 type errors when running mypy")


if __name__ == "__main__":
    unittest.main()
