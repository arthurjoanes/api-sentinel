"""Carga aberta e falhas pequenas, todas limitadas à stack local deste projeto."""

import argparse
import concurrent.futures
import json
import subprocess
import time
from datetime import UTC, datetime

from operations import (
    ARTIFACTS,
    COMPOSE,
    LOCAL_URLS,
    PROJECT,
    command,
    compose,
    credentials,
    healthy_targets,
    request,
    require_disposable,
    wait_until,
)

TOKENS = credentials()
SUMMARY = "/v1/stores/1/summary?start=2026-01-01&end=2026-03-01"
BASE = LOCAL_URLS["proxy"]


def snapshot() -> dict:
    return json.loads(compose("run", "--rm", "-T", "tools", "python", "scripts/snapshot.py"))


def query(path: str = SUMMARY, tenant: str = "tenant_a") -> tuple[int, dict, dict]:
    return request(BASE + path, TOKENS[tenant])


def metric(data: dict, prefix: str) -> float:
    return sum(value for key, value in data["totals"].items() if key.startswith(prefix))


def cache_permissions(enabled: bool) -> None:
    require_disposable()
    permissions = (
        ["+get", "+set", "+del", "+eval", "+ping", "+select", "+client|setinfo"]
        if enabled
        else ["-@all"]
    )
    compose("exec", "-T", "redis", "redis-cli", "ACL", "SETUSER", "cache", *permissions)


def scale(replicas: int) -> None:
    require_disposable()
    compose(
        "run",
        "--rm",
        "-T",
        "tools",
        "python",
        "-c",
        f"from pathlib import Path; Path('/secrets/expected-replicas').write_text('{replicas}')",
    )
    compose("up", "-d", "--no-deps", "--scale", f"api={replicas}", "api")
    wait_until("coleta por réplica", lambda: len(healthy_targets()) == replicas)
    wait_until("readiness", lambda: request(BASE + "/health/ready")[0] == 200)


