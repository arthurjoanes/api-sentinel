import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from api_sentinel.errors import Problem
from api_sentinel.metrics import DB_POOL, DB_TIMEOUTS, DB_WAIT


class Database:
    def __init__(self, url: str) -> None:
        options = dict(
            hide_parameters=True,
            max_overflow=0,
            pool_timeout=0.2,
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={
                "timeout": 2,
                "server_settings": {
                    "statement_timeout": "800",
                    "idle_in_transaction_session_timeout": "2000",
                    "application_name": "api-sentinel",
                    "timezone": "UTC",
                },
            },
        )
        self.engine = create_async_engine(url, pool_size=4, **options)
        # Autenticação faz um único SELECT. AUTOCOMMIT evita BEGIN/ROLLBACK tanto
        # na consulta quanto no pre_ping, mantendo a leitura atual a cada request.
        self.auth_engine = create_async_engine(
            url, pool_size=2, isolation_level="AUTOCOMMIT", **options
        )
        for kind in ("data", "auth"):
            DB_POOL.labels(kind, "checked_out").set(0)
            DB_POOL.labels(kind, "idle").set(0)

    @asynccontextmanager
    async def connection(self, kind: str = "data") -> AsyncIterator[AsyncConnection]:
        engine = self.auth_engine if kind == "auth" else self.engine
        pool = cast(AsyncAdaptedQueuePool, engine.sync_engine.pool)
        started = time.monotonic()
        try:
            async with engine.connect() as connection:
                DB_WAIT.labels(kind).observe(time.monotonic() - started)
                DB_POOL.labels(kind, "checked_out").set(pool.checkedout())
                DB_POOL.labels(kind, "idle").set(pool.checkedin())
                yield connection
        except PoolTimeout as exc:
            DB_TIMEOUTS.labels(kind).inc()
            DB_WAIT.labels(kind).observe(time.monotonic() - started)
            raise Problem(503, "database_pool_busy", "Banco sem capacidade disponível.", 1) from exc
        finally:
            # O __aexit__ já devolveu a conexão; saídas simultâneas usam o estado real do pool.
            DB_POOL.labels(kind, "checked_out").set(pool.checkedout())
            DB_POOL.labels(kind, "idle").set(pool.checkedin())

    async def close(self) -> None:
        await self.engine.dispose()
        await self.auth_engine.dispose()
