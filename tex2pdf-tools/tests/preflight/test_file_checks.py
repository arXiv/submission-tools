"""Tests for file_checks module."""

import os
import struct
import tempfile
import zlib

import pytest

from tex2pdf_tools.preflight.checks import CheckSeverity
from tex2pdf_tools.preflight.file_checks import (
    check_image_sizes,
    check_png_fast_copy,
    collect_image_info,
    get_image_dimensions,
    run_checks,
)


def create_test_png(
    filepath: str, width: int, height: int, color_type: int = 2, extra_chunks: list[bytes] | None = None
) -> None:
    """Create a minimal valid PNG file with specified dimensions.

    Args:
        filepath: Path where to create the PNG file
        width: Image width in pixels
        height: Image height in pixels
        color_type: PNG color type (2=RGB, 6=RGBA/RGB+alpha)
        extra_chunks: List of additional chunk names to include (e.g., [b"gAMA", b"sRGB"])
    """
    with open(filepath, "wb") as f:
        # PNG signature
        f.write(b"\x89PNG\r\n\x1a\n")

        # IHDR chunk
        ihdr_data = struct.pack(">II", width, height) + bytes([8, color_type, 0, 0, 0])
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        f.write(struct.pack(">I", 13))  # Chunk length
        f.write(b"IHDR")
        f.write(ihdr_data)
        f.write(struct.pack(">I", ihdr_crc))

        # Add extra chunks if specified
        if extra_chunks:
            for chunk_name in extra_chunks:
                # Write a minimal chunk with the specified name
                chunk_data = b"\x00\x00\x00\x00"  # Dummy data
                chunk_crc = zlib.crc32(chunk_name + chunk_data) & 0xFFFFFFFF
                f.write(struct.pack(">I", 4))  # Chunk length (4 bytes of dummy data)
                f.write(chunk_name)
                f.write(chunk_data)
                f.write(struct.pack(">I", chunk_crc))

        # IEND chunk
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        f.write(struct.pack(">I", 0))
        f.write(b"IEND")
        f.write(struct.pack(">I", iend_crc))


def create_test_jpeg(filepath: str, width: int, height: int) -> None:
    """Create a minimal valid JPEG file with specified dimensions."""
    with open(filepath, "wb") as f:
        # JPEG signature
        f.write(b"\xff\xd8")
        # SOF0 marker
        f.write(b"\xff\xc0")
        # Segment length
        f.write(struct.pack(">H", 17))
        # Precision
        f.write(b"\x08")
        # Height and width
        f.write(struct.pack(">HH", height, width))
        # Number of components
        f.write(b"\x03")
        # Component data (3 components)
        f.write(b"\x01\x22\x00\x02\x11\x01\x03\x11\x01")
        # EOI marker
        f.write(b"\xff\xd9")


def test_get_png_dimensions():
    """Test extracting PNG dimensions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "test.png")
        create_test_png(png_file, 1920, 1080)

        dims = get_image_dimensions(png_file)
        assert dims == (1920, 1080)


def test_get_jpeg_dimensions():
    """Test extracting JPEG dimensions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        jpeg_file = os.path.join(tmpdir, "test.jpg")
        create_test_jpeg(jpeg_file, 3840, 2160)

        dims = get_image_dimensions(jpeg_file)
        assert dims == (3840, 2160)


def test_check_image_sizes_normal():
    """Test that normal-sized images pass the check."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a 2MP image (well below 50MP threshold)
        png_file = os.path.join(tmpdir, "normal.png")
        create_test_png(png_file, 1600, 1200)

        files = ["normal.png"]
        result = check_image_sizes(files, tmpdir, threshold_mpixels=50)

        assert result.check_passed is True
        assert result.info == ""


def test_check_image_sizes_oversized():
    """Test that oversized images are detected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a 100MP image (exceeds 50MP threshold)
        png_file = os.path.join(tmpdir, "huge.png")
        create_test_png(png_file, 10000, 10000)

        files = ["huge.png"]
        result = check_image_sizes(files, tmpdir, threshold_mpixels=50)

        assert result.check_passed is False
        assert result.severity == CheckSeverity.warning
        assert "oversized image" in result.info.lower()
        assert "huge.png" in result.long_info
        assert result.metadata is not None
        assert "image_files" in result.metadata
        assert len(result.metadata["image_files"]) == 1
        assert result.metadata["image_files"][0]["is_oversized"] is True


