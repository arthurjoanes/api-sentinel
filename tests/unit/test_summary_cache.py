import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis

from api_sentinel.cache import SummaryCache


@pytest.mark.parametrize(
    "stored",
    ["{", "null", "[]", '{"observed_at":"invalid"}', '{"observed_at":"2026-01-01T00:00:00"}'],
)
async def test_invalid_cached_value_is_replaced_without_failing_the_query(stored: str) -> None:
    key = "summary:test:tenant-1:store-1"
    values = {key: stored}
    redis = AsyncMock(spec=Redis)
    redis.get = AsyncMock(side_effect=lambda name: values.get(name))

    async def save(name, value, **options):
        if options.get("nx") and name in values:
            return None
        values[name] = value
        return True

    redis.set = AsyncMock(side_effect=save)
    computed = {"observed_at": datetime.now(UTC).isoformat(), "revenue_cents": 12500}
    compute = AsyncMock(return_value=computed)
    cache = SummaryCache(redis, 10)

    first = await cache.get_or_fill(key, compute)
    second = await cache.get_or_fill(key, compute)

    assert first["revenue_cents"] == second["revenue_cents"] == 12500
    assert json.loads(values[key]) == computed
    compute.assert_awaited_once()
