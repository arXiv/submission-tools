"""This module implements QA checks for general files."""

import subprocess
from collections.abc import Callable

from .images import collect_image_info
from .models import CheckResult, CheckSeverity, ImageInfo, IssueType, TeXFileIssue, logger
from .plugin_api import FILE_CHECKS_GROUP, merge_check_specs, safe_call

# Default threshold for oversized images (in megapixels)
# Assuming 600dpi on a full page A4 paper we would have
# (8.3 x 11.7 x 600 x 600) / (1024 x 1024) ≈ 33.34007263 MPixels
DEFAULT_IMAGE_SIZE_THRESHOLD_MPIXELS = 34


def check_no_exe(
    files: list[str], rundir: str, extra: dict, severity: CheckSeverity = CheckSeverity.error
) -> CheckResult:
    """Check for presence of EXE files."""
    logger.debug("Checking for presence of EXE files")
    if foo := [f for f in files if f.lower().endswith(".exe")]:
        return CheckResult(
            check_passed=False,
            info="exe-in-submission",
            long_info=f"Found .exe file in list of file {foo}",
            severity=severity,
            issues=[],
        )
    return CheckResult(True, info="", long_info="", severity=severity, issues=[])


def check_image_sizes(
    files: list[str], rundir: str, extra: dict, severity: CheckSeverity = CheckSeverity.error
) -> CheckResult:
    """Check for oversized images.

    Args:
        files: List of relative file paths
        rundir: Base directory containing the files
        extra: Extra information that might be test dependent
        severity: Optional CheckSeverity level, defaults to error

    Returns:
        CheckResult with warning if oversized images found, including image metadata
    """
    logger.debug("Checking for oversized images")
    threshold_mpixels: float = (
        extra["threshold_mpixels"] if "threshold_mpixels" in extra else DEFAULT_IMAGE_SIZE_THRESHOLD_MPIXELS
    )
    all_image_info: list[ImageInfo]
    oversized_images = []

    if "image_files" in extra:
        all_image_info = extra["image_files"]
        logger.debug(f"Found image_files info {all_image_info}")
    else:
        all_image_info = collect_image_info(files, rundir)
        logger.debug(f"Created all_image_info {all_image_info}")

    for img_info in all_image_info:
        megapixels = img_info.megapixels
        fast_copy = img_info.pdftex_fast_copy
        logger.debug(f"Checking image {img_info.filename} mp = {megapixels}, fast copy = {fast_copy}")
        # if fast_copy is None, we consider it a slow copy => False
        if megapixels and megapixels > threshold_mpixels and not fast_copy:
            width = img_info.width
            height = img_info.height
            file_size_mb = img_info.file_size_mb
            filepath = img_info.filename
            oversized_images.append(f"{filepath} ({width}x{height}px, {megapixels:.1f}MP, {file_size_mb:.1f}MB)")
            img_info.is_oversized = True

    logger.debug(f"Found oversized images {oversized_images}")
    if oversized_images:
        info = (
            f"Found {len(oversized_images)} oversized image(s) (>{threshold_mpixels}MP). "
            + "This may cause timeout or compilation errors. Please see our "
            + "<a href='https://info.arxiv.org/help/sizes.html' target='_blank'>help page on image sizes</a>."
        )
        long_info = "\n".join(oversized_images)
        issue = TeXFileIssue(key=IssueType.oversized_image, info=info)
        return CheckResult(
            check_passed=False,
            info=info,
            long_info=long_info,
            severity=severity,
            issues=[issue],
        )

    return CheckResult(
        check_passed=True,
        info="",
        long_info="",
        severity=severity,
        issues=[],
    )


