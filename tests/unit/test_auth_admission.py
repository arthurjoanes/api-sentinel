import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.security import HTTPAuthorizationCredentials
from redis.asyncio import Redis

from api_sentinel import auth
from api_sentinel.admission import Admission
from api_sentinel.app import admit, principal
from api_sentinel.config import Settings
from api_sentinel.errors import Problem
from api_sentinel.rate_limit import RateLimit


@pytest.mark.parametrize(
    "scope,store,code",
    [("sales:read", 1, "insufficient_scope"), ("stores:read", 2, "store_forbidden")],
)
async def test_denied_authorization_does_not_consume_tenant_quota(scope, store, code) -> None:
    application = FastAPI()
    application.state.settings = Settings()
    application.state.quota = AsyncMock(spec=Redis)
    request = Request({"type": "http", "app": application, "headers": []})
    identity = auth.Principal(1, (1,), ("stores:read",), 30, False)

    with pytest.raises(Problem) as failure:
        await admit(request, identity, scope, store)

    assert failure.value.status == 403
    assert failure.value.code == code
    application.state.quota.execute_command.assert_not_awaited()


async def test_authentication_burst_is_bounded_and_releases_on_cancellation(monkeypatch) -> None:
    application = FastAPI()
    application.state.authentication = Admission(Settings().authentication_limit, "auth")
    application.state.authentication_rate = RateLimit(rate=100, burst=200)
    application.state.db = object()
    release, entered = asyncio.Event(), asyncio.Event()
    calls = 0

    async def held_authentication(database, token):
        nonlocal calls
        calls += 1
        if calls == 8:
            entered.set()
        await release.wait()
        return auth.Principal(1, (1,), ("stores:read",), 30, False)

    monkeypatch.setattr(auth, "authenticate", held_authentication)

    async def authenticate():
        request = Request({"type": "http", "app": application, "headers": []})
        return await principal(
            request, HTTPAuthorizationCredentials(scheme="Bearer", credentials="local-test")
        )

    tasks = [asyncio.create_task(authenticate()) for _ in range(8)]
    try:
        await asyncio.wait_for(entered.wait(), 0.2)
        with pytest.raises(Problem) as error:
            await authenticate()
        assert error.value.code == "service_saturated"
        assert calls == 8  # Excess work must never invoke the authenticator.
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        assert application.state.authentication.active == 7
        release.set()
        assert (await authenticate()).tenant_id == 1
        results = await asyncio.gather(*tasks[1:])
        assert all(result.tenant_id == 1 for result in results)
        assert application.state.authentication.active == 0
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
