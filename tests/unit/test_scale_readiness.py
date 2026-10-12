import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from scripts import quota_compare

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "pf-api-sentinel-review-scale-test"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> dict:
    state = {"now": 0.0, "sleeps": []}

    def sleep(seconds: float) -> None:
        state["sleeps"].append(seconds)
        state["now"] += seconds

    monkeypatch.setattr(quota_compare.time, "sleep", sleep)
    monkeypatch.setattr(quota_compare.time, "monotonic", lambda: state["now"])
    return state


@pytest.mark.parametrize(
    "interruption", [{"status": 200, "instance": "removed-but-reachable"}, {"status": 503}]
)
def test_old_peer_or_late_proxy_failure_restarts_the_full_healthy_window(
    clock: dict, interruption: dict
) -> None:
    requests = []
    failed_at = []

    def probe() -> dict:
        requests.append(clock["now"])
        if len(requests) == 9:
            # The old upstream returns after nginx's two-second fail_timeout,
            # beyond the three quick successes accepted by the previous guard.
            failed_at.append(clock["now"])
            return interruption
        return {"status": 200, "instance": "current"}

    proof = quota_compare.wait_for_proxy_instances(["current"], probe)
    assert clock["sleeps"][0] == 3.25
    assert requests[0] == 3.25
    assert proof["business_probes"] >= 22
    assert proof["stable_seconds"] >= 3
    assert clock["now"] - failed_at[0] >= 3
    assert proof["expected_instances"] == ["current"]


def test_skewed_round_robin_must_reach_every_current_replica(clock: dict) -> None:
    count = 0

    def probe() -> dict:
        nonlocal count
        count += 1
        # A successful reply from A alone does not establish B's readiness.
        instance = "a" if count <= 22 or count % 2 else "b"
        return {"status": 200, "instance": instance}

    proof = quota_compare.wait_for_proxy_instances(["a", "b"], probe)
    assert count >= 24
    assert proof["expected_instances"] == ["a", "b"]
    assert proof["stable_seconds"] >= 3


@pytest.mark.parametrize("replicas,ids", [(2, ["only-one"]), (1, ["a", "b"])])
def test_scale_rejects_an_actual_count_mismatch_before_stale_metrics_can_approve_it(
    monkeypatch: pytest.MonkeyPatch, replicas: int, ids: list[str]
) -> None:
    fake = ModuleType("operations")
    fake.ARTIFACTS, fake.PROJECT = ROOT / "artifacts", ROOT
    fake.COMPOSE, fake.COMPOSE_PROJECT = ["docker", "compose", "-p", PROJECT], PROJECT
    fake.LOCAL_URLS = {"proxy": "http://127.0.0.1:1234"}
    fake.credentials = lambda: {"tenant_a": "private"}
    fake.require_disposable = lambda: None
    # A previous target can remain healthy in Prometheus until its next scrape.
    fake.healthy_targets = lambda: ["old-a", "new-b"][:replicas]
    fake.compose = lambda *args: "\n".join(ids) if args == ("ps", "-q", "api") else ""

    def unexpected(*args):
        pytest.fail("Count mismatch must fail before inspection, metrics or business probes.")

    fake.command = fake.wait_until = fake.request = unexpected
    monkeypatch.setitem(sys.modules, "operations", fake)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "scale_mismatch_experiments", ROOT / "scripts/experiments.py"
    )
    assert spec and spec.loader
    experiments = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(experiments)
    with pytest.raises(RuntimeError, match="count differs"):
        experiments.scale(replicas)


@pytest.mark.parametrize("reply", [{"status": 503}, {"status": 200, "instance": "old"}])
def test_persistent_stale_or_failed_proxy_never_becomes_ready(clock: dict, reply: dict) -> None:
    with pytest.raises(TimeoutError, match="did not stabilize"):
        quota_compare.wait_for_proxy_instances(["current"], lambda: reply, timeout=1)


