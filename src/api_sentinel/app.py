import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import date
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from api_sentinel import auth, queries
from api_sentinel.admission import Admission, enforce_quota
from api_sentinel.cache import SummaryCache
from api_sentinel.config import Settings
from api_sentinel.contracts import BUSINESS_ERRORS, SalesPage, StoreList, StoreSummary
from api_sentinel.db import Database
from api_sentinel.erp import ERP, Availability
from api_sentinel.errors import Problem
from api_sentinel.telemetry import (
    RequestMiddleware,
    configure_traces,
    observe_loop,
    problem_response,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    db = Database(settings.database_url)
    app.state.settings = settings
    app.state.db = db
    app.state.cursor_secret = settings.cursor_secret()
    app.state.entry = Admission(settings.entry_limit, "entry")
    app.state.authentication = Admission(settings.authentication_limit, "auth")
    app.state.business = Admission(settings.business_limit, "tenant", settings.tenant_limit)
    app.state.quota = Redis.from_url(
        settings.redis_url,
        **settings.redis_credentials("quota"),
        socket_connect_timeout=0.15,
        socket_timeout=0.15,
        max_connections=32,
        decode_responses=True,
        retry=Retry(NoBackoff(), 0),
    )
    app.state.cache_redis = Redis.from_url(
        settings.cache_redis_url,
        **settings.redis_credentials("cache"),
        socket_connect_timeout=0.15,
        socket_timeout=0.15,
        max_connections=32,
        decode_responses=True,
        retry=Retry(NoBackoff(), 0),
    )
    app.state.cache = SummaryCache(app.state.cache_redis, settings.cache_ttl)
    app.state.erp = ERP(settings.erp_url)
    provider = configure_traces(settings, db)
    lag = asyncio.create_task(observe_loop())
    try:
        yield
    finally:
        app.state.entry.closing = True
        app.state.business.closing = True
        lag.cancel()
        with suppress(asyncio.CancelledError):
            await lag
        await app.state.erp.close()
        await app.state.quota.aclose()
        await app.state.cache_redis.aclose()
        await db.close()
        await asyncio.to_thread(provider.shutdown)


app = FastAPI(
    title="API Sentinel",
    description=(
        "Consultas de lojas com isolamento por tenant e limites de capacidade. "
        "Use **Authorize** com uma credencial local, sem escrever o prefixo Bearer. "
        "Os dias são inclusivos em America/Sao_Paulo; valores monetários são centavos de BRL. "
        "Massa comercial: 2026-01-01 a 2026-03-01. "
        "A loja técnica 7 contém apenas a fixture de 2026-01-01 e exige a credencial do probe."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)
app.add_middleware(RequestMiddleware)
bearer_auth = HTTPBearer(
    scheme_name="SentinelCredential",
    description="Token gerado pela CLI local.",
    auto_error=False,
)


@app.exception_handler(Problem)
async def handle_problem(request: Request, exc: Problem) -> JSONResponse:
    return problem_response(exc, request.state.request_id)


@app.exception_handler(RequestValidationError)
async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    return problem_response(
        Problem(422, "invalid_request", "Parâmetros inválidos; confira o contrato da API."),
        request.state.request_id,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return problem_response(
        Problem(exc.status_code, "http_error", "Rota ou método indisponível."),
        request.state.request_id,
    )


async def principal(
    request: Request,
    credential: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_auth)],
) -> auth.Principal:
    header = request.headers.get("authorization", "")
    if len(header) > 256 or credential is None:
        raise Problem(401, "invalid_credential", "Credencial Bearer obrigatória.")
    with request.app.state.authentication.enter():
        try:
            async with asyncio.timeout(0.5):
                result = await auth.authenticate(request.app.state.db, credential.credentials)
        except TimeoutError as exc:
            raise Problem(
                503, "authentication_busy", "Autenticação temporariamente indisponível.", 1
            ) from exc
    request.state.traffic = "probe" if result.is_probe else "business"
    return result


Identity = Annotated[auth.Principal, Depends(principal)]
StoreId = Annotated[int, PathParameter(ge=1, le=2**63 - 1)]


async def admit(
    request: Request, identity: auth.Principal, scope: str, store: int | None = None
) -> None:
    auth.authorize(identity, scope, store)
    await enforce_quota(request.app.state.quota, identity.tenant_id, identity.quota_per_second)


@app.get(
    "/v1/stores",
    response_model=StoreList,
    responses=BUSINESS_ERRORS,
    tags=["Lojas"],
    summary="Listar lojas permitidas e sua cobertura",
)
async def stores(request: Request, identity: Identity) -> dict:
    await admit(request, identity, "stores:read")
    with request.app.state.business.enter(identity.tenant_id):
        return await queries.list_stores(request.app.state.db, identity)


@app.get(
    "/v1/stores/{store_id}/summary",
    response_model=StoreSummary,
    responses=BUSINESS_ERRORS,
    tags=["Vendas"],
    summary="Consultar faturamento, pedidos e ticket médio",
)
async def summary(
    request: Request, identity: Identity, store_id: StoreId, start: date, end: date
) -> dict:
    await admit(request, identity, "sales:read", store_id)
    with request.app.state.business.enter(identity.tenant_id):
        dataset = await queries.dataset_info(request.app.state.db)
        key = f"summary:v1:{dataset['version']}:{identity.tenant_id}:{store_id}:{start}:{end}"
        return await request.app.state.cache.get_or_fill(
            key, lambda: queries.summary(request.app.state.db, identity, store_id, start, end)
        )


@app.get(
    "/v1/stores/{store_id}/sales",
    response_model=SalesPage,
    responses=BUSINESS_ERRORS,
    tags=["Vendas"],
    summary="Percorrer itens de venda por cursor",
)
async def sales(
    request: Request,
    identity: Identity,
    store_id: StoreId,
    start: date,
    end: date,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> dict:
    await admit(request, identity, "sales:read", store_id)
    with request.app.state.business.enter(identity.tenant_id):
        return await queries.sales(
            request.app.state.db,
            identity,
            store_id,
            start,
            end,
            limit,
            cursor,
            request.app.state.cursor_secret,
        )


@app.get(
    "/v1/stores/{store_id}/availability/{sku}",
    response_model=Availability,
    responses=BUSINESS_ERRORS
    | {
        502: {"description": "O ERP retornou contrato ou status inválido."},
        504: {"description": "O ERP excedeu o prazo total de 900 ms."},
    },
    tags=["Integração ERP"],
    summary="Consultar estoque no ERP fictício",
)
async def availability(request: Request, identity: Identity, store_id: StoreId, sku: str) -> dict:
    import re

    if not re.fullmatch(r"SKU-[0-9]{3}", sku):
        raise Problem(422, "invalid_sku", "SKU deve seguir o formato SKU-001.")
    await admit(request, identity, "inventory:read", store_id)
    with request.app.state.business.enter(identity.tenant_id):
        return await request.app.state.erp.availability(store_id, sku)


@app.get("/health/live", tags=["Saúde"], summary="Verificar se o processo responde")
async def live() -> dict:
    return {"status": "ok"}


@app.get("/health/ready", tags=["Saúde"], summary="Verificar PostgreSQL e controle de quota")
async def ready(request: Request) -> dict:
    try:
        async with asyncio.timeout(0.5):
            async with request.app.state.db.connection("auth") as connection:
                await connection.execute(text("SELECT 1"))
            await request.app.state.quota.ping()
    except Exception as exc:
        raise Problem(503, "not_ready", "Dependências indisponíveis.") from exc
    return {"status": "ready"}


@app.get("/internal/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})
