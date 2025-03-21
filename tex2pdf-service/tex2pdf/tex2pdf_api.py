"""
Tex2PDF FastAPI.
"""

import os
import re
import subprocess
import tempfile
import traceback
import typing

from fastapi import FastAPI, Query, UploadFile
from fastapi import status as STATCODE
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.responses import FileResponse, HTMLResponse

from arxiv.identifier import Identifier as arXivID, IdentifierException

from . import MAX_APPENDING_FILES, MAX_TIME_BUDGET, MAX_TOPLEVEL_TEX_FILES, USE_ADDON_TREE
from .converter_driver import ConversionOutcomeMaker, ConverterDriver, PreflightVersion, AutoTeXConverterDriver
from .fastapi_util import closer
from .pdf_watermark import Watermark
from .service_logger import get_logger
from .tarball import (
    RemovedSubmission,
    UnsupportedArchive,
    ZZRMUnderspecified,
    ZZRMUnsupportedCompiler,
    prep_tempdir,
    save_stream,
)

log_level = os.environ.get("LOGLEVEL", "INFO").upper()
get_logger().info("Starting: uid=%d gid=%d", os.getuid(), os.getgid())


DESCRIPTION = """
POST a tarball and get a PDF file.
"""
origins = [
    "http://localhost.arxiv.org",
    "https://localhost.arxiv.org",
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://localhost:8080",
]

