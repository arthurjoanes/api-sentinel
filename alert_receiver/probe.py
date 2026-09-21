import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from alert_receiver.config import Settings

logger = logging.getLogger("sentinel.receiver")


class KnownSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    revenue_cents: int = Field(strict=True, ge=0)
    order_count: int = Field(strict=True, ge=0)
    average_ticket_cents: int = Field(strict=True, ge=0)
    data_updated_at: AwareDatetime
    observed_at: AwareDatetime
    dataset_version: str = Field(min_length=1, max_length=100)


ProbeResult = Literal["success", "http_error", "contract", "deadline", "network", "configuration"]


@dataclass
class ProbeState:
    result: ProbeResult | None = None
    checked_at: datetime | None = None
    duration_seconds: float | None = None
    expected_replicas: int | None = None
    enabled: bool = True
    stale_after_seconds: float = 15.0

    def observation_status(
        self, now: datetime | None = None
    ) -> Literal["disabled", "configuration", "pending", "unavailable", "stale", "fresh"]:
        if not self.enabled:
            return "disabled"
        if self.result == "configuration":
            return "configuration"
        if self.result is None:
            return "pending"
        if self.checked_at is None or self.checked_at.tzinfo is None:
            return "unavailable"
        age = ((now or datetime.now(UTC)) - self.checked_at).total_seconds()
        if age < 0:
            return "unavailable"
        return "stale" if age > self.stale_after_seconds else "fresh"


class ReceiverMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.probe_success = Gauge(
            "sentinel_probe_success",
            "Último probe validou a fixture pelo proxy.",
            registry=self.registry,
        )
        self.probe_last_run = Gauge(
            "sentinel_probe_last_run_timestamp_seconds",
            "Instante da última consulta concluída pelo probe, sem tentativas de configuração.",
            registry=self.registry,
        )
        self.probe_stale_after = Gauge(
            "sentinel_probe_stale_after_seconds",
            "Limite de frescor da observação, derivado do intervalo e deadline configurados.",
            registry=self.registry,
        )
        self.probe_stale_after.set(15)
        self.probe_config_valid = Gauge(
            "sentinel_probe_config_valid",
            "Configuração do probe foi lida e validada na última tentativa: 0 ou 1.",
            registry=self.registry,
        )
        self.expected_replicas = Gauge(
            "sentinel_expected_replicas",
            "Réplicas desejadas no arquivo local de operação.",
            registry=self.registry,
        )
        self.probe_duration = Histogram(
            "sentinel_probe_duration_seconds",
            "Duração ponta a ponta do probe.",
            buckets=(0.1, 0.25, 0.5, 1, 2, 3),
            registry=self.registry,
        )
        self.probe_results = Counter(
            "sentinel_probe_results_total",
            "Resultados do probe por categoria limitada.",
            ["result"],
            registry=self.registry,
        )
        self.webhooks = Counter(
            "sentinel_alert_webhooks_total",
            "Entrega de webhooks ao receiver.",
            ["result"],
            registry=self.registry,
        )
        self.truncated_alerts = Counter(
            "sentinel_alert_truncated_total",
            "Alertas omitidos pelo limite do Alertmanager.",
            registry=self.registry,
        )
        self.probe_success.set(float("nan"))
        self.probe_config_valid.set(0)
        self.expected_replicas.set(float("nan"))
        for result in (
            "persisted",
            "unauthorized",
            "invalid",
            "too_large",
            "storage_error",
            "busy",
        ):
            self.webhooks.labels(result=result)


def read_probe_token(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))["probe"]
    if (
        not isinstance(value, str)
        or not 32 <= len(value) <= 512
        or any(not 33 <= ord(character) <= 126 for character in value)
    ):
        raise ValueError("Credencial técnica inválida.")
    return value


def read_expected_replicas(path: Path) -> int:
    replicas = int(path.read_text(encoding="utf-8").strip())
    if replicas not in (1, 2):
        raise ValueError("Réplicas esperadas devem ser 1 ou 2.")
    return replicas


async def check_summary(
    client: httpx.AsyncClient, url: str, token: str, timeout_seconds: float
) -> ProbeResult:
    try:
        async with asyncio.timeout(timeout_seconds):
            async with client.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"},
            ) as response:
                if response.status_code != 200:
                    return "http_error"
                if (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                ):
                    return "contract"
                if (
                    response.headers.get("content-encoding", "identity").strip().lower()
                    != "identity"
                ):
                    return "contract"
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 16_384:
                        return "contract"
                    body.extend(chunk)
                summary = KnownSummary.model_validate_json(bytes(body))
                if (summary.revenue_cents, summary.order_count, summary.average_ticket_cents) != (
                    12_500,
                    2,
                    6_250,
                ):
                    return "contract"
                return "success"
    except (TimeoutError, httpx.TimeoutException):
        return "deadline"
    except (httpx.HTTPError, OSError):
        return "network"
    except (ValidationError, ValueError):
        return "contract"


async def probe_loop(settings: Settings, state: ProbeState, metrics: ReceiverMetrics) -> None:
    state.stale_after_seconds = settings.probe_stale_after_seconds
    metrics.probe_stale_after.set(state.stale_after_seconds)
    timeout = httpx.Timeout(
        settings.probe_timeout_seconds, connect=min(0.7, settings.probe_timeout_seconds), pool=0.2
    )
    async with httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        while True:
            started = time.monotonic()
            try:
                token = await asyncio.to_thread(read_probe_token, settings.probe_credentials_file)
                state.expected_replicas = await asyncio.to_thread(
                    read_expected_replicas, settings.expected_replicas_file
                )
                metrics.expected_replicas.set(state.expected_replicas)
                result = await check_summary(
                    client, settings.probe_url, token, settings.probe_timeout_seconds
                )
            except (OSError, ValueError, KeyError, TypeError):
                result = "configuration"
                state.expected_replicas = None
                metrics.expected_replicas.set(float("nan"))
            duration = time.monotonic() - started
            if result != state.result:
                logger.info(
                    json.dumps(
                        {"event": "probe_transition", "previous": state.result, "result": result}
                    )
                )
            state.result = result
            configured = result != "configuration"
            metrics.probe_config_valid.set(int(configured))
            if configured:
                state.checked_at = datetime.now(UTC)
                state.duration_seconds = duration
                metrics.probe_success.set(int(result == "success"))
                metrics.probe_last_run.set(state.checked_at.timestamp())
                metrics.probe_duration.observe(duration)
            else:
                # Não houve consulta: nem saúde nem indisponibilidade foram observadas.
                state.checked_at = None
                state.duration_seconds = None
                metrics.probe_success.set(float("nan"))
            metrics.probe_results.labels(result=result).inc()
            # Apenas uma chamada em voo; atrasos não acumulam execuções futuras.
            await asyncio.sleep(max(0.1, settings.probe_interval_seconds - duration))
