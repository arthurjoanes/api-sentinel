import asyncio
import json
import logging
import os
import re
import time
import traceback
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api_sentinel.config import Settings
from api_sentinel.db import Database
from api_sentinel.errors import Problem
from api_sentinel.metrics import HTTP_DURATION, HTTP_REQUESTS, LOOP_LAG

logger = logging.getLogger("sentinel")


def configure_traces(settings: Settings, db: Database) -> TracerProvider:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": "api-sentinel", "service.instance.id": os.getenv("HOSTNAME", "local")}
        ),
        sampler=ParentBased(TraceIdRatioBased(settings.trace_sample_ratio)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.trace_endpoint, timeout=1),
            max_queue_size=256,
            max_export_batch_size=32,
            schedule_delay_millis=1000,
            export_timeout_millis=1500,
        )
    )
    trace.set_tracer_provider(provider)
    SQLAlchemyInstrumentor().instrument(
        engines=[db.engine.sync_engine, db.auth_engine.sync_engine],
        enable_commenter=False,
        enable_attribute_commenter=False,
    )
    RedisInstrumentor().instrument()
    HTTPXClientInstrumentor().instrument()
    return provider


async def observe_loop() -> None:
    while True:
        started = time.monotonic()
        await asyncio.sleep(0.25)
        LOOP_LAG.set(max(0, time.monotonic() - started - 0.25))


def problem_response(problem: Problem, request_id: str) -> JSONResponse:
    headers = {"X-Request-ID": request_id}
    if problem.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if problem.retry_after is not None:
        headers["Retry-After"] = str(problem.retry_after)
    return JSONResponse(
        {
            "type": f"urn:api-sentinel:problem:{problem.code}",
            "title": problem.detail,
            "status": problem.status,
            "code": problem.code,
            "request_id": request_id,
        },
        status_code=problem.status,
        media_type="application/problem+json",
        headers=headers,
    )


class ClientDisconnected(Exception):
    pass


class ResponseBuffer:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.status = 500
        self.headers: list[tuple[bytes, bytes]] = []
        self.body = bytearray()
        self.started = False
        self.complete = False

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.start" and not self.started:
            self.status = message["status"]
            self.headers = list(message.get("headers", []))
            self.started = True
        elif message["type"] == "http.response.body" and self.started and not self.complete:
            body = message.get("body", b"")
            if len(self.body) + len(body) > self.limit:
                raise Problem(500, "response_size_exceeded", "Resposta excede o limite do serviço.")
            self.body.extend(body)
            self.complete = not message.get("more_body", False)
        else:
            raise Problem(500, "invalid_response", "Falha ao concluir a resposta.")

    def error_category(self) -> str:
        if self.status < 400:
            return "none"
        content_type = next((value for name, value in self.headers if name == b"content-type"), b"")
        if content_type.startswith(b"application/problem+json"):
            try:
                payload = json.loads(self.body)
                code = payload.get("code") if isinstance(payload, dict) else None
                if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
                    return code
            except (ValueError, UnicodeError):
                pass
        return "http_error"


def normalized_route(scope: Scope) -> str:
    # Resolver antes da admissão preserva a rota dos 503 emitidos antes do router.
    application = scope.get("app")
    for route in getattr(application, "routes", ()):
        matched, _ = route.matches(scope)
        if matched in (Match.FULL, Match.PARTIAL):
            path = getattr(route, "path", None)
            if isinstance(path, str):
                return path
    return "unmatched"


def safe_exception_context(exc: Exception) -> dict[str, object]:
    # Só localização e tipo: mensagem, código-fonte e locals podem conter credenciais/SQL.
    frames = deque(traceback.walk_tb(exc.__traceback__), maxlen=8)
    return {
        "exception_type": type(exc).__name__,
        "exception_frames": [
            {
                "file": Path(frame.f_code.co_filename).name,
                "function": frame.f_code.co_name,
                "line": line,
            }
            for frame, line in frames
        ],
    }


