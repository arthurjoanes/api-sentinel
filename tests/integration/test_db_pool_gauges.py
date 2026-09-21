import asyncio
import os
from typing import cast

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import AsyncAdaptedQueuePool

from api_sentinel.db import Database
from api_sentinel.metrics import DB_POOL


@pytest.mark.parametrize("fail_after_barrier", [False, True])
async def test_pool_gauges_follow_actual_concurrent_returns(fail_after_barrier: bool) -> None:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Requer PostgreSQL de testes isolado.")
    if make_url(url).database != "sentinel_test":
        raise RuntimeError("Este teste só aceita o banco isolado sentinel_test.")
    db = Database(url)
    barrier = asyncio.Barrier(4)

    async def request() -> None:
        async with db.connection() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
            await barrier.wait()
            if fail_after_barrier:
                raise ValueError("Falha controlada após consulta concluída.")

    try:
        async with asyncio.timeout(3):
            results = await asyncio.gather(*(request() for _ in range(4)), return_exceptions=True)
        if fail_after_barrier:
            assert all(isinstance(result, ValueError) for result in results)
        else:
            assert results == [None] * 4
        pool = cast(AsyncAdaptedQueuePool, db.engine.sync_engine.pool)
        actual = {"checked_out": pool.checkedout(), "idle": pool.checkedin()}
        reported = {
            sample.labels["state"]: sample.value
            for sample in DB_POOL.collect()[0].samples
            if sample.labels.get("pool") == "data"
        }
        assert actual == {"checked_out": 0, "idle": 4}
        assert reported == actual
    finally:
        await db.close()
