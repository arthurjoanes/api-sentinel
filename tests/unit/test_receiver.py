import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alert_receiver.app import create_app
from alert_receiver.config import Settings
from alert_receiver.contracts import Webhook
from alert_receiver.storage import AlertStore

TOKEN = "receiver-test-token-with-at-least-32-characters"


def payload(status: str = "firing", starts: str = "2026-09-20T10:00:00Z") -> dict:
    return {
        "version": "4",
        "receiver": "local",
        "status": status,
        "alerts": [
            {
                "fingerprint": "1234567890abcdef",
                "status": status,
                "startsAt": starts,
                "endsAt": "2026-09-20T11:00:00Z"
                if status == "resolved"
                else "0001-01-01T00:00:00Z",
                "labels": {
                    "alertname": "SentinelUnavailable",
                    "severity": "critical",
                    "service": "api",
                },
                "annotations": {
                    "summary": "Jornada indisponível",
                    "impact": "Consulta não pode ser validada.",
                },
                "generatorURL": "http://prometheus:9090/graph",
            }
        ],
    }


@pytest.fixture
def store(tmp_path: Path) -> AlertStore:
    result = AlertStore(tmp_path / "test.sqlite3")
    result.initialize()
    return result


@pytest.fixture
def client(tmp_path: Path):
    token = tmp_path / "token"
    token.write_text(TOKEN, encoding="utf-8")
    app = create_app(
        Settings(
            database_path=tmp_path / "alerts.sqlite3", webhook_token_file=token, probe_enabled=False
        )
    )
    with TestClient(app) as test_client:
        yield test_client


def send(client: TestClient, value: dict):
    return client.post("/webhook", json=value, headers={"Authorization": f"Bearer {TOKEN}"})


@pytest.mark.parametrize("status", ["all", "firing", "resolved"])
def test_detail_and_runbook_preserve_filter_and_incident_context(client: TestClient, status: str):
    assert (
        send(client, payload("resolved" if status == "resolved" else "firing")).status_code == 200
    )
    document = client.get(f"/?status={status}").text
    assert f'href="/incidents/1?status={status}"' in document
    detail = client.get(f"/incidents/1?status={status}").text
    assert f'href="/?status={status}#incidente-1"' in detail
    assert f'href="/runbooks/telemetry?incident_id=1&amp;status={status}"' in detail
    runbook = client.get(f"/runbooks/telemetry?incident_id=1&status={status}").text
    assert f'href="/incidents/1?status={status}"' in runbook
    assert "Voltar ao incidente #1" in runbook
    assert "Voltar ao incidente" not in client.get("/runbooks/telemetry").text


@pytest.mark.parametrize(
    "path",
    [
        "/incidents/1?status=external",
        "/runbooks/erp?incident_id=0",
        "/runbooks/erp?incident_id=9223372036854775808",
        "/runbooks/erp?status=external",
    ],
)
def test_navigation_context_is_bounded_and_invalid_values_keep_html_recovery(
    client: TestClient, path: str
):
    response = client.get(path)
    assert response.status_code == 422
    assert "text/html" in response.headers["content-type"]
    assert "Voltar à central" in response.text


def test_duplicate_webhooks_share_one_incident_and_keep_history(store: AlertStore) -> None:
    event = Webhook.model_validate(payload())
    store.persist(event)
    store.persist(event)
    incidents = store.list_incidents()
    assert len(incidents) == 1
    assert incidents[0].deliveries == 2
    assert [event.transition for event in store.events(incidents[0].id)] == ["repeated", "created"]


def test_late_firing_never_reopens_resolved(store: AlertStore) -> None:
    store.persist(Webhook.model_validate(payload()))
    store.persist(Webhook.model_validate(payload("resolved")))
    store.persist(Webhook.model_validate(payload()))
    incident = store.list_incidents()[0]
    assert incident.status == "resolved"
    assert incident.ends_at is not None
    assert incident.ends_at.hour == 11
    assert store.events(incident.id)[0].transition == "late_firing_ignored"


def test_resolved_arriving_first_still_prevents_late_firing(store: AlertStore) -> None:
    store.persist(Webhook.model_validate(payload("resolved")))
    store.persist(Webhook.model_validate(payload()))
    assert store.list_incidents()[0].status == "resolved"


