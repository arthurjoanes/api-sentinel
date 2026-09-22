import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from api_sentinel.db import Database


async def test_auth_reads_without_idle_transaction_and_reconnects_after_termination() -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requer PostgreSQL de testes isolado.")
    if make_url(url).database != "sentinel_test":
        raise RuntimeError("Este teste só aceita o banco isolado sentinel_test.")
    db = Database(url)
    observer_engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with observer_engine.connect() as observer:
            async with db.connection("auth") as connection:
                pid = await connection.scalar(text("SELECT pg_backend_pid()"))
                assert await connection.scalar(text("SHOW statement_timeout")) == "800ms"
                state = await observer.scalar(
                    text("SELECT state FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
                )
                assert state == "idle", "A consulta de autenticação não deve reter transação."

            # O pre_ping precisa detectar uma conexão morta e repor o mesmo pool limitado.
            assert await observer.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            async with db.connection("auth") as connection:
                assert await connection.scalar(text("SELECT 42")) == 42
                assert await connection.scalar(text("SELECT pg_backend_pid()")) != pid
            assert db.auth_engine.sync_engine.pool.size() == 2
            assert db.auth_engine.sync_engine.pool.checkedout() == 0
    finally:
        await db.close()
        await observer_engine.dispose()