def pdf_are_pdf(
    files: list[str], rundir: str, extra: dict, severity: CheckSeverity = CheckSeverity.error
) -> CheckResult:
    """Check PDFs for actually being pdfs and not renamed docx etc.

    Args:
        files: List of relative file paths
        rundir: Base directory containing the files
        extra: Extra information that might be test dependent
        severity: Optional CheckSeverity level, defaults to error

    Returns:
        CheckResult with warning if pdfs that aren't really are found
    """
    logger.debug("Checking for pdfs actually being pdfs")
    pdf_that_arent_pdfs = []
    for pdf_file in [f for f in files if f.lower().endswith(".pdf")]:
        try:
            result = subprocess.run(
                ["pdfinfo", pdf_file], capture_output=True, text=True, timeout=5, check=False, cwd=rundir
            )
            if "May not be a PDF file" in result.stderr:
                pdf_that_arent_pdfs.append(pdf_file)
        except FileNotFoundError:
            logger.error("pdfinfo not found, this should not happen!")
        except subprocess.TimeoutExpired:
            logger.error(f"pdfinfo timed out for {pdf_file}")
        except Exception as e:
            logger.debug(f"Could not run pdfinfo on {pdf_file}: {e}")

    if pdf_that_arent_pdfs:
        info = f"Found {len(pdf_that_arent_pdfs)} PDFs that don't look like a PDF."
        long_info = "\n".join(pdf_that_arent_pdfs)
        issue = TeXFileIssue(key=IssueType.pdf_not_pdf, info=info)
        return CheckResult(
            check_passed=False,
            info=info,
            long_info=long_info,
            severity=severity,
            issues=[issue],
        )

    return CheckResult(
        check_passed=True,
        info="",
        long_info="",
        severity=severity,
        issues=[],
    )


# Registry of available file checks: name -> (callable, default severity).
# Populated in place by ``_ensure_loaded()`` from the built-in checks plus any
# checks discovered via the ``tex2pdf_tools.preflight.file_checks`` entry-point
# group.  Kept as a single module-level object (never rebound) so that test
# ``monkeypatch.setitem(file_checks.FILE_CHECKS, ...)`` keeps working.
FILE_CHECKS: dict[str, tuple[Callable[[list[str], str, dict, CheckSeverity], CheckResult], CheckSeverity]] = {}
_loaded = False


def _ensure_loaded() -> None:
    """Populate ``FILE_CHECKS`` once: built-ins first (they win), then plugins."""
    global _loaded  # noqa: PLW0603
    if _loaded:
        return
    builtins = {
        "no-exe": (check_no_exe, CheckSeverity.error),
        "image-sizes": (check_image_sizes, CheckSeverity.warning),
        "pdf-are-pdf": (pdf_are_pdf, CheckSeverity.error),
    }
    for name, spec in builtins.items():
        FILE_CHECKS.setdefault(name, spec)
    merge_check_specs(FILE_CHECKS_GROUP, FILE_CHECKS)
    _loaded = True


def reset_checks() -> None:
    """Test hook: clear the registry and force re-discovery on next use."""
    global _loaded  # noqa: PLW0603
    FILE_CHECKS.clear()
    _loaded = False


def run_checks(
    files: list[str], checks: list[str] | str, rundir: str = ".", extra: dict = {}
) -> tuple[bool, list[CheckResult], list[CheckResult]]:
    """Run a list of checks or all.

    Args:
        files: List of relative file paths to check
        checks: List of checks to run (or "all")
        rundir: Base directory containing the files (default: current directory)
        extra: dictionary of extra data

    Returns: a tuple containing:
        - a boolean indicating whether all checks passed (no errors, warnings OK)
        - the list of **failed** CheckResults with severity=error
        - the list of **failed** CheckResults with severity=warning
    """
    _ensure_loaded()
    error_results: list[CheckResult] = []
    warning_results: list[CheckResult] = []

    if type(checks) is str:
        if checks == "all":
            checks = list(FILE_CHECKS.keys())
        else:
            checks = [checks]

    for check in checks:
        if check in FILE_CHECKS:
            func = FILE_CHECKS[check][0]
            severity = FILE_CHECKS[check][1]
            # Fail-open: a check raising must never abort preflight.
            res = safe_call(func, files, rundir, extra, severity, label=f"file-check:{check}")
            if res is None:
                continue
            if not res.check_passed:
                if res.severity == CheckSeverity.error:
                    error_results.append(res)
                else:
                    warning_results.append(res)
        else:
            logger.error(f"Unknown check: {check}")

    # Pass only if no errors (warnings are OK)
    return not error_results, error_results, warning_results
