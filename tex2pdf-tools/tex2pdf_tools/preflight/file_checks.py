"""This module implements QA checks for general files."""

import os
import struct
from pathlib import Path

from .checks import CheckResult, CheckSeverity, logger

# Image file extensions we check
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".ps", ".bmp", ".gif", ".tif", ".tiff"}

# Default threshold for oversized images (in megapixels)
# 50 megapixels = reasonable maximum for academic papers
DEFAULT_IMAGE_SIZE_THRESHOLD_MPIXELS = 50

FILE_CHECKS = {
    "no-exe": lambda res, rundir: check_no_exe(res),
    "image-sizes": lambda res, rundir: check_image_sizes(res, rundir),
}


def check_no_exe(files: list[str]) -> CheckResult:
    """Check for presence of EXE files."""
    logger.debug("Checking for presence of EXE files")
    if foo := [f for f in files if f.lower().endswith(".exe")]:
        return CheckResult(False, "EXE file found", str(foo))
    return CheckResult(True, "", "")


def get_image_dimensions(filepath: str) -> tuple[int, int] | None:
    """Get image dimensions without loading the entire image into memory.

    Args:
        filepath: Path to the image file

    Returns:
        Tuple of (width, height) in pixels, or None if unable to determine
    """
    try:
        with open(filepath, "rb") as f:
            ext = Path(filepath).suffix.lower()

            if ext == ".png":
                # PNG: read IHDR chunk
                f.seek(16)  # Skip PNG signature and chunk length/type
                width, height = struct.unpack(">II", f.read(8))
                return width, height

            elif ext in {".jpg", ".jpeg"}:
                # JPEG: scan for SOF markers
                f.seek(2)  # Skip JPEG signature
                while True:
                    marker = f.read(2)
                    if len(marker) != 2:
                        break
                    if marker[0] != 0xFF:
                        break
                    marker_type = marker[1]
                    # SOF0-SOF15 markers (except SOF4, SOF8, SOF12)
                    if marker_type in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.seek(3, 1)  # Skip length and precision
                        height, width = struct.unpack(">HH", f.read(4))
                        return width, height
                    # Read segment length and skip
                    seg_len = struct.unpack(">H", f.read(2))[0]
                    f.seek(seg_len - 2, 1)

            elif ext == ".gif":
                # GIF: dimensions at bytes 6-10
                f.seek(6)
                width, height = struct.unpack("<HH", f.read(4))
                return width, height

            elif ext == ".bmp":
                # BMP: dimensions at bytes 18-26
                f.seek(18)
                width, height = struct.unpack("<II", f.read(8))
                return width, height

            elif ext in {".tif", ".tiff"}:
                # TIFF: more complex, read IFD entries
                # Read byte order
                byte_order = f.read(2)
                if byte_order == b"II":
                    endian = "<"
                elif byte_order == b"MM":
                    endian = ">"
                else:
                    return None

                # Skip magic number
                f.read(2)

                # Read IFD offset
                ifd_offset = struct.unpack(endian + "I", f.read(4))[0]
                f.seek(ifd_offset)

                # Read number of directory entries
                num_entries = struct.unpack(endian + "H", f.read(2))[0]

                width = height = None
                for _ in range(num_entries):
                    tag, field_type = struct.unpack(endian + "HH", f.read(4))
                    # count = struct.unpack(endian + "I", f.read(4))[0]
                    value_offset = f.read(4)

                    # Tag 256 = ImageWidth, Tag 257 = ImageLength
                    if tag == 256:
                        if field_type in (3, 4):  # SHORT or LONG
                            width = struct.unpack(
                                endian + ("H" if field_type == 3 else "I"), value_offset[: 2 if field_type == 3 else 4]
                            )[0]
                    elif tag == 257:
                        if field_type in (3, 4):
                            height = struct.unpack(
                                endian + ("H" if field_type == 3 else "I"), value_offset[: 2 if field_type == 3 else 4]
                            )[0]

                if width and height:
                    return width, height

            elif ext == ".pdf":
                # For PDF, we can't easily get dimensions without parsing
                # PDF structure. Return None to skip dimension check
                return None

            elif ext in {".eps", ".ps"}:
                # EPS/PS: look for BoundingBox comment
                # Read first 1KB to find BoundingBox
                data = f.read(1024).decode("latin-1", errors="ignore")
                for line in data.split("\n"):
                    if line.startswith("%%BoundingBox:"):
                        parts = line.split()
                        if len(parts) >= 5:
                            try:
                                x1, y1, x2, y2 = map(int, parts[1:5])
                                return x2 - x1, y2 - y1
                            except ValueError:
                                pass
                return None

    except Exception as e:
        logger.debug(f"Could not read dimensions for {filepath}: {e}")
        return None

    return None


