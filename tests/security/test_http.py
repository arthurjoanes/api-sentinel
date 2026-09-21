"""Segurança pelo proxy real; não modifica credenciais nem a massa de demonstração."""

import json
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HTTP_TESTS") != "1", reason="Requer RUN_HTTP_TESTS=1 e stack demo pronta."
)
PERIOD = {"start": "2026-01-01", "end": "2026-01-03"}


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
        # Esta suíte verifica contratos, não capacidade: no máximo ~7 chamadas/s.
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
    value = RedactedCredentials(
        (name, RedactedToken(token))
        for name, token in json.loads(path.read_text(encoding="utf-8")).items()
    )
    for name in ("tenant_a", "tenant_b", "restricted", "expired", "probe"):
        if not isinstance(value.get(name), str):
            pytest.fail(f"Arquivo de credenciais não contém a chave {name}.")
    return value


def bearer(credentials: dict[str, str], name: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + credentials[name]}


def assert_no_credential_leak(response: httpx.Response, credentials: dict[str, str]) -> None:
    if any(token in response.text for token in credentials.values()):
        pytest.fail("Resposta contém uma credencial; o valor foi omitido.", pytrace=False)


def assert_problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.headers["content-type"].split(";")[0] == "application/problem+json"
    body = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"urn:api-sentinel:problem:{code}"
    assert re.fullmatch(r"[a-f0-9]{32}", body["request_id"])
    assert response.headers["x-request-id"] == body["request_id"]
    assert "Traceback" not in response.text
    assert "SELECT " not in response.text
    assert "asyncpg" not in response.text


@pytest.mark.parametrize(
    "header", [None, "", "Basic abc", "Bearer short", "Bearer sentinel_" + "x" * 50]
)
def test_missing_or_invalid_credentials_are_rejected(
    client: httpx.Client, header: str | None
) -> None:
    headers = {} if header is None else {"Authorization": header}
    assert_problem(client.get("/v1/stores", headers=headers), 401, "invalid_credential")


def test_expired_credential_is_rejected(client: httpx.Client, credentials: dict[str, str]) -> None:
    response = client.get("/v1/stores", headers=bearer(credentials, "expired"))
    assert_problem(response, 401, "invalid_credential")
    assert_no_credential_leak(response, credentials)


