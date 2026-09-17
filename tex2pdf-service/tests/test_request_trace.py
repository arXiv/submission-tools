"""One request's records carry its trace id - see docs/cloud-run-logs.md in arxiv-converter."""

import asyncio
import json
import logging
import unittest
from unittest import mock

import tex2pdf
from fastapi import FastAPI
from tex2pdf.service_logger import (
    TraceBinder,
    arxiv_id_context,
    bind_arxiv_id,
    trace_context,
    trace_headers,
)


def format_record(extra: dict | None = None) -> dict:
    """Build what the service actually writes to stdout for one log call."""
    formatter = tex2pdf.CustomJsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    record = logging.LogRecord("tex2pdf", logging.INFO, __file__, 1, "hi", None, None)
    if extra:
        record.__dict__.update(extra)
    return json.loads(formatter.format(record))


class RequestTraceTest(unittest.TestCase):
    def setUp(self) -> None:
        trace_context.set("")
        arxiv_id_context.set("")

    def test_unbound_request_stamps_nothing(self) -> None:
        record = format_record()
        self.assertNotIn(tex2pdf.TRACE_FIELD, record)
        self.assertNotIn("arxiv_id", record)

    def test_trace_field_is_the_full_resource_name(self) -> None:
        trace_context.set("4bf92f3577b34da6a3ce929d0e0e4736/1234;o=1")
        with mock.patch.object(tex2pdf, "_TRACE_PREFIX", "projects/arxiv-production/traces/"):
            record = format_record()
        self.assertEqual(
            record[tex2pdf.TRACE_FIELD],
            "projects/arxiv-production/traces/4bf92f3577b34da6a3ce929d0e0e4736",
        )

    def test_trace_field_without_project(self) -> None:
        trace_context.set("abc123/1;o=1")
        with mock.patch.object(tex2pdf, "_TRACE_PREFIX", ""):
            self.assertEqual(format_record()[tex2pdf.TRACE_FIELD], "abc123")

    def test_arxiv_id_stamped_unless_given_explicitly(self) -> None:
        bind_arxiv_id("2304.99997v1")
        self.assertEqual(format_record()["arxiv_id"], "2304.99997v1")
        # the conversion tag passed as extra= stays what the caller logged
        self.assertEqual(format_record(extra={"arxiv_id": "upload"})["arxiv_id"], "upload")

    def test_headers_go_out_verbatim(self) -> None:
        trace_context.set("abc123/1;o=1")
        self.assertEqual(trace_headers(), {"X-Cloud-Trace-Context": "abc123/1;o=1"})
        trace_context.set("")
        self.assertEqual(trace_headers(), {})

    def test_middleware_binds_the_header_and_clears_the_previous_request(self) -> None:
        seen = {}

        async def inner_app(scope: dict, receive: object, send: object) -> None:
            seen["trace"] = trace_context.get()
            seen["arxiv_id"] = arxiv_id_context.get()

        bind_arxiv_id("from-the-previous-request")
        scope = {"type": "http", "headers": [(b"host", b"x"), (b"x-cloud-trace-context", b"tid/9;o=1")]}
        asyncio.run(TraceBinder(inner_app)(scope, None, None))
        self.assertEqual(seen, {"trace": "tid/9;o=1", "arxiv_id": ""})

    def test_middleware_without_the_header(self) -> None:
        seen = {}

        async def inner_app(scope: dict, receive: object, send: object) -> None:
            seen["trace"] = trace_context.get()

        asyncio.run(TraceBinder(inner_app)(scope={"type": "http", "headers": []}, receive=None, send=None))
        self.assertEqual(seen, {"trace": ""})

    def test_middleware_ignores_non_http_scopes(self) -> None:
        reached = []

        async def inner_app(scope: dict, receive: object, send: object) -> None:
            reached.append(scope["type"])

        # a lifespan scope has no headers at all
        asyncio.run(TraceBinder(inner_app)({"type": "lifespan"}, None, None))
        self.assertEqual(reached, ["lifespan"])


def get(app: FastAPI, path: str, headers: tuple = ()) -> dict:
    """Drive one GET through the app's real middleware stack.

    Plain ASGI rather than starlette's TestClient, which would pull in httpx
    just for this.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(key.lower().encode(), value.encode()) for key, value in headers],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    body = b"".join(msg.get("body", b"") for msg in sent if msg["type"] == "http.response.body")
    return json.loads(body)


class RequestTraceThroughTheAppTest(unittest.TestCase):
    """add_middleware() wiring plus the hop from endpoint to nested sync code."""

    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.add_middleware(TraceBinder)
        self.seen: list[dict] = []

        # a sync endpoint, like the service's own handlers: it runs in the anyio
        # worker thread, which copies the context
        @self.app.get("/compile/{arxiv_id}")
        def compile_one(arxiv_id: str) -> dict:
            bind_arxiv_id(arxiv_id)
            with mock.patch.object(tex2pdf, "_TRACE_PREFIX", "projects/p/traces/"):
                self.seen.append(format_record())
            return trace_headers()

    def test_trace_reaches_the_records_and_the_next_hop(self) -> None:
        header = "4bf92f3577b34da6a3ce929d0e0e4736/17;o=1"
        res = get(self.app, "/compile/2304.99997v1", (("X-Cloud-Trace-Context", header),))
        self.assertEqual(res, {"X-Cloud-Trace-Context": header})
        self.assertEqual(self.seen[0][tex2pdf.TRACE_FIELD], "projects/p/traces/4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(self.seen[0]["arxiv_id"], "2304.99997v1")

    def test_a_request_without_the_header_still_works(self) -> None:
        res = get(self.app, "/compile/0601247v1")
        self.assertEqual(res, {})
        self.assertNotIn(tex2pdf.TRACE_FIELD, self.seen[0])
        self.assertEqual(self.seen[0]["arxiv_id"], "0601247v1")


if __name__ == "__main__":
    unittest.main()
