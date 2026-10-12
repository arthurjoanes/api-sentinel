import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from scripts import quota_compare
from scripts.quota_compare import _local_base_url, uniform_policy

PROJECT = "pf-api-sentinel-review-test"
IMAGE = "sha256:recorded-image"


def replica(
    algorithm: str, capacity: int = 10, *, project: str = PROJECT, image: str = IMAGE
) -> dict:
    return {
        "Image": image,
        "Config": {
            "Labels": {"com.docker.compose.project": project},
            "Env": [f"QUOTA_ALGORITHM={algorithm}", f"QUOTA_BURST_CAPACITY={capacity}"],
        },
    }


@pytest.mark.parametrize("count", [1, 2])
@pytest.mark.parametrize("algorithm", ["fixed-window", "gcra"])
def test_runner_accepts_only_consistent_registered_replicas(count: int, algorithm: str) -> None:
    assert uniform_policy([replica(algorithm) for _ in range(count)], PROJECT, IMAGE, count) == {
        "algorithm": algorithm,
        "burst_capacity": 10,
    }


@pytest.mark.parametrize(
    "containers",
    [
        [replica("fixed-window"), replica("gcra")],
        [replica("gcra", 1), replica("gcra", 2)],
    ],
)
def test_runner_rejects_mixed_policy_rollouts(containers: list[dict]) -> None:
    with pytest.raises(RuntimeError, match="Mixed quota policies"):
        uniform_policy(containers, PROJECT, IMAGE, 2)


@pytest.mark.parametrize(
    "containers,count",
    [
        ([replica("gcra", project="pf-api-sentinel")], 1),
        ([replica("gcra", image="sha256:other")], 1),
        ([replica("gcra", 0)], 1),
        ([replica("unknown")], 1),
        ([replica("gcra")], 2),
        ([], 0),
    ],
)
def test_runner_rejects_foreign_images_invalid_policies_and_counts(
    containers: list[dict], count: int
) -> None:
    with pytest.raises(RuntimeError):
        uniform_policy(containers, PROJECT, IMAGE, count)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:1234",
        "http://public.example:1234",
        "http://127.0.0.1",
        "http://user:password@127.0.0.1:1234",
        "http://127.0.0.1:1234/path",
        "http://127.0.0.1:1234?token=secret",
    ],
)
def test_quota_comparison_rejects_external_or_credential_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _local_base_url(url)


def test_quota_comparison_accepts_loopback_proxy_address() -> None:
    assert _local_base_url("http://127.0.0.1:1234/") == "http://127.0.0.1:1234"


def test_comparison_waits_for_both_new_instances_and_quiet_quota_before_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SENTINEL_LAB_PROJECT", PROJECT)
    monkeypatch.setenv("QUOTA_ALGORITHM", "fixed-window")
    monkeypatch.setenv("QUOTA_BURST_CAPACITY", "10")
    state = {"replicas": 2, "algorithm": "fixed-window", "upstream": 0, "probed": set()}
    events: list[tuple] = []

    def compose(*arguments: str) -> str:
        if arguments[:1] == ("port",):
            return "127.0.0.1:1234"
        if arguments[:1] == ("up",):
            state["replicas"] = int(
                next(value[-1] for value in arguments if value.startswith("api="))
            )
            state["algorithm"] = quota_compare.os.environ["QUOTA_ALGORITHM"]
            state["upstream"] = 0
            state["probed"] = set()
            events.append(("configure", state["algorithm"], state["replicas"]))
        if arguments[:1] == ("ps",):
            return "\n".join(f"container-{index}" for index in range(state["replicas"]))
        return ""

    def inspect(*arguments: str) -> str:
        inspected = []
        for index in range(state["replicas"]):
            item = replica(state["algorithm"])
            item["Config"]["Hostname"] = f"instance-{index}"
            inspected.append(item)
        return json.dumps(inspected)

    def health(*arguments: object, **keywords: object) -> object:
        state["upstream"] += 1
        return nullcontext(SimpleNamespace(status=200))

    def positive(*arguments: str) -> dict:
        # Match round robin across health and stores requests. One stores probe
        # per round would see the same replica forever when two are active.
        instance = f"instance-{state['upstream'] % state['replicas']}"
        state["upstream"] += 1
        state["probed"].add(instance)
        return {"status": 200, "instance": instance}

    def settle(*arguments: object) -> dict:
        events.append(("settle",))
        return {"after_ttl_ms": [-2, -2]}

    def sample(*arguments: object) -> dict:
        assert state["probed"] == {f"instance-{index}" for index in range(state["replicas"])}
        assert events[-1] == ("settle",)
        events.append(("sample", state["algorithm"], state["replicas"]))
        return {
            "responses": [{"instance": name} for name in sorted(state["probed"])],
            "allowed": 1,
            "rejected": 1,
        }

    monkeypatch.setattr(quota_compare, "_docker", inspect)
    monkeypatch.setattr(quota_compare.urllib.request, "urlopen", health)
    monkeypatch.setattr(quota_compare, "_one_request", positive)
    monkeypatch.setattr(quota_compare, "_settle_old_state", settle)
    monkeypatch.setattr(quota_compare, "_sample", sample)
    monkeypatch.setattr(
        quota_compare,
        "_resources",
        lambda ids: {name: {"cpu_usage_us": 0, "memory_bytes": 1} for name in ids},
    )
    monkeypatch.setattr(quota_compare.time, "sleep", lambda _: None)
    output = quota_compare.quota_comparison(compose, "http://127.0.0.1:1234", "private", IMAGE)
    assert len(output["phases"]) == 4
    assert output["restored"]["replicas"] == 2
    assert output["restored"]["effective_policy"]["algorithm"] == "fixed-window"
    assert [event[1:] for event in events if event[0] == "sample"] == [
        ("fixed-window", 1),
        ("fixed-window", 2),
        ("gcra", 1),
        ("gcra", 2),
    ]
