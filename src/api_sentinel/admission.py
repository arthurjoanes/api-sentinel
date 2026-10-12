import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

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

# GCRA keeps the theoretical arrival time as relative debt, in millionths of a
# token. This avoids multiplying an epoch timestamp by a tenant's rate. The
# arithmetic stays exact for the PostgreSQL integer rate and bounded capacity.
# State is versioned and bound to its policy; a changed policy waits for expiry.
GCRA_SCRIPT = """
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
if not rate or rate < 1 or rate > 2147483647 or rate ~= math.floor(rate)
    or not capacity or capacity < 1 or capacity > 10000
    or capacity ~= math.floor(capacity) then
    return redis.error_reply('invalid quota parameters')
end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000000 + tonumber(clock[2])
local maximum = capacity * 1000000
local raw = redis.call('GET', KEYS[1])
local debt = 0
if raw then
    local saved_rate, saved_capacity, saved_at, saved_debt =
        string.match(raw, '^v1:(%d+):(%d+):(%d+):(%d+)$')
    saved_rate = tonumber(saved_rate)
    saved_capacity = tonumber(saved_capacity)
    saved_at = tonumber(saved_at)
    saved_debt = tonumber(saved_debt)
    local ttl = redis.call('PTTL', KEYS[1])
    if saved_rate ~= rate or saved_capacity ~= capacity or not saved_at
        or saved_at < 1 or saved_at > now or saved_at ~= math.floor(saved_at)
        or not saved_debt or saved_debt < 1000000 or saved_debt > maximum
        or saved_debt ~= math.floor(saved_debt) or ttl < 0 then
        return redis.error_reply('invalid quota state')
    end
    local elapsed = now - saved_at
    if elapsed > math.ceil(saved_debt / rate) + 1000 then
        return redis.error_reply('invalid quota timestamp')
    end
    -- Saturate before multiplying; even a long idle interval cannot overflow.
    if elapsed < math.ceil(saved_debt / rate) then
        debt = math.max(0, saved_debt - elapsed * rate)
    end
    -- TIME has microsecond precision; expiry uses milliseconds. Allow one ms
    -- of quantization, but never repair a missing or truncated state TTL.
    local expected_ttl = math.ceil(debt / rate / 1000)
    if ttl < expected_ttl - 1 or ttl > expected_ttl + 1 then
        return redis.error_reply('invalid quota expiry')
    end
end
local next_debt = debt + 1000000
if next_debt > maximum then
    return {0, math.ceil((next_debt - maximum) / rate)}
end
local ttl = math.max(1, math.ceil(next_debt / rate / 1000))
local state = string.format('v1:%d:%d:%.0f:%.0f', rate, capacity, now, next_debt)
redis.call('SET', KEYS[1], state, 'PX', ttl)
return {1, 0}
"""

QuotaAlgorithm = Literal["fixed-window", "gcra"]


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


async def enforce_quota(
    redis: Redis,
    tenant: int,
    limit: int,
    *,
    algorithm: QuotaAlgorithm = "fixed-window",
    burst_capacity: int = 10,
) -> None:
    """Enforce a shared tenant quota; GCRA capacity includes the first request."""
    try:
        if (
            type(limit) is not int
            or not 1 <= limit <= 2**31 - 1
            or type(burst_capacity) is not int
            or not 1 <= burst_capacity <= 10000
        ):
            raise ValueError("Invalid quota parameters")
        if algorithm == "fixed-window":
            result = await redis.execute_command("EVAL", QUOTA_SCRIPT, 1, f"quota:{tenant}")
        elif algorithm == "gcra":
            result = await redis.execute_command(
                "EVAL", GCRA_SCRIPT, 1, f"quota:gcra:{tenant}", limit, burst_capacity
            )
        else:
            raise ValueError("Invalid quota algorithm")
        if (
            not isinstance(result, list | tuple)
            or len(result) != 2
            or any(type(value) is not int for value in result)
        ):
            raise ValueError("Invalid quota result")
        first, second = result
        if algorithm == "gcra":
            if first not in (0, 1) or (first == 1 and second != 0) or (first == 0 and second < 1):
                raise ValueError("Invalid GCRA result")
            rejected = first == 0
            retry_after = max(1, (second + 999999) // 1000000)
        else:
            if first < 1 or not 0 <= second <= 1000:
                raise ValueError("Invalid fixed-window state")
            rejected = first > limit
            retry_after = max(1, (second + 999) // 1000)
    except (RedisError, ValueError, TypeError) as exc:
        raise Problem(503, "quota_unavailable", "Controle de quota indisponível.", 1) from exc
    if rejected:
        raise Problem(
            429,
            "tenant_quota_exceeded",
            "Quota contratada excedida.",
            retry_after,
        )
