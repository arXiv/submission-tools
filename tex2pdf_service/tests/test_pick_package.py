import unittest

from tex2pdf.tex_to_pdf_converters import pick_package_names


class TestPickPackage(unittest.TestCase):
    def test_none(self):
        self.assertEqual([], pick_package_names(r"\usepackage{}"))
        self.assertEqual([], pick_package_names(r"% \usepackage{foo}"))
        self.assertEqual([], pick_package_names(r"  % \usepackage{foo}"))

    def test_usepackage(self):
        self.assertEqual(["foo"], pick_package_names(r"\usepackage{foo}"))
        self.assertEqual(["foo"], pick_package_names(r"\usepackage[]{foo}"))
        self.assertEqual(["foo"], pick_package_names(r"\usepackage[bar,baz]{foo}"))

    def test_other(self):
        self.assertEqual(["foo"], pick_package_names(r"\RequirePackage{foo}"))
        self.assertEqual(["foo"], pick_package_names(r"\RequirePackage[]{foo}"))
        self.assertEqual(["foo"], pick_package_names(r"\RequirePackage[bar,baz]{foo}"))

    def test_list_of_names(self):
        self.assertEqual(["foo", "bar", "baz"], pick_package_names(r"\usepackage{foo, bar, baz}"))
        self.assertEqual(["foo", "bar"], pick_package_names(r"  \usepackage{foo,bar,}"))
        self.assertEqual(["foo", "bar"], pick_package_names(r" \usepackage{foo, bar,  }"))


if __name__ == '__main__':
    unittest.main()
