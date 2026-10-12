"""Bounded proxy comparison inside a registered, disposable review project."""

import concurrent.futures
import json
import math
import os
import re
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime


def uniform_policy(
    containers: list[dict], project: str, image_id: str, expected_replicas: int
) -> dict:
    """Reject mixed algorithms, capacities, images, or foreign container labels."""
    if len(containers) != expected_replicas or expected_replicas not in (1, 2):
        raise RuntimeError("Quota comparison requires one or two registered API replicas.")
    policies = []
    for container in containers:
        config = container["Config"]
        if config.get("Labels", {}).get("com.docker.compose.project") != project:
            raise RuntimeError("Quota comparison refused a foreign container.")
        if container["Image"] != image_id:
            raise RuntimeError("Quota comparison requires the recorded application image.")
        environment = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
        algorithm = environment.get("QUOTA_ALGORITHM", "fixed-window")
        burst_capacity = int(environment.get("QUOTA_BURST_CAPACITY", "10"))
        if algorithm not in {"fixed-window", "gcra"} or not 1 <= burst_capacity <= 10000:
            raise RuntimeError("An API replica has an invalid quota policy.")
        policies.append((algorithm, burst_capacity))
    if len(set(policies)) != 1:
        raise RuntimeError("Mixed quota policies cannot enforce a combined global quota.")
    algorithm, burst_capacity = policies[0]
    return {"algorithm": algorithm, "burst_capacity": burst_capacity}


def _docker(*arguments: str) -> str:
    result = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    if result.returncode:
        raise RuntimeError("Docker quota inspection failed.")
    return result.stdout.strip()


def _resources(containers: list[str]) -> dict:
    result = {}
    for container in containers:
        cpu = dict(
            line.split()
            for line in _docker("exec", container, "cat", "/sys/fs/cgroup/cpu.stat").splitlines()
        )
        result[container] = {
            "cpu_usage_us": int(cpu["usage_usec"]),
            "memory_bytes": int(_docker("exec", container, "cat", "/sys/fs/cgroup/memory.current")),
        }
    return result


def _local_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise ValueError("Quota comparison requires this review's loopback proxy URL.")
    return base_url.rstrip("/")


def _one_request(base_url: str, token: str) -> dict:
    started = time.monotonic()
    request = urllib.request.Request(
        base_url + "/v1/stores", headers={"Authorization": "Bearer " + token}
    )
    try:
        response = urllib.request.urlopen(request, timeout=3)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        payload = json.loads(response.read(65536))
        status = response.status
        retry = response.headers.get("Retry-After")
        if status == 200:
            if not isinstance(payload.get("items"), list) or not payload["items"]:
                raise RuntimeError("Quota comparison received an invalid positive response.")
        elif status == 429:
            if payload.get("code") != "tenant_quota_exceeded" or not retry or not retry.isdigit():
                raise RuntimeError("Quota comparison received an unexpected 429 contract.")
            if int(retry) < 1:
                raise RuntimeError("Quota Retry-After must be positive.")
        else:
            raise RuntimeError(f"Quota comparison received unexpected HTTP status {status}.")
        return {
            "status": status,
            "retry_after": int(retry) if retry is not None else None,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "instance": response.headers.get("X-Instance-ID"),
        }


def _sample(base_url: str, token: str, offsets: list[float]) -> dict:
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending = []
        for offset in offsets:
            pause = started + offset - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            pending.append(pool.submit(_one_request, base_url, token))
        results = [future.result() for future in pending]
    accepted = sum(result["status"] == 200 for result in results)
    rejected = sum(result["status"] == 429 for result in results)
    if not accepted or not rejected or accepted + rejected != len(offsets):
        raise RuntimeError("Quota comparison must exercise acceptance and quota rejection.")
    latency = sorted(result["latency_ms"] for result in results)
    return {
        "allowed": accepted,
        "rejected": rejected,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "latency_ms": {
            "p50": statistics.median(latency),
            "p95": latency[math.ceil(len(latency) * 0.95) - 1],
            "max": max(latency),
        },
        "responses": results,
    }


def _settle_old_state(compose: Callable[..., str], tenant: int) -> dict:
    # The maintenance program receives a numeric tenant ID, never an HTTP token.
    program = f"""
import asyncio, json, time
from redis.asyncio import Redis
from api_sentinel.config import Settings
async def settle():
    settings = Settings()
    client = Redis.from_url(settings.redis_url, **settings.redis_credentials('quota'))
    keys = ['quota:{tenant}', 'quota:gcra:{tenant}']
    try:
        before = [await client.pttl(key) for key in keys]
        deadline = time.monotonic() + 12
        current = before
        while current != [-2, -2]:
            if -1 in current:
                raise RuntimeError('Previous quota state has no expiry')
            if time.monotonic() >= deadline:
                raise RuntimeError('Previous quota state did not expire')
            await asyncio.sleep(0.05)
            current = [await client.pttl(key) for key in keys]
        print(json.dumps({{'keys': keys, 'before_ttl_ms': before, 'after_ttl_ms': current}}))
    finally:
        await client.aclose()
asyncio.run(settle())
"""
    return json.loads(compose("run", "--rm", "-T", "tools", "python", "-c", program))


