import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alert_receiver.app import create_app
from alert_receiver.config import Settings


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
    assert 'href="/">Voltar à central' in response.text
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
