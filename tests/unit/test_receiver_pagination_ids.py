import sqlite3
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from alert_receiver.app import create_app
from alert_receiver.config import Settings
from alert_receiver.storage import AlertStore
from tests.unit.test_receiver_retention import alert


@pytest.mark.parametrize("keep_first", [True, False])
def test_retention_never_reuses_ids_after_reopen(tmp_path: Path, keep_first: bool) -> None:
    store = AlertStore(tmp_path / "history.sqlite3")
    store.initialize()
    store.persist(alert(1, "firing" if keep_first else "resolved"))
    store.persist(alert(2))
    with store.connection() as connection:
        connection.execute(
            "UPDATE incidents SET last_activity_at=? WHERE status='resolved'",
            ((datetime.now(UTC) - timedelta(days=31)).isoformat(),),
        )
    store.prune()
    store = AlertStore(store.path)
    store.initialize()
    store.persist(alert(3))
    assert store.incident(2) is None
    assert store.incident(3).fingerprint == f"{3:016x}"
    assert store.incident(1) is not None if keep_first else store.incident(1) is None


def test_legacy_migration_preserves_events_and_sequence(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "legacy.sqlite3")
    store.initialize()
    store.persist(alert(1, "firing"))
    store.persist(alert(1, "resolved"))
    before = store.incident(1), store.events(1)
    # Rebuild a real pre-migration schema, including the child foreign key.
    with store.connection() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='incidents'"
        ).fetchone()[0]
        connection.execute(schema.replace("incidents", "legacy", 1).replace(" AUTOINCREMENT", ""))
        connection.execute("INSERT INTO legacy SELECT * FROM incidents")
        connection.execute("DROP TABLE incidents")
        connection.execute("ALTER TABLE legacy RENAME TO incidents")
    store.initialize()
    store.initialize()
    assert (store.incident(1), store.events(1)) == before
    with store.connection() as connection:
        assert list(connection.execute("PRAGMA foreign_key_check")) == []
        connection.execute("DELETE FROM incidents")
    store.persist(alert(2))
    assert store.incident(1) is None and store.incident(2) is not None


@pytest.mark.parametrize("status", [None, "firing", "resolved"])
def test_walks_every_record_once_with_tied_activity(tmp_path: Path, status: str | None) -> None:
    store = AlertStore(tmp_path / "pages.sqlite3")
    store.initialize()
    for number in range(1, 206):
        store.persist(alert(number, "firing" if number <= 105 else "resolved"))
    with store.connection() as connection:
        connection.execute(
            "UPDATE incidents SET last_activity_at=?", (datetime.now(UTC).isoformat(),)
        )
    seen = []
    cursor = None
    while True:
        page = store.page(status, cursor=cursor)
        assert page.offset == len(seen)
        seen.extend(record.id for record in page.records)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    expected = (list(range(105, 0, -1)) if status != "resolved" else []) + (
        list(range(205, 105, -1)) if status != "firing" else []
    )
    assert seen == expected
    assert len(seen) == len(set(seen))


class Links(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__()
        self.links: list[dict[str, str | None]] = []
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.links.append(dict(attrs))


def test_http_pagination_detail_return_and_invalid_cursor(tmp_path: Path) -> None:
    token = tmp_path / "token"
    token.write_text("a" * 32)
    app = create_app(
        Settings(
            database_path=tmp_path / "api.sqlite3", webhook_token_file=token, probe_enabled=False
        )
    )
    with TestClient(app) as client:
        for number in range(1, 206):
            app.state.store.persist(alert(number, "firing"))
        first = client.get("/api/incidents?status=firing").json()
        cursor = first["next_cursor"]
        second = client.get("/api/incidents", params={"status": "firing", "cursor": cursor}).json()
        third = client.get(
            "/api/incidents", params={"status": "firing", "cursor": second["next_cursor"]}
        ).json()
        assert len(first["incidents"]) == len(second["incidents"]) == 100
        assert len(third["incidents"]) == 5 and third["next_cursor"] is None
        document = client.get("/", params={"status": "firing", "cursor": cursor}).text
        links = Links(document).links
        detail = next(
            link["href"]
            for link in links
            if link.get("aria-label", "").startswith("Investigar ocorrência")
        )
        returned = Links(client.get(detail).text).links
        back = next(link["href"] for link in returned if link.get("class") == "back")
        assert parse_qs(urlsplit(back).query) == {"status": ["firing"], "cursor": [cursor]}
        assert urlsplit(back).fragment.startswith("incidente-")
        for bad in ("not-a-cursor", "[]", "a" * 1025):
            assert client.get("/", params={"cursor": bad}).status_code == 422
            assert client.get("/api/incidents", params={"cursor": bad}).status_code == 422
        assert (
            client.get(
                "/api/incidents", params={"status": "resolved", "cursor": cursor}
            ).status_code
            == 422
        )
        with app.state.store.connection() as connection:
            connection.execute("DELETE FROM incidents WHERE id=205")
        app.state.store.persist(alert(206))
        assert client.get("/incidents/205").status_code == 404
        assert client.get("/api/incidents/205").status_code == 404


def test_migration_rolls_back_on_invalid_foreign_key(tmp_path: Path) -> None:
    store = AlertStore(tmp_path / "invalid.sqlite3")
    store.initialize()
    with store.connection() as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            "INSERT INTO delivery_events VALUES (1, 99, '2026-01-01', 'firing', 'created')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.initialize()
