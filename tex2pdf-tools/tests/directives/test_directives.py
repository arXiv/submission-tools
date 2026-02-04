import unittest
import os
import json
from unittest.mock import MagicMock, patch
from tex2pdf_tools.directives import DirectiveManager

class TestDirectiveManager(unittest.TestCase):

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_list_directives_files(self, mock_listdir):
        mock_listdir.return_value = ['00README.yaml', '00README.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.list_directives_files(), ['00README.XXX', '00README.yaml'])

        # Try several bad file names
        mock_listdir.return_value = ['readme.yaml', '00README.yaml', '00READMEBackup.yaml',
                                     '00README.XXX', '00READMEv2.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.list_directives_files(), ['00README.XXX', '00README.yaml'],
                         "Expect two 00README files, one v1 and one v2.")

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_get_active_directives_file(self, mock_listdir):

        # Case 1: Single v2 file
        mock_listdir.return_value = ['00README.yaml', '00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.get_active_directives_file(), '00README.yaml')

        # Case 2: No v2 file, single v1 file
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.get_active_directives_file(), '00README.XXX')

        # Case 3: Multiple v2 files
        mock_listdir.return_value = ['00README.yaml', '00README.json', '00README.XXX']
        manager = DirectiveManager("dummy_dir")
        with self.assertRaises(ValueError):
            manager.get_active_directives_file()

        # Case 4: No directives files
        mock_listdir.return_value = ['otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.get_active_directives_file(), None)

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_is_active_directives_file(self, mock_listdir):
        """ """
        # Setup directory listing for the tests
        mock_listdir.return_value = ['00README.yaml', '00README.XXX']

        manager = DirectiveManager("dummy_dir")

        # Case 1: Active file is 00README.yaml
        self.assertTrue(manager.is_active_directives_file('00README.yaml'))
        self.assertFalse(manager.is_active_directives_file('00README.XXX'))
        self.assertFalse(manager.is_active_directives_file('otherfile.txt'))

        # Case 2: Active file is 00README.XXX (when no v2 file exists)
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.is_active_directives_file('00README.XXX'))
        self.assertFalse(manager.is_active_directives_file('00README.yaml'))


    @patch('tex2pdf_tools.directives.os.listdir')
    def test_is_v1_file(self, mock_listdir):
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.is_v1_file('00README.XXX'))
        self.assertFalse(manager.is_v1_file('00READMEjunk.XXX'))
        self.assertFalse(manager.is_v1_file('otherfile.XXX'))

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_is_v2_file(self, mock_listdir):
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.is_v2_file('00README.yaml'))
        self.assertFalse(manager.is_v2_file('00READMEjunk.yaml'))
        self.assertFalse(manager.is_v2_file('otherfile.yaml'))

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_v1_exists(self, mock_listdir):
        # Case 1: v1 file exists
        mock_listdir.return_value = ['00README.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.v1_exists())

        # Case 2: v1 file does not exist
        mock_listdir.return_value = ['00README.yaml', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.v1_exists())

        # Case 3: Multiple v2 files
        mock_listdir.return_value = ['00README.yaml', '00README.json', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        with self.assertRaises(ValueError) as context:
            manager.get_active_directives_file()
            manager.v2_exists()
        self.assertEqual(str(context.exception), 'Only one v2 00README directives file is allowed.')


    @patch('tex2pdf_tools.directives.os.listdir')
    def test_v2_exists(self, mock_listdir):
        # Case 1: v2 file exists
        mock_listdir.return_value = ['00README.yaml', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.v2_exists())

        # Case 2: v2 file does not exist
        mock_listdir.return_value = ['00README.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.v2_exists())

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_can_make_active(self, mock_listdir):
        # Case 1: No existing v2 file, and the file is v1
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00README.XXX'))

        # Case 2: Existing v2 file, trying to activate another v2 file
        mock_listdir.return_value = ['00README.yaml']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.can_make_active('00README.json'))

        # Case 3: Existing v2 file, trying to activate the same v2 file
        mock_listdir.return_value = ['00README.yaml']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00README.yaml'))

        # Case 4: Existing v1 file, no v2 file, trying to activate a new v2 file
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00README.yaml'))

        # Case 5: Invalid file, not 00README format
        mock_listdir.return_value = ['00README.XXX', '00README.yaml']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.can_make_active('otherfile.txt'))

        # Case 6: Valid v1 file exists, no v2 file, trying to activate another valid v1 file
        mock_listdir.return_value = ['00README.XXX', '00README.xxx']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00README.XXX'))

        # Case 7: New v2 file can replace existing v1 file if no existing v2
        mock_listdir.return_value = ['00README.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00README.yaml'))

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_add_files_exists(self, mock_listdir):
        """Simulate the process of adding files to a submission."""
        mock_listdir.return_value = []
        manager = DirectiveManager("dummy_dir")

        self.assertTrue(manager.can_make_active('00README.XXX'))
        self.assertFalse(manager.v1_exists())
        self.assertTrue(manager.is_v1_file('00README.XXX'))
        self.assertFalse(manager.v2_exists())
        self.assertFalse(manager.is_v2_file('00README.XXX'))
        self.assertFalse(manager.is_active_directives_file('00README.XXX'))

        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")

        self.assertTrue(manager.can_make_active('00README.XXX'))
        self.assertTrue(manager.v1_exists())
        self.assertTrue(manager.is_v1_file('00README.XXX'))
        self.assertFalse(manager.v2_exists())
        self.assertFalse(manager.is_v2_file('00README.XXX'))
        self.assertTrue(manager.is_active_directives_file('00README.XXX'))

        self.assertTrue(manager.can_make_active('00README.yaml'))
        self.assertTrue(manager.v1_exists())
        self.assertFalse(manager.is_v1_file('00README.yaml'))
        self.assertFalse(manager.v2_exists())
        self.assertTrue(manager.is_v2_file('00README.yaml'))
        self.assertFalse(manager.is_active_directives_file('00README.yaml'))

        mock_listdir.return_value = ['00README.yaml', '00README.XXX']
        manager = DirectiveManager("dummy_dir")

        self.assertFalse(manager.can_make_active('00README.XXX'), 'No longer option for active')
        self.assertTrue(manager.v1_exists())
        self.assertTrue(manager.is_v1_file('00README.XXX'))
        self.assertTrue(manager.v2_exists(), 'The v2 should exist.')
        self.assertFalse(manager.is_v2_file('00README.XXX'))
        self.assertFalse(manager.is_active_directives_file('00README.XXX'))

        self.assertTrue(manager.can_make_active('00README.yaml'))
        self.assertTrue(manager.v1_exists())
        self.assertFalse(manager.is_v1_file('00README.yaml'))
        self.assertTrue(manager.v2_exists())
        self.assertTrue(manager.is_v2_file('00README.yaml'))
        self.assertTrue(manager.is_active_directives_file('00README.yaml'))

        mock_listdir.return_value = ['00README.json', '00README.yaml',
                                     '00README.XXX']
        manager = DirectiveManager("dummy_dir")
        error_str = 'Only one v2 00README directives file is allowed.'
        #self.assertFalse(manager.can_make_active('00README.XXX'), 'No longer option for active')
        with self.assertRaises(ValueError) as context:
            manager.can_make_active('00README.XXX')
        self.assertEqual(str(context.exception), error_str)
        self.assertTrue(manager.v1_exists())
        self.assertTrue(manager.is_v1_file('00README.XXX'))
        with self.assertRaises(ValueError) as context:
            manager.get_active_directives_file()
            manager.v2_exists()
        self.assertEqual(str(context.exception), error_str)
        self.assertFalse(manager.is_v2_file('00README.XXX'))
        with self.assertRaises(ValueError) as context:
            manager.is_active_directives_file('00README.XXX')
        self.assertEqual(str(context.exception), error_str)
        with self.assertRaises(ValueError) as context:
            manager.can_make_active('00README.yaml')
        self.assertEqual(str(context.exception), error_str)
        self.assertTrue(manager.v1_exists())
        self.assertFalse(manager.is_v1_file('00README.yaml'))
        with self.assertRaises(ValueError) as context:
            manager.get_active_directives_file()
            manager.v2_exists()
        self.assertTrue(manager.is_v2_file('00README.yaml'))
        with self.assertRaises(ValueError) as context:
            manager.get_active_directives_file()
            manager.is_active_directives_file('00README.yaml')



        mock_listdir.return_value = ['00README.yaml', '00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.v2_exists())
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.v2_exists())

    def setUp(self):
        self.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixture"))

    def test_used_index_files(self) -> None:
        """Test detection of used index files."""
        dir_path = os.path.join(self.fixture_dir, "index_files")

        preflight_file = os.path.join(dir_path, 'gcp_preflight.json')
        # src_dir is not required for this test, but the module checks that
        # a src_dif exists
        src_dir = dir_path
        #output_json = <some temporary location that exists during tests>

        # Read the preflight JSON file and check specific fields
        with open(preflight_file, 'r') as f:
            preflight_json = json.load(f)
            tex_files = preflight_json.get("tex_files", [])
            # Note: "solvable.idx" exists in preflight but not in src directory
            self.assertTrue(any("solvable.idx" in file.get("used_idx_files", []) for file in tex_files))
            self.assertTrue(any("solvable.ind" in file.get("used_ind_files", []) for file in tex_files))

        # put together arguments and call

        # Create
        manager = DirectiveManager(dir_path, src_dir)
        directives = {}
        serial = manager.process_directives()
        directives["directives"] = serial
        preflight_data = manager.load_preflight_data(preflight_file)
        directives["preflight"] = preflight_data

        # For manual inspection
        with open('/tmp/test_output.json', "w") as outfile:
            json.dump(directives, outfile, indent=2)

        # Inspect the JSON output for specific field values
        self.assertIn("used_files", directives["preflight"])
        self.assertIn("solvable.ind", directives["preflight"]["used_files"])

    def test_image_files(self) -> None:
        """Ensure preflight.image_files are present and consistent in the
           directives output."""
        dir_path = os.path.join(self.fixture_dir, "image_files")

        preflight_file = os.path.join(dir_path, 'gcp_preflight.json')
        # src_dir is not required for this test, but the module checks that
        # a src_dif exists
        src_dir = dir_path
        #output_json = <some temporary location that exists during tests>

        # Read the preflight JSON file and check specific fields
        with open(preflight_file, 'r') as f:
            preflight_json = json.load(f)

        # Preflight should expose image_files as a list of dicts with filename (and possibly is_oversized)
        image_entries = preflight_json.get("image_files", [])
        self.assertIsInstance(image_entries, list, "preflight.image_files should be a list")
        self.assertGreaterEqual(len(image_entries), 1, "Expected at least one image in preflight.image_files")

        # Expected names from preflight.image_files
        expected_names = {e["filename"] for e in image_entries if isinstance(e, dict) and "filename" in e}
        self.assertTrue(all(isinstance(n, str) for n in expected_names), "Filenames must be strings")

        preflight_image_names = {e.get("filename") for e in image_entries if isinstance(e, dict)}
        self.assertSetEqual(
            preflight_image_names,
            {"fig1.png", "fig2.png", "fig3.png", "fig4.png"},
            "Unexpected image filenames in preflight.image_files"
        )

        # Oversized from preflight.image_files
        preflight_oversized = {e["filename"] for e in image_entries if isinstance(e, dict) and e.get("is_oversized")}

        # Oversized flag should be present for fig4.png as per the uploaded preflight
        oversized_map = {e.get("filename"): e.get("is_oversized", False) for e in image_entries if isinstance(e, dict)}
        self.assertTrue(
            oversized_map.get("fig4.png", False),
            "Expected fig4.png to be marked is_oversized=True in preflight.image_files"
        )

        # put together arguments and call

        # Create
        manager = DirectiveManager(dir_path, src_dir)
        directives = {}
        serial = manager.process_directives()
        directives["directives"] = serial
        preflight_data = manager.load_preflight_data(preflight_file)
        directives["preflight"] = preflight_data

        # For manual inspection
        with open('/tmp/test_output.json', "w") as outfile:
            json.dump(directives, outfile, indent=2)

        # Inspect the combined JSON output for specific field values
        # Check for image files in the preflight and directives data.

        # --- Assertions on the combined directives JSON ---

        # 1) preflight.image_files must be present in the emitted JSON and match the fixture
        out_image_entries = directives["preflight"].get("image_files", [])
        self.assertIsInstance(out_image_entries, list, "directives.preflight.image_files should be a list")
        out_names = {e["filename"] for e in out_image_entries if isinstance(e, dict) and "filename" in e}
        self.assertSetEqual(out_names, expected_names,
                            "Image filenames in directives.preflight.image_files must match preflight")

        # 2) Basic fields are present for each image entry (width/height/megapixels/file_bytes)
        for img in out_image_entries:
            self.assertIn("filename", img)
            self.assertIn("width", img)
            self.assertIn("height", img)
            self.assertIn("megapixels", img)
            self.assertIn("file_bytes", img)
            # basic value sanity
            self.assertGreater(img["width"], 0)
            self.assertGreater(img["height"], 0)
            self.assertGreater(img["file_bytes"], 0)
            self.assertGreaterEqual(img["megapixels"], 0)

        # 3) Every image filename should also appear in preflight.used_files (subset check)
        used_files = set(directives["preflight"].get("used_files", []))
        missing_from_used = sorted(n for n in expected_names if n not in used_files)
        self.assertFalse(
            missing_from_used,
            f"These images are in preflight.image_files but not in preflight.used_files: {missing_from_used}",
        )

        # 4) Oversized count consistency: issues say "Found 3 oversized..." -> count True flags must be 3
        # Pull the "oversized_image" issue message if present and extract the expected count.
        issue_msgs = []
        for det in directives["preflight"].get("detected_top_level_files", []):
            for issue in det.get("issues", []):
                if issue.get("key") == "oversized_image" and isinstance(issue.get("info"), str):
                    issue_msgs.append(issue["info"])

        # Now parse out the number of expected oversize images.

        def parse_oversized_count(msg: str) -> int | None:
            # expects pattern like: "Found 3 oversized image(s) (>34MP)"
            import re
            m = re.search(r"Found\s+(\d+)\s+oversized", msg)
            return int(m.group(1)) if m else None

        expected_oversized_count = None
        for m in issue_msgs:
            c = parse_oversized_count(m)
            if c is not None:
                expected_oversized_count = c
                break

        # Check that we have the correct number of oversize images

        if expected_oversized_count is not None:
            self.assertEqual(
                len(preflight_oversized),
                expected_oversized_count,
                f"Expected {expected_oversized_count} oversized images per "
                f"issues, found {len(preflight_oversized)} in image_files",
            )

            # If the directives side also emitted is_oversized flags, verify at least those match for the same files
            out_oversized = {e["filename"] for e in out_image_entries if isinstance(e, dict) and e.get("is_oversized")}
            if out_oversized:  # only assert mapping if the field is surfaced
                self.assertSetEqual(
                    out_oversized, preflight_oversized,
                    "Mismatch between preflight.image_files.is_oversized and directives.preflight.image_files.is_oversized",
                )


if __name__ == "__main__":
    unittest.main()
