import asyncio
import os
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis

from api_sentinel.admission import enforce_quota
from api_sentinel.cache import RELEASE_SCRIPT, SummaryCache
from api_sentinel.errors import Problem


@pytest.mark.asyncio
async def test_atomic_global_quota_shared_between_clients() -> None:
    url = os.environ["TEST_REDIS_URL"]
    first = Redis.from_url(url, decode_responses=True)
    second = Redis.from_url(url, decode_responses=True)
    tenant = 991
    await first.delete(f"quota:{tenant}")
    try:
        results = await asyncio.gather(
            *(enforce_quota(first if i % 2 else second, tenant, 10) for i in range(30)),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 10
        assert sum(isinstance(result, Problem) and result.status == 429 for result in results) == 20
        assert 0 < await first.pttl(f"quota:{tenant}") <= 1000
    finally:
        await first.delete(f"quota:{tenant}")
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_cache_stampede_expiry_and_owner_token() -> None:
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    cache = SummaryCache(redis, 1)
    key = "test:summary:v1:isolated"
    count = 0

    async def compute() -> dict:
        nonlocal count
        count += 1
        await asyncio.sleep(0.03)
        return {"observed_at": datetime.now(UTC).isoformat(), "revenue_cents": 12500}

    await redis.delete(key, f"fill:{key}")
    try:
        values = await asyncio.gather(*(cache.get_or_fill(key, compute) for _ in range(8)))
        assert all(value["revenue_cents"] == 12500 for value in values)
        assert count == 1
        await cache.get_or_fill(key, compute)
        assert count == 1
        await redis.pexpire(key, 1)
        for _ in range(100):
            if not await redis.exists(key):
                break
            await asyncio.sleep(0.002)
        assert not await redis.exists(key)
        await asyncio.gather(*(cache.get_or_fill(key, compute) for _ in range(8)))
        assert count == 2
        await redis.set(f"fill:{key}", "new-owner", px=1000)
        await redis.eval(RELEASE_SCRIPT, 1, f"fill:{key}", "old-owner")
        assert await redis.get(f"fill:{key}") == "new-owner"
    finally:
        await redis.delete(key, f"fill:{key}")
        await redis.aclose()
