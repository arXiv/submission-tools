"""Convert PNG images to pdfTeX fast copy compatible format.

This module provides utilities to convert PNG files that are incompatible with
pdfTeX's fast copy optimization into compatible versions by:
- Removing alpha channels (converting RGBA to RGB)
- Stripping problematic color/metadata chunks
- Deinterlacing if needed
- Optionally reducing file size

See check_png_fast_copy() in file_checks.py for the compatibility criteria.
"""

import argparse
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from tex2pdf_tools.preflight.file_checks import check_png_fast_copy

logger = logging.getLogger(__name__)

# Problematic PNG chunks that prevent fast copy
INCOMPATIBLE_CHUNKS = ["gAMA", "sRGB", "cHRM", "iCCP", "sBIT", "bKGD", "hIST", "tRNS", "sPLT"]


def has_tool(tool: str) -> bool:
    """Check if a tool is available in PATH."""
    return shutil.which(tool) is not None


def convert_with_imagemagick(input_path: str, output_path: str, strip_profiles: bool = True) -> bool:
    """Convert PNG using ImageMagick (convert/magick).

    Args:
        input_path: Path to input PNG
        output_path: Path to output PNG
        strip_profiles: Whether to strip color profiles and metadata

    Returns:
        True if successful, False otherwise
    """
    try:
        # Use 'magick' if available (ImageMagick 7+), otherwise 'convert'
        tool = "magick" if has_tool("magick") else "convert"
        if not has_tool(tool):
            logger.debug(f"{tool} not found")
            return False

        cmd = [tool, input_path]

        # Convert RGBA to RGB by compositing on white background
        cmd.extend(["-background", "white", "-alpha", "remove", "-alpha", "off"])

        # Strip color profiles and metadata
        if strip_profiles:
            cmd.extend(["-strip"])

        # Ensure not interlaced (non-interlaced is default)
        cmd.extend(["-interlace", "None"])

        cmd.append(output_path)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode == 0:
            logger.info(f"Successfully converted {input_path} using {tool}")
            return True
        else:
            logger.warning(f"{tool} failed: {result.stderr}")
            return False

    except FileNotFoundError:
        logger.debug("ImageMagick tool not found")
        return False
    except subprocess.TimeoutExpired:
        logger.warning(f"ImageMagick timeout converting {input_path}")
        return False
    except Exception as e:
        logger.warning(f"Error converting with ImageMagick: {e}")
        return False


def convert_with_pngcrush(input_path: str, output_path: str) -> bool:
    """Convert PNG using pngcrush.

    pngcrush removes color chunks and can reduce file size.

    Args:
        input_path: Path to input PNG
        output_path: Path to output PNG

    Returns:
        True if successful, False otherwise
    """
    try:
        if not has_tool("pngcrush"):
            logger.debug("pngcrush not found")
            return False

        # Remove problematic ancillary chunks and optimize output.
        cmd = ["pngcrush", "-q"]
        for chunk in INCOMPATIBLE_CHUNKS:
            cmd.extend(["-rem", chunk])
        cmd.extend(["-reduce", input_path, output_path])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode == 0:
            logger.info(f"Successfully converted {input_path} using pngcrush")
            return True
        else:
            logger.warning(f"pngcrush failed: {result.stderr}")
            return False

    except FileNotFoundError:
        logger.debug("pngcrush not found")
        return False
    except subprocess.TimeoutExpired:
        logger.warning(f"pngcrush timeout converting {input_path}")
        return False
    except Exception as e:
        logger.warning(f"Error converting with pngcrush: {e}")
        return False


