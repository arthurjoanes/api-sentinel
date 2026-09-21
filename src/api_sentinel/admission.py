import time
from collections.abc import Iterator
from contextlib import contextmanager

from redis.asyncio import Redis
from redis.exceptions import RedisError

from api_sentinel.errors import Problem
from api_sentinel.metrics import ADMISSION, ADMISSION_WAIT, INFLIGHT

# A chave por tenant é estável. INCR/PEXPIRE/TTL são uma única operação no Redis.
QUOTA_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('PEXPIRE', KEYS[1], 1000) end
return {current, redis.call('PTTL', KEYS[1])}
"""


class Admission:
    def __init__(self, limit: int, stage: str, per_tenant: int | None = None) -> None:
        self.limit = limit
        self.stage = stage
        self.per_tenant = per_tenant
        self.active = 0
        self.tenants: dict[int, int] = {}
        self.closing = False

    @contextmanager
    def enter(self, tenant: int = 0) -> Iterator[None]:
        started = time.monotonic()
        tenant_active = self.tenants.get(tenant, 0)
        if (
            self.closing
            or self.active >= self.limit
            or (self.per_tenant is not None and tenant_active >= self.per_tenant)
        ):
            ADMISSION.labels(self.stage, "rejected").inc()
            ADMISSION_WAIT.labels(self.stage).observe(time.monotonic() - started)
            raise Problem(503, "service_saturated", "Capacidade temporariamente esgotada.", 1)
        self.active += 1
        self.tenants[tenant] = tenant_active + 1
        ADMISSION.labels(self.stage, "accepted").inc()
        ADMISSION_WAIT.labels(self.stage).observe(time.monotonic() - started)
        INFLIGHT.labels(self.stage).inc()
        try:
            yield
        finally:
            self.active -= 1
            self.tenants[tenant] -= 1
            if not self.tenants[tenant]:
                del self.tenants[tenant]
            INFLIGHT.labels(self.stage).dec()


async def enforce_quota(redis: Redis, tenant: int, limit: int) -> None:
    try:
        count, ttl = await redis.execute_command("EVAL", QUOTA_SCRIPT, 1, f"quota:{tenant}")
    except RedisError as exc:
        raise Problem(503, "quota_unavailable", "Controle de quota indisponível.", 1) from exc
    if int(count) > limit:
        raise Problem(
            429,
            "tenant_quota_exceeded",
            "Quota contratada excedida.",
            max(1, (int(ttl) + 999) // 1000),
        )
