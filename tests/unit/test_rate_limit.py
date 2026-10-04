from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

from api_sentinel.app import principal
from api_sentinel.errors import Problem
from api_sentinel.rate_limit import RateLimit


def test_concurrent_requests_share_one_budget_and_refill(monkeypatch):
    monkeypatch.setattr("api_sentinel.rate_limit.time", SimpleNamespace(monotonic=lambda: 100.0))
    limiter = RateLimit(rate=10, burst=20)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: limiter.consume("peer"), range(100)))
    assert results.count(0) == 20
    assert all(result == 1 for result in results if result)
    monkeypatch.setattr("api_sentinel.rate_limit.time", SimpleNamespace(monotonic=lambda: 100.11))
    assert limiter.consume("peer") == 0
    assert limiter.consume("peer") == 1


def test_peer_churn_cannot_evict_old_budgets_or_allocate_unbounded_memory(monkeypatch):
    monkeypatch.setattr("api_sentinel.rate_limit.time", SimpleNamespace(monotonic=lambda: 100.0))
    limiter = RateLimit(rate=1, burst=1, max_keys=2)
    assert limiter.consume("alice") == limiter.consume("bob") == 0
    assert limiter.consume("new-peer-0") == 0
    assert all(limiter.consume(f"new-peer-{index}") == 1 for index in range(1, 1000))
    assert limiter.consume("alice") == 1
    assert len(limiter.buckets) == 3


async def test_auth_rate_precedes_database_and_ignores_spoofed_forwarded_headers(monkeypatch):
    monkeypatch.setattr("api_sentinel.rate_limit.time", SimpleNamespace(monotonic=lambda: 100.0))
    limiter = RateLimit(rate=100, burst=1)
    limiter.consume("real-peer")
    authenticator = AsyncMock()
    monkeypatch.setattr("api_sentinel.auth.authenticate", authenticator)
    request = Request(
        {
            "type": "http",
            "client": ("real-peer", 123),
            "headers": [(b"x-forwarded-for", b"spoofed-peer")],
            "app": SimpleNamespace(state=SimpleNamespace(authentication_rate=limiter)),
        }
    )
    with pytest.raises(Problem) as error:
        await principal(request, None)
    assert error.value.status == 429
    authenticator.assert_not_called()