def convert_with_pnm(input_path: str, output_path: str) -> bool:
    """Convert PNG using pnmtopng via PNM intermediate format.

    This approach strips all metadata and chunks by converting through PNM format.

    Args:
        input_path: Path to input PNG
        output_path: Path to output PNG

    Returns:
        True if successful, False otherwise
    """
    try:
        if not has_tool("pngtopnm") or not has_tool("pnmtopng"):
            logger.debug("pngtopnm or pnmtopng not found")
            return False

        with tempfile.TemporaryDirectory() as tmpdir:
            pnm_file = os.path.join(tmpdir, "temp.pnm")

            # Convert PNG to PNM (strips all chunks/profiles)
            pngtopnm_cmd = ["pngtopnm", input_path]
            with open(pnm_file, "wb") as f:
                result = subprocess.run(pngtopnm_cmd, stdout=f, stderr=subprocess.PIPE, timeout=30, check=False)
                if result.returncode != 0:
                    logger.warning(f"pngtopnm failed: {result.stderr.decode('utf-8', errors='replace')}")
                    return False

            # Convert PNM back to PNG (clean, no metadata), writing PNG bytes to output path.
            pnmtopng_cmd = ["pnmtopng", pnm_file]
            with open(output_path, "wb") as f:
                result = subprocess.run(pnmtopng_cmd, stdout=f, stderr=subprocess.PIPE, timeout=30, check=False)
            if result.returncode == 0:
                logger.info(f"Successfully converted {input_path} using pngtopnm->pnmtopng")
                return True
            else:
                logger.warning(f"pnmtopng failed: {result.stderr.decode('utf-8', errors='replace')}")
                return False

    except FileNotFoundError:
        logger.debug("pngtopnm or pnmtopng not found")
        return False
    except subprocess.TimeoutExpired:
        logger.warning(f"PNM conversion timeout for {input_path}")
        return False
    except Exception as e:
        logger.warning(f"Error converting with PNM: {e}")
        return False


def check_output_fast_copy(filepath: str) -> bool | None:
    """Check whether converted output is fast copy compatible."""
    try:
        return check_png_fast_copy(filepath)
    except Exception as e:
        logger.debug(f"Could not verify fast copy compatibility for {filepath}: {e}")
        return None


def run_method_and_verify(
    method_name: str, method_func: Callable[[str, str], bool], input_path: str, output_path: str
) -> bool:
    """Run one conversion method and verify output compatibility when possible."""
    if not method_func(input_path, output_path):
        return False

    fast_copy = check_output_fast_copy(output_path)
    if fast_copy is False:
        logger.warning(f"{method_name} conversion succeeded but output is not fast copy compatible")
        return False

    return True


def convert_png_to_fast_copy(
    input_path: str, output_path: str | None = None, method: str = "auto", backup: bool = True
) -> bool:
    """Convert a PNG to pdfTeX fast copy compatible format.

    This function attempts to convert a PNG file that may have alpha channel,
    color profiles, or metadata chunks into a format compatible with pdfTeX's
    fast copy optimization.

    Args:
        input_path: Path to input PNG file
        output_path: Path to output PNG file (defaults to input_path)
        method: Conversion method to use:
            - "auto": Try methods in order (imagemagick, pngcrush, pnm)
            - "imagemagick": Use ImageMagick only
            - "pngcrush": Use pngcrush only
            - "pnm": Use PNM conversion only
        backup: If True and output_path == input_path, create a backup of the original

    Returns:
        True if conversion was successful, False otherwise
    """
    if not os.path.exists(input_path):
        logger.error(f"Input file not found: {input_path}")
        return False

    if output_path is None:
        output_path = input_path

    # Create backup if overwriting original
    backup_path = None
    if backup and output_path == input_path:
        backup_path = f"{input_path}.bak"
        if not os.path.exists(backup_path):
            logger.info(f"Creating backup: {backup_path}")
            shutil.copy2(input_path, backup_path)

    try:
        if method == "auto":
            # Try methods in order of preference
            methods: list[tuple[str, Callable[[str, str], bool]]] = [
                ("imagemagick", convert_with_imagemagick),
                ("pngcrush", convert_with_pngcrush),
                ("pnm", convert_with_pnm),
            ]

            for method_name, method_func in methods:
                if run_method_and_verify(method_name, method_func, input_path, output_path):
                    return True

            logger.error("All conversion methods failed")
            return False

        elif method == "imagemagick":
            return run_method_and_verify("imagemagick", convert_with_imagemagick, input_path, output_path)
        elif method == "pngcrush":
            return run_method_and_verify("pngcrush", convert_with_pngcrush, input_path, output_path)
        elif method == "pnm":
            return run_method_and_verify("pnm", convert_with_pnm, input_path, output_path)
        else:
            logger.error(f"Unknown conversion method: {method}")
            return False

    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        if backup_path and os.path.exists(backup_path):
            logger.info(f"Restoring backup from {backup_path}")
            shutil.copy2(backup_path, input_path)
        return False


