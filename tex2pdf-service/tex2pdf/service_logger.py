"""
tex2pdf logger.

The primary reason is to have the CustomJsonFormatter to tailor the log output.

This works in conjunction with the logging configuration - logging.conf.

The rest of this module ties every record of one request together.  Cloud Run
mints an ``X-Cloud-Trace-Context`` per request and passes it to the app; keeping
it in a ContextVar and letting CustomJsonFormatter stamp it onto every record
makes the complete log of a single post/return cycle one query, however many
compiles interleave on the instance.  See docs/cloud-run-logs.md in
arxiv-converter.

A plain ContextVar covers a whole cycle: the endpoint, everything it calls and
the background task that closes the response all run inside the request's task,
and the anyio worker thread a sync endpoint runs in gets a copy of the context.
A thread started by hand would not (the ThreadPool in log_inspection is the only
one, and it does not log); that would need contextvars.copy_context().
"""

import logging
import logging.config
import logging.handlers
import typing
from contextvars import ContextVar

logger_name: str = "tex2pdf"

# Full inbound X-Cloud-Trace-Context ("TRACE/SPAN;o=1"), one per request.
trace_context: ContextVar[str] = ContextVar("trace_context", default="")
# The paper this request is about, set where the id is known.
arxiv_id_context: ContextVar[str] = ContextVar("arxiv_id_context", default="")


def get_logger() -> logging.Logger:
    _logger = logging.getLogger(logger_name)
    return _logger


def bind_arxiv_id(arxiv_id: str | None) -> None:
    """Stamp the paper id on the remaining log records of this request."""
    arxiv_id_context.set(arxiv_id or "")


def trace_id() -> str:
    """Return the bare Cloud Trace id of this request, empty when unknown."""
    return trace_context.get().split("/")[0]


def trace_headers() -> dict[str, str]:
    """Headers that put a downstream service's records in the same trace."""
    hdr = trace_context.get()
    return {"X-Cloud-Trace-Context": hdr} if hdr else {}


class TraceBinder:
    """ASGI middleware binding the request context every log record is stamped with.

    Pure ASGI, not a starlette BaseHTTPMiddleware: that one runs the app in a
    child task and wraps the response body, which we do not want around a
    streamed outcome tarball.  Setting a ContextVar here reaches the endpoint
    and everything it calls, since no task is spawned in between.
    """

    # typing.Any rather than starlette's ASGIApp: this module stays import-free
    def __init__(self, app: typing.Any) -> None:
        self.app = app

    async def __call__(self, scope: typing.Any, receive: typing.Any, send: typing.Any) -> None:
        if scope["type"] == "http":
            trace = b""
            for key, value in scope["headers"]:
                if key == b"x-cloud-trace-context":
                    trace = value
                    break
            # plain set, not reset: this is also what clears the previous request
            trace_context.set(trace.decode("latin-1"))
            arxiv_id_context.set("")
        await self.app(scope, receive, send)
