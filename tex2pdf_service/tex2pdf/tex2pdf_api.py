"""
Tex2PDF FastAPI.
"""

import os
import subprocess
import tempfile
import traceback
import typing

from fastapi import FastAPI, status as STATCODE, UploadFile, Query
from fastapi.responses import StreamingResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from tex2pdf import MAX_TIME_BUDGET
from tex2pdf.converter_driver import ConverterDriver, ConversionOutcomeMaker
from tex2pdf.service_logger import get_logger
from tex2pdf.tarball import save_stream, prep_tempdir, RemovedSubmission, UnsupportedArchive
from tex2pdf.fastapi_util import closer

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

app = FastAPI(description=DESCRIPTION,
              summary="TeX source compilation service to generate PDF",
              title="TeX to PDF Service")

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


@app.post('/convert/',
         responses={
             STATCODE.HTTP_200_OK: {"content": {"application/gzip": {}},
                                    "description": "Conversion result"},
             STATCODE.HTTP_400_BAD_REQUEST: {"model": Message},
             STATCODE.HTTP_422_UNPROCESSABLE_ENTITY: {"model": Message},
             STATCODE.HTTP_500_INTERNAL_SERVER_ERROR: {"model": Message}
         })
async def convert_pdf(incoming: UploadFile,
                      timeout: typing.Annotated[int | None,
                                                Query(title="Time out",
                                                      description="Time out in seconds.")] = None,
                      watermark_text: str | None = None) -> Response:
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
        driver = ConverterDriver(tempdir, filename, tag=tag, water=watermark_text,
                                 max_time_budget=timeout_secs)
        try:
            _pdf_file = driver.generate_pdf()
        except RemovedSubmission:
            logger.info("Archive is marked deleted.")
            return JSONResponse(status_code=STATCODE.HTTP_422_UNPROCESSABLE_ENTITY,
                                content={"message": "The source is marked deleted."})

        except UnsupportedArchive:
            logger.info("Archive is not supported")
            return JSONResponse(status_code=STATCODE.HTTP_400_BAD_REQUEST,
                                content={"message": "The archive is unsupported"})
        except Exception as exc:
            logger.error(f"Exception %s", str(exc), exc_info=True)
            return JSONResponse(status_code=STATCODE.HTTP_500_INTERNAL_SERVER_ERROR,
                                content={"message": traceback.format_exc()})

        more_files: typing.List[str] = []
        # if pdf_file:
        #     more_files.append(pdf_file)
        out_dir_files = os.listdir(out_dir)
        outcome_maker = ConversionOutcomeMaker(tempdir, tag)
        outcome_maker.create_outcome(driver, driver.outcome,
                                     more_files=more_files,
                                     outcome_files=out_dir_files)

        content = open(os.path.join(tempdir, outcome_maker.outcome_file), "rb")
        filename = os.path.basename(outcome_maker.outcome_file)
        headers = {
            "Content-Type": "application/gzip",
            "Content-Disposition": f"attachment; filename={filename}",
        }
        return GzipResponse(content, headers=headers,
                            background=closer(content, filename, log_extra))


@app.get('/texlive/info')
async def texlive_info() -> FileResponse:
    """
    texlive info
    """
    tlmgr_info = "texlive/2023/tlmgr-info.json"
    if not os.path.exists(tlmgr_info):
        with subprocess.Popen(["/usr/bin/tlmgr", "info", "--json"], encoding='utf-8',
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as tlmgr:
            (out, _err) = tlmgr.communicate()
            pass
        packages = out if out else "{}"
        with open(tlmgr_info, "w", encoding='utf-8') as fh:
            fh.write(packages)
            pass
        pass
    return FileResponse(tlmgr_info, media_type="application/json")


@app.get('/robots.txt', summary="robots.txt", include_in_schema=False)
async def robots_txt() -> Response:
    """
    robots.txt
    """
    go_away_robots = "User-agent: *\nDisallow: /\n"
    return Response(go_away_robots, media_type="text/plain")


@app.get('/favicon.ico', include_in_schema=False)
async def favicon_ico() -> Response:
    favicon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
    if os.path.exists(favicon):
        return FileResponse(favicon, media_type="image/x-icon")
    return JSONResponse(status_code=STATCODE.HTTP_404_NOT_FOUND,
                        content={"message": "No favicon found"})
