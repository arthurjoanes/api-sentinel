import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.engine import RowMapping, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

from api_sentinel.admission import Admission
from api_sentinel.db import Database
from api_sentinel.telemetry import RequestMiddleware


@dataclass
class CancellationLab:
    db: Database
    observer: AsyncConnection
    kind: str


@pytest.fixture(params=["data", "auth"])
async def cancellation_lab(request: pytest.FixtureRequest) -> AsyncIterator[CancellationLab]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requer TEST_DATABASE_URL e PostgreSQL de testes isolado.")
    if make_url(url).database != "sentinel_test":
        raise RuntimeError("Este teste só aceita o banco isolado sentinel_test.")
    db = Database(url)
    observer_engine = create_async_engine(
        url,
        pool_size=1,
        max_overflow=0,
        isolation_level="AUTOCOMMIT",
        connect_args={"server_settings": {"application_name": "sentinel-cancel-observer"}},
    )
    try:
        # Handshake fora da medição: o teste mede cancelamento do SQL, não conexão inicial.
        async with db.connection(request.param) as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
            assert await connection.scalar(text("SHOW statement_timeout")) == "800ms"
        async with observer_engine.connect() as observer:
            await observer.execute(text("SELECT 1"))
            yield CancellationLab(db, observer, request.param)
    finally:
        await db.close()
        await observer_engine.dispose()


async def backend_activity(observer: AsyncConnection, pid: int) -> RowMapping | None:
    # AUTOCOMMIT evita reutilizar um snapshot de pg_stat_activity entre verificações.
    return (
        (
            await observer.execute(
                text("""
                SELECT state, query, wait_event
                FROM pg_stat_activity WHERE pid = :pid
            """),
                {"pid": pid},
            )
        )
        .mappings()
        .one_or_none()
    )


async def wait_for_sleep(observer: AsyncConnection, pid: int) -> None:
    async with asyncio.timeout(0.3):
        while True:
            activity = await backend_activity(observer, pid)
            if activity is not None and (
                activity["state"] == "active"
                and "pg_sleep" in activity["query"]
                and activity["wait_event"] == "PgSleep"
            ):
                return
            await asyncio.sleep(0.002)


def unused_endpoint() -> None:
    pass


@pytest.mark.parametrize("trigger", ["disconnect", "deadline"])
async def test_cancel_active_sql_and_reuse_pool(
    cancellation_lab: CancellationLab,
    trigger: str,
    record_testsuite_property: Callable[[str, object], None],
) -> None:
    db, observer, kind = cancellation_lab.db, cancellation_lab.observer, cancellation_lab.kind
    loop = asyncio.get_running_loop()
    entry, business = Admission(48, "entry"), Admission(1, "tenant")
    request_events: asyncio.Queue[Message] = asyncio.Queue()
    request_events.put_nowait({"type": "http.request", "body": b"", "more_body": False})
    sent: list[Message] = []
    acquired, cancelled, finalized = asyncio.Event(), asyncio.Event(), asyncio.Event()
    pid = 0
    sql_started_at = 0.0
    cancellation_observed_at = 0.0
    sql_completed = False

    async def receive() -> Message:
        return await request_events.get()

    async def send(message: Message) -> None:
        sent.append(message)

    async def application(scope: Scope, downstream_receive: Receive, downstream_send: Send) -> None:
        nonlocal pid, sql_started_at, cancellation_observed_at, sql_completed
        try:
            with business.enter():
                async with db.connection(kind) as connection:
                    pid = int(await connection.scalar(text("SELECT pg_backend_pid()")))
                    sql_started_at = loop.time()
                    acquired.set()
                    try:
                        await connection.execute(
                            text("SELECT pg_sleep(:duration)"), {"duration": 0.6}
                        )
                        sql_completed = True
                    except asyncio.CancelledError:
                        cancellation_observed_at = loop.time()
                        cancelled.set()
                        raise
            await JSONResponse({"completed": True})(scope, downstream_receive, downstream_send)
        finally:
            finalized.set()

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/stores/1/summary",
        "raw_path": b"/v1/stores/1/summary",
        "query_string": b"",
        "headers": [],
        "server": ("test", 80),
        "client": ("test-client", 12345),
        "root_path": "",
        "app": SimpleNamespace(
            state=SimpleNamespace(entry=entry),
            routes=[
                Route("/v1/stores/{store_id}/summary", unused_endpoint, methods=["GET"]),
            ],
        ),
    }
    deadline = 0.1 if trigger == "deadline" else 2.0
    middleware = RequestMiddleware(application, deadline_seconds=deadline)
    request_started_at = loop.time()
    task = asyncio.create_task(middleware(scope, receive, send))
    try:
        await asyncio.wait_for(acquired.wait(), timeout=0.4)
        await wait_for_sleep(observer, pid)
        assert not task.done(), "A consulta deve estar ativa quando o cancelamento for provocado."
        if trigger == "disconnect":
            trigger_at = loop.time()
            request_events.put_nowait({"type": "http.disconnect"})
        else:
            # Referência conservadora: inclui a preparação anterior ao timeout do middleware.
            trigger_at = request_started_at + deadline
        await asyncio.wait_for(task, timeout=0.5)
        completed_at = loop.time()
        cleanup_seconds = max(0.0, completed_at - trigger_at)
        sql_lifetime_seconds = completed_at - sql_started_at
        assert cancelled.is_set() and finalized.is_set()
        assert not sql_completed
        assert cleanup_seconds < 0.35
        # O SQL duraria 600 ms; o statement_timeout configurado é 800 ms.
        assert sql_lifetime_seconds < 0.5
        engine = db.auth_engine if kind == "auth" else db.engine
        pool = cast(AsyncAdaptedQueuePool, engine.sync_engine.pool)
        assert pool.checkedout() == 0
        assert entry.active == business.active == 0

        async with asyncio.timeout(0.2):
            while True:
                activity = await backend_activity(observer, pid)
                if activity is None or activity["state"] != "active":
                    break
                await asyncio.sleep(0.002)
        assert activity is None or activity["state"] != "active"
        async with db.connection(kind) as connection:
            assert await connection.scalar(text("SELECT 42")) == 42
            replacement_pid = int(await connection.scalar(text("SELECT pg_backend_pid()")))
        assert pool.checkedout() == 0
        assert not [
            candidate
            for candidate in asyncio.all_tasks()
            if candidate.get_name().startswith("sentinel-")
        ]
        if trigger == "disconnect":
            assert sent == []
        else:
            assert [message["type"] for message in sent] == [
                "http.response.start",
                "http.response.body",
            ]
            assert sent[0]["status"] == 503
            assert json.loads(sent[1]["body"])["code"] == "request_deadline_exceeded"

        measurements: dict[str, object] = {
            "pool": kind,
            "trigger": trigger,
            "backend_pid": pid,
            "replacement_pid": replacement_pid,
            "query_was_active": True,
            "sql_duration_requested_seconds": 0.6,
            "statement_timeout_seconds": 0.8,
            "cleanup_seconds": round(cleanup_seconds, 6),
            "downstream_cleanup_seconds": round(completed_at - cancellation_observed_at, 6),
            "sql_lifetime_seconds": round(sql_lifetime_seconds, 6),
            "old_backend_after_cancel": "disconnected" if activity is None else activity["state"],
            "pool_checked_out_after_cancel": pool.checkedout(),
            "pool_reusable": True,
        }
        for name, value in measurements.items():
            record_testsuite_property(f"{kind}_{trigger}_{name}", value)
        print(json.dumps(measurements, sort_keys=True))
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
