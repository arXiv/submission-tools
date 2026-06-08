"""This module implements QA checks for PDF files."""

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .feature_flags import HIDDEN_TEXT_REJECTS
from .hidden_text_pdf import analyze_hidden_text
from .models import CheckResult, CheckSeverity, IssueType, TeXFileIssue, logger


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

    results: dict[str, Any] = {}

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

    # Make the path available to checks that need to open the PDF directly
    # (e.g. the hidden-text check via pymupdf).
    results["pdf_path"] = str(pdf_path)

    return results


def check_javascript(res: dict, severity: CheckSeverity) -> CheckResult:
    """Check for presence of JavaScript in the PDF."""
    logger.debug("Checking for presence of JavaScript in PDF")
    if "pdfinfo_js" not in res:
        # TODO what should we do if a check cannot be run or failed to run?
        # For now return success to not break PDF production.
        logger.debug("Cannot find pdfinfo_js entry in the result dictionary, skipping check.")
        return CheckResult(check_passed=True, info="", long_info="", severity=severity, issues=[])
    # "returncode" should be always set, and if it is 0, stdout and stderr are also set
    if res["pdfinfo_js"]["returncode"] == 0 and res["pdfinfo_js"]["stdout"].strip():
        logger.debug("Detected JavaScript in PDF")
        return CheckResult(
            check_passed=False,
            info="pdf-contains-js",
            long_info=res["pdfinfo_js"]["stdout"],
            severity=severity,
            issues=[],
        )
    return CheckResult(check_passed=True, info="", long_info="", severity=severity, issues=[])


def check_hidden_text(res: dict, severity: CheckSeverity) -> CheckResult:
    """Check for hidden/invisible text in the PDF (white-on-white, tiny font, off-page).

    See :mod:`tex2pdf_tools.preflight.hidden_text_pdf` for the detection method
    and sources.  Severity is warning by default and error when
    ``HIDDEN_TEXT_REJECTS`` is set (see :mod:`...feature_flags`).
    """
    logger.debug("Checking for hidden text in PDF")
    pdf_path = res.get("pdf_path")
    if not pdf_path:
        logger.debug("No pdf_path in result dictionary, skipping hidden-text check.")
        return CheckResult(check_passed=True, info="", long_info="", severity=severity, issues=[])
    result = analyze_hidden_text(pdf_path)
    if not result.flagged:
        return CheckResult(check_passed=True, info="", long_info="", severity=severity, issues=[])
    info = "pdf-contains-hidden-text"
    long_info = (
        f"{result.hidden_char_count} hidden characters detected on page(s) {result.pages} "
        f"via {result.signals}\n---\n{result.text}"
    )
    issue = TeXFileIssue(IssueType.hidden_text, info, filename=os.path.basename(pdf_path))
    return CheckResult(
        check_passed=False,
        info=info,
        long_info=long_info,
        severity=severity,
        issues=[issue],
    )


PDF_CHECKS: dict[str, tuple[Callable[[dict, CheckSeverity], CheckResult], CheckSeverity]] = {
    "javascript": (check_javascript, CheckSeverity.warning),
    "hidden-text": (check_hidden_text, CheckSeverity.error if HIDDEN_TEXT_REJECTS else CheckSeverity.warning),
}


def run_checks(pdf: str, checks: list[str] | str) -> tuple[bool, list[CheckResult], list[CheckResult]]:
    """Run a list of checks or all.

    Args:
        pdf: Path to the PDF file to check
        checks: List of checks to run

    Returns: a tuple containing:
        - a boolean indicating whether all checks passed (no errors, warnings OK)
        - the list of **failed** CheckResults with severity=error
        - the list of **failed** CheckResults with severity=warning
    """
    pdf_info = get_pdf_info(pdf)
    error_results: list[CheckResult] = []
    warning_results: list[CheckResult] = []
    if type(checks) is str:
        if checks == "all":
            checks = list(PDF_CHECKS.keys())
        else:
            checks = [checks]
    for check in checks:
        if check in PDF_CHECKS:
            func = PDF_CHECKS[check][0]
            severity = PDF_CHECKS[check][1]
            res = func(pdf_info, severity)
            if not res.check_passed:
                if res.severity == CheckSeverity.error:
                    error_results.append(res)
                else:
                    warning_results.append(res)
        else:
            logger.error(f"Unknown check: {check}")
    # if check_results is empty, all tests have passed and we return true, and the check_results
    return not error_results, error_results, warning_results
