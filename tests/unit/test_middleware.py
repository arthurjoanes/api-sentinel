import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api_sentinel.admission import Admission
from api_sentinel.errors import Problem
from api_sentinel.metrics import HTTP_REQUESTS
from api_sentinel.telemetry import RequestMiddleware, problem_response, safe_exception_context

SUMMARY_ROUTE = "/v1/stores/{store_id}/summary"


def unused_endpoint() -> None:
    pass


class HTTPHarness:
    def __init__(self, entry_limit: int = 48) -> None:
        self.entry = Admission(entry_limit, "entry")
        self.events: asyncio.Queue[Message] = asyncio.Queue()
        self.events.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        self.sent: list[Message] = []
        self.scope: Scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/v1/stores/7/summary",
            "raw_path": b"/v1/stores/7/summary",
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": ("test-client", 12345),
            "root_path": "",
            "app": SimpleNamespace(
                state=SimpleNamespace(entry=self.entry),
                routes=[
                    Route(SUMMARY_ROUTE, unused_endpoint, methods=["GET"]),
                ],
            ),
        }

    async def receive(self) -> Message:
        return await self.events.get()

    async def send(self, message: Message) -> None:
        self.sent.append(message)

    async def run(self, app: ASGIApp, deadline: float = 2) -> None:
        await RequestMiddleware(app, deadline)(self.scope, self.receive, self.send)

    def response(self) -> tuple[int, dict]:
        assert len(self.sent) == 2
        return self.sent[0]["status"], json.loads(self.sent[1]["body"])


def assert_no_request_tasks() -> None:
    assert not [task for task in asyncio.all_tasks() if task.get_name().startswith("sentinel-")]


def request_count(outcome: str, traffic: str = "business") -> float:
    for sample in HTTP_REQUESTS.collect()[0].samples:
        if sample.name == "sentinel_http_requests_total" and sample.labels == {
            "route": SUMMARY_ROUTE,
            "method": "GET",
            "outcome": outcome,
            "traffic": traffic,
        }:
            return sample.value
    return 0


async def test_deadline_cancels_downstream_and_never_sends_partial_success() -> None:
    lab = HTTPHarness()
    business = Admission(1, "tenant")
    released = asyncio.Event()

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        with business.enter():
            try:
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await asyncio.Event().wait()
            finally:
                released.set()

    started = asyncio.get_running_loop().time()
    await lab.run(application, deadline=0.03)
    assert asyncio.get_running_loop().time() - started < 0.4
    assert lab.response()[0] == 503
    assert lab.response()[1]["code"] == "request_deadline_exceeded"
    assert released.is_set()
    assert lab.entry.active == business.active == 0
    assert_no_request_tasks()


async def test_disconnect_cancels_work_without_writing_to_disconnected_client() -> None:
    lab = HTTPHarness()
    acquired, released = asyncio.Event(), asyncio.Event()
    business = Admission(1, "tenant")

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        with business.enter():
            try:
                acquired.set()
                await asyncio.Event().wait()
            finally:
                released.set()

    task = asyncio.create_task(lab.run(application))
    await asyncio.wait_for(acquired.wait(), timeout=0.5)
    await lab.events.put({"type": "http.disconnect"})
    await asyncio.wait_for(task, timeout=0.5)
    assert released.is_set()
    assert lab.sent == []
    assert lab.entry.active == business.active == 0
    assert_no_request_tasks()


