"""Jornada real e fixture independente pelo proxy; falhas/carga têm roteiro próprio."""

import json
import os
import re
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HTTP_TESTS") != "1", reason="Requer RUN_HTTP_TESTS=1 e stack demo pronta."
)
DAY = {"start": "2026-01-01", "end": "2026-01-01"}


class RedactedToken(str):
    def __repr__(self) -> str:
        return "'<credencial omitida>'"


class RedactedCredentials(dict[str, str]):
    def __repr__(self) -> str:
        return "<Credenciais de demonstração: valores omitidos>"


def wait_for_ready_proxy(session: httpx.Client, credentials: RedactedCredentials) -> None:
    deadline = time.monotonic() + 90
    expected = int(os.getenv("SENTINEL_EXPECTED_REPLICAS", "1"))
    if expected not in (1, 2):
        pytest.fail("SENTINEL_EXPECTED_REPLICAS deve ser 1 ou 2.", pytrace=False)
    instances: set[str] = set()
    last_state = "nenhuma resposta"
    while time.monotonic() < deadline:
        try:
            ready = session.get("/health/ready")
            last_state = f"health/ready HTTP {ready.status_code}"
            if ready.status_code == 200:
                response = session.get(
                    "/v1/stores/7/summary",
                    params={"start": "2026-01-01", "end": "2026-01-01"},
                    headers=bearer(credentials, "probe"),
                )
                last_state = f"fixture autenticada HTTP {response.status_code}"
                if response.status_code == 200:
                    body = response.json()
                    correct = (
                        body.get("revenue_cents") == 12500
                        and body.get("order_count") == 2
                        and body.get("average_ticket_cents") == 6250
                    )
                    instance = response.headers.get("x-instance-id")
                    if correct and instance:
                        instances.add(instance)
                        if len(instances) >= expected:
                            return
                        last_state = f"réplicas prontas {len(instances)}/{expected}"
                    else:
                        last_state = "fixture ainda não confirmou totais/identidade"
        except (httpx.RequestError, ValueError):
            last_state = "resposta de prontidão indisponível ou inválida"
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.5, remaining))
    pytest.fail(f"Proxy não ficou pronto em 90s: {last_state}.", pytrace=False)


@pytest.fixture(scope="session")
def client(credentials: RedactedCredentials) -> Iterator[httpx.Client]:
    previous = 0.0

    def pace_request(request: httpx.Request) -> None:
        nonlocal previous
        remaining = 0.14 - (time.monotonic() - previous)
        if remaining > 0:
            time.sleep(remaining)
        previous = time.monotonic()

    with httpx.Client(
        base_url=os.getenv("SENTINEL_BASE_URL", "http://proxy"),
        timeout=3,
        trust_env=False,
        follow_redirects=False,
        event_hooks={"request": [pace_request]},
    ) as session:
        wait_for_ready_proxy(session, credentials)
        yield session


@pytest.fixture(scope="session")
def credentials() -> RedactedCredentials:
    path = Path(os.getenv("SENTINEL_CREDENTIALS_FILE", "/secrets/demo.json"))
    return RedactedCredentials(
        (name, RedactedToken(token))
        for name, token in json.loads(path.read_text(encoding="utf-8")).items()
    )


def bearer(credentials: dict[str, str], name: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + credentials[name]}


@pytest.mark.parametrize("path,status", [("live", "ok"), ("ready", "ready")])
def test_health_journey_uses_proxy(client: httpx.Client, path: str, status: str) -> None:
    response = client.get(f"/health/{path}")
    assert response.status_code == 200
    assert response.json() == {"status": status}


@pytest.mark.parametrize(
    "name,ids", [("tenant_a", [1, 2, 3]), ("tenant_b", [4, 5, 6]), ("probe", [7])]
)
def test_seeded_store_coverage_is_visible(
    client: httpx.Client, credentials: dict[str, str], name: str, ids: list[int]
) -> None:
    response = client.get("/v1/stores", headers=bearer(credentials, name))
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ids
    for item in response.json()["items"]:
        assert item["coverage"]["starts_on"] == "2026-01-01"
        assert item["coverage"]["ends_on"] == ("2026-01-01" if name == "probe" else "2026-03-01")


