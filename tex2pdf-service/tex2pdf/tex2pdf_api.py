"""Tex2PDF FastAPI."""

import os
import re
import subprocess
import tempfile
import traceback
import typing
from enum import Enum
from pathlib import Path

from arxiv.identifier import Identifier as arXivID
from arxiv.identifier import IdentifierException
from fastapi import FastAPI, Query, UploadFile
from fastapi import status as STATCODE
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.background import BackgroundTasks
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse
from tex2pdf_tools.preflight import generate_preflight_response
from tex2pdf_tools.zerozeroreadme import ZeroZeroReadMe, ZZRMException

from . import (
    MAX_APPENDING_FILES,
    MAX_TIME_BUDGET,
    MAX_TOPLEVEL_TEX_FILES,
    TEX2PDF_KEYS_TO_URLS,
    TEX2PDF_PROXY_RELEASE,
    TEX2PDF_SCOPES,
    TEXLIVE_BASE_RELEASE,
    USE_ADDON_TREE,
)
from .converter_driver import AutoTeXConverterDriver, ConversionOutcomeMaker, ConverterDriver
from .fastapi_util import closer
from .pdf_watermark import Watermark, WatermarkError, WatermarkFileTypeError, add_watermark_text_to_pdf
from .remote_call import convert_pdf_remote
from .service_logger import get_logger
from .tarball import (
    RemovedSubmission,
    UnsupportedArchive,
    ZZRMUnderspecified,
    ZZRMUnsupportedCompiler,
    chmod_775,
    prep_tempdir,
    save_stream,
    unpack_tarball,
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


# make it more obious if a validation error happened
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "HTTP exception: " + str(exc.detail)}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "Invalid request format: " + str(exc)}
    )


class Message(BaseModel):
    """Message DTO."""

    message: str


class BinaryData(BaseModel):
    """Binary data DTO."""

    pass


class PDFResponse(StreamingResponse):
    """PDF response."""

    media_type = "application/pdf"


class GzipResponse(StreamingResponse):
    """gzip response."""

    media_type = "application/gzip"


class PreflightVersion(Enum):
    """Possible values of preflight version."""

    NONE = 0
    V1 = 1
    V2 = 2


