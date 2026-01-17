"""Tests for file_checks module."""

import os
import struct
import tempfile
from pathlib import Path

import pytest

from tex2pdf_tools.preflight.file_checks import (
    check_image_sizes,
    collect_image_info,
    get_image_dimensions,
    run_checks,
)
from tex2pdf_tools.preflight.checks import CheckSeverity


def create_test_png(filepath: str, width: int, height: int) -> None:
    """Create a minimal valid PNG file with specified dimensions."""
    with open(filepath, "wb") as f:
        # PNG signature
        f.write(b"\x89PNG\r\n\x1a\n")
        # IHDR chunk
        f.write(struct.pack(">I", 13))  # Chunk length
        f.write(b"IHDR")
        f.write(struct.pack(">II", width, height))
        f.write(b"\x08\x02\x00\x00\x00")  # bit depth, color type, etc.
        # CRC (dummy)
        f.write(b"\x00\x00\x00\x00")
        # IEND chunk
        f.write(struct.pack(">I", 0))
        f.write(b"IEND")
        f.write(b"\x00\x00\x00\x00")


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
        normal_img = [img for img in result.metadata["image_files"] if img["filename"] == "normal.png"][0]
        huge_img = [img for img in result.metadata["image_files"] if img["filename"] == "huge.png"][0]

        assert normal_img.get("is_oversized", False) is False
        assert huge_img["is_oversized"] is True