def test_old_resolution_does_not_close_new_occurrence(store: AlertStore) -> None:
    store.persist(Webhook.model_validate(payload()))
    store.persist(Webhook.model_validate(payload(starts="2026-09-20T10:30:00Z")))
    store.persist(Webhook.model_validate(payload("resolved")))
    assert store.counts() == {"firing": 1, "resolved": 1}
    assert store.list_incidents("firing")[0].starts_at.minute == 30


def test_operational_reconciliation_preserves_deliveries_and_records_its_origin(
    store: AlertStore,
) -> None:
    value = payload()
    value["alerts"][0]["labels"].update(alertname="SentinelReplicaLost", environment="demo")
    store.persist(Webhook.model_validate(value))
    before = store.list_incidents()[0]
    store.reconcile_replica(before.id, "Duas réplicas e probe confirmados; sem webhook resolved.")
    after = store.incident(before.id)
    assert after is not None and after.status == "resolved"
    assert after.deliveries == before.deliveries == 1
    assert after.last_received_at == before.last_received_at
    assert after.ends_at is not None
    assert after.annotations["reconciliation"].endswith("sem webhook resolved.")
    assert store.events(before.id)[0].transition == "operator_reconciled"
    assert store.events(before.id)[1].transition == "created"
    store.persist(Webhook.model_validate(value))
    assert store.incident(before.id).status == "resolved"
    assert store.events(before.id)[0].transition == "late_firing_ignored"


@pytest.mark.parametrize(
    "alertname,environment,status",
    [
        ("SentinelUnavailable", "demo", "firing"),
        ("SentinelReplicaLost", "reference", "firing"),
        ("SentinelReplicaLost", "demo", "resolved"),
    ],
)
def test_reconciliation_rejects_unrelated_or_already_resolved_incidents(
    store: AlertStore,
    alertname: str,
    environment: str,
    status: str,
) -> None:
    value = payload(status)
    value["alerts"][0]["labels"].update(alertname=alertname, environment=environment)
    store.persist(Webhook.model_validate(value))
    before = store.list_incidents()[0]
    with pytest.raises(ValueError, match="reconciliação aceita apenas"):
        store.reconcile_replica(before.id, "Observação controlada.")
    assert store.incident(before.id) == before
    assert len(store.events(before.id)) == 1


def test_equivalent_timezone_timestamps_deduplicate(store: AlertStore) -> None:
    store.persist(Webhook.model_validate(payload()))
    store.persist(Webhook.model_validate(payload(starts="2026-09-20T07:00:00-03:00")))
    assert len(store.list_incidents()) == 1


def test_concurrent_duplicate_deliveries_are_atomic(store: AlertStore) -> None:
    event = Webhook.model_validate(payload())
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(store.persist, [event] * 12))
    assert len(store.list_incidents()) == 1
    assert store.list_incidents()[0].deliveries == 12


def test_webhook_transaction_rolls_back_entire_batch_on_storage_failure(store: AlertStore) -> None:
    with store.connection() as connection:
        connection.execute(
            "CREATE TRIGGER fail_second BEFORE INSERT ON incidents "
            "WHEN NEW.fingerprint='ffffffffffffffff' "
            "BEGIN SELECT RAISE(ABORT, 'controlled test'); END"
        )
    value = payload()
    value["alerts"].append(copy.deepcopy(value["alerts"][0]))
    value["alerts"][1]["fingerprint"] = "ffffffffffffffff"
    with pytest.raises(sqlite3.IntegrityError):
        store.persist(Webhook.model_validate(value))
    assert store.list_incidents() == []


def test_authentication_is_required_before_parsing(client: TestClient) -> None:
    response = client.post("/webhook", content="not json")
    assert response.status_code == 401
    assert response.json()["code"] == "webhook_unauthorized"
    assert client.get("/api/incidents").json()["incidents"] == []


def test_webhook_rejects_ambiguous_authentication_without_persisting(client: TestClient) -> None:
    response = client.post(
        "/webhook",
        json=payload(),
        headers=[("Authorization", f"Bearer {TOKEN}"), ("Authorization", "Bearer other")],
    )
    assert response.status_code == 401
    assert client.get("/api/incidents").json()["scope"]["total"] == 0


