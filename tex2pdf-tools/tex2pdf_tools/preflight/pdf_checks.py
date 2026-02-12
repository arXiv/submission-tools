"""This module implements QA checks for PDF files."""

import subprocess
from pathlib import Path
from typing import Any

from .feature_flags import ENABLE_JS_CHECKS
from .models import CheckResult, logger

PDF_CHECKS = {
    "javascript": lambda res: check_javascript(res),
}


def get_pdf_info(pdf: str) -> dict[str, Any]:
    """
    Get PDF information using various pdfinfo commands.

    Args:
        pdf: Path to the PDF file to check

    Returns:
        Dictionary containing output from various PDF checking commands.
        Each key is the command name, with 'stdout', 'stderr', and 'returncode' subkeys.
    """
    pdf_path = Path(pdf)
    if not pdf_path.exists():
        logger.error(f"PDF file not found: {pdf}")
        return {"error": f"PDF file not found: {pdf}"}

    # Define commands to run against the PDF
    # Format: (key_name, command_parts)
    cmds = [
        # ("pdfinfo", ["pdfinfo", str(pdf_path)]),
        ("pdfinfo_js", ["pdfinfo", "-js", str(pdf_path)]),
        # ("pdfinfo_meta", ["pdfinfo", "-meta", str(pdf_path)]),
        # ("pdffonts", ["pdffonts", str(pdf_path)]),
        # ("pdfimages_list", ["pdfimages", "-list", str(pdf_path)]),
    ]

    results = {}

    for key, cmd in cmds:
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            results[key] = {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
            logger.debug(f"Ran {' '.join(cmd)}: returncode={result.returncode}")
        except subprocess.TimeoutExpired:
            logger.warning(f"Command timed out: {' '.join(cmd)}")
            results[key] = {"error": "timeout", "returncode": -1}
        except FileNotFoundError:
            logger.warning(f"Command not found: {cmd[0]}")
            results[key] = {"error": f"command not found: {cmd[0]}", "returncode": -1}
        except Exception as e:
            logger.error(f"Error running {' '.join(cmd)}: {e}")
            results[key] = {"error": str(e), "returncode": -1}

    return results


def check_javascript(res: dict) -> CheckResult:
    """Check for presence of JavaScript in the PDF."""
    logger.debug("Checking for presence of JavaScript in PDF")
    if "pdfinfo_js" not in res:
        # TODO what should we do if a check cannot be run or failed to run?
        # For now return success to not break PDF production.
        logger.debug("Cannot find pdfinfo_js entry in the result dictionary, skipping check.")
        return CheckResult(True, "", "")
    # "returncode" should be always set, and if it is 0, stdout and stderr are also set
    if res["pdfinfo_js"]["returncode"] == 0 and res["pdfinfo_js"]["stdout"].strip():
        logger.debug("Detected JavaScript in PDF")
        return CheckResult(False, "JavaScript code found in PDF", res["pdfinfo_js"]["stdout"])
    return CheckResult(True, "", "")


def run_checks(pdf: str, checks: list[str] | str) -> tuple[bool, list[CheckResult]]:
    """Run a list of checks or all.

    Args:
        pdf: Path to the PDF file to check
        checks: List of checks to run

    Returns: a tuple containing:
        a boolean indicating whether all checks passed
        the list of **failed** CheckResults
    """
    pdf_info = get_pdf_info(pdf)
    check_results: list[CheckResult] = []
    if type(checks) is str:
        if checks == "all":
            checks = list(PDF_CHECKS.keys())
        else:
            checks = [checks]
    for check in checks:
        if check in PDF_CHECKS:
            if check == "javascript" and not ENABLE_JS_CHECKS:
                logger.debug("Skipping JavaScript check, not enabled in ENABLE_JS_CHECKS env")
                continue
            res = PDF_CHECKS[check](pdf_info)
            if not res.check_passed:
                check_results.append(res)
        else:
            logger.error(f"Unknown check: {check}")
    # if check_results is empty, all tests have passed and we return true, and the check_results
    return not check_results, check_results
