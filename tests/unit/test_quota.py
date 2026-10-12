from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError, ResponseError

from api_sentinel.admission import GCRA_SCRIPT, QUOTA_SCRIPT, enforce_quota
from api_sentinel.errors import Problem


@pytest.mark.asyncio
async def test_fixed_window_remains_default_with_original_namespace() -> None:
    redis = AsyncMock(spec=Redis)
    redis.execute_command.return_value = [4, 900]
    await enforce_quota(redis, 44, 4)
    redis.execute_command.assert_awaited_once_with("EVAL", QUOTA_SCRIPT, 1, "quota:44")


@pytest.mark.asyncio
async def test_gcra_passes_only_policy_parameters_and_uses_separate_namespace() -> None:
    redis = AsyncMock(spec=Redis)
    redis.execute_command.return_value = [1, 0]
    await enforce_quota(redis, 44, 30, algorithm="gcra", burst_capacity=3)
    redis.execute_command.assert_awaited_once_with("EVAL", GCRA_SCRIPT, 1, "quota:gcra:44", 30, 3)
    assert "redis.call('TIME')" in GCRA_SCRIPT


@pytest.mark.asyncio
@pytest.mark.parametrize("wait_us,expected", [(1, 1), (999999, 1), (1000000, 1), (1000001, 2)])
async def test_gcra_retry_after_rounds_up(wait_us: int, expected: int) -> None:
    redis = AsyncMock(spec=Redis)
    redis.execute_command.return_value = [0, wait_us]
    with pytest.raises(Problem) as error:
        await enforce_quota(redis, 44, 3, algorithm="gcra", burst_capacity=2)
    assert (error.value.status, error.value.code, error.value.retry_after) == (
        429,
        "tenant_quota_exceeded",
        expected,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("algorithm", ["fixed-window", "gcra"])
@pytest.mark.parametrize("failure", [ConnectionError("offline"), ResponseError("invalid state")])
async def test_redis_failure_closes_both_policies(algorithm: str, failure: Exception) -> None:
    redis = AsyncMock(spec=Redis)
    redis.execute_command.side_effect = failure
    with pytest.raises(Problem) as error:
        await enforce_quota(redis, 44, 30, algorithm=algorithm)
    assert (error.value.status, error.value.code, error.value.retry_after) == (
        503,
        "quota_unavailable",
        1,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "algorithm,result",
    [
        ("fixed-window", [1, -1]),
        ("fixed-window", [0, 1000]),
        ("fixed-window", [1, 1001]),
        ("gcra", [0, 0]),
        ("gcra", [2, 1]),
        ("gcra", [1, 1]),
        ("gcra", [1.0, 0]),
        ("gcra", [1, "0"]),
        ("gcra", [1]),
        ("gcra", None),
    ],
)
async def test_malformed_result_is_unavailable(algorithm: str, result: object) -> None:
    redis = AsyncMock(spec=Redis)
    redis.execute_command.return_value = result
    with pytest.raises(Problem) as error:
        await enforce_quota(redis, 44, 30, algorithm=algorithm)
    assert error.value.status == 503 and error.value.code == "quota_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"algorithm": "unknown"},
        {"limit": 0},
        {"limit": True},
        {"limit": 2**31},
        {"burst_capacity": 0},
        {"burst_capacity": 10001},
        {"burst_capacity": True},
    ],
)
async def test_invalid_runtime_quota_parameters_do_not_reach_redis(overrides: dict) -> None:
    redis = AsyncMock(spec=Redis)
    parameters = {"tenant": 44, "limit": 30, "algorithm": "gcra", "burst_capacity": 3}
    parameters.update(overrides)
    with pytest.raises(Problem) as error:
        await enforce_quota(redis, **parameters)
    assert error.value.code == "quota_unavailable"
    redis.execute_command.assert_not_awaited()