app = FastAPI(
    description=DESCRIPTION, summary="TeX source compilation service to generate PDF", title="TeX to PDF Service"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    """Message DTO"""

    message: str


class BinaryData(BaseModel):
    """Binary data DTO"""

    pass


class PDFResponse(StreamingResponse):
    """PDF response"""

    media_type = "application/pdf"


class GzipResponse(StreamingResponse):
    """gzip response"""

    media_type = "application/gzip"


@app.get("/", response_class=HTMLResponse)
def healthcheck() -> str:
    """Health check endpoint."""
    return '<h1><a href="./docs/">All good!</a></h1>'


@app.post(
    "/convert/",
    responses={
        STATCODE.HTTP_200_OK: {"content": {"application/gzip": {}}, "description": "Conversion result"},
        STATCODE.HTTP_400_BAD_REQUEST: {"model": Message},
        STATCODE.HTTP_422_UNPROCESSABLE_ENTITY: {"model": Message},
        STATCODE.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Message},
    },
)
async def convert_pdf(
    incoming: UploadFile,
    use_addon_tree: typing.Annotated[
        bool, Query(title="Use addon tree", description="Determines whether an addon tree is used.")
    ] = USE_ADDON_TREE,
    timeout: typing.Annotated[int | None, Query(title="Time out", description="Time out in seconds.")] = None,
    max_tex_files: typing.Annotated[
        int | None,
        Query(
            title="Max Tex File count",
            description=f"Maximum number of TeX files processed in the input. Default is {MAX_TOPLEVEL_TEX_FILES}",
        ),
    ] = None,
    max_appending_files: typing.Annotated[
        int | None,
        Query(
            title="Max Extra File count",
            description=f"Maximum number of appending files. Default is {MAX_APPENDING_FILES}",
        ),
    ] = None,
    preflight: typing.Annotated[
        str | None, Query(title="Preflight", description="Do preflight check, currently only supports v2")
    ] = None,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
) -> Response:
    """
    get a tarball, and convert to PDF
    """
    filename = incoming.filename if incoming.filename else tempfile.mktemp(prefix="download")
    log_extra = {"source_filename": filename}
    logger = get_logger()
    logger.info("%s", incoming.filename)
    tag = os.path.basename(filename)
    while True:
        [stem, ext] = os.path.splitext(tag)
        if ext in [".gz", ".zip", ".tar"]:
            tag = stem
            continue
        break

    if max_tex_files is None:
        max_tex_files = MAX_TOPLEVEL_TEX_FILES

    if max_appending_files is None:
        max_appending_files = MAX_APPENDING_FILES

    preflight_version: PreflightVersion
    if preflight is None:
        preflight_version = PreflightVersion.NONE
    elif preflight == "v1" or preflight == "V1":
        preflight_version = PreflightVersion.V1
        logger.info("Preflight version 1 not supported anymore.")
        return JSONResponse(
            status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "Preflight version 1 not supported anymore."}
        )
    elif preflight == "v2" or preflight == "V2":
        preflight_version = PreflightVersion.V2
    else:
        logger.info("Invalid preflight version string %s.", preflight)
        return JSONResponse(
            status_code=STATCODE.HTTP_400_BAD_REQUEST,
            content={"message": f"Invalid preflight version string {preflight}."},
        )
    logger.debug("preflight string %s value %s", preflight, preflight_version)

    with tempfile.TemporaryDirectory(prefix=tag) as tempdir:
        in_dir, out_dir = prep_tempdir(tempdir)
        await save_stream(in_dir, incoming, filename, log_extra)
        timeout_secs = float(MAX_TIME_BUDGET)
        if timeout is not None:
            try:
                timeout_secs = float(timeout)
            except ValueError:
                pass
            pass
        driver = ConverterDriver(
            tempdir,
            filename,
            use_addon_tree=use_addon_tree,
            tag=tag,
            watermark=Watermark(watermark_text, watermark_link),
            max_time_budget=timeout_secs,
            max_tex_files=max_tex_files,
            max_appending_files=max_appending_files,
            preflight=preflight_version,
            auto_detect=auto_detect,
            hide_anc_dir=hide_anc_dir,
        )
        try:
            _pdf_file = driver.generate_pdf()
        except RemovedSubmission:
            logger.info("Archive is marked deleted.")
            return JSONResponse(
                status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY, content={"message": "The source is marked deleted."}
            )

        except ZZRMUnsupportedCompiler:
            logger.info("ZZRM selected compiler is not supported.")
            return JSONResponse(
                status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"message": "ZZRM selected compiler is not supported."},
            )

        except ZZRMUnderspecified:
            logger.info("ZZRM missing or underspecified.")
            return JSONResponse(
                status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                content={"message": "ZZRM missing or underspecified."},
            )

        except UnsupportedArchive:
            logger.info("Archive is not supported")
            return JSONResponse(
                status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "The archive is unsupported"}
            )

        except Exception as exc:
            logger.error("Exception %s", str(exc), exc_info=True)
            return JSONResponse(
                status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": traceback.format_exc()}
            )

        if preflight_version == PreflightVersion.V2:
            if "preflight_v2" in driver.outcome:
                return Response(
                    status_code=STATCODE.HTTP_200_OK,
                    headers={"Content-Type": "application/json"},
                    content=driver.outcome["preflight_v2"],
                )
            else:
                return JSONResponse(
                    status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={"message": "Preflight v2 data not found"},
                )

        more_files: list[str] = []
        # if pdf_file:
        #     more_files.append(pdf_file)
        out_dir_files = os.listdir(out_dir)
        outcome_maker = ConversionOutcomeMaker(tempdir, tag)
        outcome_maker.create_outcome(driver, driver.outcome, more_files=more_files, outcome_files=out_dir_files)

        content = open(os.path.join(tempdir, outcome_maker.outcome_file), "rb")
        filename = os.path.basename(outcome_maker.outcome_file)
        headers = {
            "Content-Type": "application/gzip",
            "Content-Disposition": f"attachment; filename={filename}",
        }
        return GzipResponse(content, headers=headers, background=closer(content, filename, log_extra))

@app.post('/autotex/',
          responses={
              STATCODE.HTTP_200_OK: {"content": {"application/gzip": {}},
                                     "description": "Conversion result"},
              STATCODE.HTTP_400_BAD_REQUEST: {"model": Message},
              STATCODE.HTTP_422_UNPROCESSABLE_ENTITY: {"model": Message},
              STATCODE.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Message}
          })