def determine_compilation_system(ts: int | None, texlive_version: int | None, with_zzrm: bool) -> str:
    """Determine the compilation system based on TEX2PDF_SCOPES and the given arXiv ID."""
    logger = get_logger()
    logger.debug("determine_compilation_system: ts=%s texlive_version=%s", ts, texlive_version)
    logger.debug("determine_compilation_system: TEX2PDF_SCOPES = %s", TEX2PDF_SCOPES)
    logger.debug("determine_compilation_system: TEX2PDF_KEYS_TO_URLS = %s", TEX2PDF_KEYS_TO_URLS)
    # texlive_version takes priority:
    if texlive_version is not None:
        if str(texlive_version) == TEXLIVE_BASE_RELEASE:
            # the requested version is the one included in the current docker image
            return "current"
        # if we have a texlive version, we can use it to determine the
        # compilation system.
        # We assume that our keys are called "tl2025" etc
        tlver = f"tl{texlive_version}"
        logger.debug("Using texlive version %s to determine compilation system", texlive_version)
        if tlver in TEX2PDF_KEYS_TO_URLS:
            return TEX2PDF_KEYS_TO_URLS[tlver]
        else:
            raise ValueError(f"Undefined TeX Live version requested in ZZRM: {tlver}")
    # we need to look into identifier
    # and select either local _generate_pdf or remote depending on the
    # time frame
    # Input comes from an environment variable
    # TEX2PDF_DATE_SCOPES="autotex-te2:CUTOF1:autotex-te3:CUTOF1:tl2009:...:CUTOFN:tl2023"
    # with the interpretations:
    # - submission date < CUTOF1 -> use autotex-te2
    # - CUTOF1 <= submission date < CUTOF2 -> use autotex-te3
    # ...
    # - CUTOFEND <= submission date -> use tl2023
    # Format of CUTOVERXXX: epoch seconds!
    # The entries between the CUTOF ts are comma-separated keys into TEX2PDF_KEYS_TO_URLS
    # This is necessary since we have times when both tl2023 and autotex-tl2023 were running
    #
    # all of the following is only necessary if we actually have multiple
    # TeX systems running
    if TEX2PDF_SCOPES != "" and ts is not None:
        scope_list: list[str] = TEX2PDF_SCOPES.split(":")
        if len(scope_list) % 2:
            # uneven length is not good
            raise ValueError(f"Invalid scope definition: {scope_list}")
        # check for correct format and ordering!
        last_date: float = 0
        for tex_key, cut_of_day in [scope_list[i : i + 2] for i in range(len(scope_list))[::2]]:
            for tex_key_entry in tex_key.split(","):
                if tex_key_entry not in TEX2PDF_KEYS_TO_URLS.keys():
                    raise ValueError(f"Invalid tex key: {tex_key_entry}")
            curr_date: float = float(cut_of_day)
            if curr_date < last_date:
                raise ValueError(f"Invalid scope definition, not increasing time stamps: {scope_list}")
            last_date = curr_date
        # if we have no ts, we can only use the current system
        if ts is None:
            return "current"
        tex_system_key: str | None = None
        for tex_key, cut_of_day in [scope_list[i : i + 2] for i in range(len(scope_list))[::2]]:
            logger.debug("Checking submission date against curdate: %s", cut_of_day)
            curr_date = float(cut_of_day)
            if ts < curr_date:
                # we allow for comma-separated keys when autotex and tex2pdf services were used in parallel
                if "," in tex_key:
                    # we need to distinguish between v1 and v1.5 submissions
                    # v1 submissions have keys starting with "autotex-"
                    # v1.5 submissions have keys without that prefix
                    tex_key_a, tex_key_b = tex_key.split(",")
                    if not with_zzrm:
                        if tex_key_a.startswith("autotex-"):
                            tex_system_key = tex_key_a
                        elif tex_key_b.startswith("autotex-"):
                            tex_system_key = tex_key_b
                        else:
                            raise ValueError(f"Invalid tex key for v1 submission: {tex_key}")
                    else:
                        if not tex_key_a.startswith("autotex-"):
                            tex_system_key = tex_key_a
                        elif not tex_key_b.startswith("autotex-"):
                            tex_system_key = tex_key_b
                        else:
                            raise ValueError(f"Invalid tex key for v1.5 submission: {tex_key}")
                else:
                    tex_system_key = tex_key
                break
        if tex_system_key is None:
            tex_system_key = "current"
    else:
        # no compilation services defined, we always use current
        tex_system_key = "current"
    logger.debug("Detected tex system: %s", tex_system_key)
    if tex_system_key == "current":
        compile_service = tex_system_key
    else:
        # we already checked above that all entries in the scope list are
        # available in the GEN_PDF_KEYS_TO_URLS hash.
        compile_service = TEX2PDF_KEYS_TO_URLS[tex_system_key]
    return compile_service


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
    request: Request,
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
    ts: typing.Annotated[
        int | None,
        Query(
            title="Timestamp",
            description="Timestamp to determine compilation system.",
        ),
    ] = None,
    arxivid: typing.Annotated[
        str | None,
        Query(
            title="arXiv or submission ID",
            description="arXiv identifier (or submission id) to determine compilation system.",
        ),
    ] = None,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
) -> Response:
    """Get a tarball, and convert to PDF."""
    filename = incoming.filename if incoming.filename else tempfile.mktemp(prefix="download")
    log_extra = {"source_filename": filename}
    logger = get_logger()
    logger.debug("Request: %s", request.url, extra=log_extra)
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
        await save_stream(tempdir, incoming, filename, log_extra)
        timeout_secs = float(MAX_TIME_BUDGET)
        if timeout is not None:
            try:
                timeout_secs = float(timeout)
            except ValueError:
                pass
            pass

        # unpack the tarball
        local_tarball = os.path.join(tempdir, filename)
        unpack_tarball(in_dir, local_tarball, log_extra)
        chmod_775(tempdir)

        # deal with preflight computation
        if preflight_version is not PreflightVersion.NONE:
            logger.debug("[convert_pdf] running preflight version %s", preflight_version)
            if preflight_version == PreflightVersion.V1:
                # should not happen, we bail out already at the API entry point.
                raise ValueError("Preflight v1 is not supported anymore")
            elif preflight_version == PreflightVersion.V2:
                rep = generate_preflight_response(in_dir, json=True)
                return Response(
                    status_code=STATCODE.HTTP_200_OK,
                    headers={"Content-Type": "application/json"},
                    content=rep,
                )
            else:
                # Should not happen, we check this already on entrance of API call
                raise ValueError(f"Invalid PreflightVersion: {preflight}")

        # if we proxying is permitted, check ZZRM for the texlive version
        if TEX2PDF_PROXY_RELEASE == "1":
            # load ZZRM and check whether a texlive version is set
            try:
                zzrm = ZeroZeroReadMe(in_dir)
                # in case there is a zzrm file or we enable auto_detect, we select the new-style system
                compile_service = determine_compilation_system(
                    ts, zzrm.texlive_version, (zzrm.readme_filename is not None) or auto_detect
                )
            except ZZRMException as e:
                logger.error("Failed to load ZeroZeroReadMe from %s", in_dir, exc_info=True, extra=log_extra)
                return JSONResponse(
                    status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"message": f"ZZRM cannot be loaded: {e!s}"},
                )
            except ValueError as e:
                logger.error("Failed to determine compilation system: %s -- %s, %s", str(e), ts, zzrm.texlive_version)
                return JSONResponse(
                    status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"message": f"Invalid configuration: {e!s}"},
                )
        else:
            # we are not proxying, so we always use the current compilation service
            compile_service = "current"
        logger.debug("compile_service: %s", compile_service, extra=log_extra)

        if compile_service == "current":
            logger.info("Using current compilation service.")
            return _convert_pdf_current(
                tempdir=tempdir,
                in_dir=in_dir,
                out_dir=out_dir,
                tag=tag,
                source=filename,
                use_addon_tree=use_addon_tree,
                timeout=timeout_secs,
                max_tex_files=max_tex_files,
                max_appending_files=max_appending_files,
                watermark_text=watermark_text,
                watermark_link=watermark_link,
                auto_detect=auto_detect,
                hide_anc_dir=hide_anc_dir,
                log_extra=log_extra,
            )
        else:
            logger.info("Using convert_pdf_remote")
            status_code, msg = convert_pdf_remote(
                compile_service=compile_service,
                arxivid=arxivid,
                tempdir=tempdir,
                tag=tag,
                source=filename,
                use_addon_tree=use_addon_tree,
                timeout=timeout_secs,
                max_tex_files=max_tex_files,
                max_appending_files=max_appending_files,
                watermark_text=watermark_text,
                watermark_link=watermark_link,
                auto_detect=auto_detect,
                hide_anc_dir=hide_anc_dir,
                log_extra=log_extra,
            )
            if status_code == 200:
                headers = {
                    "Content-Type": "application/gzip",
                    "Content-Disposition": f"attachment; filename={os.path.basename(msg)}",
                }
                content = open(msg, "rb")
                return GzipResponse(content, headers=headers, background=closer(content, msg, log_extra))
            else:
                return JSONResponse(status_code=status_code, content={"message": msg})