def test_check_image_sizes_multiple_oversized():
    """Test detecting multiple oversized images."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create two oversized images
        png1 = os.path.join(tmpdir, "huge1.png")
        png2 = os.path.join(tmpdir, "huge2.jpg")
        create_test_png(png1, 8000, 8000)
        create_test_jpeg(png2, 9000, 9000)

        files = ["huge1.png", "huge2.jpg"]
        result = check_image_sizes(files, tmpdir, threshold_mpixels=50)

        assert result.check_passed is False
        assert "2" in result.info or "multiple" in result.info.lower()
        assert "huge1.png" in result.long_info
        assert "huge2.jpg" in result.long_info


def test_check_image_sizes_custom_threshold():
    """Test using a custom threshold."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a 10MP image
        png_file = os.path.join(tmpdir, "medium.png")
        create_test_png(png_file, 3162, 3162)  # ~10MP

        files = ["medium.png"]

        # Should pass with 20MP threshold
        result = check_image_sizes(files, tmpdir, threshold_mpixels=20)
        assert result.check_passed is True

        # Should fail with 5MP threshold
        result = check_image_sizes(files, tmpdir, threshold_mpixels=5)
        assert result.check_passed is False


def test_check_image_sizes_ignores_non_images():
    """Test that non-image files are ignored."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a text file
        txt_file = os.path.join(tmpdir, "not_an_image.txt")
        with open(txt_file, "w") as f:
            f.write("This is not an image")

        files = ["not_an_image.txt"]
        result = check_image_sizes(files, tmpdir, threshold_mpixels=50)

        # Should pass (no images found)
        assert result.check_passed is True


def test_run_checks_with_image_sizes():
    """Test running image size checks through run_checks interface."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create oversized image
        png_file = os.path.join(tmpdir, "oversized.png")
        create_test_png(png_file, 10000, 10000)

        files = ["oversized.png"]
        passed, error_checks, warning_checks = run_checks(files, "image-sizes", tmpdir)

        # Should pass (no errors), but have warnings
        assert passed is True
        assert len(error_checks) == 0
        assert len(warning_checks) == 1
        assert "oversized" in warning_checks[0].info.lower()
        assert warning_checks[0].severity == CheckSeverity.warning


def test_run_checks_all():
    """Test running all checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a valid small image
        png_file = os.path.join(tmpdir, "small.png")
        create_test_png(png_file, 800, 600)

        files = ["small.png"]
        passed, error_checks, warning_checks = run_checks(files, "all", tmpdir)

        # Should pass all checks (no errors)
        assert passed is True
        assert len(error_checks) == 0
        # May have warnings with metadata about images
        # but none should be oversized
        for warning in warning_checks:
            if warning.metadata and "image_files" in warning.metadata:
                for img in warning.metadata["image_files"]:
                    assert img.get("is_oversized", False) is False


def test_get_image_dimensions_invalid_file():
    """Test handling of invalid/corrupted image files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create an invalid PNG file
        bad_png = os.path.join(tmpdir, "bad.png")
        with open(bad_png, "wb") as f:
            f.write(b"Not a real PNG file")

        dims = get_image_dimensions(bad_png)
        # Should return None for invalid files
        assert dims is None


def test_get_image_dimensions_nonexistent_file():
    """Test handling of nonexistent files."""
    dims = get_image_dimensions("/nonexistent/file.png")
    assert dims is None


def test_collect_image_info():
    """Test collecting image information."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create images of various sizes
        png1 = os.path.join(tmpdir, "small.png")
        png2 = os.path.join(tmpdir, "large.png")
        create_test_png(png1, 800, 600)
        create_test_png(png2, 4000, 3000)

        files = ["small.png", "large.png"]
        image_info = collect_image_info(files, tmpdir)

        assert len(image_info) == 2
        assert image_info[0]["filename"] == "small.png"
        assert image_info[0]["width"] == 800
        assert image_info[0]["height"] == 600
        assert image_info[0]["megapixels"] == pytest.approx(0.48, rel=0.01)
        assert image_info[1]["filename"] == "large.png"
        assert image_info[1]["width"] == 4000
        assert image_info[1]["height"] == 3000
        assert image_info[1]["megapixels"] == pytest.approx(12.0, rel=0.01)


def test_check_image_sizes_returns_all_images():
    """Test that check returns info about all images, not just oversized ones."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create mix of normal and oversized images
        png1 = os.path.join(tmpdir, "normal.png")
        png2 = os.path.join(tmpdir, "huge.png")
        create_test_png(png1, 1920, 1080)
        create_test_png(png2, 10000, 10000)

        files = ["normal.png", "huge.png"]
        result = check_image_sizes(files, tmpdir, threshold_mpixels=50)

        # Should fail due to oversized image
        assert result.check_passed is False
        assert result.severity == CheckSeverity.warning

        # But metadata should contain info about ALL images
        assert result.metadata is not None
        assert "image_files" in result.metadata
        assert len(result.metadata["image_files"]) == 2

        # Check that is_oversized flag is set correctly
        normal_img = next(img for img in result.metadata["image_files"] if img["filename"] == "normal.png")
        huge_img = next(img for img in result.metadata["image_files"] if img["filename"] == "huge.png")

        assert normal_img.get("is_oversized", False) is False
        assert huge_img["is_oversized"] is True