def quota_comparison(
    compose: Callable[..., str],
    base_url: str,
    token: str,
    image_id: str,
    *,
    tenant: int = 1,
    quota_per_second: int = 30,
) -> dict:
    """Compare identical inputs, quiesce between policies, and restore fixed-window/2."""
    project = os.environ.get("SENTINEL_LAB_PROJECT", "")
    if not re.fullmatch(r"pf-api-sentinel-review-[a-z0-9-]+", project):
        raise RuntimeError("Quota comparison requires a disposable review project.")
    base_url = _local_base_url(base_url)
    expected_address = compose("port", "proxy", "80").splitlines()[0]
    if urllib.parse.urlsplit(base_url).netloc != expected_address:
        raise ValueError("The proxy URL does not belong to this review project.")
    if tenant != 1 or quota_per_second != 30:
        raise ValueError("The bounded comparison uses the known synthetic tenant 1 at 30/s.")
    offsets = sorted([0.0] * 12 + [index / 40 for index in range(60)] + [0.99, 1.01])
    output = {
        "started_at": datetime.now(UTC).isoformat(),
        "project": project,
        "image_id": image_id,
        "quota_per_second": quota_per_second,
        "burst_capacity": 10,
        "request_offsets_seconds": offsets,
        "scope": "bounded policy comparison; shared daemon; no maximum-throughput claim",
        "phases": [],
    }

    def configure(algorithm: str, replicas: int) -> tuple[list[str], dict, list[str]]:
        os.environ["QUOTA_ALGORITHM"] = algorithm
        os.environ["QUOTA_BURST_CAPACITY"] = "10"
        compose(
            "run",
            "--rm",
            "-T",
            "tools",
            "python",
            "-c",
            "from pathlib import Path; "
            f"Path('/secrets/expected-replicas').write_text('{replicas}')",
        )
        compose("up", "-d", "--no-deps", "--force-recreate", "--scale", f"api={replicas}", "api")
        ids = compose("ps", "-q", "api").splitlines()
        inspected = json.loads(_docker("inspect", *ids))
        policy = uniform_policy(inspected, project, image_id, replicas)
        if policy != {"algorithm": algorithm, "burst_capacity": 10}:
            raise RuntimeError("API replicas did not apply the requested quota policy.")
        expected_instances = sorted(container["Config"]["Hostname"] for container in inspected)
        if len(set(expected_instances)) != replicas or not all(expected_instances):
            raise RuntimeError("API replicas need distinct inspected hostnames.")
        # nginx resolves the service every three seconds. A first successful
        # reply can still coexist with a cached address for a removed replica.
        time.sleep(3.25)
        deadline = time.monotonic() + 30
        seen: set[str] = set()
        consecutive_ready = 0
        while consecutive_ready < 3 or seen != set(expected_instances):
            try:
                with urllib.request.urlopen(base_url + "/health/ready", timeout=3) as response:
                    if response.status != 200:
                        raise RuntimeError("API replica is not ready.")
                positives = [_one_request(base_url, token) for _ in range(replicas)]
                if all(
                    positive["status"] == 200 and positive["instance"] in expected_instances
                    for positive in positives
                ):
                    seen.update(positive["instance"] for positive in positives)
                    consecutive_ready += 1
                else:
                    consecutive_ready = 0
            except (urllib.error.URLError, TimeoutError, RuntimeError):
                consecutive_ready = 0
            if time.monotonic() >= deadline:
                raise TimeoutError("Quota comparison did not reach all inspected API replicas.")
            time.sleep(0.25)
        return ids, policy, expected_instances

    try:
        for algorithm in ("fixed-window", "gcra"):
            for replicas in (1, 2):
                previous = _settle_old_state(compose, tenant)
                ids, policy, expected_instances = configure(algorithm, replicas)
                readiness_state = _settle_old_state(compose, tenant)
                before = _resources(ids)
                phase = _sample(base_url, token, offsets)
                after = _resources(ids)
                phase.update(
                    algorithm=algorithm,
                    replicas=replicas,
                    effective_policy=policy,
                    containers=ids,
                    expected_instances=expected_instances,
                    previous_state=previous,
                    readiness_state=readiness_state,
                    resources_before=before,
                    resources_after=after,
                    api_cpu_usage_us=sum(
                        after[container]["cpu_usage_us"] - before[container]["cpu_usage_us"]
                        for container in ids
                    ),
                )
                if {result["instance"] for result in phase["responses"]} != set(expected_instances):
                    raise RuntimeError("The proxy did not exercise all configured replicas.")
                output["phases"].append(phase)
    finally:
        output["restore_state"] = _settle_old_state(compose, tenant)
        ids, policy, expected_instances = configure("fixed-window", 2)
        output["restored"] = {
            "containers": ids,
            "effective_policy": policy,
            "replicas": 2,
            "expected_instances": expected_instances,
        }
    output["finished_at"] = datetime.now(UTC).isoformat()
    return output
