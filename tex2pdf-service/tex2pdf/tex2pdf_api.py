"""Tex2PDF FastAPI."""

import os
import subprocess
import tempfile
import traceback
import typing
from enum import Enum

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

from . import MAX_APPENDING_FILES, MAX_TIME_BUDGET, MAX_TOPLEVEL_TEX_FILES, USE_ADDON_TREE
from .converter_driver import ConversionOutcomeMaker, ConverterDriver, TimeStampProvider
from .fastapi_util import closer
from .pdf_watermark import Watermark, WatermarkError, WatermarkFileTypeError, add_watermark_text_to_pdf
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


class DummyTimeStampProvider(TimeStampProvider):
    """Dummy TimeStampProvider for testing purposes."""

    def __init__(self, identifier: str):
        """Initialize with a dummy identifier."""
        self.identifier = identifier

    def get_timestamp(self) -> int | None:
        """Return a dummy timestamp."""
        return None


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
    identifier: typing.Annotated[
        str | None,
        Query(
            title="ID",
            description="String that can be converted to a TimeStampProvider.",
        ),
    ] = None,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
) -> Response:
    return await _convert_pdf(
        DummyTimeStampProvider,
        incoming,
        use_addon_tree,
        timeout,
        max_tex_files,
        max_appending_files,
        preflight,
        identifier,
        watermark_text,
        watermark_link,
        auto_detect,
        hide_anc_dir,
    )


T = typing.TypeVar("T", bound=TimeStampProvider)


async def _convert_pdf(
    TimeStampProviderClass: type[T],
    incoming: UploadFile,
    use_addon_tree: bool,
    timeout: int | None,
    max_tex_files: int | None,
    max_appending_files: int | None,
    preflight: str | None,
    identifier: str | None,
    watermark_text: str | None = None,
    watermark_link: str | None = None,
    auto_detect: bool = False,
    hide_anc_dir: bool = False,
) -> Response:
    """Get a tarball, and convert to PDF."""
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

    ts_identifier: T | None = None
    if identifier is not None:
        ts_identifier = TimeStampProviderClass(identifier)

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

        # deal with preflight computation
        if preflight_version is not PreflightVersion.NONE:
            logger.debug("[convert_pdf] running preflight version %s", preflight_version)
            if preflight_version == PreflightVersion.V1:
                # should not happen, we bail out already at the API entry point.
                raise ValueError("Preflight v1 is not supported anymore")
            elif preflight_version == PreflightVersion.V2:
                local_tarball = os.path.join(in_dir, filename)
                unpack_tarball(in_dir, local_tarball, log_extra)
                chmod_775(tempdir)
                rep = generate_preflight_response(in_dir, json=True)
                return Response(
                    status_code=STATCODE.HTTP_200_OK,
                    headers={"Content-Type": "application/json"},
                    content=rep,
                )
            else:
                # Should not happen, we check this already on entrance of API call
                raise ValueError(f"Invalid PreflightVersion: {preflight}")

        timestamp = None if ts_identifier is None else ts_identifier.get_timestamp()
        if timestamp is None:
            logger.debug("Timestamp is None, using builtin conversion driver.")
        else:
            logger.debug("Using timestamp %s for conversion driver.", timestamp)
            # TODO use timestamp to determine the conversion driver (local/remote)

        driver = ConverterDriver(
            tempdir,
            filename,
            use_addon_tree=use_addon_tree,
            tag=tag,
            watermark=Watermark(watermark_text, watermark_link),
            max_time_budget=timeout_secs,
            max_tex_files=max_tex_files,
            max_appending_files=max_appending_files,
            identifier=None,
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


@app.get("/texlive/info")
async def texlive_info() -> FileResponse:
    """Get TeX Live info."""
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
    """robots.txt."""
    go_away_robots = "User-agent: *\nDisallow: /\n"
    return Response(go_away_robots, media_type="text/plain")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> Response:
    favicon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
    if os.path.exists(favicon):
        return FileResponse(favicon, media_type="image/x-icon")
    return JSONResponse(status_code=STATCODE.HTTP_404_NOT_FOUND, content={"message": "No favicon found"})
