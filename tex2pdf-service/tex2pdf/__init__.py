"""tex2pdf: FastAPI to compile arXiv submissions to PDF."""

import os
import stat
from typing import Any

from pythonjsonlogger.jsonlogger import JsonFormatter

# local_exec is True for running this with IDE, and using the local docker image as command.
local_exec = os.environ.get("LOCAL_EXEC") == "y"

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

GIT_COMMIT_HASH: str = os.environ.get("GIT_COMMIT_HASH", "(unknown)")
TEXLIVE_BASE_RELEASE: str = os.environ.get("TEXLIVE_BASE_RELEASE", "")
AUTOTEX_BRANCH: str = os.environ.get("AUTOTEX_BRANCH", "")

PROJECT_ID: str = os.environ.get("PROJECT_ID", "")
PROJECT_NR: int = int(os.environ.get("PROJECT_NR", "0"))

# The default TeX Live version to use for compilation
# Default is empty, so use the current built-in version.
TEX2PDF_PROXY_RELEASE = os.environ.get("TEX2PDF_PROXY_RELEASE", "0")
TEX2PDF_SCOPES: str = ""
TEX2PDF_KEYS_TO_URLS: dict[str, str] = {}
# check whether deployment is a proxy deployment
# only if TEX2PDF_PROXY_RELEASE is set to 1 we allow for proxy setup
if TEX2PDF_PROXY_RELEASE == "1":
    # initialize TEX2PDF_KEYS_TO_URLS from env vars
    #   _TEX2PDF_KEYS_TO_URLS_<key> = <url>
    _TEX2PDF_KEYS_TO_URLS: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith("TEX2PDF_KEYS_TO_URLS_"):
            url_key = key[len("TEX2PDF_KEYS_TO_URLS_") :]
            _TEX2PDF_KEYS_TO_URLS[url_key] = value
    if _TEX2PDF_KEYS_TO_URLS:
        TEX2PDF_KEYS_TO_URLS = _TEX2PDF_KEYS_TO_URLS
        TEX2PDF_SCOPES = os.environ.get("TEX2PDF_SCOPES", "")
    elif PROJECT_NR != 0:
        # defaults
        TEX2PDF_KEYS_TO_URLS = {
            "autotex-te2": f"https://tex2pdf-autotex-te2-{PROJECT_NR}.us-central1.run.app/autotex/",
            "autotex-te3": f"https://tex2pdf-autotex-te3-{PROJECT_NR}.us-central1.run.app/autotex/",
            "autotex-tl2009": f"https://tex2pdf-autotex-tl2009-{PROJECT_NR}.us-central1.run.app/autotex/",
            "autotex-tl2011": f"https://tex2pdf-autotex-tl2011-{PROJECT_NR}.us-central1.run.app/autotex/",
            "autotex-tl2016": f"https://tex2pdf-autotex-tl2016-{PROJECT_NR}.us-central1.run.app/autotex/",
            "autotex-tl2020": f"https://tex2pdf-autotex-tl2020-{PROJECT_NR}.us-central1.run.app/autotex/",
            "autotex-tl2023": f"https://tex2pdf-autotex-tl2020-{PROJECT_NR}.us-central1.run.app/autotex/",
            "tl2023": f"https://tex-to-pdf-2023-{PROJECT_NR}.us-central1.run.app/convert/",
            "tl2025": f"https://tex-to-pdf-2025-{PROJECT_NR}.us-central1.run.app/convert/",
        }
        # TODO how to deal with parallel v1 and v1.5 submissions where we have autotex-tl2023 and tl2023?
        # Idea to be implemented:
        # - allow for autotex-XXXX and XXXX in the left part of the scope
        # - check for presence of autotex-XXXX prefix to distinguish between v1 and v1.5 submissions
        # - we also need a "auto" variant that uses the ZZRM set version!
        DEFAULT_SCOPES = (
            "autotex-te2:1162425600:"
            "autotex-te3:1262217600:"
            "autotex-tl2009:1323129600:"
            "autotex-tl2011:1486670400:"
            "autotex-tl2016:1601553600:"
            "autotex-tl2020:1684778400:"
            "autotex-tl2023,tl2023:1767225600:"
            "tl2025"
        )
        TEX2PDF_SCOPES = os.environ.get("TEX2PDF_SCOPES", DEFAULT_SCOPES)
    else:
        # neither env vars nor project number set, just default to no proxy
        TEX2PDF_PROXY_RELEASE = "0"
        TEX2PDF_KEYS_TO_URLS = {}
        TEX2PDF_SCOPES = ""


class CustomJsonFormatter(JsonFormatter):
    """Logging formatter to play nice with JSON logger."""

    def __init__(self, *args: list, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs, rename_fields={"levelname": LOG_LEVEL_NAME, "asctime": "time"})

    def _perform_rename_log_fields(self, log_record: dict) -> None:
        if "color_message" in log_record:
            del log_record["color_message"]
        for old_field_name, new_field_name in self.rename_fields.items():
            log_field = log_record.get(old_field_name)
            if log_field:
                log_record[new_field_name] = log_field
                del log_record[old_field_name]


def file_props(filename: str) -> dict:
    """Fstat the file and return the size and name."""
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
    """Run the file prots to each file in a directory."""
    return [file_props(os.path.join(a_dir, filename)) for filename in os.listdir(a_dir)]


def catalog_files(root_dir: str) -> dict[str, Any]:
    """Catalog the files in the root_dir."""
    catalog = {}
    for a_dir, _dirs, files in os.walk(root_dir):
        for filename in files:
            filepath = os.path.join(a_dir, filename)
            catalog[filepath[len(root_dir) + 1 :]] = file_props(filepath)
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