def test_webhook_scheme_name_is_case_insensitive(client: TestClient) -> None:
    response = client.post("/webhook", json=payload(), headers={"Authorization": f"bearer {TOKEN}"})
    assert response.status_code == 200


def test_success_means_committed_record_is_already_queryable(client: TestClient) -> None:
    assert send(client, payload()).status_code == 200
    record = client.get("/api/incidents").json()["incidents"][0]
    assert record["status"] == "firing"
    assert record["deliveries"] == 1
    assert 'sentinel_alert_webhooks_total{result="persisted"} 1.0' in client.get("/metrics").text


def test_persistence_failure_returns_retryable_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_value: Webhook) -> int:
        raise sqlite3.OperationalError("disk full test")

    monkeypatch.setattr(client.app.state.store, "persist", fail)
    response = send(client, payload())
    assert response.status_code == 503
    assert response.json()["code"] == "webhook_storage"
    assert "disk full" not in response.text


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "unknown"),
        ("startsAt", "2026-09-20T10:00:00"),
        ("fingerprint", "../bad"),
        ("annotations", {}),
        ("labels", {}),
    ],
)
def test_invalid_alert_contract_is_rejected(client: TestClient, field: str, value: object) -> None:
    body = payload()
    body["alerts"][0][field] = value
    assert send(client, body).status_code == 422


def test_body_limit_counts_actual_bytes_even_if_header_lies(client: TestClient) -> None:
    response = client.post(
        "/webhook",
        content=b" " * 65_537,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Content-Length": "1",
        },
    )
    assert response.status_code == 413
    assert client.get("/api/incidents").json()["incidents"] == []


def test_content_type_and_malformed_json_are_rejected(client: TestClient) -> None:
    assert (
        client.post(
            "/webhook",
            content=json.dumps(payload()),
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/webhook",
            content=b"{bad",
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        ).status_code
        == 422
    )


def test_rendered_values_and_links_cannot_inject_markup(client: TestClient) -> None:
    body = payload()
    body["alerts"][0]["annotations"]["summary"] = '<script>alert("bad")</script>'
    body["alerts"][0]["annotations"]["runbook_url"] = "javascript:alert(1)"
    body["alerts"][0]["labels"]["service"] = '<img src=x onerror="alert(1)">'
    assert send(client, body).status_code == 200
    response = client.get("/")
    assert "<script>" not in response.text
    assert "<img src=x" not in response.text
    assert "javascript:" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_runbooks_and_occurrence_history_are_real_routes(client: TestClient) -> None:
    send(client, payload())
    assert client.get("/incidents/1").status_code == 200
    assert client.get("/api/incidents/1").json()["events"][0]["transition"] == "created"
    assert client.get("/incidents/9999").status_code == 404
    assert client.get("/runbooks/unavailable").status_code == 200
    assert client.get("/runbooks/unknown").status_code == 404
    assert client.get("/styles.css").status_code == 200


def test_runbook_catalog_links_to_every_available_procedure(client: TestClient) -> None:
    from alert_receiver.ui import RUNBOOKS

    catalog = client.get("/runbooks")
    assert catalog.status_code == 200
    for slug in RUNBOOKS:
        assert f'href="/runbooks/{slug}"' in catalog.text
        procedure = client.get(f"/runbooks/{slug}")
        assert procedure.status_code == 200
        assert 'href="/runbooks">← Todos os runbooks' in procedure.text


def test_disabled_probe_is_not_presented_as_healthy(client: TestClient) -> None:
    assert "Probe desativado" in client.get("/").text
    assert "sentinel_probe_success NaN" in client.get("/metrics").text


def test_probe_configuration_failure_is_observation_gap_not_business_outage(
    client: TestClient,
) -> None:
    client.app.state.probe.enabled = True
    client.app.state.probe.result = "configuration"
    body = client.get("/").text
    assert "Consulta indisponível" in body
    assert "Confira a configuração do probe." in body
    assert "Consulta de referência falhou" not in body
    assert "Consulta de referência aprovada" not in body
