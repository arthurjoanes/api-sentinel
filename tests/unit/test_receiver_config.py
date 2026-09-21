import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from alert_receiver.app import read_webhook_token
from alert_receiver.config import Settings
from alert_receiver.probe import ProbeState, read_probe_token


@pytest.mark.parametrize("retention", [0, -1, 366])
def test_invalid_retention_fails_before_application_start(retention: int) -> None:
    with pytest.raises(ValueError):
        Settings(retention_days=retention)


@pytest.mark.parametrize("value", ["", "invalid", "0", "-1", "366"])
def test_invalid_retention_environment_is_not_silently_replaced(monkeypatch, value) -> None:
    monkeypatch.setenv("ALERT_RETENTION_DAYS", value)
    with pytest.raises(ValueError):
        Settings.from_environment()


def test_environment_retention_and_probe_switch_are_explicit(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_RETENTION_DAYS", "7")
    monkeypatch.setenv("PROBE_ENABLED", "false")
    assert Settings.from_environment().retention_days == 7
    assert not Settings.from_environment().probe_enabled
    monkeypatch.setenv("PROBE_ENABLED", "typo")
    with pytest.raises(ValueError):
        Settings.from_environment()


@pytest.mark.parametrize("interval,timeout,expected", [(3, 2, 15), (60, 2, 120), (3, 10, 20)])
def test_freshness_follows_configured_schedule(interval, timeout, expected) -> None:
    settings = Settings(probe_interval_seconds=interval, probe_timeout_seconds=timeout)
    assert settings.probe_stale_after_seconds == expected


@pytest.mark.parametrize(
    "age,status", [(0, "fresh"), (15, "fresh"), (15.01, "stale"), (-1, "unavailable")]
)
def test_last_success_is_only_fresh_inside_observation_window(age, status) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    state = ProbeState(result="success", checked_at=now - timedelta(seconds=age))
    assert state.observation_status(now) == status


@pytest.mark.parametrize("checked_at", [None, datetime(2026, 9, 21)])
def test_success_without_reliable_timestamp_is_not_current(checked_at) -> None:
    assert ProbeState(result="success", checked_at=checked_at).observation_status() == "unavailable"


def test_disabled_and_unconfigured_probe_do_not_claim_pending_or_success() -> None:
    assert ProbeState(enabled=False).observation_status() == "disabled"
    assert ProbeState(result="configuration").observation_status() == "configuration"
    assert ProbeState().observation_status() == "pending"


@pytest.mark.parametrize(
    "value", ["a" * 31, "a" * 513, "á" * 32, "a" * 32 + "\nbad", "a" * 32 + " bad"]
)
def test_invalid_tokens_are_rejected_before_http_header_creation(
    tmp_path: Path, value: str
) -> None:
    path = tmp_path / "token"
    path.write_text(value, encoding="utf-8")
    with pytest.raises(ValueError):
        read_webhook_token(path)
    path.write_text(json.dumps({"probe": value}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_probe_token(path)


@pytest.mark.parametrize("length", [32, 512])
def test_token_size_boundaries_are_accepted(tmp_path: Path, length: int) -> None:
    path = tmp_path / "token"
    value = "a" * length
    path.write_text(value + "\n", encoding="utf-8")
    assert read_webhook_token(path) == value
    path.write_text(json.dumps({"probe": value}), encoding="utf-8")
    assert read_probe_token(path) == value
