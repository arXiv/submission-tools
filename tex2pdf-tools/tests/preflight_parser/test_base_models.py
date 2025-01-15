import unittest

from tex2pdf_tools.preflight_parser import (
    TEX_EXTENSIONS,
    BibCompiler,
    BibProcessSpec,
    CompilerSpec,
    FileType,
    IncludeSpec,
    IndexCompiler,
    IndexProcessSpec,
    MainProcessSpec,
    PreflightStatus,
    PreflightStatusValues,
)


class TestBaseModels(unittest.TestCase):
    def test_preflightstatus(self):
        pfs = PreflightStatus(key=PreflightStatusValues.success, info="Something")
        ret = pfs.json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "key": "success",
    "info": "Something"
}"""
        self.assertEqual(exp, ret)

    def test_includespec_1(self):
        inc = IncludeSpec(cmd="input", source="core", type=FileType.tex, extensions=TEX_EXTENSIONS, take_options=False)
        ret = inc.json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "cmd": "input",
    "source": "core",
    "type": "tex",
    "extensions": "tex",
    "take_options": false
}"""
        self.assertEqual(exp, ret)

    def test_includespec_2(self):
        inc = IncludeSpec(
            cmd="usepackage", source="core", type=FileType.tex, extensions="sty", take_options=True, multi_args=True
        )
        ret = inc.json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "cmd": "usepackage",
    "source": "core",
    "type": "tex",
    "extensions": "sty",
    "multi_args": true
}"""
        self.assertEqual(exp, ret)

    def test_indexprocessorspec(self):
        ips = IndexProcessSpec(processor=IndexCompiler.makeindex, pre_generated=True)
        ret = ips.json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "processor": "makeindex",
    "pre_generated": true
}"""
        self.assertEqual(exp, ret)

    def test_bibprocessorspec(self):
        ips = BibProcessSpec(processor=BibCompiler.biber, pre_generated=False)
        ret = ips.json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "processor": "biber",
    "pre_generated": false
}"""
        self.assertEqual(exp, ret)

    def test_compilerspec_1(self):
        """Test CompilerSpec initialized from compiler string."""
        self.assertEqual(
            CompilerSpec(compiler="etex+dvipdfmx").json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "tex", "output": "dvi", "postp": "dvipdfmx"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="pdflatex").json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="etex+dvips_ps2pdf").json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "tex", "output": "dvi", "postp": "dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="latex+dvips_ps2pdf").json(exclude_none=True, exclude_defaults=True),
            """{"engine": "tex", "lang": "latex", "output": "dvi", "postp": "dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="pdf_submission").json(exclude_none=True, exclude_defaults=True),
            """{"engine": "unknown", "lang": "pdf", "output": "unknown", "postp": "none"}""",
        )

    def test_compilerspec_2(self):
        """Test CompilerSpec initialized from dict of data."""
        self.assertEqual(
            CompilerSpec(engine="tex", lang="tex", output="dvi", postp="dvipdfmx").json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine": "tex", "lang": "tex", "output": "dvi", "postp": "dvipdfmx"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="tex", lang="latex", output="pdf", postp="none").json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="tex", lang="tex", output="dvi", postp="dvips_ps2pdf").json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine": "tex", "lang": "tex", "output": "dvi", "postp": "dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="tex", lang="latex", output="dvi", postp="dvips_ps2pdf").json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine": "tex", "lang": "latex", "output": "dvi", "postp": "dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="unknown", lang="pdf", output="unknown", postp="none").json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine": "unknown", "lang": "pdf", "output": "unknown", "postp": "none"}""",
        )

    def test_main_process_spec_1(self):
        """Test MainProcessSpec initialized from dict of data."""
        self.assertEqual(
            MainProcessSpec(
                compiler=CompilerSpec(engine="tex", lang="latex", output="pdf", postp="none"),
                bibliography=BibProcessSpec(processor=BibCompiler.bibtex, pre_generated=True),
                index=IndexProcessSpec(processor=IndexCompiler.makeindex, pre_generated=True),
                fontmaps=[]
            ).json(exclude_none=True, exclude_defaults=True),
            """{"compiler": {"engine": "tex", "lang": "latex", "output": "pdf", "postp": "none"}, "bibliography": {"processor": "bibtex", "pre_generated": true}, "index": {"processor": "makeindex", "pre_generated": true}, "fontmaps": []}"""
        )
