import asyncio
import contextlib
import hmac
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlencode

from fastapi import FastAPI, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import ValidationError
from starlette.responses import FileResponse, RedirectResponse

from alert_receiver import ui
from alert_receiver.config import Settings
from alert_receiver.contracts import Webhook
from alert_receiver.diagnostics import tool_url
from alert_receiver.probe import ProbeState, ReceiverMetrics, probe_loop
from alert_receiver.storage import AlertStore
from api_sentinel.rate_limit import RateLimit

logger = logging.getLogger("sentinel.receiver")
RUNBOOKS = frozenset(ui.RUNBOOKS)
IncidentId = Annotated[int, PathParameter(ge=1, le=2**63 - 1)]
IncidentFilter = Literal["all", "firing", "resolved"]
OriginIncidentId = Annotated[int | None, Query(ge=1, le=2**63 - 1)]
PageCursor = Annotated[str | None, Query(max_length=1024)]


def problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": detail,
            "status": status,
            "code": code,
            "request_id": str(uuid.uuid4()),
        },
        media_type="application/problem+json",
    )


def read_webhook_token(path: Path) -> str:
    token = path.read_text(encoding="utf-8").strip()
    if not 32 <= len(token) <= 512 or any(not 33 <= ord(character) <= 126 for character in token):
        raise ValueError("O segredo do webhook deve ter entre 32 e 512 caracteres ASCII.")
    return token