def run_load(name: str, rate: int, duration: str = "20s", path: str = SUMMARY) -> dict:
    require_disposable()
    print(f"k6 {name}: {rate} chegadas/s por {duration}", flush=True)
    before = snapshot()
    result = subprocess.run(
        [
            *COMPOSE,
            "run",
            "--rm",
            "-T",
            "-e",
            f"RATE={rate}",
            "-e",
            f"DURATION={duration}",
            "-e",
            f"SCENARIO={name}",
            "-e",
            f"REQUEST_PATH={path}",
            "k6",
            "run",
            "/load/steady.js",
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    summary = next(
        (line for line in result.stdout.splitlines() if line.startswith('{"scenario"')),
        "Resumo não encontrado",
    )
    (ARTIFACTS / f"load-{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(summary, flush=True)
    if result.returncode:
        raise RuntimeError(f"k6 falhou: {result.stderr[-1500:]}")
    after = snapshot()
    data = json.loads((ARTIFACTS / f"load-{name}.json").read_text())
    assert data["metrics"]["checks"]["values"]["rate"] == 1, "Status inesperado na carga"
    assert data["sentinel"]["started"] == data["sentinel"]["completed"]
    assert data["sentinel"]["completed"] == sum(
        data["metrics"].get(key, {}).get("values", {}).get("count", 0)
        for key in ("accepted", "quota_rejected", "service_rejected")
    )
    if name != "pool-pressure":
        assert data["metrics"].get("accepted", {}).get("values", {}).get("count", 0) > 0
    assert (
        data["metrics"].get("dropped_iterations", {"values": {"count": 0}})["values"]["count"] == 0
    )
    return {"scenario": name, "before": before, "after": after, "k6": data}


def cache_experiment() -> dict:
    require_disposable()
    compose("exec", "-T", "redis", "redis-cli", "-n", "1", "FLUSHDB")
    assert query("/v1/stores/7/summary?start=2026-01-01&end=2026-01-01", "probe")[0] == 200
    before = snapshot()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        cold = list(pool.map(lambda _: query(), range(4)))
    middle = snapshot()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        warm = list(pool.map(lambda _: query(), range(4)))
    after = snapshot()
    assert all(item[0] == 200 for item in cold + warm)
    version = cold[0][1]["dataset_version"]
    key = f"summary:v1:{version}:1:1:2026-01-01:2026-03-01"
    compose("exec", "-T", "redis", "redis-cli", "-n", "1", "PEXPIRE", key, "1")
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        expired = list(pool.map(lambda _: query(), range(4)))
    final = snapshot()
    assert all(item[0] == 200 for item in expired)
    counter = 'sentinel_db_queries_total{"operation": "summary"}'
    counts = {
        "cold_sql": metric(middle, counter) - metric(before, counter),
        "warm_sql": metric(after, counter) - metric(middle, counter),
        "expiry_sql": metric(final, counter) - metric(after, counter),
        "requests_each_phase": 4,
        "before": before,
        "after": final,
    }
    assert [counts[key] for key in ("cold_sql", "warm_sql", "expiry_sql")] == [1, 0, 1]
    expected = {
        key: cold[0][1][key]
        for key in ("store_id", "revenue_cents", "order_count", "average_ticket_cents")
    }
    assert all(
        {key: item[1][key] for key in expected} == expected for item in cold + warm + expired
    )
    return counts


def erp_mode(mode: str) -> None:
    require_disposable()
    compose(
        "run",
        "--rm",
        "-T",
        "tools",
        "python",
        "-c",
        f"from pathlib import Path; Path('/faults/erp-mode').write_text('{mode}')",
    )


def dependency_experiments() -> dict:
    output: dict = {}
    expected = json.loads((ARTIFACTS / "oracle.json").read_text())["tenants"]["tenant_a"]
    cache_permissions(False)
    try:
        responses = [query() for _ in range(5)]
        output["cache_only"] = [item[0] for item in responses]
        assert output["cache_only"] == [200] * 5
        assert all(
            all(
                item[1][key] == expected[key]
                for key in ("revenue_cents", "order_count", "average_ticket_cents")
            )
            for item in responses
        )
    finally:
        cache_permissions(True)
    compose("stop", "redis")
    try:
        before_down = snapshot()
        response = query()
        output["redis_down"] = {
            "status": response[0],
            "problem": response[1],
            "live": request(BASE + "/health/live")[0],
            "ready": request(BASE + "/health/ready")[0],
        }
        assert response[0] == 503 and response[1]["code"] == "quota_unavailable"
        assert output["redis_down"]["live"] == 200
        assert output["redis_down"]["ready"] == 503
        for _ in range(3):
            status, body, _ = query(
                "/v1/stores/4/summary?start=2026-01-01&end=2026-03-01", "tenant_b"
            )
            assert status == 503 and body["code"] == "quota_unavailable"
        after_down = snapshot()
        counter = 'sentinel_db_queries_total{"operation": "summary"}'
        output["redis_down"]["summary_sql_delta"] = metric(after_down, counter) - metric(
            before_down, counter
        )
        assert output["redis_down"]["summary_sql_delta"] == 0
    finally:
        compose("start", "redis")
    wait_until("Redis recuperado", lambda: query()[0] == 200)
    recovered = query()
    assert all(
        recovered[1][key] == expected[key]
        for key in ("revenue_cents", "order_count", "average_ticket_cents")
    )
    output["redis_recovered"] = {"status": recovered[0], "body": recovered[1]}
    erp_mode("trickle")
    try:
        started = time.monotonic()
        result = query("/v1/stores/1/availability/SKU-001")
        output["trickle"] = {
            "status": result[0],
            "elapsed": time.monotonic() - started,
            "main_status": query()[0],
        }
        assert result[0] == 504 and output["trickle"]["elapsed"] < 1.5
        assert output["trickle"]["main_status"] == 200
        codes = []
        for _ in range(8):
            codes.append(query("/v1/stores/1/availability/SKU-001")[1].get("code"))
        assert "erp_circuit_open" in codes
        output["erp_failure_codes"] = codes
        output["circuit"] = query("/v1/stores/1/availability/SKU-001")[1]
    finally:
        erp_mode("normal")
    wait_until(
        "probe controlado do circuito", lambda: query("/v1/stores/1/availability/SKU-001")[0] == 200
    )
    before = snapshot()
    compose("stop", "jaeger")
    try:
        output["traces_down_load"] = run_load("traces-down", 10, "10s")
        after = snapshot()
        output["traces_memory"] = {
            "before": metric(before, "process_resident_memory_bytes"),
            "after": metric(after, "process_resident_memory_bytes"),
        }
    finally:
        compose("start", "jaeger")
    return output


def pressure_experiment() -> dict:
    cache_permissions(False)
    process = subprocess.Popen(
        [*COMPOSE, "run", "--rm", "-T", "tools", "python", "scripts/db_pressure.py"],
        cwd=PROJECT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        wait_until(
            "bloqueio controlado do banco",
            lambda: compose(
                "run",
                "--rm",
                "-T",
                "tools",
                "python",
                "-c",
                "from pathlib import Path; print(Path('/faults/db-lock-ready').exists())",
            )
            == "True",
            timeout=20,
        )
        result = run_load("pool-pressure", 20, "10s")
        process.communicate(timeout=25)
        assert process.returncode == 0
        assert (
            result["k6"]["metrics"].get("service_rejected", {}).get("values", {}).get("count", 0)
            > 0
        )
        recovered = query()
        assert recovered[0] == 200
        expected = json.loads((ARTIFACTS / "oracle.json").read_text())["tenants"]["tenant_a"]
        assert recovered[1]["revenue_cents"] == expected["revenue_cents"]
        recovered_snapshot = snapshot()
        checked_out = metric(
            recovered_snapshot,
            'sentinel_db_pool_connections{"pool": "data", "state": "checked_out"}',
        )
        assert checked_out == 0
        result["recovered_pool_checked_out"] = checked_out
        result["recovered_revenue_cents"] = recovered[1]["revenue_cents"]
        return result
    finally:
        try:
            if process.poll() is None:
                process.communicate(timeout=25)
        finally:
            cache_permissions(True)


def revocation() -> dict:
    require_disposable()
    name = "verification-" + str(int(time.time()))
    issued = json.loads(
        compose(
            "run",
            "--rm",
            "-T",
            "tools",
            "python",
            "-m",
            "api_sentinel.cli",
            "issue",
            "--tenant",
            "1",
            "--name",
            name,
        )
    )
    seen: dict[str, int] = {}
    for _ in range(8):
        status, _, headers = request(BASE + "/v1/stores", issued["token"])
        assert status == 200
        seen[headers.get("x-instance-id", headers.get("X-Instance-ID", "unknown"))] = status
    assert len(seen) == 2
    compose(
        "run", "--rm", "-T", "tools", "python", "-m", "api_sentinel.cli", "revoke", "--name", name
    )
    rejected: dict[str, int] = {}
    for _ in range(8):
        status, _, headers = request(BASE + "/v1/stores", issued["token"])
        assert status == 401
        rejected[headers.get("x-instance-id", headers.get("X-Instance-ID", "unknown"))] = status
    assert len(rejected) == 2
    return {"before": seen, "after": rejected, "credential_name": name}


def main() -> None:
    require_disposable()
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-dependencies", action="store_true")
    parser.add_argument("--resume-pressure", action="store_true")
    args = parser.parse_args()
    ARTIFACTS.mkdir(exist_ok=True)
    output: dict = {
        "executed_at": datetime.now(UTC).isoformat(),
        "active_containers": command(
            "docker", "ps", "--format", "{{.Names}} {{.Image}}"
        ).splitlines(),
        "loads": [],
    }
    if args.resume_dependencies or args.resume_pressure:
        output = json.loads((ARTIFACTS / "experiments.json").read_text(encoding="utf-8"))
        output["dependencies_restarted_at"] = datetime.now(UTC).isoformat()
    try:
        if not args.resume_dependencies and not args.resume_pressure:
            scale(1)
            cache_permissions(False)
            try:
                output["loads"].append(run_load("baseline-sql-one", 5))
            finally:
                cache_permissions(True)
            output["loads"].append(run_load("warm-one", 20))
            output["loads"].append(run_load("quota-one", 60))
            scale(2)
            output["loads"].append(run_load("warm-two", 20))
            output["loads"].append(run_load("quota-two", 60))
            print("k6 isolamento: tenant A 60/s, tenant B 5/s", flush=True)
            compose("run", "--rm", "-T", "k6", "run", "/load/isolation.js")
            output["isolation"] = json.loads((ARTIFACTS / "load-isolation.json").read_text())
            output["cache"] = cache_experiment()
        if not args.resume_pressure:
            output["dependencies"] = dependency_experiments()
        output["pool_pressure"] = pressure_experiment()
        output["revocation"] = revocation()
        output["explain"] = json.loads(
            compose("run", "--rm", "-T", "tools", "python", "-m", "api_sentinel.cli", "explain")
        )
        output["resources"] = command(
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
            *compose("ps", "-q").splitlines(),
        )
    finally:
        (ARTIFACTS / "experiments.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print("Testes concluídos: artifacts/experiments.json", flush=True)


if __name__ == "__main__":
    main()
