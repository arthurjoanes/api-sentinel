import base64
import binascii
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alert_receiver.contracts import Incident, IncidentEvent, IncidentPage, Webhook


class AlertStore:
    """Chamadas são síncronas; a aplicação sempre as executa em uma thread."""

    def __init__(self, path: Path, retention_days: int = 30) -> None:
        self.path = path
        if not 1 <= retention_days <= 365:
            raise ValueError("A retenção deve estar entre 1 e 365 dias.")
        self.retention_days = retention_days

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('firing', 'resolved')),
                    ends_at TEXT,
                    first_received_at TEXT NOT NULL,
                    last_received_at TEXT NOT NULL,
                    last_activity_at TEXT,
                    deliveries INTEGER NOT NULL DEFAULT 1,
                    labels TEXT NOT NULL,
                    annotations TEXT NOT NULL,
                    UNIQUE(fingerprint, starts_at)
                );
                CREATE TABLE IF NOT EXISTS delivery_events (
                    id INTEGER PRIMARY KEY,
                    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
                    received_at TEXT NOT NULL,
                    delivered_status TEXT NOT NULL,
                    transition TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS incidents_latest ON incidents(last_received_at DESC);
                CREATE INDEX IF NOT EXISTS events_incident ON delivery_events(incident_id, id DESC);
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(incidents)")}
            if "last_activity_at" not in columns:
                connection.execute("ALTER TABLE incidents ADD COLUMN last_activity_at TEXT")
            # Reconciliação não muda o horário de entrega do webhook.
            connection.execute(
                "UPDATE incidents SET last_activity_at=MAX(last_received_at, "
                "COALESCE((SELECT MAX(received_at) FROM delivery_events "
                "WHERE incident_id=incidents.id), last_received_at)) "
                "WHERE last_activity_at IS NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS incidents_activity ON incidents(last_activity_at DESC)"
            )
        self._migrate_incident_ids()

    def _migrate_incident_ids(self) -> None:
        # Rebuild only the legacy parent table. Foreign keys must be disabled before
        # BEGIN, otherwise dropping the parent would cascade into delivery_events.
        with self.connection() as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("BEGIN IMMEDIATE")
            schema = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='incidents'"
            ).fetchone()[0]
            if "AUTOINCREMENT" not in schema.upper():
                connection.execute(
                    schema.replace("incidents", "incidents_migrating", 1).replace(
                        "INTEGER PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT", 1
                    )
                )
                connection.execute("INSERT INTO incidents_migrating SELECT * FROM incidents")
                connection.execute("DROP TABLE incidents")
                connection.execute("ALTER TABLE incidents_migrating RENAME TO incidents")
                connection.execute(
                    "CREATE INDEX incidents_latest ON incidents(last_received_at DESC)"
                )
                connection.execute(
                    "CREATE INDEX incidents_activity ON incidents(last_activity_at DESC)"
                )
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise sqlite3.IntegrityError("Histórico com referências de ocorrência inválidas.")

    def persist(self, webhook: Webhook) -> int:
        received_at = datetime.now(UTC).isoformat(timespec="microseconds")
        with self.connection() as connection:
            # Impede corrida read/insert entre entregas simultâneas da mesma ocorrência.
            connection.execute("BEGIN IMMEDIATE")
            for alert in webhook.alerts:
                existing = connection.execute(
                    "SELECT id, status FROM incidents WHERE fingerprint=? AND starts_at=?",
                    (alert.fingerprint.lower(), alert.start_key),
                ).fetchone()
                ends_at = (
                    alert.endsAt.astimezone(UTC).isoformat() if alert.status == "resolved" else None
                )
                labels = json.dumps(alert.labels, ensure_ascii=False)
                annotations = json.dumps(alert.annotations, ensure_ascii=False)
                if existing is None:
                    cursor = connection.execute(
                        "INSERT INTO incidents (fingerprint, starts_at, status, ends_at, "
                        "first_received_at, last_received_at, last_activity_at, "
                        "labels, annotations) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            alert.fingerprint.lower(),
                            alert.start_key,
                            alert.status,
                            ends_at,
                            received_at,
                            received_at,
                            received_at,
                            labels,
                            annotations,
                        ),
                    )
                    incident_id = cursor.lastrowid
                    transition = "created"
                else:
                    incident_id = existing["id"]
                    late_firing = existing["status"] == "resolved" and alert.status == "firing"
                    transition = (
                        "late_firing_ignored"
                        if late_firing
                        else ("recovered" if existing["status"] != alert.status else "repeated")
                    )
                    if late_firing:
                        connection.execute(
                            "UPDATE incidents SET last_received_at=?, last_activity_at=?, "
                            "deliveries=deliveries+1 WHERE id=?",
                            (received_at, received_at, incident_id),
                        )
                    else:
                        connection.execute(
                            "UPDATE incidents SET status=?, ends_at=?, last_received_at=?, "
                            "last_activity_at=?, "
                            "deliveries=deliveries+1, labels=?, annotations=? WHERE id=?",
                            (
                                alert.status,
                                ends_at,
                                received_at,
                                received_at,
                                labels,
                                annotations,
                                incident_id,
                            ),
                        )
                connection.execute(
                    "INSERT INTO delivery_events "
                    "(incident_id, received_at, delivered_status, transition) VALUES (?,?,?,?)",
                    (incident_id, received_at, alert.status, transition),
                )
        return len(webhook.alerts)

    @staticmethod
    def _incident(row: sqlite3.Row) -> Incident:
        values = dict(row)
        values["labels"] = json.loads(values["labels"])
        values["annotations"] = json.loads(values["annotations"])
        return Incident.model_validate(values)

    def list_incidents(self, status: str | None = None, limit: int = 100) -> list[Incident]:
        return self.page(status, limit).records

    def page(
        self,
        status: str | None = None,
        limit: int = 100,
        *,
        now: datetime | None = None,
        cursor: str | None = None,
        activity_days: int = 7,
    ) -> IncidentPage:
        if status not in (None, "firing", "resolved") or not 1 <= limit <= 200:
            raise ValueError("Filtro ou limite de ocorrências inválido.")
        if type(activity_days) is not int or activity_days not in (1, 7, 30):
            raise ValueError("Janela de atividade inválida.")
        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise ValueError("O instante da consulta deve informar o fuso.")
        observed_at = observed_at.astimezone(UTC)
        cutoff = observed_at - timedelta(days=self.retention_days)
        activity_start = (observed_at - timedelta(days=activity_days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        after: tuple[int, str, int] | None = None
        offset = 0
        if cursor is not None:
            cursor_cutoff, after, offset = self.decode_cursor(cursor, status)
            cutoff = max(cutoff, cursor_cutoff)
        # Mesmo recorte lógico antes da limpeza física; uma entrega concorrente não
        # pode atualizar o contador no meio da leitura da página.
        with self.connection() as connection:
            connection.execute("BEGIN")
            condition = ""
            arguments: list[object] = [cutoff.isoformat(timespec="microseconds"), status, status]
            if after is not None:
                condition = (
                    "AND (CASE status WHEN 'firing' THEN 1 ELSE 0 END, last_activity_at, id) "
                    "< (?, ?, ?) "
                )
                arguments.extend(after)
            arguments.append(limit + 1)
            rows = connection.execute(
                "SELECT * FROM incidents WHERE (status='firing' OR last_activity_at>=?) "
                "AND (? IS NULL OR status=?) "
                + condition
                + "ORDER BY CASE status WHEN 'firing' THEN 0 ELSE 1 END, "
                "last_activity_at DESC, id DESC LIMIT ?",
                arguments,
            ).fetchall()
            counts = connection.execute(
                "SELECT status, COUNT(*) AS total FROM incidents "
                "WHERE status='firing' OR last_activity_at>=? GROUP BY status",
                (cutoff.isoformat(timespec="microseconds"),),
            ).fetchall()
            activity = connection.execute(
                "SELECT date(starts_at) AS day, COUNT(*) AS total FROM incidents "
                "WHERE (status='firing' OR last_activity_at>=?) "
                "AND (? IS NULL OR status=?) AND starts_at>=? AND starts_at<=? "
                "GROUP BY date(starts_at) ORDER BY day",
                (
                    cutoff.isoformat(timespec="microseconds"),
                    status,
                    status,
                    activity_start.isoformat(timespec="microseconds"),
                    observed_at.isoformat(timespec="microseconds"),
                ),
            ).fetchall()
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            payload = [
                1,
                status,
                self.retention_days,
                cutoff.isoformat(),
                [int(last["status"] == "firing"), last["last_activity_at"], last["id"]],
                offset + len(rows),
            ]
            next_cursor = (
                base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("ascii"))
                .decode("ascii")
                .rstrip("=")
            )
        return IncidentPage(
            records=[self._incident(row) for row in rows],
            counts={"firing": 0, "resolved": 0} | {row["status"]: row["total"] for row in counts},
            generated_at=observed_at,
            cutoff_at=cutoff,
            retention_days=self.retention_days,
            limit=limit,
            cursor=cursor,
            next_cursor=next_cursor,
            offset=offset,
            activity_counts={row["day"]: row["total"] for row in activity},
            activity_days=activity_days,
        )

    def decode_cursor(
        self, cursor: str, status: str | None
    ) -> tuple[datetime, tuple[int, str, int], int]:
        try:
            if not 1 <= len(cursor) <= 1024:
                raise ValueError
            value = json.loads(
                base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            )
            version, selected, retention, cutoff, after, offset = value
            if version != 1 or selected != status or retention != self.retention_days:
                raise ValueError
            boundary = datetime.fromisoformat(cutoff)
            rank, activity, identity = after
            activity_time = datetime.fromisoformat(activity)
            if (
                boundary.tzinfo is None
                or activity_time.tzinfo is None
                or type(rank) is not int
                or rank not in (0, 1)
                or type(identity) is not int
                or not 1 <= identity <= 2**63 - 1
                or type(offset) is not int
                or not 0 <= offset <= 2**63 - 1
            ):
                raise ValueError
            return boundary.astimezone(UTC), (rank, activity, identity), offset
        except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
            raise ValueError("Página inválida. Volte à primeira página da fila.") from exc

    def incident(self, incident_id: int) -> Incident | None:
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat(
            timespec="microseconds"
        )
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM incidents WHERE id=? AND (status='firing' OR last_activity_at>=?)",
                (incident_id, cutoff),
            ).fetchone()
        return self._incident(row) if row else None

    def events(self, incident_id: int) -> list[IncidentEvent]:
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat(
            timespec="microseconds"
        )
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT received_at, delivered_status, transition FROM delivery_events "
                "WHERE incident_id=? AND received_at>=? ORDER BY id DESC LIMIT 100",
                (incident_id, cutoff),
            ).fetchall()
        return [IncidentEvent.model_validate(dict(row)) for row in rows]

    def incident_snapshot(
        self, incident_id: int, *, now: datetime | None = None
    ) -> tuple[Incident | None, list[IncidentEvent], datetime]:
        """Read the occurrence and its retained events from one SQLite snapshot."""
        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None or not 1 <= incident_id <= 2**63 - 1:
            raise ValueError("A ocorrência e o instante da leitura devem ser válidos.")
        observed_at = observed_at.astimezone(UTC)
        cutoff = (observed_at - timedelta(days=self.retention_days)).isoformat(
            timespec="microseconds"
        )
        with self.connection() as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                "SELECT * FROM incidents WHERE id=? AND (status='firing' OR last_activity_at>=?)",
                (incident_id, cutoff),
            ).fetchone()
            events = (
                connection.execute(
                    "SELECT received_at, delivered_status, transition FROM delivery_events "
                    "WHERE incident_id=? AND received_at>=? ORDER BY id DESC LIMIT 100",
                    (incident_id, cutoff),
                ).fetchall()
                if row is not None
                else []
            )
        return (
            self._incident(row) if row is not None else None,
            [IncidentEvent.model_validate(dict(event)) for event in events],
            observed_at,
        )

    def counts(self) -> dict[str, int]:
        return self.page(limit=1).counts

    def reconcile_replica(self, incident_id: int, observation: str) -> None:
        """Encerra após checagem externa, sem criar entrega de webhook."""
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        if not 1 <= len(observation) <= 1_000:
            raise ValueError("A observação deve ter de 1 a 1000 caracteres.")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM incidents WHERE id=?", (incident_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Ocorrência inexistente.")
            labels = json.loads(row["labels"])
            if (
                row["status"] != "firing"
                or labels.get("alertname") != "SentinelReplicaLost"
                or labels.get("environment") != "demo"
            ):
                raise ValueError("A reconciliação aceita apenas perda de réplica ativa da demo.")
            annotations = json.loads(row["annotations"])
            annotations["reconciliation"] = observation
            connection.execute(
                "UPDATE incidents SET status='resolved', ends_at=?, last_activity_at=?, "
                "annotations=? WHERE id=?",
                (now, now, json.dumps(annotations, ensure_ascii=False), incident_id),
            )
            connection.execute(
                "INSERT INTO delivery_events "
                "(incident_id, received_at, delivered_status, transition) VALUES (?,?,?,?)",
                (incident_id, now, "resolved", "operator_reconciled"),
            )

    def prune(self) -> None:
        cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat(
            timespec="microseconds"
        )
        with self.connection() as connection:
            # Preserva incidentes ativos e limita histórico de entregas independentemente.
            connection.execute(
                "DELETE FROM incidents WHERE status='resolved' AND last_activity_at<?", (cutoff,)
            )
            connection.execute("DELETE FROM delivery_events WHERE received_at<?", (cutoff,))
            connection.execute(
                "DELETE FROM delivery_events WHERE id NOT IN "
                "(SELECT id FROM delivery_events ORDER BY id DESC LIMIT 10000)"
            )
