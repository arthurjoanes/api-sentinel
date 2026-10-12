from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alert_receiver.contracts import Webhook
from alert_receiver.storage import AlertStore


def delivery(status: str) -> Webhook:
    return Webhook.model_validate(
        {
            "status": status,
            "alerts": [
                {
                    "status": status,
                    "fingerprint": "abcdef0123456789",
                    "startsAt": "2026-01-01T00:00:00Z",
                    "endsAt": "2026-01-01T00:01:00Z",
                    "labels": {"alertname": "SnapshotCase"},
                    "annotations": {"summary": "Snapshot"},
                }
            ],
        }
    )


def test_detail_and_events_share_snapshot_during_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    store.persist(delivery("firing"))
    writer = AlertStore(store.path)
    original = store.connection
    delivered = False

    @contextmanager
    def interleave():
        with original() as connection:

            class ConcurrentConnection:
                def execute(self, sql, *arguments):
                    nonlocal delivered
                    if sql.startswith("SELECT received_at") and not delivered:
                        writer.persist(delivery("resolved"))
                        delivered = True
                    return connection.execute(sql, *arguments)

            yield ConcurrentConnection()

    monkeypatch.setattr(store, "connection", interleave)
    incident, events, generated = store.incident_snapshot(1)
    assert delivered and incident is not None and generated.tzinfo is UTC
    assert incident.status == "firing" and incident.deliveries == 1
    assert [event.transition for event in events] == ["created"]
    current, events, _ = store.incident_snapshot(1)
    assert current is not None and current.status == "resolved" and current.deliveries == 2
    assert [event.transition for event in events] == ["recovered", "created"]


def test_snapshot_uses_one_retention_boundary_and_excludes_missing_record(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3", retention_days=7)
    store.initialize()
    store.persist(delivery("resolved"))
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=7)
    with store.connection() as connection:
        connection.execute("UPDATE incidents SET last_activity_at=?", (cutoff.isoformat(),))
        connection.execute("UPDATE delivery_events SET received_at=?", (cutoff.isoformat(),))
    record, events, generated = store.incident_snapshot(1, now=now)
    assert record is not None and len(events) == 1 and generated == now
    record, events, _ = store.incident_snapshot(1, now=now + timedelta(microseconds=1))
    assert record is None and events == []
    assert store.incident_snapshot(999, now=now) == (None, [], now)