def _convert_pdf_current(
    tempdir: str,
    in_dir: str,
    out_dir: str,
    tag: str,
    source: str,
    use_addon_tree: bool,
    timeout: float | None,
    max_tex_files: int,
    max_appending_files: int,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
    log_extra: dict[str, typing.Any] = {},
) -> Response:
    """Convert source to PDF using the built-in TeX system."""
    driver = ConverterDriver(
        work_dir=tempdir,
        source=source,
        use_addon_tree=use_addon_tree,
        tag=tag,
        watermark=Watermark(watermark_text, watermark_link),
        max_time_budget=timeout,
        max_tex_files=max_tex_files,
        max_appending_files=max_appending_files,
        ts=None,
        auto_detect=auto_detect,
        hide_anc_dir=hide_anc_dir,
    )
    logger = get_logger()
    logger.debug("XXXX work_dir: %s; source: %s", in_dir, source, extra=log_extra)
    try:
        _pdf_file = driver.generate_pdf()
    except RemovedSubmission as exc:
        logger.info("Archive is marked deleted: %s", str(exc), exc_info=True, extra=log_extra)
        return JSONResponse(
            status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY, content={"message": "The source is marked deleted."}
        )

    except ZZRMUnsupportedCompiler as exc:
        logger.error("ZZRM selected compiler is not supported: %s", str(exc), exc_info=True, extra=log_extra)
        return JSONResponse(
            status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"message": "ZZRM selected compiler is not supported."},
        )

    except ZZRMUnderspecified as exc:
        logger.error("ZZRM missing or underspecified: %s", str(exc), exc_info=True, extra=log_extra)
        return JSONResponse(
            status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"message": "ZZRM missing or underspecified."},
        )

    except UnsupportedArchive as exc:
        logger.info("Archive is not supported: %s", str(exc), exc_info=True, extra=log_extra)
        return JSONResponse(
            status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "The archive is unsupported"}
        )

    except Exception as exc:
        logger.error("Exception %s", str(exc), exc_info=True, extra=log_extra)
        return JSONResponse(status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": str(exc)})

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


@app.post(
    "/stamp/",
    responses={
        STATCODE.HTTP_200_OK: {"content": {"application/gzip": {}}, "description": "Conversion result"},
        STATCODE.HTTP_400_BAD_REQUEST: {"model": Message},
        STATCODE.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Message},
    },
)
async def stamp_pdf(
    background_tasks: BackgroundTasks,
    incoming: UploadFile,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
) -> Response:
    """Get a PDF and return the PDF with a watermark."""
    filename = incoming.filename if incoming.filename else tempfile.mktemp(prefix="download")
    log_extra = {"in_pdf": filename}
    logger = get_logger()
    logger.info("Stamping incoming pdf: %s", incoming.filename)
    tag = os.path.basename(filename)

    if watermark_text is None or not watermark_text.strip():
        logger.warning("No watermark text provided", extra=log_extra)
        return JSONResponse(
            status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "No watermark text provided"}
        )

    tempdir = tempfile.TemporaryDirectory(prefix=tag)
    in_dir, out_dir = prep_tempdir(tempdir.name)
    await save_stream(in_dir, incoming, filename, log_extra)
    in_file = os.path.join(in_dir, filename)
    out_file = os.path.join(out_dir, filename)

    watermark = Watermark(watermark_text, watermark_link)
    try:
        add_watermark_text_to_pdf(watermark, in_file, out_file)
    except WatermarkFileTypeError as exc:
        logger.warning("Failed watermarking - input file type error %s: %s", filename, exc, extra=log_extra)
        return JSONResponse(
            status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "input file type not supported"}
        )
    except WatermarkError as exc:
        logger.warning("Failed watermarking - other error %s: %s", filename, exc, extra=log_extra)
        return JSONResponse(status_code=STATCODE.HTTP_400_BAD_REQUEST, content={"message": "failed to watermark PDF"})
    except Exception as exc:
        logger.error("Exception while watermarking: %s", str(exc), exc_info=True)
        return JSONResponse(
            status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": "internal server error"}
        )
    if not os.path.exists(out_file):
        logger.warning("Watermarked file %s does not exist after watermarking", out_file, extra=log_extra)
        return JSONResponse(
            status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "Watermarked file does not exist"},
        )
    headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": f"attachment; filename={filename}",
    }
    background_tasks.add_task(tempdir.cleanup)
    return FileResponse(out_file, headers=headers)


