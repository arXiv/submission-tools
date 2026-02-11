import os
import re
import struct
import subprocess
from pathlib import Path

from .models import ImageInfo, logger

# Image file extensions we check
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".eps", ".ps", ".bmp", ".gif", ".tif", ".tiff"}


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
                # PNG: validate signature and read IHDR chunk
                # PNG signature: 89 50 4E 47 0D 0A 1A 0A
                signature = f.read(8)
                if signature != b"\x89PNG\r\n\x1a\n":
                    logger.debug(f"Invalid PNG signature in {filepath}")
                    return None
                # Read chunk length (4 bytes), chunk type (4 bytes), then IHDR data
                f.read(8)  # Skip chunk length and chunk type (IHDR)
                width, height = struct.unpack(">II", f.read(8))
                return width, height

            elif ext in {".jpg", ".jpeg"}:
                # JPEG: validate signature and scan for SOF markers
                # JPEG signature: FF D8
                signature = f.read(2)
                if signature != b"\xff\xd8":
                    logger.debug(f"Invalid JPEG signature in {filepath}")
                    return None

                # Scan for SOF markers with safety limit to prevent infinite loops on malformed files
                max_iterations = 100
                for _ in range(max_iterations):
                    marker = f.read(2)
                    if len(marker) != 2:
                        break
                    if marker[0] != 0xFF:
                        break
                    marker_type = marker[1]
                    # SOF0-SOF15 markers (except SOF4, SOF8, SOF12 which are unsupported)
                    if marker_type in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.seek(3, 1)  # Skip segment length (2 bytes) and precision (1 byte)
                        height, width = struct.unpack(">HH", f.read(4))
                        return width, height
                    # Read segment length and skip to next marker
                    seg_len = struct.unpack(">H", f.read(2))[0]
                    f.seek(seg_len - 2, 1)

            elif ext == ".gif":
                # GIF: validate signature and read dimensions
                # GIF signature: "GIF87a" or "GIF89a"
                signature = f.read(6)
                if signature not in (b"GIF87a", b"GIF89a"):
                    logger.debug(f"Invalid GIF signature in {filepath}")
                    return None
                # Dimensions immediately follow signature
                width, height = struct.unpack("<HH", f.read(4))
                return width, height

            elif ext == ".bmp":
                # BMP: validate signature and read dimensions
                # BMP signature: "BM" (42 4D)
                signature = f.read(2)
                if signature != b"BM":
                    logger.debug(f"Invalid BMP signature in {filepath}")
                    return None
                # Skip to dimensions at offset 18
                f.seek(18)
                width, height = struct.unpack("<II", f.read(8))
                return width, height

            elif ext in {".tif", ".tiff"}:
                # TIFF: more complex, read IFD entries
                # TIFF uses either little-endian (II) or big-endian (MM) byte order
                byte_order = f.read(2)
                if byte_order == b"II":
                    endian = "<"
                elif byte_order == b"MM":
                    endian = ">"
                else:
                    logger.debug(f"Invalid TIFF byte order in {filepath}")
                    return None

                # Validate TIFF magic number (42)
                magic = struct.unpack(endian + "H", f.read(2))[0]
                if magic != 42:
                    logger.debug(f"Invalid TIFF magic number in {filepath}")
                    return None

                # Read IFD (Image File Directory) offset
                ifd_offset = struct.unpack(endian + "I", f.read(4))[0]
                f.seek(ifd_offset)

                # Read number of directory entries
                num_entries = struct.unpack(endian + "H", f.read(2))[0]

                width = height = None
                # Each IFD entry is 12 bytes: tag(2) + type(2) + count(4) + value/offset(4)
                for _ in range(num_entries):
                    tag, field_type = struct.unpack(endian + "HH", f.read(4))
                    f.read(4)  # Skip count field (4 bytes)
                    # For SHORT(3) and LONG(4) types with count=1, value is stored directly
                    # in the value/offset field rather than being a pointer
                    value_bytes = f.read(4)

                    # Tag 256 = ImageWidth, Tag 257 = ImageLength (height)
                    # We only handle field types 3 (SHORT, 2 bytes) and 4 (LONG, 4 bytes)
                    if tag == 256 and field_type in (3, 4):
                        width = struct.unpack(
                            endian + ("H" if field_type == 3 else "I"), value_bytes[: 2 if field_type == 3 else 4]
                        )[0]
                    elif tag == 257 and field_type in (3, 4):
                        height = struct.unpack(
                            endian + ("H" if field_type == 3 else "I"), value_bytes[: 2 if field_type == 3 else 4]
                        )[0]

                if width and height:
                    return width, height

            elif ext == ".pdf":
                # For PDF, we can't easily get dimensions without parsing
                # the full PDF structure. Return None to skip dimension check
                return None

            elif ext in {".eps", ".ps"}:
                # EPS/PS: look for BoundingBox comment in DSC (Document Structuring Conventions)
                # Read first 1KB to find BoundingBox (sufficient for most well-formed EPS files)
                # Note: Some files may have BoundingBox later, but reading more increases I/O cost
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

    except (OSError, struct.error, UnicodeDecodeError) as e:
        logger.debug(f"Could not read dimensions for {filepath}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error reading dimensions for {filepath}: {e}")
        return None

    return None


