import asyncio
import os
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis
from redis.exceptions import AuthenticationError, NoPermissionError

from api_sentinel.admission import enforce_quota
from api_sentinel.cache import RELEASE_SCRIPT, SummaryCache
from api_sentinel.config import Settings
from api_sentinel.errors import Problem
from scripts.redis_admin import experiment_client


@pytest.mark.asyncio
async def test_atomic_global_quota_shared_between_clients() -> None:
    url = os.environ["TEST_REDIS_URL"]
    first = Redis.from_url(url, **Settings().redis_credentials("quota"), decode_responses=True)
    second = Redis.from_url(url, **Settings().redis_credentials("quota"), decode_responses=True)
    admin = experiment_client(0)
    tenant = 991
    await admin.delete(f"quota:{tenant}")
    try:
        results = await asyncio.gather(
            *(enforce_quota(first if i % 2 else second, tenant, 10) for i in range(30)),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 10
        assert sum(isinstance(result, Problem) and result.status == 429 for result in results) == 20
        assert 0 < await first.pttl(f"quota:{tenant}") <= 1000
    finally:
        await admin.delete(f"quota:{tenant}")
        await admin.aclose()
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_cache_stampede_expiry_and_owner_token() -> None:
    redis = Redis.from_url(
        os.environ["TEST_REDIS_URL"],
        **Settings().redis_credentials("cache"),
        decode_responses=True,
    )
    admin = experiment_client(0)
    cache = SummaryCache(redis, 1)
    key = "summary:test:v1:isolated"
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
        await admin.pexpire(key, 1)
        for _ in range(100):
            if not await admin.exists(key):
                break
            await asyncio.sleep(0.002)
        assert not await admin.exists(key)
        await asyncio.gather(*(cache.get_or_fill(key, compute) for _ in range(8)))
        assert count == 2
        await redis.set(f"fill:{key}", "new-owner", px=1000)
        await redis.eval(RELEASE_SCRIPT, 1, f"fill:{key}", "old-owner")
        assert await redis.get(f"fill:{key}") == "new-owner"
    finally:
        await redis.delete(key, f"fill:{key}")
        await redis.aclose()
        await admin.aclose()


@pytest.mark.asyncio
async def test_redis_anonymous_and_default_connections_cannot_execute_commands() -> None:
    anonymous = Redis.from_url(os.environ["TEST_REDIS_URL"])
    try:
        with pytest.raises(AuthenticationError):
            await anonymous.ping()
        with pytest.raises(AuthenticationError):
            await anonymous.execute_command("AUTH", "default", "")
    finally:
        await anonymous.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["cache", "quota"])
async def test_redis_application_roles_cannot_administer_or_cross_key_scopes(role: str) -> None:
    client = Redis.from_url(
        os.environ["TEST_REDIS_URL"],
        **Settings().redis_credentials(role),
        decode_responses=True,
    )
    try:
        assert await client.ping()
        for command in (
            ("CONFIG", "GET", "maxmemory"),
            ("ACL", "SETUSER", "default", "on", "nopass", "+@all"),
            ("FLUSHALL",),
            ("FLUSHDB",),
        ):
            with pytest.raises(NoPermissionError):
                await client.execute_command(*command)
        # EVAL has to retain the caller's key and command restrictions as well.
        with pytest.raises(NoPermissionError):
            if role == "cache":
                await client.get("quota:991")
            else:
                await client.eval("return redis.call('INCR', KEYS[1])", 1, "summary:forbidden")
        with pytest.raises(AuthenticationError):
            await client.execute_command("AUTH", "default", "")
    finally:
        await client.aclose()
