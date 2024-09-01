import os
import unittest

from tex_inspection import ZeroZeroReadMe, find_primary_tex
from preflight_parser import generate_preflight_response, PreflightResponse, PreflightStatus, PreflightStatusValues, \
    IncludeSpec, FileType, TEX_EXTENSIONS, IndexProcessSpec, IndexCompiler, BibProcessSpec, BibCompiler, \
    CompilerSpec

class TestBaseModels(unittest.TestCase):
    def test_preflightstatus(self):
        pfs = PreflightStatus(key=PreflightStatusValues.success, info="Something")
        ret = pfs.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = \
"""{
    "key": "success",
    "info": "Something"
}"""
        self.assertEqual(exp, ret)

    def test_includespec_1(self):
        inc = IncludeSpec(cmd="input", source="core", type=FileType.tex, extensions=TEX_EXTENSIONS, take_options=False)
        ret = inc.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = \
"""{
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
        exp = \
"""{
    "cmd": "usepackage",
    "source": "core",
    "type": "tex",
    "extensions": "sty",
    "multi_args": true
}"""
        self.assertEqual(exp, ret)

    def test_indexprocessorspec(self):
        ips = IndexProcessSpec(processor=IndexCompiler.makeindex, pre_generated=True)
        ret = ips.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = \
"""{
    "processor": "makeindex",
    "pre_generated": true
}"""
        self.assertEqual(exp, ret)

    def test_bibprocessorspec(self):
        ips = BibProcessSpec(processor=BibCompiler.biber, pre_generated=False)
        ret = ips.model_dump_json(indent=4, exclude_none=True, exclude_defaults=True)
        exp = \
"""{
    "processor": "biber",
    "pre_generated": false
}"""
        self.assertEqual(exp, ret)

    def test_compilerspec(self):
        self.assertEqual(
            CompilerSpec(compiler="etex+dvipdfmx").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvipdfmx"}"""
        )
        self.assertEqual(
            CompilerSpec(compiler="pdflatex").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"pdf","postp":"none"}"""
        )
        self.assertEqual(
            CompilerSpec(compiler="etex+dvips_ps2pdf").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"tex","output":"dvi","postp":"dvips_ps2pdf"}"""
        )
        self.assertEqual(
            CompilerSpec(compiler="latex+dvips_ps2pdf").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"tex","lang":"latex","output":"dvi","postp":"dvips_ps2pdf"}"""
        )
        self.assertEqual(
            CompilerSpec(compiler="pdf_submission").model_dump_json(exclude_none=True, exclude_defaults=True),
            """{"engine":"unknown","lang":"pdf","output":"unknown","postp":"none"}"""
        )