def test_manual_fixture_totals_and_observation_contract(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get("/v1/stores/7/summary", params=DAY, headers=bearer(credentials, "probe"))
    assert response.status_code == 200
    body = response.json()
    # Três linhas e dois pedidos: 2*2500 + 3500 + 4000 = 12500; 12500/2 = 6250.
    assert body["revenue_cents"] == 12500
    assert body["order_count"] == 2
    assert body["average_ticket_cents"] == 6250
    assert body["store_id"] == 7
    assert body["currency"] == "BRL"
    assert body["start"] == body["end"] == "2026-01-01"
    assert body["coverage"]["complete"] is True
    assert body["dataset_version"]
    for field in ("revenue_cents", "order_count", "average_ticket_cents"):
        assert type(body[field]) is int
    assert datetime.fromisoformat(body["observed_at"]).tzinfo is not None
    assert datetime.fromisoformat(body["data_updated_at"]).tzinfo is not None
    assert body["cache_age_seconds"] >= 0


def test_fixture_cursor_pages_cover_both_sao_paulo_day_boundaries(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    cursor = None
    items = []
    for page_number in range(3):
        params: dict[str, str | int] = DAY | {"limit": 1}
        if cursor:
            params["cursor"] = cursor
        response = client.get(
            "/v1/stores/7/sales", params=params, headers=bearer(credentials, "probe")
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        items.extend(body["items"])
        cursor = body["next_cursor"]
        assert (cursor is not None) == (page_number < 2)
    assert [item["id"] for item in items] == [7000000000003, 7000000000002, 7000000000001]
    assert [item["line_total_cents"] for item in items] == [4000, 3500, 5000]
    assert len({item["id"] for item in items}) == 3
    assert len({item["order_id"] for item in items}) == 2
    assert sum(item["line_total_cents"] for item in items) == 12500
    assert items[0]["sold_at"].startswith("2026-01-02T02:59:59")
    assert items[-1]["sold_at"].startswith("2026-01-01T03:00:00")


def test_commercial_page_is_bounded_and_order_is_stable(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    params = {"start": "2026-01-01", "end": "2026-03-01", "limit": 100}
    first = client.get("/v1/stores/1/sales", params=params, headers=bearer(credentials, "tenant_a"))
    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 100
    assert first_body["next_cursor"]
    second = client.get(
        "/v1/stores/1/sales",
        params=params | {"cursor": first_body["next_cursor"]},
        headers=bearer(credentials, "tenant_a"),
    )
    assert second.status_code == 200
    items = first_body["items"] + second.json()["items"]
    assert len({item["id"] for item in items}) == len(items)
    positions = [(datetime.fromisoformat(item["sold_at"]), item["id"]) for item in items]
    assert positions == sorted(positions, reverse=True)


def test_uncovered_period_is_explicit_instead_of_zero(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get(
        "/v1/stores/7/summary",
        params={"start": "2026-01-02", "end": "2026-01-02"},
        headers=bearer(credentials, "probe"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "data_outside_coverage"
    assert "revenue_cents" not in response.json()


def test_cache_preserves_data_and_compute_timestamps(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    previous = None
    for _ in range(5):
        response = client.get(
            "/v1/stores/1/summary", params=DAY, headers=bearer(credentials, "tenant_a")
        )
        assert response.status_code == 200
        current = response.json()
        if previous and previous["observed_at"] == current["observed_at"]:
            assert previous["data_updated_at"] == current["data_updated_at"]
            assert previous["dataset_version"] == current["dataset_version"]
            assert previous["revenue_cents"] == current["revenue_cents"]
            assert current["cache_age_seconds"] >= previous["cache_age_seconds"]
            break
        previous = current
    else:
        pytest.fail("Nenhum par consecutivo preservou observed_at: cache não demonstrou hit.")


def test_cached_summaries_keep_store_and_tenant_identity(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    responses = []
    for name, store in [("tenant_a", 1), ("tenant_b", 4), ("tenant_a", 1), ("tenant_b", 4)]:
        response = client.get(
            f"/v1/stores/{store}/summary", params=DAY, headers=bearer(credentials, name)
        )
        assert response.status_code == 200
        assert response.json()["store_id"] == store
        responses.append(response.json())
    assert responses[0]["revenue_cents"] == responses[2]["revenue_cents"]
    assert responses[1]["revenue_cents"] == responses[3]["revenue_cents"]
    assert responses[0]["store_id"] != responses[1]["store_id"]


def test_erp_registry_contract_is_usable(client: httpx.Client, credentials: dict[str, str]) -> None:
    response = client.get(
        "/v1/stores/1/availability/SKU-001", headers=bearer(credentials, "tenant_a")
    )
    assert response.status_code == 200
    assert response.json() == {"store_id": 1, "sku": "SKU-001", "available": 21}


def test_proxy_reports_expected_replicas_and_correlation_ids(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    expected = int(os.getenv("SENTINEL_EXPECTED_REPLICAS", "1"))
    assert expected in (1, 2), "Laboratório suporta esta verificação com uma ou duas réplicas."
    instances = set()
    requests = set()
    for _ in range(max(4, expected * 4)):
        response = client.get("/v1/stores", headers=bearer(credentials, "tenant_a"))
        assert response.status_code == 200
        assert re.fullmatch(r"[a-f0-9]{32}", response.headers["x-request-id"])
        assert re.fullmatch(r"[a-f0-9]{32}", response.headers["x-trace-id"])
        instances.add(response.headers["x-instance-id"])
        requests.add(response.headers["x-request-id"])
    assert len(instances) >= expected
    assert len(requests) == max(4, expected * 4)
