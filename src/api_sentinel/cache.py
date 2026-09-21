import asyncio
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from api_sentinel.errors import Problem
from api_sentinel.metrics import CACHE_DURATION, CACHE_FILL, CACHE_REQUESTS

RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class SummaryCache:
    def __init__(self, redis: Redis, ttl: int) -> None:
        self.redis = redis
        self.ttl = ttl

    @staticmethod
    def with_age(payload: dict) -> dict:
        result = dict(payload)
        observed = datetime.fromisoformat(result["observed_at"])
        result["cache_age_seconds"] = round(
            max(0, (datetime.now(UTC) - observed).total_seconds()), 3
        )
        return result

    async def get_or_fill(self, key: str, compute: Callable[[], Awaitable[dict]]) -> dict:
        started = time.monotonic()
        lock = f"fill:{key}"
        token = secrets.token_hex(16)
        acquired = False
        computed: dict | None = None
        try:
            cached = await self.redis.get(key)
            if cached is not None:
                CACHE_REQUESTS.labels("hit").inc()
                return self.with_age(json.loads(cached))
            CACHE_REQUESTS.labels("miss").inc()
            acquired = bool(await self.redis.set(lock, token, nx=True, px=2000))
            if not acquired:
                CACHE_FILL.labels("contended").inc()
                deadline = time.monotonic() + 0.25
                while time.monotonic() < deadline:
                    await asyncio.sleep(0.015)
                    cached = await self.redis.get(key)
                    if cached is not None:
                        CACHE_REQUESTS.labels("hit").inc()
                        return self.with_age(json.loads(cached))
                CACHE_FILL.labels("timeout").inc()
                raise Problem(503, "cache_fill_busy", "Resumo em cálculo; tente novamente.", 1)
            CACHE_FILL.labels("owner").inc()
            # Outra réplica pode concluir entre o GET e a obtenção do lock.
            cached = await self.redis.get(key)
            if cached is not None:
                return self.with_age(json.loads(cached))
            computed = await compute()
            await self.redis.set(key, json.dumps(computed), ex=self.ttl)
            return self.with_age(computed)
        except RedisError:
            CACHE_REQUESTS.labels("error").inc()
            # A quota já foi validada. Este fallback conserva a admissão de negócio.
            return self.with_age(computed if computed is not None else await compute())
        finally:
            if acquired:
                try:
                    await self.redis.execute_command("EVAL", RELEASE_SCRIPT, 1, lock, token)
                except RedisError:
                    CACHE_REQUESTS.labels("error").inc()
            CACHE_DURATION.labels("get_or_fill").observe(time.monotonic() - started)
