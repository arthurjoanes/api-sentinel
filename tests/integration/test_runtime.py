import asyncio
import json
import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from fractions import Fraction

import pytest
from redis.asyncio import Redis
from redis.exceptions import AuthenticationError, NoPermissionError

from api_sentinel.admission import GCRA_SCRIPT, enforce_quota
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
        if role == "quota":
            for key in ("summary:forbidden", "fill:summary:forbidden", "unrelated"):
                with pytest.raises(NoPermissionError):
                    await client.get(key)
                with pytest.raises(NoPermissionError):
                    await client.eval("return redis.call('SET', KEYS[1], 'x')", 1, key)
            with pytest.raises(NoPermissionError):
                await client.delete("quota:gcra:991")
        with pytest.raises(AuthenticationError):
            await client.execute_command("AUTH", "default", "")
    finally:
        await client.aclose()


@asynccontextmanager
async def quota_clients(*tenants: int) -> AsyncIterator[tuple[Redis, Redis, Redis]]:
    credentials = Settings().redis_credentials("quota")
    first = Redis.from_url(os.environ["TEST_REDIS_URL"], **credentials, decode_responses=True)
    second = Redis.from_url(os.environ["TEST_REDIS_URL"], **credentials, decode_responses=True)
    admin = experiment_client(0)
    keys = [f"quota:gcra:{tenant}" for tenant in tenants]
    await admin.delete(*keys)
    try:
        yield first, second, admin
    finally:
        await admin.delete(*keys)
        await admin.aclose()
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
async def test_gcra_capacity_is_global_across_two_concurrent_clients() -> None:
    async with quota_clients(992) as (first, second, _):
        results = await asyncio.gather(
            *(
                enforce_quota(
                    first if index % 2 else second, 992, 1, algorithm="gcra", burst_capacity=3
                )
                for index in range(24)
            ),
            return_exceptions=True,
        )
        assert sum(result is None for result in results) == 3
        rejected = [result for result in results if isinstance(result, Problem)]
        assert len(rejected) == 21
        assert all(
            (result.status, result.code, result.retry_after) == (429, "tenant_quota_exceeded", 1)
            for result in rejected
        )
        assert 0 < await first.pttl("quota:gcra:992") <= 3000


@pytest.mark.asyncio
async def test_gcra_tenants_and_legacy_counter_are_independent() -> None:
    async with quota_clients(993, 994) as (first, second, admin):
        await enforce_quota(first, 993, 1, algorithm="gcra", burst_capacity=1)
        with pytest.raises(Problem) as error:
            await enforce_quota(second, 993, 1, algorithm="gcra", burst_capacity=1)
        assert error.value.status == 429
        await enforce_quota(second, 994, 1, algorithm="gcra", burst_capacity=1)
        await admin.delete("quota:993")
        try:
            await enforce_quota(first, 993, 1)
            assert await first.get("quota:993") == "1"
            assert (await first.get("quota:gcra:993")).startswith("v1:1:1:")
        finally:
            await admin.delete("quota:993")


@pytest.mark.asyncio
async def test_gcra_refills_one_token_without_resetting_the_burst() -> None:
    async with quota_clients(995) as (first, second, _):
        for _ in range(2):
            await enforce_quota(first, 995, 5, algorithm="gcra", burst_capacity=2)
        with pytest.raises(Problem):
            await enforce_quota(second, 995, 5, algorithm="gcra", burst_capacity=2)
        await asyncio.sleep(0.22)
        await enforce_quota(second, 995, 5, algorithm="gcra", burst_capacity=2)
        with pytest.raises(Problem):
            await enforce_quota(first, 995, 5, algorithm="gcra", burst_capacity=2)


@pytest.mark.asyncio
async def test_gcra_state_expires_when_capacity_has_fully_recovered() -> None:
    async with quota_clients(996) as (first, _, admin):
        for _ in range(2):
            await enforce_quota(first, 996, 20, algorithm="gcra", burst_capacity=2)
        assert 0 < await first.pttl("quota:gcra:996") <= 100
        for _ in range(80):
            if not await admin.exists("quota:gcra:996"):
                break
            await asyncio.sleep(0.005)
        assert not await admin.exists("quota:gcra:996")
        for _ in range(2):
            await enforce_quota(first, 996, 20, algorithm="gcra", burst_capacity=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["3", "garbage", "NaN", "v1:1:2:0:1000000", "v1:1:2:9:0"])
async def test_gcra_corrupt_state_is_not_repaired_or_admitted(raw: str) -> None:
    async with quota_clients(997) as (first, _, _):
        await first.set("quota:gcra:997", raw, px=1000)
        with pytest.raises(Problem) as error:
            await enforce_quota(first, 997, 1, algorithm="gcra", burst_capacity=2)
        assert (error.value.status, error.value.code) == (503, "quota_unavailable")
        assert await first.get("quota:gcra:997") == raw


