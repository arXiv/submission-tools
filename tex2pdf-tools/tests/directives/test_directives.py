import unittest
import os
from unittest.mock import MagicMock, patch
from tex2pdf_tools.directives import DirectiveManager

class TestDirectiveManager(unittest.TestCase):

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_list_directives_files(self, mock_listdir):
        mock_listdir.return_value = ['00readme.yaml', '00README.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.list_directives_files(), ['00README.XXX', '00readme.yaml'])

        # Try several bad file names
        mock_listdir.return_value = ['readme.yaml', '00readme.yaml', '00readmeBackup.yaml',
                                     '00README.XXX', '00READMEv2.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.list_directives_files(), ['00README.XXX', '00readme.yaml'],
                         "Expect two 00readme files, one v1 and one v2.")

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_get_active_directives_file(self, mock_listdir):

        # Case 1: Single v2 file
        mock_listdir.return_value = ['00readme.yaml', '00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.get_active_directives_file(), '00readme.yaml')

        # Case 2: No v2 file, single v1 file
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertEqual(manager.get_active_directives_file(), '00README.XXX')

        # Case 3: Multiple v2 files
        mock_listdir.return_value = ['00readme.yaml', '00readme.json', '00README.XXX']
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
        mock_listdir.return_value = ['00readme.yaml', '00README.XXX']

        manager = DirectiveManager("dummy_dir")

        # Case 1: Active file is 00readme.yaml
        self.assertTrue(manager.is_active_directives_file('00readme.yaml'))
        self.assertFalse(manager.is_active_directives_file('00README.XXX'))
        self.assertFalse(manager.is_active_directives_file('otherfile.txt'))

        # Case 2: Active file is 00README.XXX (when no v2 file exists)
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.is_active_directives_file('00README.XXX'))
        self.assertFalse(manager.is_active_directives_file('00readme.yaml'))


    @patch('tex2pdf_tools.directives.os.listdir')
    def test_is_v1_file(self, mock_listdir):
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.is_v1_file('00README.XXX'))
        self.assertFalse(manager.is_v1_file('00READMEjunk.XXX'))
        self.assertFalse(manager.is_v1_file('otherfile.XXX'))

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_is_v2_file(self, mock_listdir):
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.is_v2_file('00readme.yaml'))
        self.assertFalse(manager.is_v2_file('00readmejunk.yaml'))
        self.assertFalse(manager.is_v2_file('otherfile.yaml'))

    @patch('tex2pdf_tools.directives.os.listdir')
    def test_v1_exists(self, mock_listdir):
        # Case 1: v1 file exists
        mock_listdir.return_value = ['00README.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.v1_exists())

        # Case 2: v1 file does not exist
        mock_listdir.return_value = ['00readme.yaml', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.v1_exists())

        # Case 3: Multiple v2 files
        mock_listdir.return_value = ['00readme.yaml', '00readme.json', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        with self.assertRaises(ValueError) as context:
            manager.get_active_directives_file()
            manager.v2_exists()
        self.assertEqual(str(context.exception), 'Only one v2 00readme directives file is allowed.')


    @patch('tex2pdf_tools.directives.os.listdir')
    def test_v2_exists(self, mock_listdir):
        # Case 1: v2 file exists
        mock_listdir.return_value = ['00readme.yaml', 'otherfile.txt']
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
        mock_listdir.return_value = ['00readme.yaml']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.can_make_active('00readme.json'))

        # Case 3: Existing v2 file, trying to activate the same v2 file
        mock_listdir.return_value = ['00readme.yaml']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00readme.yaml'))

        # Case 4: Existing v1 file, no v2 file, trying to activate a new v2 file
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00readme.yaml'))

        # Case 5: Invalid file, not 00readme format
        mock_listdir.return_value = ['00README.XXX', '00readme.yaml']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.can_make_active('otherfile.txt'))

        # Case 6: Valid v1 file exists, no v2 file, trying to activate another valid v1 file
        mock_listdir.return_value = ['00README.XXX', '00readme.xxx']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00README.XXX'))

        # Case 7: New v2 file can replace existing v1 file if no existing v2
        mock_listdir.return_value = ['00README.XXX', 'otherfile.txt']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.can_make_active('00readme.yaml'))

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

        self.assertTrue(manager.can_make_active('00readme.yaml'))
        self.assertTrue(manager.v1_exists())
        self.assertFalse(manager.is_v1_file('00readme.yaml'))
        self.assertFalse(manager.v2_exists())
        self.assertTrue(manager.is_v2_file('00readme.yaml'))
        self.assertFalse(manager.is_active_directives_file('00readme.yaml'))

        mock_listdir.return_value = ['00readme.yaml', '00README.XXX']
        manager = DirectiveManager("dummy_dir")

        self.assertFalse(manager.can_make_active('00README.XXX'), 'No longer option for active')
        self.assertTrue(manager.v1_exists())
        self.assertTrue(manager.is_v1_file('00README.XXX'))
        self.assertTrue(manager.v2_exists(), 'The v2 should exist.')
        self.assertFalse(manager.is_v2_file('00README.XXX'))
        self.assertFalse(manager.is_active_directives_file('00README.XXX'))

        self.assertTrue(manager.can_make_active('00readme.yaml'))
        self.assertTrue(manager.v1_exists())
        self.assertFalse(manager.is_v1_file('00readme.yaml'))
        self.assertTrue(manager.v2_exists())
        self.assertTrue(manager.is_v2_file('00readme.yaml'))
        self.assertTrue(manager.is_active_directives_file('00readme.yaml'))

        mock_listdir.return_value = ['00readme.json', '00readme.yaml',
                                     '00README.XXX']
        manager = DirectiveManager("dummy_dir")
        error_str = 'Only one v2 00readme directives file is allowed.'
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
            manager.can_make_active('00readme.yaml')
        self.assertEqual(str(context.exception), error_str)
        self.assertTrue(manager.v1_exists())
        self.assertFalse(manager.is_v1_file('00readme.yaml'))
        with self.assertRaises(ValueError) as context:
            manager.get_active_directives_file()
            manager.v2_exists()
        self.assertTrue(manager.is_v2_file('00readme.yaml'))
        with self.assertRaises(ValueError) as context:
            manager.get_active_directives_file()
            manager.is_active_directives_file('00readme.yaml')



        mock_listdir.return_value = ['00readme.yaml', '00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertTrue(manager.v2_exists())
        mock_listdir.return_value = ['00README.XXX']
        manager = DirectiveManager("dummy_dir")
        self.assertFalse(manager.v2_exists())

if __name__ == "__main__":
    unittest.main()
