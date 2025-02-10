"""
Directives Manager.

This package enforces policies related to the directives or 00readme file. The main
policy is to allow a single v2 directives file. When a document contains a legacy v1
00README.XXX and no v2 directives file, the 00README.XXX will be converted to a v2
file, with the 00README.XXX being retained for the historical record.

The directive file contains 'instructions', 'directives', and 'hints' that help
to guide how we compile, construct, and detail the PDF for a submission or article.

This package supports a single v2 directives file. There is no need to include
more than one v2 directives file.

The legacy v1 00README.XXX may be used as the 'active' directives file, but it is limited
in the sense it does not support the v2 format. This will be the case when processing existing
articles (unless we generate a v2 directives file). While a submitter may upload this
file, it only supports v1 directives, so the system will need to convert this file
to v2 before recording any changes to directives.
"""

# we need os imported due to some mock in pytest tests/directives/test_directives.py
import os  # noqa

# import all toplevel objects into the main module directives.
from .directives import DirectiveManager, serialize_data, write_readme_file

__all__ = ["DirectiveManager", "serialize_data", "write_readme_file"]
