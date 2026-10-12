import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alert_receiver.app import create_app
from alert_receiver.config import Settings
from alert_receiver.contracts import Webhook


@pytest.fixture
def client(tmp_path: Path):
    token = tmp_path / "webhook-token"
    token.write_text("receiver-review-token-with-at-least-32-characters", encoding="utf-8")
    app = create_app(
        Settings(
            database_path=tmp_path / "alerts.sqlite3",
            webhook_token_file=token,
            probe_enabled=False,
            runbooks_path=tmp_path / "missing-runbooks",
        )
    )
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "path,status",
    [
        ("/incidents/999", 404),
        ("/incidents/not-a-number", 422),
        ("/runbooks/unknown", 404),
        ("/runbooks/unavailable", 503),
        ("/?status=unknown", 422),
    ],
)
def test_navigation_errors_offer_a_route_back(client: TestClient, path: str, status: int) -> None:
    response = client.get(path)
    assert response.status_code == status
    assert response.headers["content-type"].startswith("text/html")
    destination = "/?status=all#incidente-999" if path == "/incidents/999" else "/"
    assert f'href="{destination}">Voltar à central' in response.text
    assert "default-src 'none'" in response.headers["content-security-policy"]


@pytest.mark.parametrize("path", ["/api/incidents/999", "/api/incidents/not-a-number"])
def test_api_errors_keep_machine_readable_contract(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code in (404, 422)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["request_id"]


@pytest.mark.parametrize("value", [0, -1, 2**63])
@pytest.mark.parametrize("prefix", ["/incidents/", "/api/incidents/"])
def test_incident_id_bounds_prevent_sqlite_integer_overflow(client, value, prefix) -> None:
    response = client.get(prefix + str(value))
    assert response.status_code == 422
    assert "OverflowError" not in response.text


def test_storage_failure_is_not_an_empty_or_healthy_history(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object) -> None:
        raise sqlite3.OperationalError("PRIVATE_STORAGE_DETAIL")

    monkeypatch.setattr(client.app.state.store, "page", fail)
    page = client.get("/")
    api = client.get("/api/incidents")
    assert page.status_code == api.status_code == 503
    assert "Histórico indisponível" in page.text
    assert "Confira o armazenamento" in page.text
    assert api.json()["code"] == "receiver_storage"
    assert "PRIVATE_STORAGE_DETAIL" not in page.text + api.text


@pytest.mark.parametrize(
    "path",
    [
        "/?status=firing",
        "/incidents/12?status=resolved",
        "/runbooks/erp?incident_id=12&status=firing",
    ],
)
def test_busy_browser_keeps_html_context_retry_and_security_headers(
    client: TestClient, path: str
) -> None:
    client.app.state.active_requests = 24
    response = client.get(path)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["retry-after"] == "1"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert "Tentar novamente" in response.text and "Receiver ocupado" in response.text
    assert "status=firing" in response.text or "status=resolved" in response.text
    if "12" in path:
        assert "#incidente-12" in response.text
    assert client.app.state.active_requests == 24


@pytest.mark.parametrize("path", ["/api/incidents", "/webhook"])
def test_busy_machine_clients_keep_problem_json(client: TestClient, path: str) -> None:
    client.app.state.active_requests = 24
    response = client.post(path) if path == "/webhook" else client.get(path)
    assert response.status_code == 503 and response.json()["code"] == "receiver_busy"
    assert response.headers["content-type"] == "application/problem+json"
    assert (
        response.headers["cache-control"] == "no-store" and response.headers["retry-after"] == "1"
    )


@pytest.mark.parametrize("value", ["", "0", "-1", "1.1", "1e3", "１２", str(2**63), "9" * 20])
def test_lookup_invalid_id_is_inline_and_preserves_filter(client: TestClient, value: str) -> None:
    response = client.get("/incident-lookup", params={"incident_id": value, "status": "resolved"})
    assert response.status_code == 422
    assert 'name="status" value="resolved"' in response.text
    assert 'id="incident-id-error" role="alert"' in response.text
    assert 'aria-invalid="true"' in response.text
    assert "Informe um ID entre" in response.text and "Consulta inválida" not in response.text
    assert "location" not in response.headers


def test_lookup_canonicalizes_int64_without_float_and_returns_to_same_filter(
    client: TestClient,
) -> None:
    response = client.get(
        "/incident-lookup",
        params={"incident_id": str(2**63 - 1), "status": "firing"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/incidents/{2**63 - 1}?status=firing"
    missing = client.get(response.headers["location"])
    assert missing.status_code == 404 and "status=firing#incidente-" in missing.text


def test_lookup_reaches_active_record_beyond_the_bounded_queue(client: TestClient) -> None:
    for identity in range(1, 106):
        client.app.state.store.persist(
            Webhook.model_validate(
                {
                    "status": "firing",
                    "alerts": [
                        {
                            "status": "firing",
                            "fingerprint": f"{identity:016x}",
                            "startsAt": "2026-01-01T00:00:00Z",
                            "endsAt": "2026-01-01T00:01:00Z",
                            "labels": {"alertname": "LookupCase"},
                            "annotations": {"summary": f"Alerta {identity}"},
                        }
                    ],
                }
            )
        )
    listing = client.get("/?status=firing")
    assert 'href="/incidents/1?status=firing"' not in listing.text
    response = client.get("/incident-lookup?incident_id=1&status=firing")
    assert response.status_code == 200 and "Incidente #1" in response.text
    assert 'href="/?status=firing#incidente-1"' in response.text


def test_tool_redirect_strips_navigation_context_and_error_preserves_it(
    client: TestClient, tmp_path: Path
) -> None:
    from alert_receiver.app import create_app

    destinations = tmp_path / "urls.json"
    destinations.write_text('{"jaeger":"http://127.0.0.1:45678"}', encoding="utf-8")
    application = create_app(Settings(probe_enabled=False, public_urls_file=destinations))
    session = TestClient(application)
    path = (
        "/tools/jaeger/search?service=api-sentinel&start=123&end=456"
        "&sentinel_status=resolved&sentinel_incident=12"
    )
    response = session.get(path, follow_redirects=False)
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == "http://127.0.0.1:45678/search?service=api-sentinel&start=123&end=456"
    )
    destinations.unlink()
    response = session.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 503 and "status=resolved#incidente-12" in response.text
    assert "Tentar novamente" in response.text and "location" not in response.headers
    session.close()


def test_untrusted_error_context_never_becomes_a_return_destination(client: TestClient) -> None:
    response = client.get(
        "/tools/unknown/?sentinel_status=https://evil.test&sentinel_incident=9223372036854775808",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 404 and 'href="/">Voltar à central' in response.text
    assert "evil.test" not in response.text