def collect_image_info(files: list[str], rundir: str) -> list[dict]:
    """Collect information about all image files.

    Args:
        files: List of relative file paths
        rundir: Base directory containing the files

    Returns:
        List of dictionaries containing image metadata
    """
    image_info_list = []

    for filepath in files:
        ext = Path(filepath).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue

        full_path = os.path.join(rundir, filepath)
        if not os.path.isfile(full_path):
            continue

        dimensions = get_image_dimensions(full_path)
        file_size = os.path.getsize(full_path)

        image_info = {
            "filename": filepath,
            "file_size_bytes": file_size,
        }

        if dimensions:
            width, height = dimensions
            megapixels = (width * height) / 1_000_000
            image_info.update(
                {
                    "width": width,
                    "height": height,
                    "megapixels": megapixels,
                }
            )

        image_info_list.append(image_info)

    return image_info_list


def check_image_sizes(
    files: list[str], rundir: str, threshold_mpixels: float = DEFAULT_IMAGE_SIZE_THRESHOLD_MPIXELS
) -> CheckResult:
    """Check for oversized images.

    Args:
        files: List of relative file paths
        rundir: Base directory containing the files
        threshold_mpixels: Maximum allowed image size in megapixels

    Returns:
        CheckResult with warning if oversized images found, including image metadata
    """
    logger.debug("Checking for oversized images")
    oversized_images = []
    all_image_info = collect_image_info(files, rundir)

    for img_info in all_image_info:
        megapixels = img_info.get("megapixels")
        if megapixels and megapixels > threshold_mpixels:
            width = img_info["width"]
            height = img_info["height"]
            file_size_mb = img_info["file_size_bytes"] / (1024 * 1024)
            filepath = img_info["filename"]
            oversized_images.append(f"{filepath} ({width}x{height}px, {megapixels:.1f}MP, {file_size_mb:.1f}MB)")
            img_info["is_oversized"] = True

    if oversized_images:
        info = f"Found {len(oversized_images)} oversized image(s) (>{threshold_mpixels}MP)"
        long_info = "\n".join(oversized_images)
        return CheckResult(
            check_passed=False,
            info=info,
            long_info=long_info,
            severity=CheckSeverity.warning,
            metadata={"image_files": all_image_info, "threshold_mpixels": threshold_mpixels},
        )

    return CheckResult(
        check_passed=True,
        info="",
        long_info="",
        severity=CheckSeverity.warning,
        metadata={"image_files": all_image_info, "threshold_mpixels": threshold_mpixels},
    )


def run_checks(
    files: list[str], checks: list[str] | str, rundir: str = "."
) -> tuple[bool, list[CheckResult], list[CheckResult]]:
    """Run a list of checks or all.

    Args:
        files: List of relative file paths to check
        checks: List of checks to run (or "all")
        rundir: Base directory containing the files (default: current directory)

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
            res = FILE_CHECKS[check](files, rundir)
            if not res.check_passed:
                if res.severity == CheckSeverity.error:
                    error_results.append(res)
                else:
                    warning_results.append(res)
        else:
            logger.error(f"Unknown check: {check}")

    # Pass only if no errors (warnings are OK)
    return not error_results, error_results, warning_results
