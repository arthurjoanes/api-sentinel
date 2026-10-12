from pathlib import Path

import pytest
from pydantic import ValidationError

from api_sentinel.config import Settings


@pytest.mark.parametrize(
    "override",
    [
        {"cache_ttl": 0},
        {"cache_ttl": -1},
        {"cache_ttl": 301},
        {"entry_limit": 0},
        {"entry_limit": 49},
        {"authentication_limit": 0},
        {"authentication_limit": 9},
        {"business_limit": 17},
        {"tenant_limit": 0},
        {"tenant_limit": 9, "business_limit": 8},
        {"entry_limit": 8, "business_limit": 16},
        {"trace_sample_ratio": -0.1},
        {"trace_sample_ratio": 1.1},
        {"trace_sample_ratio": float("nan")},
        {"sentinel_env": "production"},
        {"quota_algorithm": "token-bucket"},
        {"quota_burst_capacity": 0},
        {"quota_burst_capacity": -1},
        {"quota_burst_capacity": 10001},
        {"quota_burst_capacity": 1.5},
    ],
)
def test_invalid_configuration_fails_before_serving(override: dict) -> None:
    with pytest.raises(ValidationError):
        Settings(**override)


def test_capacity_can_be_reduced_without_breaking_its_order() -> None:
    config = Settings(
        entry_limit=8,
        authentication_limit=2,
        business_limit=4,
        tenant_limit=2,
        trace_sample_ratio=0,
    )
    assert (config.entry_limit, config.business_limit, config.tenant_limit) == (8, 4, 2)
    assert config.authentication_limit == 2


@pytest.mark.parametrize("secret", ["", "too-short", "a" * 513, "á" * 40])
def test_cursor_secret_is_validated_at_startup(tmp_path: Path, secret: str) -> None:
    (tmp_path / "cursor-key").write_text(secret, encoding="utf-8")
    with pytest.raises(ValueError, match="segredo do cursor"):
        Settings(secrets_dir=tmp_path).cursor_secret()


def test_cursor_secret_accepts_bootstrap_format(tmp_path: Path) -> None:
    (tmp_path / "cursor-key").write_text("s" * 64 + "\n", encoding="utf-8")
    assert Settings(secrets_dir=tmp_path).cursor_secret() == "s" * 64


def test_quota_defaults_and_total_burst_are_separate_from_rate() -> None:
    config = Settings()
    assert config.quota_algorithm == "fixed-window"
    assert config.quota_burst_capacity == 10
    config = Settings(quota_algorithm="gcra", quota_burst_capacity=1)
    assert config.quota_algorithm == "gcra"
    assert config.quota_burst_capacity == 1


def test_quota_policy_can_be_selected_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTA_ALGORITHM", "gcra")
    monkeypatch.setenv("QUOTA_BURST_CAPACITY", "7")
    config = Settings()
    assert config.quota_algorithm == "gcra"
    assert config.quota_burst_capacity == 7