class RequestMiddleware:
    def __init__(self, app: ASGIApp, deadline_seconds: float = 2.0) -> None:
        self.app = app
        self.deadline_seconds = deadline_seconds
        self.max_header_bytes = 8192
        self.max_body_bytes = 16384
        self.max_response_bytes = 262144

    def validate_input(self, scope: Scope) -> None:
        headers = scope.get("headers", [])
        if (
            len(headers) > 64
            or sum(len(name) + len(value) + 4 for name, value in headers) > self.max_header_bytes
        ):
            raise Problem(431, "headers_too_large", "Cabeçalhos excedem o limite permitido.")
        if len(scope.get("query_string", b"")) > 4096 or len(scope.get("path", "")) > 2048:
            raise Problem(
                414, "request_target_too_large", "Endereço ou parâmetros excedem o limite."
            )
        lengths = [value for name, value in headers if name.lower() == b"content-length"]
        if sum(name.lower() == b"authorization" for name, _ in headers) > 1:
            raise Problem(400, "ambiguous_credential", "Envie apenas um cabeçalho Authorization.")
        if len(lengths) > 1 or (lengths and (not lengths[0].isdigit() or len(lengths[0]) > 20)):
            raise Problem(400, "invalid_content_length", "Tamanho de corpo inválido.")
        if lengths and int(lengths[0]) > self.max_body_bytes:
            raise Problem(413, "request_body_too_large", "Corpo excede o limite de 16 KiB.")
        if scope["path"].startswith("/v1/") and scope["method"] != "GET":
            raise Problem(405, "method_not_allowed", "As consultas de negócio aceitam somente GET.")

    async def read_body(self, receive: Receive) -> bytes:
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                raise ClientDisconnected
            if message["type"] != "http.request":
                raise Problem(400, "invalid_request", "Mensagem HTTP inválida.")
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_body_bytes:
                raise Problem(413, "request_body_too_large", "Corpo excede o limite de 16 KiB.")
            body.extend(chunk)
            if not message.get("more_body", False):
                return bytes(body)

    async def run_application(
        self, scope: Scope, receive: Receive, response: ResponseBuffer
    ) -> None:
        body = await self.read_body(receive)
        disconnected = asyncio.Event()
        delivered = False

        async def downstream_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def watch_disconnect() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    disconnected.set()
                    return
                if message["type"] != "http.request" or message.get("body", b""):
                    raise Problem(400, "invalid_request", "Mensagem HTTP inesperada após o corpo.")

        async def invoke_application() -> None:
            await self.app(scope, downstream_receive, response.send)

        # A entrada global já foi adquirida: há no máximo duas tarefas por request admitido.
        application = asyncio.create_task(invoke_application(), name="sentinel-request")
        watcher = asyncio.create_task(watch_disconnect(), name="sentinel-disconnect")
        try:
            done, _ = await asyncio.wait(
                {application, watcher}, return_when=asyncio.FIRST_COMPLETED
            )
            if watcher in done:
                await watcher
                raise ClientDisconnected
            await application
            if not response.complete:
                raise Problem(500, "invalid_response", "Falha ao concluir a resposta.")
        finally:
            for task in (application, watcher):
                if not task.done():
                    task.cancel()
            # Inclui finally do downstream, rollback do driver e liberação dos limites.
            await asyncio.gather(application, watcher, return_exceptions=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        request_id = uuid4().hex
        state["request_id"] = request_id
        state["traffic"] = "business"
        started = time.monotonic()
        route = normalized_route(scope)
        method = scope["method"]
        label_method = (
            method
            if method in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD")
            else "OTHER"
        )
        status, error = 500, "none"
        diagnostic: dict[str, object] = {}
        response_started = False
        response_complete = False
        transport_failure = False
        tracer = trace.get_tracer("api_sentinel.http")
        with tracer.start_as_current_span(
            f"{label_method} {route}", kind=trace.SpanKind.SERVER, record_exception=False
        ) as span:
            trace_id = f"{span.get_span_context().trace_id:032x}"
            extra_headers = [
                (b"x-request-id", request_id.encode()),
                (b"x-trace-id", trace_id.encode()),
                (b"x-instance-id", os.getenv("HOSTNAME", "local").encode()),
                (b"cache-control", b"no-store"),
            ]

            async def send_observed(message: Message) -> None:
                nonlocal status, response_started, response_complete
                if message["type"] == "http.response.start":
                    status = message["status"]
                    reserved = {name for name, _ in extra_headers}
                    headers = [
                        (name, value)
                        for name, value in message.get("headers", [])
                        if name.lower() not in reserved
                    ]
                    message = {**message, "headers": headers + extra_headers}
                    response_started = True
                await send(message)
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    response_complete = True

            async def serve() -> None:
                nonlocal status, error
                async with asyncio.timeout(self.deadline_seconds):
                    self.validate_input(scope)
                    response = ResponseBuffer(self.max_response_bytes)
                    await self.run_application(scope, receive, response)
                    status = response.status
                    error = response.error_category()
                    await send_observed(
                        {
                            "type": "http.response.start",
                            "status": status,
                            "headers": response.headers,
                        }
                    )
                    await send_observed(
                        {"type": "http.response.body", "body": bytes(response.body)}
                    )

            async def send_problem(problem: Problem) -> None:
                nonlocal status, error, transport_failure
                error = problem.code
                if response_started:
                    transport_failure = True
                    return
                status = problem.status
                response = problem_response(problem, request_id)
                if status == 405:
                    response.headers["Allow"] = "GET"
                try:
                    async with asyncio.timeout(0.2):
                        await response(scope, receive, send_observed)
                except (OSError, TimeoutError):
                    transport_failure = True

            try:
                if scope["path"].startswith("/v1/"):
                    with scope["app"].state.entry.enter():
                        await serve()
                else:
                    await serve()
            except ClientDisconnected:
                status, error = 499, "client_disconnected"
            except asyncio.CancelledError:
                status, error = 499, "request_cancelled"
                raise
            except Problem as exc:
                await send_problem(exc)
            except TimeoutError:
                await send_problem(
                    Problem(
                        503, "request_deadline_exceeded", "Prazo total da consulta excedido.", 1
                    )
                )
            except (SQLAlchemyError, OSError) as exc:
                diagnostic = safe_exception_context(exc)
                await send_problem(
                    Problem(
                        503,
                        "dependency_unavailable",
                        "Dependência temporariamente indisponível.",
                        1,
                    )
                )
            except Exception as exc:
                diagnostic = safe_exception_context(exc)
                # Categorias estáveis: exceções podem conter SQL, tokens ou payloads privados.
                await send_problem(
                    Problem(500, "internal_error", "Falha interna ao processar consulta.")
                )
            finally:
                outcome = (
                    "server_error"
                    if transport_failure or status >= 500
                    else "success"
                    if status < 400
                    else "quota"
                    if status == 429
                    else "client_error"
                )
                elapsed = time.monotonic() - started
                span.set_attribute("http.route", route)
                span.set_attribute("http.response.status_code", status)
                span.set_attribute("request.id", request_id)
                span.set_attribute("error.category", error)
                if outcome == "server_error":
                    span.set_status(trace.Status(trace.StatusCode.ERROR))
                if route.startswith("/v1/") or route == "unmatched":
                    traffic = "probe" if state.get("traffic") == "probe" else "business"
                    labels = (route, label_method, outcome, traffic)
                    HTTP_REQUESTS.labels(*labels).inc()
                    HTTP_DURATION.labels(*labels).observe(elapsed)
                    logger.info(
                        json.dumps(
                            {
                                "timestamp": datetime.now(UTC).isoformat(),
                                "request_id": request_id,
                                "trace_id": trace_id,
                                "route": route,
                                "method": label_method,
                                "status": status,
                                "duration_seconds": round(elapsed, 6),
                                "error_category": error,
                                "traffic": traffic,
                                "response_complete": response_complete,
                                "instance": os.getenv("HOSTNAME", "local"),
                                **diagnostic,
                            }
                        )
                    )