@app.post(
    "/autotex/",
    responses={
        STATCODE.HTTP_200_OK: {"content": {"application/gzip": {}}, "description": "Conversion result"},
        STATCODE.HTTP_400_BAD_REQUEST: {"model": Message},
        STATCODE.HTTP_422_UNPROCESSABLE_ENTITY: {"model": Message},
        STATCODE.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Message},
    },
)
async def autotex_pdf(
    incoming: UploadFile,
    arxivid: typing.Annotated[str | None, Query(title="arXiv ID", description="arXiv identifier")] = None,
    timeout: typing.Annotated[int | None, Query(title="Time out", description="Time out in seconds.")] = None,
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
                return JSONResponse(
                    status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                    content={"message": "Cannot determine arXiv identifier."},
                )
    if arxiv_identifier_id is None:
        # this should not happen, but I don't want an assertion here
        return JSONResponse(
            status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "Unexpected internal error, please report - arxivid is None."},
        )
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
            return JSONResponse(
                status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY, content={"message": "The source is marked deleted."}
            )

        except Exception as exc:
            logger.error("Exception %s", str(exc), exc_info=True)
            return JSONResponse(
                status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR, content={"message": traceback.format_exc()}
            )

        out_dir_files = os.listdir(out_dir)
        outcome_maker = ConversionOutcomeMaker(tempdir, tag)
        outcome_maker.create_outcome(driver, driver.outcome, outcome_files=out_dir_files)

        content = open(os.path.join(tempdir, outcome_maker.outcome_file), "rb")
        filename = os.path.basename(outcome_maker.outcome_file)
        headers = {
            "Content-Type": "application/gzip",
            "Content-Disposition": f"attachment; filename={filename}",
        }
        return GzipResponse(content, headers=headers, background=closer(content, filename, log_extra))


