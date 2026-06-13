"""This module implements QA checks for PDF files."""

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import CheckResult, CheckSeverity, logger
from .plugin_api import PDF_CHECKS_GROUP, merge_check_specs, safe_call


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
    # (e.g. PDF-check plugins that parse the PDF rather than read pdfinfo output).
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


# Registry of available PDF checks: name -> (callable, default severity).
# Populated in place by ``_ensure_loaded()`` from the built-in checks plus any
# checks discovered via the ``tex2pdf_tools.preflight.pdf_checks`` entry-point
# group.  Kept as a single module-level object (never rebound) so that test
# ``monkeypatch.setitem(pdf_checks.PDF_CHECKS, ...)`` keeps working.
PDF_CHECKS: dict[str, tuple[Callable[[dict, CheckSeverity], CheckResult], CheckSeverity]] = {}
_loaded = False


def _ensure_loaded() -> None:
    """Populate ``PDF_CHECKS`` once: built-ins first (they win), then plugins."""
    global _loaded  # noqa: PLW0603
    if _loaded:
        return
    PDF_CHECKS.setdefault("javascript", (check_javascript, CheckSeverity.warning))
    merge_check_specs(PDF_CHECKS_GROUP, PDF_CHECKS)
    _loaded = True


def reset_checks() -> None:
    """Test hook: clear the registry and force re-discovery on next use."""
    global _loaded  # noqa: PLW0603
    PDF_CHECKS.clear()
    _loaded = False


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
    _ensure_loaded()
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
            # Fail-open: a check raising must never abort PDF production.
            res = safe_call(func, pdf_info, severity, label=f"pdf-check:{check}")
            if res is None:
                continue
            if not res.check_passed:
                if res.severity == CheckSeverity.error:
                    error_results.append(res)
                else:
                    warning_results.append(res)
        else:
            logger.error(f"Unknown check: {check}")
    # if check_results is empty, all tests have passed and we return true, and the check_results
    return not error_results, error_results, warning_results
