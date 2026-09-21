import asyncio
import random
import time

import httpx
from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from api_sentinel.admission import Admission
from api_sentinel.errors import Problem
from api_sentinel.metrics import ERP_CIRCUIT, ERP_DURATION, ERP_REQUESTS, ERP_RETRIES


class Availability(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    store_id: int
    sku: str
    available: int = Field(ge=0, le=100000)


class ERP:
    def __init__(self, url: str) -> None:
        self.client = httpx.AsyncClient(
            base_url=url,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(connect=0.2, read=0.3, write=0.2, pool=0.05),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )
        self.admission = Admission(4, "erp")
        self.failures = 0
        self.open_until = 0.0
        self.probing = False

    async def availability(self, store: int, sku: str) -> dict:
        # O span HTTPX termina nos headers; este inclui corpo, contrato e retries.
        with trace.get_tracer("api_sentinel.erp").start_as_current_span(
            "erp.availability", record_exception=False, set_status_on_exception=False
        ) as span:
            try:
                return await self._availability(store, sku)
            except Problem as exc:
                span.set_attribute("error.category", exc.code)
                span.set_status(trace.Status(trace.StatusCode.ERROR))
                raise

    async def _availability(self, store: int, sku: str) -> dict:
        started = time.monotonic()
        if self.open_until > started or (self.open_until and self.probing):
            ERP_REQUESTS.labels("circuit_open").inc()
            raise Problem(
                503, "erp_circuit_open", "ERP em recuperação; consulta principal disponível.", 3
            )
        half_open = self.open_until > 0
        if half_open:
            self.probing = True
        outcome = "error"
        try:
            with self.admission.enter():
                async with asyncio.timeout(0.9):
                    result = await self._request(store, sku, started + 0.85)
            self.failures = 0
            self.open_until = 0
            ERP_CIRCUIT.set(0)
            outcome = "success"
            return result
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError) as exc:
            self._failure()
            raise Problem(504, "erp_deadline", "ERP não respondeu dentro do prazo.") from exc
        except (httpx.RemoteProtocolError, httpx.DecodingError) as exc:
            self._failure()
            raise Problem(
                502, "erp_transport", "ERP retornou resposta de transporte inválida."
            ) from exc
        except Problem as exc:
            if exc.code not in ("service_saturated", "erp_pool_busy"):
                self._failure()
            raise
        finally:
            if half_open:
                self.probing = False
            ERP_REQUESTS.labels(outcome).inc()
            ERP_DURATION.labels(outcome).observe(time.monotonic() - started)

    def _failure(self) -> None:
        self.failures += 1
        if self.failures >= 3:
            self.open_until = time.monotonic() + 3
            ERP_CIRCUIT.set(1)

    async def _request(self, store: int, sku: str, deadline: float) -> dict:
        for attempt in range(2):
            try:
                async with self.client.stream(
                    "GET", f"/availability/{store}/{sku}", headers={"Accept-Encoding": "identity"}
                ) as response:
                    if response.status_code in (502, 503, 504):
                        raise httpx.ConnectError("ERP temporariamente indisponível")
                    if response.status_code != 200:
                        raise Problem(502, "erp_status", "ERP retornou status inesperado.")
                    if response.headers.get("content-type", "").split(";")[0] != "application/json":
                        raise Problem(502, "erp_contract", "ERP retornou formato inválido.")
                    if (
                        response.headers.get("content-encoding", "identity").strip().lower()
                        != "identity"
                    ):
                        raise Problem(
                            502, "erp_contract", "ERP retornou codificação não permitida."
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > 8192:
                            raise Problem(
                                502, "erp_response_size", "Resposta ERP excedeu o limite."
                            )
                        body.extend(chunk)
                    try:
                        result = Availability.model_validate_json(bytes(body))
                    except ValidationError as exc:
                        raise Problem(
                            502, "erp_contract", "ERP retornou contrato inválido."
                        ) from exc
                    if result.store_id != store or result.sku != sku:
                        raise Problem(502, "erp_contract", "ERP retornou identificação divergente.")
                    return result.model_dump()
            except httpx.PoolTimeout as exc:
                raise Problem(503, "erp_pool_busy", "Conexões ERP ocupadas.") from exc
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                if attempt or deadline - time.monotonic() < 0.3:
                    raise
                ERP_RETRIES.inc()
                await asyncio.sleep(random.uniform(0.025, 0.05))
        raise RuntimeError("Retry sem resultado")

    async def close(self) -> None:
        await self.client.aclose()