async def retention_loop(store: AlertStore) -> None:
    while True:
        try:
            await asyncio.to_thread(store.prune)
        except (sqlite3.Error, OSError):
            logger.error(json.dumps({"event": "alert_retention_failed", "category": "storage"}))
        await asyncio.sleep(3_600)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()
    store = AlertStore(settings.database_path, settings.retention_days)
    metrics = ReceiverMetrics()
    probe = ProbeState(
        enabled=settings.probe_enabled, stale_after_seconds=settings.probe_stale_after_seconds
    )
    metrics.probe_stale_after.set(probe.stale_after_seconds)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(store.initialize)
        application.state.webhook_token = await asyncio.to_thread(
            read_webhook_token, settings.webhook_token_file
        )
        tasks = [asyncio.create_task(retention_loop(store))]
        if settings.probe_enabled:
            tasks.append(asyncio.create_task(probe_loop(settings, probe, metrics)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    application = FastAPI(
        title="API Sentinel · alertas",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.state.store = store
    application.state.metrics = metrics
    application.state.probe = probe
    application.state.active_requests = 0
    webhook_rate = RateLimit(rate=10, burst=20)

    def navigation_context(request: Request) -> tuple[str, int | None]:
        value = request.query_params.get(
            "sentinel_status", request.query_params.get("status", "all")
        )
        status = value if value in {"all", "firing", "resolved"} else "all"
        path_identity = re.fullmatch(r"/incidents/([0-9]{1,19})", request.url.path)
        raw = str(
            request.path_params.get(
                "incident_id",
                path_identity.group(1)
                if path_identity
                else request.query_params.get(
                    "sentinel_incident", request.query_params.get("incident_id", "")
                ),
            )
        )
        identity = int(raw) if re.fullmatch(r"[0-9]{1,19}", raw) else 0
        return status, identity if 1 <= identity <= 2**63 - 1 else None

    def is_navigation(request: Request) -> bool:
        return (
            request.url.path in {"/", "/incident-lookup", "/runbooks"}
            or request.url.path.startswith(("/incidents/", "/runbooks/"))
            or (
                request.url.path.startswith("/tools/")
                and "text/html" in request.headers.get("accept", "")
            )
        )

    def navigation_problem(
        request: Request,
        status: int,
        title: str,
        detail: str,
        *,
        retry: bool = False,
    ) -> HTMLResponse:
        incident_filter, incident_id = navigation_context(request)
        retry_url = None
        if retry:
            if request.url.path.startswith("/incidents/") and incident_id is not None:
                retry_url = f"/incidents/{incident_id}?status={incident_filter}"
            elif request.url.path.removeprefix("/runbooks/") in RUNBOOKS:
                slug = request.url.path.removeprefix("/runbooks/")
                retry_url = f"/runbooks/{slug}?status={incident_filter}"
                if incident_id is not None:
                    retry_url += f"&incident_id={incident_id}"
            elif request.url.path.startswith("/tools/"):
                known = {"from", "to", "service", "start", "end", "lookback", "limit"}
                query = urlencode(
                    [(key, value) for key, value in parse_qsl(request.url.query) if key in known]
                )
                retry_url = request.url.path + ("?" + query if query else "")
                if incident_id is not None:
                    retry_url = ui.tool_context(retry_url, incident_filter, incident_id)
            else:
                retry_url = ui.central_url(incident_filter)
        return HTMLResponse(
            ui.problem_page(
                status,
                title,
                detail,
                incident_filter=incident_filter,
                incident_id=incident_id,
                retry_url=retry_url,
            ),
            status_code=status,
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_parameters(request: Request, exc: RequestValidationError) -> Response:
        if is_navigation(request):
            return navigation_problem(
                request,
                422,
                "Consulta inválida",
                "Confira o endereço ou volte à central.",
            )
        return problem(422, "invalid_request", "Parâmetros de consulta inválidos.")

    @application.exception_handler(sqlite3.Error)
    async def storage_unavailable(request: Request, exc: sqlite3.Error) -> Response:
        logger.error(json.dumps({"event": "alert_read_failed", "category": "storage"}))
        if is_navigation(request):
            return navigation_problem(
                request,
                503,
                "Histórico indisponível",
                "Falha ao ler incidentes. Confira o armazenamento do receiver e tente novamente.",
                retry=True,
            )
        return problem(503, "receiver_storage", "Histórico indisponível.")

    @application.middleware("http")
    async def bounded_receiver(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response: Response
        if application.state.active_requests >= 24:
            if request.url.path == "/webhook":
                metrics.webhooks.labels(result="busy").inc()
            response = (
                navigation_problem(
                    request,
                    503,
                    "Receiver ocupado",
                    "Não foi possível concluir esta leitura. Tente novamente.",
                    retry=True,
                )
                if is_navigation(request)
                else problem(503, "receiver_busy", "Receiver ocupado. Tente novamente.")
            )
        else:
            application.state.active_requests += 1
            try:
                response = await call_next(request)
            finally:
                application.state.active_requests -= 1
        if response.status_code == 503:
            response.headers.setdefault("Retry-After", "1")
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; "
            "font-src 'self'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @application.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": "alert-receiver"}

    @application.get("/metrics")
    async def prometheus_metrics() -> Response:
        return Response(
            generate_latest(metrics.registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    @application.post("/webhook")
    async def webhook(request: Request) -> Response:
        peer = request.client.host if request.client else "unknown"
        retry = webhook_rate.consume(peer)
        if retry:
            response = problem(429, "webhook_rate_exceeded", "Limite de entregas excedido.")
            response.headers["Retry-After"] = str(retry)
            return response
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied_token = authorization.partition(" ")
        if (
            len(request.headers.getlist("authorization")) != 1
            or scheme.lower() != "bearer"
            or not hmac.compare_digest(
                supplied_token.encode("utf-8"), application.state.webhook_token.encode("utf-8")
            )
        ):
            metrics.webhooks.labels(result="unauthorized").inc()
            return problem(401, "webhook_unauthorized", "Credencial do webhook inválida.")
        if (
            request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            != "application/json"
        ):
            metrics.webhooks.labels(result="invalid").inc()
            return problem(
                415, "webhook_content_type", "O webhook aceita somente application/json."
            )
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
                if length < 0:
                    raise ValueError
            except ValueError:
                metrics.webhooks.labels(result="invalid").inc()
                return problem(400, "webhook_content_length", "Tamanho declarado inválido.")
            if length > settings.webhook_max_bytes:
                metrics.webhooks.labels(result="too_large").inc()
                return problem(413, "webhook_too_large", "O webhook excedeu o limite de bytes.")
        body = bytearray()
        try:
            async with asyncio.timeout(3):
                async for chunk in request.stream():
                    if len(body) + len(chunk) > settings.webhook_max_bytes:
                        metrics.webhooks.labels(result="too_large").inc()
                        return problem(
                            413, "webhook_too_large", "O webhook excedeu o limite de bytes."
                        )
                    body.extend(chunk)
        except TimeoutError:
            metrics.webhooks.labels(result="invalid").inc()
            return problem(408, "webhook_body_deadline", "Tempo de leitura do webhook excedido.")
        try:
            payload = Webhook.model_validate_json(bytes(body))
        except ValidationError:
            metrics.webhooks.labels(result="invalid").inc()
            return problem(
                422, "webhook_schema", "O corpo do webhook não segue o contrato Alertmanager v4."
            )
        try:
            count = await asyncio.to_thread(store.persist, payload)
        except (sqlite3.Error, OSError):
            metrics.webhooks.labels(result="storage_error").inc()
            logger.error(json.dumps({"event": "alert_persistence_failed", "category": "storage"}))
            return problem(503, "webhook_storage", "Falha ao gravar o webhook. Repita a entrega.")
        metrics.webhooks.labels(result="persisted").inc()
        metrics.truncated_alerts.inc(payload.truncatedAlerts)
        return JSONResponse({"status": "persisted", "alerts": count})

    @application.get("/api/incidents")
    async def incidents(
        status: Literal["firing", "resolved"] | None = None, cursor: PageCursor = None
    ) -> Response:
        try:
            page = await asyncio.to_thread(store.page, status, cursor=cursor)
        except ValueError:
            return problem(422, "invalid_cursor", "Página inválida. Reabra a primeira página.")
        return JSONResponse(
            {
                "incidents": [record.model_dump(mode="json") for record in page.records],
                "counts": page.counts,
                "next_cursor": page.next_cursor,
                "scope": {
                    "generated_at": page.generated_at.isoformat(),
                    "cutoff_at": page.cutoff_at.isoformat(),
                    "retention_days": page.retention_days,
                    "limit": page.limit,
                    "shown": len(page.records),
                    "total": page.total,
                    "filtered_total": page.counts[status] if status else page.total,
                    "offset": page.offset,
                },
            }
        )

    @application.get("/api/incidents/{incident_id}")
    async def incident_json(incident_id: IncidentId) -> Response:
        record, events, _ = await asyncio.to_thread(store.incident_snapshot, incident_id)
        if record is None:
            return problem(404, "incident_not_found", "Ocorrência não encontrada.")
        return JSONResponse(
            {
                "incident": record.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in events],
            }
        )

    @application.get("/", response_class=HTMLResponse)
    async def index(
        request: Request, status: IncidentFilter = "all", cursor: PageCursor = None
    ) -> Response:
        try:
            page = await asyncio.to_thread(
                store.page, None if status == "all" else status, cursor=cursor
            )
        except ValueError:
            return navigation_problem(
                request, 422, "Página inválida", "Volte à central para iniciar uma nova leitura."
            )
        return HTMLResponse(ui.home(page, probe, status))

    @application.get("/incident-lookup")
    async def lookup(
        request: Request,
        incident_id: str = "",
        status: IncidentFilter = "all",
        cursor: PageCursor = None,
    ) -> Response:
        try:
            page = await asyncio.to_thread(
                store.page, None if status == "all" else status, cursor=cursor
            )
        except ValueError:
            return navigation_problem(request, 422, "Página inválida", "Volte à central.")
        identity = int(incident_id) if re.fullmatch(r"[0-9]{1,19}", incident_id) else 0
        if 1 <= identity <= 2**63 - 1:
            origin = "&" + urlencode({"cursor": cursor}) if cursor else ""
            return RedirectResponse(
                f"/incidents/{identity}?status={status}{origin}", status_code=303
            )
        return HTMLResponse(
            ui.home(
                page,
                probe,
                status,
                lookup_error="Informe um ID entre 1 e 9223372036854775807.",
                lookup_value=incident_id[:19],
            ),
            status_code=422,
        )

    @application.get("/incidents/{incident_id}", response_class=HTMLResponse)
    async def incident_html(
        request: Request,
        incident_id: IncidentId,
        status: IncidentFilter = "all",
        cursor: PageCursor = None,
    ) -> Response:
        if cursor is not None:
            try:
                store.decode_cursor(cursor, None if status == "all" else status)
            except ValueError:
                return navigation_problem(request, 422, "Página inválida", "Volte à central.")
        record, events, generated_at = await asyncio.to_thread(store.incident_snapshot, incident_id)
        if record is None:
            return navigation_problem(
                request,
                404,
                "Ocorrência não encontrada",
                "Incidente não encontrado. O histórico de resolvidos pode ter expirado.",
            )
        return HTMLResponse(
            ui.incident_detail(record, events, status, generated_at=generated_at, cursor=cursor)
        )

    @application.get("/styles.css")
    async def styles() -> FileResponse:
        return FileResponse(Path(__file__).with_name("styles.css"), media_type="text/css")

    @application.get("/assets/{name}")
    async def interface_asset(name: str) -> Response:
        assets = {
            "mark.svg": "image/svg+xml",
            "mark-light.svg": "image/svg+xml",
            "mark-mono.svg": "image/svg+xml",
            "wordmark.svg": "image/svg+xml",
            "wordmark-light.svg": "image/svg+xml",
            "wordmark-mono.svg": "image/svg+xml",
            "favicon.svg": "image/svg+xml",
            "plex-sans-regular.woff2": "font/woff2",
            "plex-sans-semibold.woff2": "font/woff2",
        }
        if name not in assets:
            return problem(404, "asset_not_found", "Recurso de interface não encontrado.")
        return FileResponse(Path(__file__).with_name("assets") / name, media_type=assets[name])

    @application.get("/tools/{service}/{path:path}")
    async def investigate(request: Request, service: str, path: str) -> Response:
        forwarded_query = urlencode(
            [
                (key, value)
                for key, value in parse_qsl(request.url.query)
                if key not in {"sentinel_status", "sentinel_incident"}
            ]
        )
        try:
            destination = await asyncio.to_thread(
                tool_url, service, path, forwarded_query, settings.public_urls_file
            )
        except KeyError:
            if "text/html" in request.headers.get("accept", ""):
                return navigation_problem(
                    request,
                    404,
                    "Ferramenta desconhecida",
                    "Use os links de investigação da central.",
                )
            return problem(404, "tool_not_found", "Ferramenta desconhecida.")
        except (OSError, ValueError, TypeError):
            if "text/html" in request.headers.get("accept", ""):
                return navigation_problem(
                    request,
                    503,
                    "Investigação indisponível",
                    "O endereço da ferramenta não está configurado para esta execução. "
                    "Confira os destinos locais antes de tentar novamente; "
                    "o histórico de incidentes continua acessível.",
                    retry=True,
                )
            return problem(
                503,
                "tool_unavailable",
                "Destino de investigação não configurado para esta execução.",
            )
        return RedirectResponse(destination)

    @application.get("/snapshot.js")
    async def snapshot_script() -> FileResponse:
        return FileResponse(Path(__file__).with_name("snapshot.js"), media_type="text/javascript")

    @application.get("/runbooks/{slug}", response_class=HTMLResponse)
    async def runbook(
        request: Request,
        slug: str,
        incident_id: OriginIncidentId = None,
        status: IncidentFilter = "all",
        cursor: PageCursor = None,
    ) -> Response:
        if cursor is not None:
            try:
                store.decode_cursor(cursor, None if status == "all" else status)
            except ValueError:
                return navigation_problem(request, 422, "Página inválida", "Volte à central.")
        if slug not in RUNBOOKS:
            return navigation_problem(
                request,
                404,
                "Runbook não encontrado",
                "Abra o runbook pelo incidente na central.",
            )
        try:
            markdown = await asyncio.to_thread(
                (settings.runbooks_path / f"{slug}.md").read_text, encoding="utf-8"
            )
        except FileNotFoundError:
            return navigation_problem(
                request,
                503,
                "Runbook temporariamente indisponível",
                "Runbook ausente. Confira docs/runbooks na imagem do receiver.",
                retry=True,
            )
        return HTMLResponse(
            ui.runbook_page(slug, markdown, incident_id=incident_id, status=status, cursor=cursor)
        )

    @application.get("/runbooks", response_class=HTMLResponse)
    async def runbooks() -> str:
        return ui.runbook_index()

    return application


app = create_app()
