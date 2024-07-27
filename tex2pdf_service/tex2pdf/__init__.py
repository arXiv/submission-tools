"""
tex2pdf: FastAPI to compile arXiv submissions to PDF.
"""
import os
import stat
from typing import Any

from pythonjsonlogger.jsonlogger import JsonFormatter

# local_exec is True for running this with IDE, and using the local docker image as command.
local_exec = os.environ.get('LOCAL_EXEC') == 'y'

ID_TAG = "arxiv_id"

# Graphics file extensions except for .pdf, .ps, and .eps
_gexts_ = [".png", ".jpg", ".jpeg", ".gif"]
graphics_exts = {key: True for key in _gexts_}


MAX_TIME_BUDGET: float = float(os.environ.get("MAX_TIME_BUDGET", "595"))
MAX_LATEX_RUNS: int = int(os.environ.get("MAX_LATEX_RUNS", "5"))

# Log level name may be different depending on the service provider
LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL_NAME", "severity")

USE_ADDON_TREE: bool = os.environ.get("USE_ADDON_TREE") in ["y", "true"]

MAX_TOPLEVEL_TEX_FILES: int = int(os.environ.get("MAX_TOPLEVEL_TEX_FILES", "1"))
MAX_APPENDING_FILES: int = int(os.environ.get("MAX_APPENDING_FILES", "0"))

# Currently used TL release year and docker image tag
# this information is duplicated in cloudbuild.yaml files and needs to be kept
# in sync
TEXLIVE_RELEASE_YEAR: int = int(os.environ.get("TEXLIVE_RELEASE_YEAR", "2024"))
TEXLIVE_RELEASE_TAG: str = os.environ.get("TEXLIVE_RELEASE_TAG", "2024-07-21")

class CustomJsonFormatter(JsonFormatter):
    """Logging formatter to play nice with JSON logger"""
    def __init__(self, *args: list, **kwargs: Any):
        super().__init__(*args, **kwargs,
                         rename_fields={"levelname": LOG_LEVEL_NAME, "asctime": "time"})

    def _perform_rename_log_fields(self, log_record: dict) -> None:
        if "color_message" in log_record:
            del log_record["color_message"]
        for old_field_name, new_field_name in self.rename_fields.items():
            log_field = log_record.get(old_field_name)
            if log_field:
                log_record[new_field_name] = log_field
                del log_record[old_field_name]


def file_props(filename: str) -> dict:
    """fstat the file and return the size and name."""
    if os.path.exists(filename):
        file_stat = os.stat(filename)
        file_mode = file_stat.st_mode
        base_name = os.path.basename(filename)
        if stat.S_ISREG(file_mode):
            return {"size": file_stat.st_size, "name": base_name}
        if stat.S_ISDIR(file_mode):
            return {"name": base_name, "is_dir": True}
        if stat.S_ISLNK(file_mode):
            return {"name": base_name, "is_link": True}
        return {"mode": repr(file_mode), "name": base_name}
    return {"size": None, "name": os.path.basename(filename)}


def file_props_in_dir(a_dir: str) -> list:
    """Runs the file prots to each file in a directory."""
    return [file_props(os.path.join(a_dir, filename)) for filename in os.listdir(a_dir)]


def catalog_files(root_dir: str) -> dict[str, Any]:
    """
    catalog the files in the root_dir
    """
    catalog = {}
    for a_dir, _dirs, files in os.walk(root_dir):
        for filename in files:
            filepath = os.path.join(a_dir, filename)
            catalog[filepath[len(root_dir)+1:]] = file_props(filepath)
            pass
        pass
    return catalog



def test_file_extent(filename: str, exts: list | dict, no_ext: str | None = None) -> None | str:
    """Test if the filename ends with any of the extensions."""
    ext = os.path.splitext(filename)[1]
    if not ext and no_ext is not None:
        ext = no_ext
        filename = filename + no_ext
        pass
    return filename if ext.lower() in exts else None
