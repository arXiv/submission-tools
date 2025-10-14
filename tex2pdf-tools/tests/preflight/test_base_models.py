import unittest

from tex2pdf_tools.preflight import (
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
        ret = pfs.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "key": "success",
    "info": "Something"
}"""
        self.assertEqual(exp, ret)

    def test_includespec_1(self):
        inc = IncludeSpec(cmd="input", source="core", type=FileType.tex, extensions=TEX_EXTENSIONS, take_options=False)
        ret = inc.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
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
        ret = inc.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "cmd": "usepackage",
    "source": "core",
    "type": "tex",
    "extensions": "sty",
    "multi_args": true
}"""
        self.assertEqual(exp, ret)

    def test_indexprocessorspec(self):
        ips = IndexProcessSpec(processor=IndexCompiler.makeindex, pre_generated=True, can_be_generated=False)
        ret = ips.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "processor": "makeindex",
    "pre_generated": true,
    "can_be_generated": false
}"""
        self.assertEqual(exp, ret)

    def test_bibprocessorspec(self):
        ips = BibProcessSpec(processor=BibCompiler.biber, pre_generated=False, can_be_generated=False)
        ret = ips.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = """{
    "processor": "biber",
    "pre_generated": false,
    "can_be_generated": false
}"""
        self.assertEqual(exp, ret)

    def test_compilerspec_1(self):
        """Test CompilerSpec initialized from compiler string."""
        self.assertEqual(
            CompilerSpec(compiler="etex+dvipdfmx").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvipdfmx"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="pdflatex").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="etex+dvips_ps2pdf").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="latex+dvips_ps2pdf").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="pdf_submission").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"pdf","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="html_submission").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"html","output":"unknown","postp":"none"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="tex").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(compiler="latex").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )

    def test_compilerspec_2(self):
        """Test CompilerSpec initialized from dict of data."""
        self.assertEqual(
            CompilerSpec(engine="tex", lang="tex", output="dvi", postp="dvipdfmx").model_dump_json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvipdfmx"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="tex", lang="latex", output="pdf", postp="none").model_dump_json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="tex", lang="tex", output="dvi", postp="dvips_ps2pdf").model_dump_json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="tex", lang="latex", output="dvi", postp="dvips_ps2pdf").model_dump_json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}""",
        )
        self.assertEqual(
            CompilerSpec(engine="unknown", lang="pdf", output="unknown", postp="none").model_dump_json(
                exclude_none=True, exclude_defaults=True
            ),
            """{"engine":"unknown","lang":"pdf","output":"unknown","postp":"none"}""",
        )

    def test_main_process_spec_1(self):
        """Test MainProcessSpec initialized from dict of data."""
        self.assertEqual(
            MainProcessSpec(
                compiler=CompilerSpec(engine="tex", lang="latex", output="pdf", postp="none"),
                bibliography=BibProcessSpec(processor=BibCompiler.bibtex, pre_generated=True, can_be_generated=False),
                index=IndexProcessSpec(processor=IndexCompiler.makeindex, pre_generated=True, can_be_generated=False),
                fontmaps=[]
            ).model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"compiler":{"engine":"tex","lang":"latex","output":"pdf","postp":"none"},"bibliography":{"processor":"bibtex","pre_generated":true,"can_be_generated":false},"index":{"processor":"makeindex","pre_generated":true,"can_be_generated":false},"fontmaps":[]}"""
        )