@app.get("/texlive/info")
async def texlive_info(request: Request) -> Response:
    """Get TeX Live info."""
    return _texlive_info(request)


def _texlive_info(request: Request) -> Response:
    logger = get_logger()
    if not TEXLIVE_BASE_RELEASE:
        logger.warning("TEXLIVE_BASE_RELEASE is not set, cannot provide tlmgr-info.json")
        return JSONResponse(
            status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "TEXLIVE_BASE_RELEASE is not set."},
        )
    tlmgr_info = Path(f"/usr/local/texlive/{TEXLIVE_BASE_RELEASE}/local-info/tlmgr-info.json")
    if not tlmgr_info.exists():
        logger.warning("tlmgr-info.json not found in %s", tlmgr_info)
        return JSONResponse(
            status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "tlmgr-info.json file missing."},
        )

    if request.method == "HEAD":
        headers = {
            "Content-Length": str(tlmgr_info.stat().st_size),
            "Content-Type": "application/json",
            "Content-Disposition": f"attachment; filename={os.path.basename(tlmgr_info.name)}",
        }
        return Response(status_code=STATCODE.HTTP_200_OK, headers=headers)

    return FileResponse(tlmgr_info, media_type="application/json")


@app.get("/texlive/version")
async def texlive_version() -> JSONResponse:
    """Get TeX Live version."""
    logger = get_logger()
    if not TEXLIVE_BASE_RELEASE:
        logger.warning("TEXLIVE_BASE_RELEASE is not set, cannot provide tlmgr-info.json")
        return JSONResponse(
            status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"message": "TEXLIVE_BASE_RELEASE is not set."},
        )
    # note that this is run in /home/worker and we don't have write permissions
    # to /usr/local/texlive/... - thus, save the file simply in CWD.
    tlmgr_version = "tlmgr-version.txt"
    if not os.path.exists(tlmgr_version):
        with subprocess.Popen(
            ["/usr/bin/tlmgr", "version"], encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as tlmgr:
            (out, _err) = tlmgr.communicate()
        vers_info = out if out else ""
        with open(tlmgr_version, "w", encoding="utf-8") as fh:
            fh.write(vers_info)
    else:
        with open(tlmgr_version, encoding="utf-8") as fh:
            vers_info = fh.read()
    ret: dict[str, typing.Any] = {
        "version": TEXLIVE_BASE_RELEASE,
        "description": vers_info,
    }
    if TEX2PDF_PROXY_RELEASE:
        ret["proxy_version"] = list(TEX2PDF_KEYS_TO_URLS.keys())
    return JSONResponse(status_code=STATCODE.HTTP_200_OK, content=ret)


@app.get("/robots.txt", summary="robots.txt", include_in_schema=False)
async def robots_txt() -> Response:
    """robots.txt."""
    go_away_robots = "User-agent: *\nDisallow: /\n"
    return Response(go_away_robots, media_type="text/plain")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> Response:
    favicon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
    if os.path.exists(favicon):
        return FileResponse(favicon, media_type="image/x-icon")
    return JSONResponse(status_code=STATCODE.HTTP_404_NOT_FOUND, content={"message": "No favicon found"})
