"""Tests for PNG to fast copy conversion module."""

import os
import subprocess
import tempfile
from unittest.mock import patch

import pytest

from .test_file_checks import create_test_png
from tex2pdf_tools.preflight.file_checks import check_png_fast_copy
from tex2pdf_tools.preflight.png_to_fast_copy import (
    convert_png_directory,
    convert_png_to_fast_copy,
    convert_with_imagemagick,
    convert_with_pngcrush,
    convert_with_pnm,
    has_tool,
    main,
)


class TestHasTool:
    """Test the has_tool function."""

    def test_has_tool_existing(self):
        """Test detection of existing tools."""
        # Python should always be available
        assert has_tool("python") or has_tool("python3")

    def test_has_tool_nonexistent(self):
        """Test detection of nonexistent tools."""
        assert not has_tool("nonexistent-tool-xyz-123")


class TestConvertPngToFastCopy:
    """Test the main convert_png_to_fast_copy function."""

    def test_file_not_found(self):
        """Test error handling for nonexistent input file."""
        result = convert_png_to_fast_copy("/nonexistent/file.png")
        assert result is False

    def test_backup_creation(self):
        """Test that backup files are created when overwriting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            # Test with mocked conversion function
            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True):
                result = convert_png_to_fast_copy(png_file, backup=True)
                assert result is True

                # Backup should be created
                backup_file = f"{png_file}.bak"
                assert os.path.exists(backup_file)

    def test_no_backup_creation(self):
        """Test that backup files are not created when backup=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True):
                result = convert_png_to_fast_copy(png_file, backup=False)
                assert result is True

                # Backup should not be created
                backup_file = f"{png_file}.bak"
                assert not os.path.exists(backup_file)

    def test_output_to_different_file(self):
        """Test conversion to a different output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.png")
            output_file = os.path.join(tmpdir, "output.png")
            create_test_png(input_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True):
                result = convert_png_to_fast_copy(input_file, output_path=output_file)
                assert result is True

    def test_backup_not_recreated(self):
        """Test that existing backups are not overwritten."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            backup_file = f"{png_file}.bak"
            create_test_png(png_file, 100, 100)

            # Create initial backup
            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True):
                convert_png_to_fast_copy(png_file, backup=True)
                assert os.path.exists(backup_file)
                backup_stat = os.stat(backup_file)

            # Try to convert again - backup should not be recreated
            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True):
                convert_png_to_fast_copy(png_file, backup=True)
                assert os.path.exists(backup_file)
                # Backup mtime should be same (file not recreated)
                assert backup_stat.st_mtime == os.stat(backup_file).st_mtime

    def test_method_selection(self):
        """Test different conversion method selection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            # Test auto method (tries each in order)
            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=False), \
                 patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_pngcrush", return_value=True):
                result = convert_png_to_fast_copy(png_file, method="auto", backup=False)
                assert result is True

            # Test specific method
            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True):
                result = convert_png_to_fast_copy(png_file, method="imagemagick", backup=False)
                assert result is True

    def test_all_methods_fail(self):
        """Test handling when all conversion methods fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=False), \
                 patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_pngcrush", return_value=False), \
                 patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_pnm", return_value=False):
                result = convert_png_to_fast_copy(png_file, method="auto", backup=False)
                assert result is False

    def test_output_must_be_fast_copy_compatible(self):
        """Test conversion is rejected when output is still incompatible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True), \
                 patch("tex2pdf_tools.preflight.png_to_fast_copy.check_output_fast_copy", return_value=False):
                result = convert_png_to_fast_copy(png_file, method="imagemagick", backup=False)
                assert result is False

    def test_auto_fallback_on_incompatible_output(self):
        """Test auto mode falls back when a method output is incompatible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_imagemagick", return_value=True), \
                 patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_with_pngcrush", return_value=True), \
                 patch("tex2pdf_tools.preflight.png_to_fast_copy.check_output_fast_copy", side_effect=[False, True]):
                result = convert_png_to_fast_copy(png_file, method="auto", backup=False)
                assert result is True


