"""tex2pdf: FastAPI to compile arXiv submissions to PDF."""

import os
import stat
from typing import Any

from pythonjsonlogger.jsonlogger import JsonFormatter

from .service_logger import get_logger


def env_flag(env_var: str, default: bool = False) -> bool:
    environ_string = os.environ.get(env_var, "").strip().lower()
    if not environ_string:
        return default
    return environ_string in ["1", "true", "yes", "on", "y"]


# local_exec is True for running this with IDE, and using the local docker image as command.
local_exec: bool = env_flag("LOCAL_EXEC")

ID_TAG = "arxiv_id"

# Graphics file extensions except for .pdf, .ps, and .eps
_gexts_ = [".png", ".jpg", ".jpeg", ".gif"]
graphics_exts = {key: True for key in _gexts_}


MAX_TIME_BUDGET: float = float(os.environ.get("MAX_TIME_BUDGET", "595"))
MAX_LATEX_RUNS: int = int(os.environ.get("MAX_LATEX_RUNS", "5"))

# Log level name may be different depending on the service provider
LOG_LEVEL_NAME = os.environ.get("LOG_LEVEL_NAME", "severity")

USE_ADDON_TREE: bool = env_flag("USE_ADDON_TREE")

MAX_TOPLEVEL_TEX_FILES: int = int(os.environ.get("MAX_TOPLEVEL_TEX_FILES", "1"))
MAX_APPENDING_FILES: int = int(os.environ.get("MAX_APPENDING_FILES", "0"))

GIT_COMMIT_HASH: str = os.environ.get("GIT_COMMIT_HASH", "(unknown)")
TEXLIVE_BASE_RELEASE: str = os.environ.get("TEXLIVE_BASE_RELEASE", "")
AUTOTEX_BRANCH: str = os.environ.get("AUTOTEX_BRANCH", "")

# if TEXLIVE_BASE_RELEASE is empty, we run an autotex container and then the path is irrelevant
TEXLIVE_ROOT: str = f"/usr/local/texlive/{TEXLIVE_BASE_RELEASE}"
TEXLIVE_BIN_DIR: str = f"{TEXLIVE_ROOT}/bin/x86_64-linux"

ENABLE_SANDBOX: bool = env_flag("ENABLE_SANDBOX")

PROJECT_ID: str = os.environ.get("PROJECT_ID", "")
PROJECT_NR: int = int(os.environ.get("PROJECT_NR", "0"))

TEX2PDF_DEFAULT_KEYS_TO_URLS = {
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
TEX2PDF_DEFAULT_SCOPES = (
    "autotex-te2:1162425600:"
    "autotex-te3:1262217600:"
    "autotex-tl2009:1323129600:"
    "autotex-tl2011:1486670400:"
    "autotex-tl2016:1601553600:"
    "autotex-tl2020:1684778400:"
    "autotex-tl2023,tl2023:1757894400"
)

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
    logger = get_logger()
    logger.debug("Running in proxy mode")
    logger.debug("Setting up TEX2PDF_KEYS_TO_URLS from environment variables")
    _TEX2PDF_KEYS_TO_URLS: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith("TEX2PDF_KEYS_TO_URLS_"):
            url_key = key[len("TEX2PDF_KEYS_TO_URLS_") :]
            _TEX2PDF_KEYS_TO_URLS[url_key] = value
    if _TEX2PDF_KEYS_TO_URLS:
        logger.debug("Found TEX2PDF_KEYS_TO_URLS in environment variables")
        logger.debug("TEX2PDF_KEYS_TO_URLS: %s", _TEX2PDF_KEYS_TO_URLS)
        TEX2PDF_KEYS_TO_URLS = _TEX2PDF_KEYS_TO_URLS
        TEX2PDF_SCOPES = os.environ.get("TEX2PDF_SCOPES", "")
        logger.debug("TEX2PDF_SCOPES: %s", TEX2PDF_SCOPES)
    elif PROJECT_NR != "0" and PROJECT_NR != 0:
        logger.debug("No TEX2PDF_KEYS_TO_URLS found in environment variables")
        logger.debug("Setting up TEX2PDF_KEYS_TO_URLS with project number %d", PROJECT_NR)
        # set up TEX2PDF_KEYS_TO_URLS with known keys and project number
        # defaults
        # AutoTeX has the following definitions for cutover, which we need to duplicate here
        #           CUTOVER2023  => 1684778400, # Date::Parse::str2time('2023-05-22T18:00', 'GMT')
        #           CUTOVER2020  => 1601553600, # Date::Parse::str2time('2020-10-01T12:00', 'GMT')
        #           CUTOVER2016  => 1486670400, # Date::Parse::str2time('2017-02-09T20:00', 'GMT')
        #           CUTOVER2011  => 1323129600, # Date::Parse::str2time('2011-12-06', 'GMT')
        #           CUTOVER2009  => 1262217600, # Date::Parse::str2time('2009-12-31', 'GMT')
        #           CUTOVER2006  => 1162425600, # Date::Parse::str2time('2006-11-02', 'GMT')
        #           CUTOVER2004  => 1072915200, # Date::Parse::str2time('2004-01-01', 'GMT')
        #           CUTOVER2003  => 1041379200, # Date::Parse::str2time('2003-01-01', 'GMT')
        #           CUTOVER2002  => 1030838400, # Date::Parse::str2time('2002-09-01', 'GMT')
        # where CUTOVER2002/2003/2004 are all for teTeX2 with different TEXMFCNF files
        #
        # for tl2025 default for now we used Date::Parse::str2time('2025-09-15T00:00', 'GMT')
        TEX2PDF_KEYS_TO_URLS = TEX2PDF_DEFAULT_KEYS_TO_URLS
        TEX2PDF_SCOPES = os.environ.get("TEX2PDF_SCOPES", TEX2PDF_DEFAULT_SCOPES)
        logger.debug("TEX2PDF_KEYS_TO_URLS: %s", TEX2PDF_KEYS_TO_URLS)
        logger.debug("TEX2PDF_SCOPES: %s", TEX2PDF_SCOPES)
    else:
        logger.debug("No TEX2PDF_KEYS_TO_URLS found in environment variables and no PROJECT_NR - initialize empty")
        # neither env vars nor project number set, just default to no proxy
        TEX2PDF_PROXY_RELEASE = "0"
        TEX2PDF_KEYS_TO_URLS = {}
        TEX2PDF_SCOPES = ""


class CustomJsonFormatter(JsonFormatter):
    """Logging formatter to play nice with JSON logger."""

    def __init__(self, *args: list, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs, rename_fields={"levelname": LOG_LEVEL_NAME, "asctime": "time"})

    def _perform_rename_log_fields(self, log_record: dict) -> None:
        log_record.pop("color_message", None)
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
