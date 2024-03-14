import unittest
from tex2pdf.tex_inspection import maybe_banned_tex_file, is_banned_tex


class BanTest(unittest.TestCase):

    def test_ban_1(self):
        self.assertTrue(maybe_banned_tex_file("sample-foo.tex"))
        self.assertFalse(maybe_banned_tex_file("main.tex"))
        pass

    def test_ban_2(self):
        self.assertTrue(is_banned_tex("sample-foo.tex", "\\title{The Name of the Title is Hope}"))
        self.assertFalse(is_banned_tex("foo.tex", "\\title{The Name of the Title is Hope}"))
        self.assertFalse(is_banned_tex("sample-foo.tex", "\\title{Cold Fusion}"))
        pass

    def test_ban_3(self):
        self.assertTrue(is_banned_tex("docsimart.tex",
        "\\title{Guide to Using SIAM's \\LaTeX\\ Style\\thanks{Submitted to the editors DATE."))
        self.assertFalse(is_banned_tex("docsimart.text",
        "\\title{Guide to Using SIAM's \\LaTeX\\ Style\\thanks{Submitted to the editors DATE."))
        pass

