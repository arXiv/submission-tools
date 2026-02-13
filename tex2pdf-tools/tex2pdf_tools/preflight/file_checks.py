"""This module implements QA checks for general files."""

from collections.abc import Callable

from .images import collect_image_info
from .models import CheckResult, CheckSeverity, ImageInfo, IssueType, TeXFileIssue, logger

# Default threshold for oversized images (in megapixels)
# Assuming 600dpi on a full page A4 paper we would have
# (8.3 x 11.7 x 600 x 600) / (1024 x 1024) ≈ 33.34007263 MPixels
DEFAULT_IMAGE_SIZE_THRESHOLD_MPIXELS = 34


def check_no_exe(files: list[str], rundir: str, extra: dict) -> CheckResult:
    """Check for presence of EXE files."""
    logger.debug("Checking for presence of EXE files")
    if foo := [f for f in files if f.lower().endswith(".exe")]:
        return CheckResult(False, "EXE file found", str(foo))
    return CheckResult(True, "", "")


def check_image_sizes(files: list[str], rundir: str, extra: dict) -> CheckResult:
    """Check for oversized images.

    Args:
        files: List of relative file paths
        rundir: Base directory containing the files
        extra: Extra information that might be test dependent

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
            + "This may cause timeout or compilation errors. See https://info.arxiv.org/help/sizes.html"
        )
        long_info = "\n".join(oversized_images)
        issue = TeXFileIssue(key=IssueType.oversized_image, info=info)
        return CheckResult(
            check_passed=False,
            info=info,
            long_info=long_info,
            severity=CheckSeverity.warning,
            issues=[issue],
        )

    return CheckResult(
        check_passed=True,
        info="",
        long_info="",
        severity=CheckSeverity.warning,
        issues=[],
    )


FILE_CHECKS: dict[str, Callable[[list[str], str, dict], CheckResult]] = {
    "no-exe": check_no_exe,
    "image-sizes": check_image_sizes,
}


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
    error_results: list[CheckResult] = []
    warning_results: list[CheckResult] = []

    if type(checks) is str:
        if checks == "all":
            checks = list(FILE_CHECKS.keys())
        else:
            checks = [checks]

    for check in checks:
        if check in FILE_CHECKS:
            res = FILE_CHECKS[check](files, rundir, extra)
            if not res.check_passed:
                if res.severity == CheckSeverity.error:
                    error_results.append(res)
                else:
                    warning_results.append(res)
        else:
            logger.error(f"Unknown check: {check}")

    # Pass only if no errors (warnings are OK)
    return not error_results, error_results, warning_results