def test_check_png_fast_copy_simple_rgb():
    """Test that a simple RGB PNG supports fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "simple.png")
        # Create simple RGB PNG without problematic chunks
        create_test_png(png_file, 800, 600, color_type=2)

        result = check_png_fast_copy(png_file)
        # Should return True (supports fast copy) or None (pngcheck not available)
        assert result is True or result is None


def test_check_png_fast_copy_with_alpha():
    """Test that PNG with alpha channel does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "alpha.png")
        # Create RGBA PNG (color type 6 = RGB+alpha)
        create_test_png(png_file, 800, 600, color_type=6)

        result = check_png_fast_copy(png_file)
        # Should return False (does not support fast copy) or None (pngcheck not available)
        assert result is False or result is None


def test_check_png_fast_copy_with_gamma():
    """Test that PNG with gAMA chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "gamma.png")
        # Create PNG with gAMA chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"gAMA"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_srgb():
    """Test that PNG with sRGB chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "srgb.png")
        # Create PNG with sRGB chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"sRGB"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_chrm():
    """Test that PNG with cHRM chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "chrm.png")
        # Create PNG with cHRM chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"cHRM"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_iccp():
    """Test that PNG with iCCP chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "iccp.png")
        # Create PNG with iCCP chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"iCCP"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_trns():
    """Test that PNG with tRNS chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "trns.png")
        # Create PNG with tRNS chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"tRNS"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_sbit():
    """Test that PNG with sBIT chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "sbit.png")
        # Create PNG with sBIT chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"sBIT"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_bkgd():
    """Test that PNG with bKGD chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "bkgd.png")
        # Create PNG with bKGD chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"bKGD"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_hist():
    """Test that PNG with hIST chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "hist.png")
        # Create PNG with hIST chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"hIST"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_splt():
    """Test that PNG with sPLT chunk does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "splt.png")
        # Create PNG with sPLT chunk
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"sPLT"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_check_png_fast_copy_with_multiple_chunks():
    """Test that PNG with multiple problematic chunks does not support fast copy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        png_file = os.path.join(tmpdir, "multi.png")
        # Create PNG with multiple problematic chunks
        create_test_png(png_file, 800, 600, color_type=2, extra_chunks=[b"gAMA", b"sRGB", b"cHRM"])

        result = check_png_fast_copy(png_file)
        assert result is False or result is None


def test_collect_image_info_includes_pdftex_fast_copy():
    """Test that collect_image_info includes pdftex-fast-copy field for PNG files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a simple PNG that should support fast copy
        png_simple = os.path.join(tmpdir, "simple.png")
        create_test_png(png_simple, 800, 600, color_type=2)

        # Create a PNG with alpha that should not support fast copy
        png_alpha = os.path.join(tmpdir, "alpha.png")
        create_test_png(png_alpha, 800, 600, color_type=6)

        # Create a JPEG (should not have pdftex-fast-copy field)
        jpeg_file = os.path.join(tmpdir, "test.jpg")
        create_test_jpeg(jpeg_file, 800, 600)

        files = ["simple.png", "alpha.png", "test.jpg"]
        image_info = collect_image_info(files, tmpdir)

        assert len(image_info) == 3

        # Find each image in the results
        simple_info = next(img for img in image_info if img["filename"] == "simple.png")
        alpha_info = next(img for img in image_info if img["filename"] == "alpha.png")
        jpeg_info = next(img for img in image_info if img["filename"] == "test.jpg")

        # PNG files should have pdftex-fast-copy field (if pngcheck is available)
        # If pngcheck is not available, the field won't be present
        if "pdftex-fast-copy" in simple_info:
            assert simple_info["pdftex-fast-copy"] is True
        if "pdftex-fast-copy" in alpha_info:
            assert alpha_info["pdftex-fast-copy"] is False

        # JPEG should not have pdftex-fast-copy field
        assert "pdftex-fast-copy" not in jpeg_info