def test_transport_failure_restarts_preparation_but_contract_errors_propagate(clock: dict) -> None:
    calls = 0

    def transient() -> dict:
        nonlocal calls
        calls += 1
        if calls == 6:
            raise ConnectionError("transient connection")
        return {"status": 200, "instance": "current"}

    proof = quota_compare.wait_for_proxy_instances(["current"], transient)
    assert proof["business_probes"] >= 19
    assert proof["stable_seconds"] >= 3

    def invalid_contract() -> dict:
        raise RuntimeError("invalid positive contract")

    with pytest.raises(RuntimeError, match="invalid positive contract"):
        quota_compare.wait_for_proxy_instances(["current"], invalid_contract)


def test_503_is_retried_only_in_preparation_and_still_fails_the_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Reply:
        status = 503
        headers = {"Retry-After": "1"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit: int) -> bytes:
            return b'{"code":"proxy_unavailable"}'

    monkeypatch.setattr(quota_compare.urllib.request, "urlopen", lambda *args, **kwargs: Reply())
    assert (
        quota_compare._one_request("http://127.0.0.1:1234", "private", preparing=True)["status"]
        == 503
    )
    with pytest.raises(RuntimeError, match="unexpected HTTP status 503"):
        quota_compare._sample("http://127.0.0.1:1234", "private", [0.0])


def container(
    identity: str, hostname: str, *, project: str = PROJECT, service: str = "api"
) -> dict:
    return {
        "Id": identity,
        "Config": {
            "Hostname": hostname,
            "Labels": {
                "com.docker.compose.project": project,
                "com.docker.compose.service": service,
            },
        },
    }


@pytest.mark.parametrize(
    "containers,ids",
    [
        ([container("other-id", "current")], ["expected-id"]),
        ([container("id", "current", project="pf-api-sentinel")], ["id"]),
        ([container("id", "current", service="erp")], ["id"]),
        ([container("a", "same"), container("b", "same")], ["a", "b"]),
    ],
)
def test_readiness_cannot_approve_foreign_ids_projects_services_or_duplicate_hostnames(
    containers: list[dict], ids: list[str]
) -> None:
    with pytest.raises(RuntimeError):
        quota_compare.inspected_instances(containers, PROJECT, ids)


def test_scale_inspects_the_current_deployment_and_returns_preparation_proof(
    monkeypatch: pytest.MonkeyPatch, clock: dict
) -> None:
    events = []
    fake = ModuleType("operations")
    ids = ["new-a", "new-b"]
    fake.ARTIFACTS, fake.PROJECT = ROOT / "artifacts", ROOT
    fake.COMPOSE, fake.COMPOSE_PROJECT = ["docker", "compose", "-p", PROJECT], PROJECT
    fake.LOCAL_URLS = {"proxy": "http://127.0.0.1:1234"}
    fake.credentials = lambda: {"tenant_a": "private"}
    fake.require_disposable = lambda: None
    fake.healthy_targets = lambda: ["a", "b"]

    def compose(*args: str) -> str:
        events.append(args)
        return "\n".join(ids) if args == ("ps", "-q", "api") else ""

    def inspect(*args: str) -> str:
        assert args == ("docker", "inspect", *ids)
        events.append(("inspect",))
        return json.dumps([container("new-a", "a"), container("new-b", "b")])

    def wait(description: str, predicate) -> None:
        events.append(("metrics",))
        assert predicate()

    requests = []

    def request(url: str, token: str) -> tuple:
        assert url.endswith("/v1/stores") and token == "private"
        requests.append(clock["now"])
        return 200, {"items": [{}]}, {"X-Instance-ID": "a" if len(requests) % 2 else "b"}

    fake.compose, fake.command, fake.wait_until, fake.request = compose, inspect, wait, request
    monkeypatch.setitem(sys.modules, "operations", fake)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "scale_experiments", ROOT / "scripts/experiments.py"
    )
    assert spec and spec.loader
    experiments = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(experiments)
    proof = experiments.scale(2)
    assert events[-2:] == [("inspect",), ("metrics",)]
    assert requests[0] >= 3.25
    assert proof["containers"] == ids
    assert proof["replicas"] == 2
    assert proof["expected_instances"] == ["a", "b"]
    assert proof["stable_seconds"] >= 3