@pytest.mark.asyncio
async def test_gcra_missing_ttl_and_changed_policy_fail_closed() -> None:
    async with quota_clients(998) as (first, _, _):
        await enforce_quota(first, 998, 1, algorithm="gcra", burst_capacity=2)
        original = await first.get("quota:gcra:998")
        for rate, capacity in ((2, 2), (1, 3)):
            with pytest.raises(Problem) as error:
                await enforce_quota(first, 998, rate, algorithm="gcra", burst_capacity=capacity)
            assert error.value.status == 503
            assert await first.get("quota:gcra:998") == original
        await first.set("quota:gcra:998", original)
        with pytest.raises(Problem) as error:
            await enforce_quota(first, 998, 1, algorithm="gcra", burst_capacity=2)
        assert error.value.code == "quota_unavailable"
        assert await first.pttl("quota:gcra:998") == -1


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", ["fixed-window", "gcra"])
async def test_real_redis_connection_failure_closes_quota(algorithm: str) -> None:
    client = Redis.from_url(
        "redis://127.0.0.1:0/0", socket_connect_timeout=0.05, socket_timeout=0.05
    )
    try:
        with pytest.raises(Problem) as error:
            await enforce_quota(client, 998, 1, algorithm=algorithm)
        assert (error.value.status, error.value.code) == (503, "quota_unavailable")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_gcra_rejects_future_timestamp_excess_debt_and_truncated_ttl() -> None:
    async with quota_clients(1000) as (first, _, admin):
        seconds, microseconds = await first.time()
        now = seconds * 1000000 + microseconds
        for raw in (
            f"v1:1:2:{now + 1000000}:1000000",
            f"v1:1:2:{now}:3000000",
            f"v1:1:2:{now - 10000000}:1000000",
        ):
            await first.set("quota:gcra:1000", raw, px=1000)
            with pytest.raises(Problem) as error:
                await enforce_quota(first, 1000, 1, algorithm="gcra", burst_capacity=2)
            assert error.value.status == 503
            assert await first.get("quota:gcra:1000") == raw
        await admin.delete("quota:gcra:1000")
        await enforce_quota(first, 1000, 1, algorithm="gcra", burst_capacity=2)
        original = await first.get("quota:gcra:1000")
        await admin.pexpire("quota:gcra:1000", 500)
        with pytest.raises(Problem) as error:
            await enforce_quota(first, 1000, 1, algorithm="gcra", burst_capacity=2)
        assert error.value.code == "quota_unavailable"
        assert await first.get("quota:gcra:1000") == original


# Execute the actual production Lua against an in-script clock/store. This
# changes no production entry point and lets a fractional token-bucket oracle
# test GCRA at exact boundaries, independently of Docker scheduler timings.
GCRA_SEQUENCE_HARNESS = (
    """
local real = redis
local moments = cjson.decode(ARGV[3])
local now, raw, expires = 0, nil, 0
local redis = {
    error_reply = real.error_reply,
    call = function(command, key, value, option, ttl)
        if command == 'TIME' then
            return {math.floor(now / 1000000), now % 1000000}
        elseif command == 'GET' then
            if now >= expires then raw = nil end
            return raw
        elseif command == 'PTTL' then
            return math.floor((expires - now) / 1000)
        elseif command == 'SET' then
            raw, expires = value, now + ttl * 1000
            return 'OK'
        end
        error('unexpected command')
    end
}
local function apply()
"""
    + GCRA_SCRIPT
    + """
end
local results = {}
for _, moment in ipairs(moments) do
    now = 1800000000000000 + moment
    local result = apply()
    if result.err then return result end
    table.insert(results, result)
end
return results
"""
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rate,capacity,moments",
    [
        (1, 1, [0, 0, 999999, 1000000, 1000000, 2000000]),
        (2, 3, [0] * 5 + [499999, 500000, 500000, 1500000, 1500000, 1500000]),
        (3, 2, [0, 0, 333333, 333334, 666666, 666667, 2000000, 2000000, 2000000]),
        (30, 4, [index * 5000 for index in range(250)]),
        (1, 2, [990000, 990000, 1000000, 1010000, 1989999, 1990000]),
        (2**31 - 1, 3, [0, 0, 0, 0, 1, 1, 1, 1]),
    ],
)
async def test_gcra_matches_capacity_and_exact_rate_properties(
    rate: int, capacity: int, moments: list[int]
) -> None:
    expected = []
    tokens = Fraction(capacity)
    previous = moments[0]
    for now in moments:
        tokens = min(capacity, tokens + Fraction((now - previous) * rate, 1000000))
        previous = now
        if tokens >= 1:
            tokens -= 1
            expected.append([1, 0])
        else:
            expected.append([0, math.ceil((1 - tokens) * 1000000 / rate)])
    async with quota_clients(999) as (first, _, _):
        actual = await first.eval(
            GCRA_SEQUENCE_HARNESS, 1, "quota:gcra:999", rate, capacity, json.dumps(moments)
        )
    assert actual == expected