def test_identity_claims_from_client_do_not_select_tenant(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get(
        "/v1/stores",
        params={"tenant_id": 2, "roles": "admin", "store_ids": "4,5,6"},
        headers=bearer(credentials, "tenant_a") | {"X-Tenant-ID": "2", "X-Roles": "admin"},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [1, 2, 3]


def test_restricted_credential_lists_only_authorized_store(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get("/v1/stores", headers=bearer(credentials, "restricted"))
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [1]


@pytest.mark.parametrize("path", ["summary", "sales", "availability/SKU-001"])
def test_restricted_scope_cannot_read_business_data(
    client: httpx.Client, credentials: dict[str, str], path: str
) -> None:
    response = client.get(
        f"/v1/stores/1/{path}", params=PERIOD, headers=bearer(credentials, "restricted")
    )
    assert_problem(response, 403, "insufficient_scope")


@pytest.mark.parametrize("name,store", [("tenant_a", 4), ("tenant_b", 1), ("tenant_a", 7)])
@pytest.mark.parametrize("path", ["summary", "sales", "availability/SKU-001"])
def test_valid_store_id_of_another_tenant_is_forbidden(
    client: httpx.Client, credentials: dict[str, str], name: str, store: int, path: str
) -> None:
    response = client.get(
        f"/v1/stores/{store}/{path}", params=PERIOD, headers=bearer(credentials, name)
    )
    assert_problem(response, 403, "store_forbidden")


def test_authorization_precedes_warm_cache_lookup(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    own = client.get("/v1/stores/4/summary", params=PERIOD, headers=bearer(credentials, "tenant_b"))
    assert own.status_code == 200
    forbidden = client.get(
        "/v1/stores/4/summary", params=PERIOD, headers=bearer(credentials, "tenant_a")
    )
    assert_problem(forbidden, 403, "store_forbidden")
    assert "revenue_cents" not in forbidden.json()
    valid = client.get(
        "/v1/stores/1/summary", params=PERIOD, headers=bearer(credentials, "tenant_a")
    )
    assert valid.status_code == 200
    restricted = client.get(
        "/v1/stores/1/summary", params=PERIOD, headers=bearer(credentials, "restricted")
    )
    assert_problem(restricted, 403, "insufficient_scope")


@pytest.fixture(scope="module")
def cursor(client: httpx.Client, credentials: dict[str, str]) -> str:
    response = client.get(
        "/v1/stores/1/sales",
        params=PERIOD | {"limit": 1},
        headers=bearer(credentials, "tenant_a"),
    )
    assert response.status_code == 200
    value = response.json()["next_cursor"]
    assert isinstance(value, str) and value
    return value


@pytest.mark.parametrize("name,store", [("tenant_a", 2), ("tenant_b", 4)])
def test_cursor_is_bound_to_tenant_and_store(
    client: httpx.Client, credentials: dict[str, str], cursor: str, name: str, store: int
) -> None:
    response = client.get(
        f"/v1/stores/{store}/sales",
        params=PERIOD | {"cursor": cursor},
        headers=bearer(credentials, name),
    )
    assert_problem(response, 422, "invalid_cursor")


def test_cursor_is_bound_to_filters(
    client: httpx.Client, credentials: dict[str, str], cursor: str
) -> None:
    response = client.get(
        "/v1/stores/1/sales",
        params=PERIOD | {"end": "2026-01-02", "cursor": cursor},
        headers=bearer(credentials, "tenant_a"),
    )
    assert_problem(response, 422, "invalid_cursor")


def test_cursor_signature_cannot_be_modified(
    client: httpx.Client, credentials: dict[str, str], cursor: str
) -> None:
    body, signature = cursor.split(".")
    changed = ("A" if signature[0] != "A" else "B") + signature[1:]
    response = client.get(
        "/v1/stores/1/sales",
        params=PERIOD | {"cursor": body + "." + changed},
        headers=bearer(credentials, "tenant_a"),
    )
    assert_problem(response, 422, "invalid_cursor")


@pytest.mark.parametrize("value", [0, -1, 101, 100000])
def test_page_size_is_bounded(
    client: httpx.Client, credentials: dict[str, str], value: int
) -> None:
    response = client.get(
        "/v1/stores/1/sales",
        params=PERIOD | {"limit": value},
        headers=bearer(credentials, "tenant_a"),
    )
    assert_problem(response, 422, "invalid_request")


def test_cursor_size_is_bounded(client: httpx.Client, credentials: dict[str, str]) -> None:
    response = client.get(
        "/v1/stores/1/sales",
        params=PERIOD | {"cursor": "x" * 2049},
        headers=bearer(credentials, "tenant_a"),
    )
    assert_problem(response, 422, "invalid_request")


@pytest.mark.parametrize(
    "start,end",
    [("2026-01-03", "2026-01-01"), ("2026-01-01", "2026-04-01"), ("9999-12-31", "9999-12-31")],
)
def test_commercial_period_is_bounded(
    client: httpx.Client, credentials: dict[str, str], start: str, end: str
) -> None:
    response = client.get(
        "/v1/stores/1/summary",
        params={"start": start, "end": end},
        headers=bearer(credentials, "tenant_a"),
    )
    assert_problem(response, 422, "invalid_period")


@pytest.mark.parametrize("field", ["start", "limit", "cursor"])
def test_sql_shaped_input_is_rejected_without_internal_details(
    client: httpx.Client, credentials: dict[str, str], field: str
) -> None:
    response = client.get(
        "/v1/stores/1/sales",
        params=PERIOD | {field: "1' OR 1=1; SELECT current_user--"},
        headers=bearer(credentials, "tenant_a"),
    )
    assert_problem(response, 422, "invalid_cursor" if field == "cursor" else "invalid_request")


def test_store_id_is_validated_before_query(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get(
        "/v1/stores/1%20OR%201=1/summary", params=PERIOD, headers=bearer(credentials, "tenant_a")
    )
    assert_problem(response, 422, "invalid_request")


@pytest.mark.parametrize("store", [0, -1, 2**63])
def test_store_id_is_a_positive_database_integer(client, credentials, store) -> None:
    response = client.get(
        f"/v1/stores/{store}/summary", params=PERIOD, headers=bearer(credentials, "tenant_a")
    )
    assert_problem(response, 422, "invalid_request")


@pytest.mark.parametrize(
    "sku", ["erp:8080", "127.0.0.1", "SKU-001?url=erp", "..", "SKU-１２３", "SKU-١٢٣"]
)
def test_sku_cannot_be_used_as_an_outbound_destination(
    client: httpx.Client, credentials: dict[str, str], sku: str
) -> None:
    encoded = quote(sku, safe="")
    # O ponto duplo seria normalizado pelo cliente; codificação mantém a entrada sob teste.
    if sku == "..":
        encoded = "%2E%2E"
    response = client.get(
        f"/v1/stores/1/availability/{encoded}", headers=bearer(credentials, "tenant_a")
    )
    assert response.status_code in (404, 422)
    assert "location" not in response.headers


def test_outbound_url_and_host_query_parameters_do_not_override_registry(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get(
        "/v1/stores/1/availability/SKU-001",
        params={"url": "http://erp:8080/health/live", "host": "erp:8080", "credential": "ignored"},
        headers=bearer(credentials, "tenant_a"),
    )
    assert response.status_code == 200
    assert response.json() == {"store_id": 1, "sku": "SKU-001", "available": 21}


def test_untrusted_correlation_headers_are_not_reflected(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    marker = '<script>alert("sentinel-test")</script>'
    response = client.get(
        "/v1/stores",
        headers=bearer(credentials, "tenant_a")
        | {"X-Request-ID": marker, "X-Trace-ID": marker, "X-Forwarded-Host": "untrusted.invalid"},
    )
    assert response.status_code == 200
    assert re.fullmatch(r"[a-f0-9]{32}", response.headers["x-request-id"])
    assert re.fullmatch(r"[a-f0-9]{32}", response.headers["x-trace-id"])
    assert marker not in response.text
    assert marker not in str(response.headers)
    assert_no_credential_leak(response, credentials)
    assert response.headers["cache-control"] == "no-store"


def test_bearer_api_does_not_enable_unrestricted_cors_or_session_cookie(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get(
        "/v1/stores",
        headers=bearer(credentials, "tenant_a") | {"Origin": "http://127.0.0.1:9184"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("path", ["/internal/metrics", "/%69nternal/metrics", "/metrics"])
def test_metrics_are_not_exposed_by_public_proxy(client: httpx.Client, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 404
    assert "sentinel_http_requests_total" not in response.text
    assert "process_resident_memory_bytes" not in response.text


def test_proxy_bounds_body_size(client: httpx.Client, credentials: dict[str, str]) -> None:
    response = client.request(
        "GET", "/v1/stores", content=b"x" * 17000, headers=bearer(credentials, "tenant_a")
    )
    assert response.status_code == 413


def test_proxy_bounds_header_size(client: httpx.Client, credentials: dict[str, str]) -> None:
    response = client.get(
        "/v1/stores", headers=bearer(credentials, "tenant_a") | {"X-Limit-Test": "x" * 9000}
    )
    assert response.status_code in (400, 431)


def test_bearer_scheme_accepts_case_insensitive_http_convention(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get(
        "/v1/stores", headers={"Authorization": "bearer " + credentials["tenant_a"]}
    )
    assert response.status_code == 200
    assert [store["id"] for store in response.json()["items"]] == [1, 2, 3]


def test_duplicate_credentials_are_rejected_before_authentication(
    client: httpx.Client, credentials: dict[str, str]
) -> None:
    response = client.get(
        "/v1/stores",
        headers=[
            ("Authorization", "Bearer " + credentials["tenant_a"]),
            ("Authorization", "Bearer " + credentials["tenant_b"]),
        ],
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "items" not in response.json()
    assert_no_credential_leak(response, credentials)


def test_deployed_openapi_allows_authenticated_exploration(client: httpx.Client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["components"]["securitySchemes"]["SentinelCredential"]["scheme"] == "bearer"
    summary = schema["paths"]["/v1/stores/{store_id}/summary"]["get"]
    assert summary["security"] == [{"SentinelCredential": []}]
    assert summary["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/StoreSummary"
    }
