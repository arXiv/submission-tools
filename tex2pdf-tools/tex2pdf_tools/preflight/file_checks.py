"""This module implements QA checks for general files."""

from .checks import CheckResult, logger

FILE_CHECKS = {
    "no-exe": lambda res: check_no_exe(res),
}


def check_no_exe(files: list[str]) -> CheckResult:
    """Check for presence of EXE files."""
    logger.debug("Checking for presence of EXE files")
    if foo := [f for f in files if f.lower().endswith(".exe")]:
        return CheckResult(False, "EXE file found", str(foo))
    return CheckResult(True, "", "")


def run_checks(files: list[str], checks: list[str] | str) -> tuple[bool, list[CheckResult]]:
    """Run a list of checks or all.

    Args:
        files: List of local paths for files to check
        checks: List of checks to run

    Returns: a tuple containing:
        a boolean indicating whether all checks passed
        the list of **failed** CheckResults
    """
    check_results: list[CheckResult] = []
    if type(checks) is str:
        if checks == "all":
            checks = list(FILE_CHECKS.keys())
        else:
            checks = [checks]
    for check in checks:
        if check in FILE_CHECKS:
            res = FILE_CHECKS[check](files)
            if not res.check_passed:
                check_results.append(res)
        else:
            logger.error(f"Unknown check: {check}")
    # if check_results is empty, all tests have passed and we return true, and the check_results
    return not check_results, check_results