class TestConvertPngDirectory:
    """Test directory conversion functionality."""

    def test_convert_directory_empty(self):
        """Test converting empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            successful, failed = convert_png_directory(tmpdir)
            assert successful == 0
            assert failed == 0

    def test_convert_directory_single_file(self):
        """Test converting directory with one file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy", return_value=True):
                successful, failed = convert_png_directory(tmpdir)
                assert successful == 1
                assert failed == 0

    def test_convert_directory_multiple_files(self):
        """Test converting directory with multiple files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                png_file = os.path.join(tmpdir, f"test{i}.png")
                create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy", return_value=True):
                successful, failed = convert_png_directory(tmpdir)
                assert successful == 3
                assert failed == 0

    def test_convert_directory_mixed_results(self):
        """Test directory conversion with some successes and failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                png_file = os.path.join(tmpdir, f"test{i}.png")
                create_test_png(png_file, 100, 100)

            call_count = [0]

            def mock_convert(input_path, *args, **kwargs):
                call_count[0] += 1
                return call_count[0] != 2  # Fail on second call

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy", side_effect=mock_convert):
                successful, failed = convert_png_directory(tmpdir)
                assert successful == 2
                assert failed == 1

    def test_convert_directory_no_inplace(self):
        """Test directory conversion with --no-inplace option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy") as mock_convert:
                mock_convert.return_value = True
                successful, failed = convert_png_directory(tmpdir, inplace=False)

                # Should be called with output_path argument (positional arg[1])
                called_output = mock_convert.call_args[0][1] if len(mock_convert.call_args[0]) > 1 else None
                assert called_output is not None
                assert called_output.endswith(".fastcopy.png")


class TestConversionMethods:
    """Test individual conversion methods."""

    def test_imagemagick_not_available(self):
        """Test ImageMagick handling when tool not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.png")
            output_file = os.path.join(tmpdir, "output.png")
            create_test_png(input_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.has_tool", return_value=False):
                result = convert_with_imagemagick(input_file, output_file)
                assert result is False

    def test_pngcrush_not_available(self):
        """Test pngcrush handling when tool not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.png")
            output_file = os.path.join(tmpdir, "output.png")
            create_test_png(input_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.has_tool", return_value=False):
                result = convert_with_pngcrush(input_file, output_file)
                assert result is False

    def test_pngcrush_command(self):
        """Test pngcrush invocation shape."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.png")
            output_file = os.path.join(tmpdir, "output.png")
            create_test_png(input_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.has_tool", return_value=True), \
                 patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stderr = ""
                result = convert_with_pngcrush(input_file, output_file)
                assert result is True
                cmd = mock_run.call_args[0][0]
                assert cmd[0] == "pngcrush"
                assert "-rem" in cmd
                assert input_file in cmd
                assert output_file in cmd

    def test_pnm_uses_stdout_for_output(self):
        """Test PNM path writes pnmtopng stdout to output file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.png")
            output_file = os.path.join(tmpdir, "output.png")
            create_test_png(input_file, 100, 100)

            call_index = {"n": 0}

            def mock_run(cmd, **kwargs):
                call_index["n"] += 1
                result = type("R", (), {})()
                result.returncode = 0
                result.stderr = b""
                if call_index["n"] == 1:
                    assert cmd[0] == "pngtopnm"
                    assert cmd[1] == input_file
                    assert "stdout" in kwargs
                else:
                    assert cmd[0] == "pnmtopng"
                    assert len(cmd) == 2
                    assert cmd[1].endswith("temp.pnm")
                    assert "stdout" in kwargs
                return result

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.has_tool", return_value=True), \
                 patch("subprocess.run", side_effect=mock_run):
                result = convert_with_pnm(input_file, output_file)
                assert result is True

    def test_pnm_not_available(self):
        """Test PNM conversion handling when tools not available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.png")
            output_file = os.path.join(tmpdir, "output.png")
            create_test_png(input_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.has_tool", return_value=False):
                result = convert_with_pnm(input_file, output_file)
                assert result is False


@pytest.mark.skipif(
    not all(has_tool(tool) for tool in ("magick", "pngcrush", "pngcheck", "pngtopnm", "pnmtopng")),
    reason="requires magick/pngcrush/pngcheck/pngtopnm/pnmtopng",
)
class TestIntegrationRealTools:
    """Integration tests using real external conversion tools."""

    def _create_incompatible_png(self, output_path: str, rgba: bool = False) -> None:
        color = "rgba(255,0,0,0.5)" if rgba else "red"
        subprocess.run(["magick", "-size", "16x16", f"xc:{color}", output_path], check=True)

    def _create_png_with_gamma_chunk(self, output_path: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_file = os.path.join(tmpdir, "base.png")
            subprocess.run(["magick", "-size", "16x16", "xc:red", base_file], check=True)
            subprocess.run(["pngcrush", "-q", "-g", "0.45455", base_file, output_path], check=True)

    def _find_icc_profile(self) -> str | None:
        candidates = [
            "/usr/share/ghostscript/iccprofiles/srgb.icc",
            "/usr/share/ghostscript/iccprofiles/default_rgb.icc",
            "/usr/share/color/icc/colord/sRGB.icc",
        ]
        for profile in candidates:
            if os.path.exists(profile):
                return profile
        return None

    def _create_png_with_iccp_chunk(self, output_path: str) -> None:
        icc_profile = self._find_icc_profile()
        if icc_profile is None:
            pytest.skip("requires a local ICC profile for iCCP test")
        with tempfile.TemporaryDirectory() as tmpdir:
            base_file = os.path.join(tmpdir, "base.png")
            subprocess.run(["magick", "-size", "16x16", "xc:red", base_file], check=True)
            subprocess.run(["magick", base_file, "-profile", icc_profile, output_path], check=True)

    def _pngcheck_output(self, png_path: str) -> str:
        result = subprocess.run(["pngcheck", "-v", png_path], capture_output=True, text=True, check=False)
        return result.stdout + result.stderr

    def test_imagemagick_end_to_end(self):
        """ImageMagick conversion should produce fast-copy-compatible output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input_im.png")
            output_file = os.path.join(tmpdir, "output_im.png")
            self._create_incompatible_png(input_file, rgba=True)

            assert check_png_fast_copy(input_file) is False
            assert convert_png_to_fast_copy(input_file, output_path=output_file, method="imagemagick", backup=False)
            assert check_png_fast_copy(output_file) is True

    def test_pngcrush_end_to_end(self):
        """pngcrush conversion should remove incompatible PNG chunks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input_crush.png")
            output_file = os.path.join(tmpdir, "output_crush.png")
            self._create_incompatible_png(input_file, rgba=False)

            assert check_png_fast_copy(input_file) is False
            assert convert_png_to_fast_copy(input_file, output_path=output_file, method="pngcrush", backup=False)
            assert check_png_fast_copy(output_file) is True

    def test_pnm_end_to_end(self):
        """PNM conversion should produce fast-copy-compatible output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input_pnm.png")
            output_file = os.path.join(tmpdir, "output_pnm.png")
            self._create_incompatible_png(input_file, rgba=True)

            assert check_png_fast_copy(input_file) is False
            assert convert_png_to_fast_copy(input_file, output_path=output_file, method="pnm", backup=False)
            assert check_png_fast_copy(output_file) is True

    @pytest.mark.parametrize("method", ["imagemagick", "pngcrush", "pnm"])
    def test_converts_png_with_gamma_chunk(self, method):
        """Real tools should handle PNGs containing gAMA."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, f"input_gamma_{method}.png")
            output_file = os.path.join(tmpdir, f"output_gamma_{method}.png")
            self._create_png_with_gamma_chunk(input_file)

            assert "gAMA" in self._pngcheck_output(input_file)
            assert check_png_fast_copy(input_file) is False
            assert convert_png_to_fast_copy(input_file, output_path=output_file, method=method, backup=False)
            assert check_png_fast_copy(output_file) is True

    @pytest.mark.parametrize("method", ["imagemagick", "pngcrush", "pnm"])
    def test_converts_png_with_iccp_chunk(self, method):
        """Real tools should handle PNGs containing iCCP."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, f"input_iccp_{method}.png")
            output_file = os.path.join(tmpdir, f"output_iccp_{method}.png")
            self._create_png_with_iccp_chunk(input_file)

            assert "iCCP" in self._pngcheck_output(input_file)
            assert check_png_fast_copy(input_file) is False
            assert convert_png_to_fast_copy(input_file, output_path=output_file, method=method, backup=False)
            assert check_png_fast_copy(output_file) is True


class TestMainCLI:
    """Test the main CLI function."""

    def test_main_help(self, capsys):
        """Test --help argument."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Convert PNG images" in captured.out

    def test_main_no_args(self, capsys):
        """Test main with no arguments."""
        exit_code = main([])
        assert exit_code == 1

    def test_main_single_file_success(self, capsys):
        """Test main CLI with single file success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy", return_value=True):
                exit_code = main([png_file])
                assert exit_code == 0
                captured = capsys.readouterr()
                assert "Successfully converted" in captured.out

    def test_main_single_file_failure(self, capsys):
        """Test main CLI with single file failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy", return_value=False):
                exit_code = main([png_file])
                assert exit_code == 1
                captured = capsys.readouterr()
                assert "Failed to convert" in captured.out

    def test_main_with_output_option(self, capsys):
        """Test main CLI with output option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_file = os.path.join(tmpdir, "input.png")
            output_file = os.path.join(tmpdir, "output.png")
            create_test_png(input_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy", return_value=True):
                exit_code = main([input_file, "-o", output_file])
                assert exit_code == 0
                captured = capsys.readouterr()
                assert output_file in captured.out

    def test_main_directory_option(self, capsys):
        """Test main CLI with directory option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_directory") as mock_convert:
                mock_convert.return_value = (1, 0)
                exit_code = main(["--directory", tmpdir])
                assert exit_code == 0
                mock_convert.assert_called_once()

    def test_main_method_option(self, capsys):
        """Test main CLI with method option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy") as mock_convert:
                mock_convert.return_value = True
                exit_code = main([png_file, "--method", "imagemagick"])
                assert exit_code == 0
                # Check that method was passed
                assert mock_convert.call_args[1]["method"] == "imagemagick"

    def test_main_no_backup_option(self, capsys):
        """Test main CLI with --no-backup option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy") as mock_convert:
                mock_convert.return_value = True
                exit_code = main([png_file, "--no-backup"])
                assert exit_code == 0
                # Check that backup=False was passed
                assert mock_convert.call_args[1]["backup"] is False

    def test_main_verbose_option(self):
        """Test main CLI with verbose option."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_file = os.path.join(tmpdir, "test.png")
            create_test_png(png_file, 100, 100)

            with patch("tex2pdf_tools.preflight.png_to_fast_copy.convert_png_to_fast_copy", return_value=True), \
                 patch("logging.basicConfig") as mock_logging:
                exit_code = main([png_file, "--verbose"])
                assert exit_code == 0
                # Verify logging was configured with DEBUG level
                mock_logging.assert_called()
