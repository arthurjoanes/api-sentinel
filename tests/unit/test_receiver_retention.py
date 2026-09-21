from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alert_receiver.app import create_app
from alert_receiver.config import Settings
from alert_receiver.contracts import Webhook
from alert_receiver.storage import AlertStore


def alert(number: int, status: str = "resolved") -> Webhook:
    return Webhook.model_validate(
        {
            "status": status,
            "alerts": [
                {
                    "status": status,
                    "fingerprint": f"{number:016x}",
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": "2026-01-01T00:01:00Z",
                    "labels": {"alertname": "RetentionCase"},
                    "annotations": {"summary": "Exemplo de retenção"},
                }
            ],
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> AlertStore:
    store = AlertStore(tmp_path / "history.sqlite3", retention_days=7)
    store.initialize()
    return store


def test_logical_window_has_exact_boundary_and_preserves_old_active_alerts(
    store: AlertStore,
) -> None:
    now = datetime(2026, 9, 21, 12, tzinfo=UTC)
    cutoff = now - timedelta(days=7)
    for number, status, received in (
        (1, "resolved", cutoff - timedelta(microseconds=1)),
        (2, "resolved", cutoff),
        (3, "resolved", now),
        (4, "firing", cutoff - timedelta(days=90)),
    ):
        store.persist(alert(number, status))
        with store.connection() as connection:
            connection.execute(
                "UPDATE incidents SET last_received_at=?, last_activity_at=? WHERE fingerprint=?",
                (
                    received.isoformat(timespec="microseconds"),
                    received.isoformat(timespec="microseconds"),
                    f"{number:016x}",
                ),
            )
    page = store.page(now=now)
    assert page.counts == {"firing": 1, "resolved": 2}
    assert [record.fingerprint for record in page.records] == [f"{n:016x}" for n in (4, 3, 2)]
    assert page.cutoff_at == cutoff and page.generated_at == now
    assert page.retention_days == 7
    # A filtragem não depende de a manutenção já ter removido os registros físicos.
    with store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 4


def test_count_includes_records_beyond_first_page_and_has_deterministic_order(
    store: AlertStore,
) -> None:
    for number in range(1, 106):
        store.persist(alert(number, "firing" if number > 103 else "resolved"))
    with store.connection() as connection:
        connection.execute(
            "UPDATE incidents SET last_activity_at=?",
            (datetime.now(UTC).isoformat(timespec="microseconds"),),
        )
    page = store.page("resolved")
    assert len(page.records) == page.limit == 100
    assert page.counts == {"firing": 2, "resolved": 103} and page.total == 105
    assert all(record.status == "resolved" for record in page.records)
    assert len({record.id for record in page.records}) == 100
    assert [record.id for record in page.records] == list(range(103, 3, -1))
    assert page.records == store.page("resolved").records


def test_list_and_counts_share_snapshot_during_concurrent_delivery(
    store: AlertStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.persist(alert(1))
    original_connection = store.connection
    writer = AlertStore(store.path, retention_days=7)
    delivered = False

    @contextmanager
    def deliver_between_reads():
        with original_connection() as connection:

            class InterleavedConnection:
                def execute(self, sql, *args):
                    nonlocal delivered
                    if sql.startswith("SELECT status, COUNT") and not delivered:
                        delivered = True
                        writer.persist(alert(2))
                    return connection.execute(sql, *args)

            yield InterleavedConnection()

    monkeypatch.setattr(store, "connection", deliver_between_reads)
    page = store.page()
    assert delivered
    assert len(page.records) == page.total == 1
    assert store.page().total == 2


def test_expired_resolved_detail_and_events_are_not_visible_before_pruning(
    store: AlertStore,
) -> None:
    store.persist(alert(1))
    expired = (datetime.now(UTC) - timedelta(days=8)).isoformat(timespec="microseconds")
    with store.connection() as connection:
        connection.execute(
            "UPDATE incidents SET last_received_at=?, last_activity_at=?", (expired, expired)
        )
        connection.execute("UPDATE delivery_events SET received_at=?", (expired,))
    assert store.page().total == 0
    assert store.incident(1) is None and store.events(1) == []
    store.prune()
    with store.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0


def test_old_active_reconciliation_keeps_new_audit_and_original_delivery(store: AlertStore) -> None:
    payload = alert(1, "firing")
    payload.alerts[0].labels.update(alertname="SentinelReplicaLost", environment="demo")
    store.persist(payload)
    old = (datetime.now(UTC) - timedelta(days=90)).isoformat(timespec="microseconds")
    with store.connection() as connection:
        connection.execute(
            "UPDATE incidents SET last_received_at=?, last_activity_at=?", (old, old)
        )
        connection.execute("UPDATE delivery_events SET received_at=?", (old,))
    store.reconcile_replica(
        1, "Réplicas/probe recuperados; encerramento administrativo confirmado."
    )
    store.prune()
    incident = store.incident(1)
    assert incident is not None and incident.status == "resolved"
    assert incident.last_received_at == datetime.fromisoformat(old)
    assert incident.deliveries == 1
    assert [event.transition for event in store.events(1)] == ["operator_reconciled"]
    assert store.page().counts == {"firing": 0, "resolved": 1}


def test_additive_migration_reconstructs_activity_without_changing_delivery(
    store: AlertStore,
) -> None:
    payload = alert(1, "firing")
    payload.alerts[0].labels.update(alertname="SentinelReplicaLost", environment="demo")
    store.persist(payload)
    store.reconcile_replica(1, "Recuperação confirmada antes desta migração.")
    before = store.incident(1)
    events = store.events(1)
    # Reproduz o layout anterior: coluna nova ausente, histórico original preservado.
    with store.connection() as connection:
        connection.execute("DROP INDEX incidents_activity")
        connection.execute("ALTER TABLE incidents DROP COLUMN last_activity_at")
    store.initialize()
    store.initialize()
    assert store.incident(1) == before
    assert store.events(1) == events
    with store.connection() as connection:
        activity = connection.execute(
            "SELECT last_activity_at FROM incidents WHERE id=1"
        ).fetchone()[0]
    assert datetime.fromisoformat(activity) == events[0].received_at


@pytest.mark.parametrize("status,limit", [("unknown", 100), (None, 0), (None, -1), (None, 201)])
def test_internal_page_bounds_reject_unbounded_sql_limit(store, status, limit) -> None:
    with pytest.raises(ValueError):
        store.page(status, limit)


def test_api_reports_actual_window_total_and_displayed_count(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("a" * 32)
    app = create_app(
        Settings(
            database_path=tmp_path / "api.sqlite3",
            webhook_token_file=token,
            probe_enabled=False,
            retention_days=7,
        )
    )
    with TestClient(app) as client:
        for number in range(1, 103):
            app.state.store.persist(alert(number, "firing"))
        response = client.get("/api/incidents?status=firing")
        assert response.status_code == 200
        body = response.json()
        assert len(body["incidents"]) == body["scope"]["shown"] == 100
        assert body["scope"]["total"] == body["scope"]["filtered_total"] == 102
        assert body["counts"] == {"firing": 102, "resolved": 0}
        scope = body["scope"]
        assert datetime.fromisoformat(scope["generated_at"]) - datetime.fromisoformat(
            scope["cutoff_at"]
        ) == timedelta(days=scope["retention_days"])