def convert_png_directory(
    directory: str, pattern: str = "*.png", method: str = "auto", backup: bool = True, inplace: bool = True
) -> tuple[int, int]:
    """Convert all PNG files in a directory to fast copy compatible format.

    Args:
        directory: Path to directory containing PNG files
        pattern: Glob pattern for matching files (default: *.png)
        method: Conversion method to use (see convert_png_to_fast_copy)
        backup: Whether to create backups
        inplace: If True, overwrite originals; if False, create .fastcopy.png variants

    Returns:
        Tuple of (successful_count, failed_count)
    """
    png_files = Path(directory).glob(pattern)
    successful = 0
    failed = 0

    for png_file in png_files:
        output_file = str(png_file) if inplace else str(png_file).replace(".png", ".fastcopy.png")

        if convert_png_to_fast_copy(str(png_file), output_file, method=method, backup=backup):
            successful += 1
        else:
            failed += 1

    return successful, failed


def main(argv: list[str] | None = None) -> int:
    """Run the PNG to fast copy conversion CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        prog="png-to-fast-copy",
        description="Convert PNG images to pdfTeX fast copy compatible format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
DESCRIPTION:
  Converts PNG images that have alpha channels, color profiles, metadata chunks,
  or interlacing into a format compatible with pdfTeX's fast copy optimization.
  This can improve TeX compilation performance by avoiding PNG recompression.

INCOMPATIBLE FEATURES REMOVED:
  - Alpha channels (RGBA → RGB conversion)
  - Color/metadata chunks: gAMA, sRGB, cHRM, iCCP, sBIT, bKGD, hIST, tRNS, sPLT
  - Interlacing (Adam7 → non-interlaced)

CONVERSION METHODS:
  auto         Try ImageMagick, pngcrush, and PNM in order (default)
  imagemagick  Use ImageMagick (convert/magick) only
  pngcrush     Use pngcrush only
  pnm          Use pngtopnm and pnmtopng for maximum chunk removal

EXAMPLES:
  # Convert single PNG in-place
  png-to-fast-copy image.png

  # Convert and save to different file
  png-to-fast-copy image.png -o converted.png

  # Convert all PNGs in directory
  png-to-fast-copy --directory /path/to/images

  # Use specific method
  png-to-fast-copy image.png --method imagemagick

  # Don't create backups when overwriting
  png-to-fast-copy image.png --no-backup

  # Create .fastcopy.png variants instead of overwriting
  png-to-fast-copy --directory /path --no-inplace
        """,
    )

    parser.add_argument("file", nargs="?", help="PNG file to convert")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument("-d", "--directory", help="Convert all PNGs in directory")
    parser.add_argument(
        "-m",
        "--method",
        choices=["auto", "imagemagick", "pngcrush", "pnm"],
        default="auto",
        help="Conversion method (default: auto)",
    )
    parser.add_argument("--no-backup", action="store_true", help="Don't create backups when overwriting")
    parser.add_argument(
        "--no-inplace", action="store_true", help="Create .fastcopy.png variants instead of overwriting"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output")

    args = parser.parse_args(argv)

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format="%(levelname)s: %(message)s")

    # Process directory
    if args.directory:
        print(f"Converting PNGs in {args.directory} (method: {args.method})...")
        successful, failed = convert_png_directory(
            args.directory, method=args.method, backup=not args.no_backup, inplace=not args.no_inplace
        )
        print(f"\n✓ Success: {successful}")
        if failed > 0:
            print(f"✗ Failed: {failed}")
        return 0 if failed == 0 else 1

    # Process single file
    elif args.file:
        print(f"Converting PNG (method: {args.method})...")
        success = convert_png_to_fast_copy(
            args.file, output_path=args.output, method=args.method, backup=not args.no_backup
        )
        if success:
            output_info = f" → {args.output}" if args.output else " (in-place)"
            print(f"✓ Successfully converted: {args.file}{output_info}")
            return 0
        else:
            print(f"✗ Failed to convert: {args.file}")
            return 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
