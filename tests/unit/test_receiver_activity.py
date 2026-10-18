import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from alert_receiver.app import create_app
from alert_receiver.config import Settings
from alert_receiver.contracts import Webhook
from alert_receiver.storage import AlertStore
from tests.unit.test_receiver_pagination_ids import Links

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def event(number: int, starts: datetime, status: str = "firing") -> Webhook:
    return Webhook.model_validate(
        {
            "status": status,
            "alerts": [
                {
                    "fingerprint": f"{number:016x}",
                    "status": status,
                    "startsAt": starts.isoformat(),
                    "endsAt": (starts + timedelta(minutes=1)).isoformat()
                    if status == "resolved"
                    else "0001-01-01T00:00:00Z",
                    "labels": {"alertname": "SentinelERP"},
                    "annotations": {"summary": "ERP"},
                }
            ],
        }
    )


def test_activity_counts_all_retained_incidents_independently_of_page_limit(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    for number in range(4):
        store.persist(event(number, NOW - timedelta(hours=number)))
    page = store.page(limit=1, now=NOW, activity_days=7)
    assert len(page.records) == 1
    assert page.activity_counts == {"2026-10-12": 4}
    assert page.activity_days == 7
    assert store.page(now=NOW, cursor=page.next_cursor).activity_counts == page.activity_counts


def test_activity_uses_inclusive_utc_days_and_excludes_future_starts(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    for number, starts in enumerate(
        [
            NOW.replace(hour=0) - timedelta(microseconds=1),
            NOW.replace(hour=0),
            NOW,
            NOW + timedelta(microseconds=1),
            datetime.fromisoformat("2026-10-13T00:30:00+14:00"),
        ]
    ):
        store.persist(event(number, starts))
    assert store.page(now=NOW, activity_days=1).activity_counts == {"2026-10-12": 3}
    assert store.page(now=NOW, activity_days=7).activity_counts == {
        "2026-10-11": 1,
        "2026-10-12": 3,
    }


def test_activity_uses_status_filter_and_retention_but_totals_keep_both_states(
    tmp_path: Path,
) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3", retention_days=7)
    store.initialize()
    store.persist(event(1, NOW - timedelta(days=2)))
    store.persist(event(2, NOW - timedelta(days=2), "resolved"))
    store.persist(event(3, NOW - timedelta(days=2), "resolved"))
    with store.connection() as connection:
        connection.execute(
            "UPDATE incidents SET last_activity_at=? WHERE fingerprint=?",
            ((NOW - timedelta(days=8)).isoformat(), f"{3:016x}"),
        )
    page = store.page("resolved", now=NOW, activity_days=30)
    assert page.activity_counts == {"2026-10-10": 1}
    assert page.counts == {"firing": 1, "resolved": 1}


@pytest.mark.parametrize("days", [0, 2, 31, True, "7"])
def test_activity_rejects_unsupported_windows(tmp_path: Path, days: object) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    with pytest.raises(ValueError):
        store.page(activity_days=days)  # type: ignore[arg-type]


def test_activity_and_list_share_one_read_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = AlertStore(tmp_path / "alerts.sqlite3")
    store.initialize()
    store.persist(event(1, NOW))
    writer = AlertStore(store.path)
    original = store.connection
    delivered = False

    @contextmanager
    def interleave():
        with original() as connection:

            class ConcurrentConnection:
                def execute(self, sql, *arguments):
                    nonlocal delivered
                    if sql.startswith("SELECT date(starts_at)") and not delivered:
                        writer.persist(event(2, NOW))
                        delivered = True
                    return connection.execute(sql, *arguments)

            yield ConcurrentConnection()

    monkeypatch.setattr(store, "connection", interleave)
    page = store.page(now=NOW)
    assert delivered and len(page.records) == 1 and page.counts["firing"] == 1
    assert page.activity_counts == {"2026-10-12": 1}
    assert store.page(now=NOW).activity_counts == {"2026-10-12": 2}


def test_http_activity_window_survives_filter_detail_runbook_and_lookup(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("a" * 32)
    app = create_app(
        Settings(
            database_path=tmp_path / "history.sqlite3",
            webhook_token_file=token,
            probe_enabled=False,
            runbooks_path=Path(__file__).resolve().parents[2] / "docs/runbooks",
            public_urls_file=tmp_path / "tools.json",
        )
    )
    with TestClient(app) as client:
        app.state.store.persist(event(1, datetime.now(UTC) - timedelta(hours=1)))
        document = client.get("/?status=firing&days=30").text
        links = Links(document).links
        detail = next(
            link["href"]
            for link in links
            if link.get("aria-label", "").startswith("Investigar ocorrência")
        )
        assert parse_qs(urlsplit(detail).query) == {"status": ["firing"], "days": ["30"]}
        assert 'value="30" selected' in document
        for link in links:
            if link.get("class", "").startswith("filter"):
                assert parse_qs(urlsplit(link["href"]).query)["days"] == ["30"]
        detail_links = Links(client.get(detail).text).links
        back = next(link["href"] for link in detail_links if link.get("class") == "back")
        assert parse_qs(urlsplit(back).query)["days"] == ["30"]
        refresh = next(
            link["href"]
            for link in detail_links
            if link.get("class") == "text-link" and link["href"].startswith("/incidents/")
        )
        assert parse_qs(urlsplit(refresh).query)["days"] == ["30"]
        runbook = next(
            link["href"]
            for link in detail_links
            if link.get("href", "").startswith("/runbooks/") and "incident_id=" in link["href"]
        )
        runbook_links = Links(client.get(runbook).text).links
        central = next(link["href"] for link in runbook_links if link.get("class") == "text-link")
        assert parse_qs(urlsplit(central).query)["days"] == ["30"]
        looked_up = client.get(
            "/incident-lookup?incident_id=1&status=firing&days=30", follow_redirects=False
        )
        assert parse_qs(urlsplit(looked_up.headers["location"]).query)["days"] == ["30"]
        for invalid in ("0", "2", "31", "7.0", "<script>"):
            assert client.get("/", params={"days": invalid}).status_code == 422
        metrics = next(
            link["href"]
            for link in links
            if link.get("href", "").startswith("/tools/grafana/") and "from=" in link["href"]
        )
        failure = client.get(metrics, headers={"accept": "text/html"})
        assert failure.status_code == 503
        failed_back = next(
            link["href"]
            for link in Links(failure.text).links
            if link.get("class") == "button secondary"
        )
        assert parse_qs(urlsplit(failed_back).query) == {"status": ["firing"], "days": ["30"]}
        (tmp_path / "tools.json").write_text(json.dumps({"grafana": "http://localhost:3104"}))
        redirected = client.get(metrics, follow_redirects=False)
        assert redirected.status_code == 307
        assert set(parse_qs(urlsplit(redirected.headers["location"]).query)) == {"from", "to"}


def test_metrics_link_uses_the_exact_utc_window() -> None:
    from alert_receiver.contracts import IncidentPage
    from alert_receiver.ui import activity_metrics

    snapshot = IncidentPage(
        [],
        {"firing": 0, "resolved": 0},
        NOW,
        NOW - timedelta(days=30),
        30,
        100,
        activity_counts={},
        activity_days=7,
    )
    href = Links(activity_metrics(snapshot)).links[0]["href"]
    query = parse_qs(urlsplit(href).query)
    assert query == {
        "from": [str(int(datetime(2026, 10, 6, tzinfo=UTC).timestamp() * 1000))],
        "to": [str(int(NOW.timestamp() * 1000))],
    }