async def test_shutdown_cancellation_joins_both_child_tasks() -> None:
    lab = HTTPHarness()
    acquired, released = asyncio.Event(), asyncio.Event()

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            acquired.set()
            await asyncio.Event().wait()
        finally:
            released.set()

    task = asyncio.create_task(lab.run(application))
    await asyncio.wait_for(acquired.wait(), timeout=0.5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released.is_set()
    assert lab.entry.active == 0
    assert_no_request_tasks()


async def test_rejected_entry_creates_no_tasks_and_preserves_sli_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lab = HTTPHarness(entry_limit=0)
    before = request_count("server_error")

    def unexpected_task(*args: object, **kwargs: object) -> None:
        pytest.fail("A rejeição criou uma tarefa antes de adquirir admissão.")

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("A rejeição alcançou autenticação/negócio.")

    monkeypatch.setattr(asyncio, "create_task", unexpected_task)
    await lab.run(application)
    assert lab.response()[0] == 503
    assert lab.response()[1]["code"] == "service_saturated"
    assert request_count("server_error") == before + 1
    assert lab.entry.active == 0


@pytest.mark.parametrize("handled", [False, True])
async def test_problem_code_survives_http_handler_and_no_secrets_are_logged(
    caplog: pytest.LogCaptureFixture, handled: bool
) -> None:
    lab = HTTPHarness()
    lab.scope["headers"] = [(b"authorization", b"Bearer sentinel_PRIVATE_TOKEN")]
    lab.scope["query_string"] = b"sensitive=PRIVATE_QUERY"
    caplog.set_level("INFO", logger="sentinel")

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        problem = Problem(403, "store_forbidden", "A credencial não permite esta loja.")
        if not handled:
            raise problem
        await problem_response(problem, scope["state"]["request_id"])(scope, receive, send)

    await lab.run(application)
    record = json.loads(caplog.records[-1].message)
    assert record["error_category"] == "store_forbidden"
    assert record["route"] == SUMMARY_ROUTE
    assert "PRIVATE_TOKEN" not in caplog.text
    assert "PRIVATE_QUERY" not in caplog.text
    assert lab.response()[0] == 403
    assert_no_request_tasks()


async def test_unexpected_exception_does_not_leak_its_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    lab = HTTPHarness()
    caplog.set_level("INFO", logger="sentinel")

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("SELECT password='PRIVATE_DATABASE_PASSWORD'")

    await lab.run(application)
    assert lab.response()[1]["code"] == "internal_error"
    assert "PRIVATE_DATABASE_PASSWORD" not in caplog.text
    assert "PRIVATE_DATABASE_PASSWORD" not in str(lab.sent)
    diagnostic = json.loads(caplog.records[-1].message)
    assert diagnostic["exception_type"] == "RuntimeError"
    assert diagnostic["exception_frames"][-1]["function"] == "application"
    assert diagnostic["exception_frames"][-1]["file"] == "test_middleware.py"
    assert diagnostic["exception_frames"][-1]["line"] > 0
    assert all(
        set(frame) == {"file", "function", "line"} for frame in diagnostic["exception_frames"]
    )
    assert_no_request_tasks()


@pytest.mark.parametrize(
    "filename", ["/private/project/handler.py", r"C:\private\project\handler.py"]
)
def test_exception_diagnostics_strip_paths_from_both_platforms(filename: str) -> None:
    code = compile("raise RuntimeError('PRIVATE_VALUE')", filename, "exec")
    with pytest.raises(RuntimeError) as caught:
        exec(code, {})
    diagnostic = safe_exception_context(caught.value)
    assert diagnostic["exception_frames"][-1]["file"] == "handler.py"
    assert "private" not in json.dumps(diagnostic).lower()


async def test_probe_classification_and_generated_request_headers() -> None:
    lab = HTTPHarness()
    lab.scope["headers"] = [(b"x-request-id", b"untrusted-id")]
    before = request_count("success", "probe")

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        scope["state"]["traffic"] = "probe"
        await JSONResponse({"revenue_cents": 12500})(scope, receive, send)

    await lab.run(application)
    assert lab.response() == (200, {"revenue_cents": 12500})
    headers = dict(lab.sent[0]["headers"])
    assert headers[b"x-request-id"] != b"untrusted-id"
    assert len(headers[b"x-request-id"]) == 32
    assert headers[b"cache-control"] == b"no-store"
    assert request_count("success", "probe") == before + 1
    assert lab.entry.active == 0
    assert_no_request_tasks()


@pytest.mark.parametrize(
    "headers,method,status,code",
    [
        ([], "POST", 405, "method_not_allowed"),
        ([(b"x-large", b"x" * 8192)], "GET", 431, "headers_too_large"),
        ([(b"content-length", b"16385")], "GET", 413, "request_body_too_large"),
        (
            [(b"content-length", b"1"), (b"content-length", b"1")],
            "GET",
            400,
            "invalid_content_length",
        ),
        ([(b"content-length", b"-1")], "GET", 400, "invalid_content_length"),
        ([(b"content-length", b"9" * 5000)], "GET", 400, "invalid_content_length"),
        (
            [(b"authorization", b"Bearer first"), (b"Authorization", b"Bearer second")],
            "GET",
            400,
            "ambiguous_credential",
        ),
    ],
)
async def test_input_limits_run_before_downstream(
    headers: list[tuple[bytes, bytes]], method: str, status: int, code: str
) -> None:
    lab = HTTPHarness()
    lab.scope["headers"], lab.scope["method"] = headers, method

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("Entrada inválida chegou ao downstream.")

    await lab.run(application)
    assert lab.response()[0] == status
    assert lab.response()[1]["code"] == code
    if status == 405:
        assert dict(lab.sent[0]["headers"])[b"allow"] == b"GET"
    assert lab.entry.active == 0
    assert_no_request_tasks()


async def test_actual_body_limit_ignores_misleading_content_length() -> None:
    lab = HTTPHarness()
    lab.scope["headers"] = [(b"content-length", b"1")]
    lab.events.get_nowait()
    lab.events.put_nowait({"type": "http.request", "body": b"a" * 10000, "more_body": True})
    lab.events.put_nowait({"type": "http.request", "body": b"a" * 6385, "more_body": False})

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("Corpo grande chegou ao downstream.")

    await lab.run(application)
    assert lab.response()[0] == 413
    assert lab.entry.active == 0
    assert_no_request_tasks()


async def test_slow_body_is_included_in_request_deadline() -> None:
    lab = HTTPHarness()
    lab.events.get_nowait()
    lab.events.put_nowait({"type": "http.request", "body": b"a", "more_body": True})

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        pytest.fail("Corpo incompleto chegou ao downstream.")

    await lab.run(application, deadline=0.03)
    assert lab.response()[0] == 503
    assert lab.response()[1]["code"] == "request_deadline_exceeded"
    assert lab.entry.active == 0
    assert_no_request_tasks()


async def test_response_memory_is_bounded() -> None:
    lab = HTTPHarness()

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"x" * 262145})

    await lab.run(application)
    assert lab.response()[0] == 500
    assert lab.response()[1]["code"] == "response_size_exceeded"
    assert lab.entry.active == 0
    assert_no_request_tasks()
