import asyncio
import gzip
import json
import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from alert_receiver import probe
from alert_receiver.config import Settings
from alert_receiver.probe import ProbeState, ReceiverMetrics, check_summary


def known_summary() -> dict[str, object]:
    return {
        "revenue_cents": 12500,
        "order_count": 2,
        "average_ticket_cents": 6250,
        "data_updated_at": "2026-01-02T03:00:00Z",
        "observed_at": "2026-09-20T03:00:00Z",
        "dataset_version": "fixture-v1",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("revenue_cents", 0),
        ("order_count", True),
        ("average_ticket_cents", "6250"),
        ("dataset_version", ""),
        ("observed_at", "yesterday"),
    ],
)
async def test_probe_rejects_wrong_result_and_schema(field: str, value: object) -> None:
    summary = known_summary()
    summary[field] = value
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=summary))
    ) as client:
        assert (
            await check_summary(client, "http://proxy/fixture", "separate-probe-token", 1)
            == "contract"
        )


async def test_probe_accepts_exact_result_and_uses_bearer() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer separate-probe-token"
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, json=known_summary())

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        assert (
            await check_summary(client, "http://proxy/fixture", "separate-probe-token", 1)
            == "success"
        )


@pytest.mark.parametrize("status", [401, 429, 503, 302])
async def test_http_errors_and_redirects_are_not_success(status: int) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as client:
        assert await check_summary(client, "http://proxy/fixture", "token", 1) == "http_error"


async def test_probe_enforces_actual_response_bytes() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json", "content-length": "1"},
                content=b" " * 16_385,
            )
        )
    ) as client:
        assert await check_summary(client, "http://proxy/fixture", "token", 1) == "contract"


class ProbeBody(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "identity, gzip", "gzip, identity"])
async def test_probe_refuses_compression_before_reading(encoding: str) -> None:
    stream = ProbeBody([gzip.compress(b" " * 1_000_000)])

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": encoding},
            stream=stream,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await check_summary(client, "http://proxy/fixture", "token", 1) == "contract"
    assert stream.read_count == 0
    assert stream.closed


@pytest.mark.parametrize("extra_byte", [False, True])
async def test_probe_response_limit_across_chunks_closes_stream(extra_byte: bool) -> None:
    body = json.dumps(known_summary()).encode().ljust(16_384, b" ")
    chunks = [body[:8192], body[8192:] + (b" " if extra_byte else b"")]
    if extra_byte:
        chunks.append(b"must not be read")
    stream = ProbeBody(chunks)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json", "content-encoding": "identity"},
                stream=stream,
            )
        )
    ) as client:
        assert await check_summary(client, "http://proxy/fixture", "token", 1) == (
            "contract" if extra_byte else "success"
        )
    assert stream.read_count == 2
    assert stream.closed


class SlowChunks(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.01)
            yield b" "

    async def aclose(self) -> None:
        self.closed = True


async def test_total_deadline_cancels_continuous_small_chunks_and_closes_stream() -> None:
    stream = SlowChunks()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/json"}, stream=stream
            )
        )
    ) as client:
        assert await check_summary(client, "http://proxy/fixture", "token", 0.06) == "deadline"
    assert stream.closed


async def test_probe_cancellation_propagates_and_closes_stream() -> None:
    stream = SlowChunks()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/json"}, stream=stream
            )
        )
    ) as client:
        task = asyncio.create_task(check_summary(client, "http://proxy/fixture", "token", 2))
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert stream.closed


def test_probe_begins_with_unknown_result_and_invalid_configuration() -> None:
    metrics = ReceiverMetrics()
    assert metrics.registry.get_sample_value("sentinel_probe_config_valid") == 0
    assert math.isnan(metrics.registry.get_sample_value("sentinel_probe_success"))
    assert math.isnan(metrics.registry.get_sample_value("sentinel_expected_replicas"))
    assert metrics.registry.get_sample_value("sentinel_probe_last_run_timestamp_seconds") == 0


async def stop_after_probe_iteration(delay: float) -> None:
    raise asyncio.CancelledError


@pytest.mark.parametrize(
    "reader,error_type",
    [
        ("read_probe_token", OSError),
        ("read_probe_token", ValueError),
        ("read_expected_replicas", OSError),
        ("read_expected_replicas", ValueError),
    ],
)
async def test_invalid_configuration_is_unknown_without_network_or_freshness(
    monkeypatch: pytest.MonkeyPatch, reader: str, error_type: type[Exception]
) -> None:
    metrics = ReceiverMetrics()
    metrics.probe_success.set(1)
    metrics.probe_config_valid.set(1)
    metrics.expected_replicas.set(2)
    metrics.probe_last_run.set(100)
    state = ProbeState(
        result="success", checked_at=datetime.fromtimestamp(100, UTC), expected_replicas=2
    )
    monkeypatch.setattr(probe, "read_probe_token", lambda _: "unit-test-only-probe-token")
    monkeypatch.setattr(probe, "read_expected_replicas", lambda _: 2)

    def fail_read(path: Path) -> str:
        raise error_type("configuração de teste indisponível")

    async def unexpected_query(*args: object) -> str:
        pytest.fail("Configuração inválida não pode executar uma consulta de negócio.")

    monkeypatch.setattr(probe, reader, fail_read)
    monkeypatch.setattr(probe, "check_summary", unexpected_query)
    monkeypatch.setattr(probe.asyncio, "sleep", stop_after_probe_iteration)
    with pytest.raises(asyncio.CancelledError):
        await probe.probe_loop(Settings(), state, metrics)
    assert state.result == "configuration"
    assert state.checked_at is None
    assert state.expected_replicas is None
    assert metrics.registry.get_sample_value("sentinel_probe_config_valid") == 0
    assert math.isnan(metrics.registry.get_sample_value("sentinel_probe_success"))
    assert math.isnan(metrics.registry.get_sample_value("sentinel_expected_replicas"))
    assert metrics.registry.get_sample_value("sentinel_probe_last_run_timestamp_seconds") == 100
    assert metrics.registry.get_sample_value("sentinel_probe_duration_seconds_count") == 0


@pytest.mark.parametrize("result,success", [("success", 1), ("http_error", 0)])
async def test_valid_configuration_restores_observed_result_and_freshness(
    monkeypatch: pytest.MonkeyPatch, result: str, success: int
) -> None:
    metrics = ReceiverMetrics()
    state = ProbeState(result="configuration")
    calls = []
    monkeypatch.setattr(probe, "read_probe_token", lambda _: "unit-test-only-probe-token")
    monkeypatch.setattr(probe, "read_expected_replicas", lambda _: 2)

    async def query(*args: object) -> str:
        calls.append("fixture")
        return result

    monkeypatch.setattr(probe, "check_summary", query)
    monkeypatch.setattr(probe.asyncio, "sleep", stop_after_probe_iteration)
    with pytest.raises(asyncio.CancelledError):
        await probe.probe_loop(Settings(), state, metrics)
    assert calls == ["fixture"]
    assert state.result == result
    assert state.expected_replicas == 2
    assert state.checked_at is not None
    assert metrics.registry.get_sample_value("sentinel_probe_config_valid") == 1
    assert metrics.registry.get_sample_value("sentinel_probe_success") == success
    assert metrics.registry.get_sample_value("sentinel_expected_replicas") == 2
    assert metrics.registry.get_sample_value("sentinel_probe_last_run_timestamp_seconds") > 100
    assert metrics.registry.get_sample_value("sentinel_probe_duration_seconds_count") == 1