async def autotex_pdf(incoming: UploadFile,
                      arxivid: typing.Annotated[
                          str | None, Query(title="arXiv ID", description="arXiv identifier")
                      ] = None,
                      timeout: typing.Annotated[int | None,
                        Query(title="Time out", description="Time out in seconds.")] = None,
                      ) -> Response:
    """Get a tarball, and convert to PDF using autotex."""
    filename = incoming.filename if incoming.filename else tempfile.mktemp(prefix="download")
    log_extra = {"source_filename": filename}
    logger = get_logger()
    logger.info("%s", incoming.filename)
    tag = os.path.basename(filename)
    while True:
        [stem, ext] = os.path.splitext(tag)
        if ext in [".gz", ".zip", ".tar"]:
            tag = stem
            continue
        break
    # now tag points to the bare basename without extensions of the upload filename
    arxiv_identifier: arXivID | None = None
    arxiv_identifier_id: str | None = None
    if arxivid is not None:
        # check for arxivid as \d+ (in-process submissions)
        if re.match(r"[0-9]+$", arxivid):
            arxiv_identifier_id = arxivid
        else:
            try:
                arxiv_identifier = arXivID(arxivid)
                arxiv_identifier_id = arxiv_identifier.id
            except IdentifierException:
                logger.warning("Unparsable arXiv identifier: %s - trying to detect from filename", tag, exc_info=True)
    # if we still not have an identifier, then either the passed in arxivid
    # could not be parsed, or it wasn't passed in. Try parsing it from the filename.
    if arxiv_identifier_id is None:
        # try to determine arXiv ID from the filename
        if re.match(r"[0-9]+$", tag):
            arxiv_identifier_id = tag
        else:
            try:
                arxiv_identifier = arXivID(tag)
                arxiv_identifier_id = arxiv_identifier.id
            except IdentifierException:
                return JSONResponse(status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                                    content={"message": "Cannot determine arXiv identifier."})
    if arxiv_identifier_id is None:
        # this should not happen, but I don't want an assertion here
        return JSONResponse(status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
                            content={"message": "Unexpected internal error, please report - arxivid is None."})
    # now we have and arxiv_identifier!
    with tempfile.TemporaryDirectory(prefix=tag) as tempdir:
        in_dir, out_dir = prep_tempdir(tempdir)
        await save_stream(in_dir, incoming, filename, log_extra)
        timeout_secs = float(MAX_TIME_BUDGET)
        if timeout is not None:
            try:
                timeout_secs = float(timeout)
            except ValueError:
                pass
            pass
        driver = AutoTeXConverterDriver(tempdir, filename, tag=arxiv_identifier_id, max_time_budget=timeout_secs)
        try:
            _pdf_file = driver.generate_pdf()
        except RemovedSubmission:
            # TODO how can we detect this???
            logger.info("Archive is marked deleted.")
            return JSONResponse(status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                                content={"message": "The source is marked deleted."})

        except Exception as exc:
            logger.error(f"Exception %s", str(exc), exc_info=True)
            return JSONResponse(status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
                                content={"message": traceback.format_exc()})

        out_dir_files = os.listdir(out_dir)
        outcome_maker = ConversionOutcomeMaker(tempdir, tag)
        outcome_maker.create_outcome(driver, driver.outcome, outcome_files=out_dir_files)

        content = open(os.path.join(tempdir, outcome_maker.outcome_file), "rb")
        filename = os.path.basename(outcome_maker.outcome_file)
        headers = {
            "Content-Type": "application/gzip",
            "Content-Disposition": f"attachment; filename={filename}",
        }
        return GzipResponse(content, headers=headers,
                            background=closer(content, filename, log_extra))



@app.get("/texlive/info")
async def texlive_info() -> FileResponse:
    """
    texlive info
    """
    # note that this is run in /home/worker and we don't have write permissions
    # to /usr/local/texlive/... - thus, save the file simply in CWD.
    tlmgr_info = "tlmgr-info.json"
    if not os.path.exists(tlmgr_info):
        with subprocess.Popen(
            ["/usr/bin/tlmgr", "info", "--json"], encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as tlmgr:
            (out, _err) = tlmgr.communicate()
            pass
        packages = out if out else "{}"
        with open(tlmgr_info, "w", encoding="utf-8") as fh:
            fh.write(packages)
            pass
        pass
    return FileResponse(tlmgr_info, media_type="application/json")


@app.get("/robots.txt", summary="robots.txt", include_in_schema=False)
async def robots_txt() -> Response:
    """
    robots.txt
    """
    go_away_robots = "User-agent: *\nDisallow: /\n"
    return Response(go_away_robots, media_type="text/plain")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> Response:
    favicon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
    if os.path.exists(favicon):
        return FileResponse(favicon, media_type="image/x-icon")
    return JSONResponse(status_code=STATCODE.HTTP_404_NOT_FOUND, content={"message": "No favicon found"})