def check_png_fast_copy(filepath: str) -> bool | None:
    """Check if a PNG file supports pdfTeX fast copy optimization.

    pdfTeX can include PNG files without recompression ("fast copy") only if the PNG:
    - Does not have an alpha channel (RGB+alpha, alpha)
    - Does not contain certain chunks: gAMA, sRGB, cHRM, iCCP, sBIT, bKGD, hIST, tRNS, sPLT
    - Is not interlaced

    This check matches the logic in pdftex's writepng.c source code.

    Args:
        filepath: Path to the PNG file

    Returns:
        True if the PNG supports fast copy, False if it does not, None if check failed
    """
    try:
        result = subprocess.run(
            ["pngcheck", "-v", filepath],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        # pngcheck returns non-zero for invalid files, but we still check the output
        output = result.stdout + result.stderr

        # Check for patterns that prevent fast copy
        # Based on pdftex's writepng.c logic
        # RGB+alpha and alpha indicate alpha channel presence
        # The other patterns are chunk types or properties that require reprocessing
        # Note: Use negative lookbehind for "interlaced" to avoid matching "non-interlaced"
        incompatible_pattern = re.compile(
            r"RGB\+alpha|gAMA|sRGB|cHRM|iCCP|sBIT|bKGD|hIST|tRNS|sPLT|(?<!non-)interlaced|(?<!RGB\+)alpha"
        )

        if incompatible_pattern.search(output):
            return False
        else:
            return True

    except FileNotFoundError:
        logger.debug("pngcheck not found, skipping fast copy check")
        return None
    except subprocess.TimeoutExpired:
        logger.warning(f"pngcheck timed out for {filepath}")
        return None
    except Exception as e:
        logger.debug(f"Could not run pngcheck on {filepath}: {e}")
        return None


def collect_image_info(files: list[str], rundir: str) -> list[ImageInfo]:
    """Collect information about all image files.

    Args:
        files: List of relative file paths
        rundir: Base directory containing the files

    Returns:
        List of dictionaries containing image metadata
    """
    image_info_list: list[ImageInfo] = []

    for filepath in files:
        ext = Path(filepath).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            continue

        img_info = ImageInfo(filename=filepath)
        full_path = os.path.join(rundir, filepath)
        if not os.path.isfile(full_path):
            continue

        dimensions = get_image_dimensions(full_path)
        file_size = os.path.getsize(full_path)

        img_info.file_bytes = file_size

        if dimensions:
            width, height = dimensions
            megapixels = (width * height) / 1_000_000
            img_info.width = width
            img_info.height = height
            img_info.megapixels = megapixels

        # Check if PNG supports pdfTeX fast copy
        if ext == ".png":
            fast_copy = check_png_fast_copy(full_path)
            if fast_copy is not None:
                img_info.pdftex_fast_copy = fast_copy
        else:
            # Assume all other images can be copied fast
            # TODO verify that for jpeg!
            img_info.pdftex_fast_copy = True

        image_info_list.append(img_info)

    return image_info_list
