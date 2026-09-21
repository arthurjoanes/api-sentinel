"""Run bounded operational evidence in a fresh project; preserve the demonstration stack."""

import argparse
import concurrent.futures
import hashlib
import http.client
import json
import os
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def record_cleanup_outcome(record: dict, save: Callable[[], None]) -> Iterator[None]:
    if record["status"] == "passed":
        record["status"] = "cleanup_pending"
    save()
    try:
        yield
    except BaseException as exc:
        record["status"] = "failed"
        record["cleanup_failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if record["status"] == "cleanup_pending":
            record["status"] = "passed"
        record["finished_at"] = datetime.now(UTC).isoformat()
        save()


def fingerprint() -> dict[str, str]:
    files = [
        ROOT / name
        for name in (
            "compose.yml",
            "compose.review.yml",
            "compose.test.yml",
            "Dockerfile",
            ".dockerignore",
            ".env.example",
            "pyproject.toml",
            "uv.lock",
            "alembic.ini",
        )
    ]
    for folder in (
        "src",
        "alert_receiver",
        "erp_simulator",
        "scripts",
        "load",
        "monitoring",
        "deploy",
        "migrations",
        "tests",
    ):
        files.extend(
            path
            for path in (ROOT / folder).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["all", "load", "alerts"], default="all")
    parser.add_argument(
        "--keep", action="store_true", help="Keep a successful disposable stack for inspection."
    )
    args = parser.parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ").lower()
    project = "pf-api-sentinel-review-" + run_id
    output = ROOT / "artifacts" / "problem-review" / run_id
    output.mkdir(parents=True, exist_ok=False)
    os.environ["SENTINEL_LAB_PROJECT"] = project
    os.environ["SENTINEL_RUN_DIR"] = str(output)
    os.environ["SENTINEL_TEST_IMAGE"] = "pf-api-sentinel-review:local"
    os.environ["SENTINEL_TEST_ARTIFACTS"] = str(output)
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "--project-directory",
        str(ROOT),
        "--env-file",
        str(ROOT / ".env.example"),
        "-f",
        str(ROOT / "compose.yml"),
        "-f",
        str(ROOT / "compose.review.yml"),
    ]
    record: dict = {
        "schema_version": 1,
        "id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "project": project,
        "scenario": args.scenario,
        "source_files_sha256": fingerprint(),
        "commands": [],
        "status": "running",
    }

    def save() -> None:
        (output / "run.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def run(label: str, command: list[str], timeout: int = 300) -> str:
        print(label, flush=True)
        started = datetime.now(UTC)
        process = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        (output / (label + ".log")).write_text(process.stdout + process.stderr, encoding="utf-8")
        record["commands"].append(
            {
                "name": label,
                "command": command,
                "started_at": started.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "exit_code": process.returncode,
            }
        )
        if process.returncode:
            record["status"] = "failed"
            record["failed_command"] = label
        save()
        if process.returncode:
            raise RuntimeError(
                f"{label}: exit {process.returncode}; veja {output / (label + '.log')}"
            )
        return process.stdout.strip()

    def local(*arguments: str) -> list[str]:
        return [*compose, *arguments]

    def mixed(name: str, mode: str, seconds: int) -> dict:
        before = exp.snapshot()
        measured_start = time.time()

        def resources() -> str:
            time.sleep(seconds / 2)
            return ops.command(
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                *ops.compose("ps", "-q").splitlines(),
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as sampler:
            sample = sampler.submit(resources)
            try:
                run(
                    "load-" + name,
                    local(
                        "run",
                        "--rm",
                        "-T",
                        "-e",
                        "MODE=" + mode,
                        "-e",
                        "SCENARIO=" + name,
                        "-e",
                        "SECONDS=" + str(seconds),
                        "k6",
                        "run",
                        "/load/review.js",
                    ),
                    timeout=seconds + 90,
                )
            finally:
                (output / ("resources-" + name + ".jsonl")).write_text(
                    sample.result(), encoding="utf-8"
                )
                (output / ("metrics-" + name + ".json")).write_text(
                    json.dumps({"before": before, "after": exp.snapshot()}, indent=2),
                    encoding="utf-8",
                )
        result = json.loads((output / ("load-" + name + ".json")).read_text())
        summary = result["sentinel"]
        assert summary["started"] == summary["completed"] == sum(summary["categories"].values())
        assert summary["dropped"] == 0
        if mode in ("quota", "isolation"):
            assert summary["categories"]["tenant_a_quota"] > 0
            assert (
                30 * (seconds - 1) <= summary["categories"]["tenant_a_valid"] <= 30 * (seconds + 1)
            )
        if mode == "degraded":
            assert (
                sum(
                    summary["categories"][key]
                    for key in ("tenant_a_erp_failure", "tenant_b_erp_failure")
                )
                > 0
            )
        observations = {}
        for metric in (
            "sentinel_requests_inflight",
            "sentinel_db_pool_connections",
            "sentinel_erp_circuit_open",
            "sentinel_event_loop_lag_seconds",
            "process_resident_memory_bytes",
        ):
            parameters = urllib.parse.urlencode(
                {
                    "query": metric + '{job="api"}',
                    "start": measured_start,
                    "end": time.time(),
                    "step": "5s",
                }
            )
            status, body, _ = ops.request(
                ops.LOCAL_URLS["prometheus"] + "/api/v1/query_range?" + parameters
            )
            assert status == 200 and body["status"] == "success"
            assert body["data"]["result"], "Métrica ausente: " + metric
            observations[metric] = body["data"]["result"]
        (output / ("observations-" + name + ".json")).write_text(
            json.dumps(observations, indent=2), encoding="utf-8"
        )
        return summary

    tests = ["docker", "compose", "-p", project + "-tests", "-f", str(ROOT / "compose.test.yml")]
    save()
    try:
        record["working_tree"] = run("git-state", ["git", "status", "--short"])
        revision = subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
        record["git_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
        record["revision_probe_exit_code"] = revision.returncode
        record["active_containers_before"] = run(
            "concurrent-services", ["docker", "ps", "--format", "{{.Names}} {{.Image}}"]
        ).splitlines()
        record["docker_resources"] = run(
            "docker-resources",
            [
                "docker",
                "info",
                "--format",
                "CPUs={{.NCPU}} memory_bytes={{.MemTotal}} version={{.ServerVersion}}",
            ],
        )
        record["compose_version"] = run(
            "compose-version", ["docker", "compose", "version", "--short"]
        )
        demo_filter = [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=pf-api-sentinel",
        ]
        record["demo_containers_before"] = run("demo-before", demo_filter).splitlines()
        run("build", local("build", "api"), timeout=600)
        record["image_id"] = run(
            "image-id",
            ["docker", "image", "inspect", "pf-api-sentinel-review:local", "--format", "{{.Id}}"],
        )
        run("lint", local("run", "--rm", "-T", "tools", "ruff", "check", "."))
        run("format", local("run", "--rm", "-T", "tools", "ruff", "format", "--check", "."))
        run("types", local("run", "--rm", "-T", "tools", "mypy", "--cache-dir=/tmp/mypy-cache"))
        run("monitoring", [sys.executable, str(ROOT / "scripts/check_monitoring.py")])
        run(
            "isolated-tests",
            [*tests, "up", "--abort-on-container-exit", "--exit-code-from", "tests", "tests"],
        )
        run("isolated-cleanup", [*tests, "down", "--volumes", "--remove-orphans"])
        run("database", local("up", "-d", "--wait", "postgres", "redis"))
        run("seed", local("run", "--rm", "-T", "tools", "python", "scripts/bootstrap.py"))
        run("start", local("--profile", "observability", "up", "-d", "--scale", "api=2"))

        # Imported only after ephemeral published ports exist; credentials remain in memory.
        import experiments as exp
        import operations as ops

        ops.wait_until(
            "readiness pelo proxy",
            lambda: ops.request(ops.LOCAL_URLS["proxy"] + "/health/ready")[0] == 200,
        )
        ops.wait_until("duas réplicas coletadas", lambda: len(ops.healthy_targets()) == 2)
        record["urls"] = ops.LOCAL_URLS
        print(json.dumps({"urls_locais_desta_execucao": ops.LOCAL_URLS}), flush=True)
        destinations = {
            key: value
            for key, value in ops.LOCAL_URLS.items()
            if key in ("grafana", "jaeger", "prometheus", "alertmanager")
        }
        run(
            "investigation-links",
            local(
                "run",
                "--rm",
                "-T",
                "tools",
                "python",
                "-c",
                "import sys; from pathlib import Path; p=Path('/secrets/public-urls.json'); "
                "p.write_text(sys.argv[1]); p.chmod(0o644)",
                json.dumps(destinations),
            ),
        )
        receiver_url = urllib.parse.urlsplit(ops.LOCAL_URLS["receiver"])
        record["operator_links"] = {}
        for service, base_url in destinations.items():
            connection = http.client.HTTPConnection(
                receiver_url.hostname, receiver_url.port, timeout=3
            )
            try:
                connection.request("GET", "/tools/" + service + "/")
                response = connection.getresponse()
                assert response.status == 307 and response.getheader("Location") == base_url + "/"
                record["operator_links"][service] = {
                    "status": response.status,
                    "location": response.getheader("Location"),
                }
            finally:
                connection.close()
        run("oracle", local("run", "--rm", "-T", "tools", "python", "scripts/review_oracle.py"))
        run(
            "contract-mutations", local("run", "--rm", "-T", "k6", "run", "/load/contract-check.js")
        )
        run(
            "http-tests",
            local(
                "run",
                "--rm",
                "-T",
                "-e",
                "RUN_HTTP_TESTS=1",
                "-e",
                "SENTINEL_EXPECTED_REPLICAS=2",
                "tools",
                "pytest",
                "-q",
                "tests/security",
                "tests/operations",
                "--junitxml=/artifacts/http-tests.xml",
            ),
        )
        if args.scenario in ("all", "load"):
            record["cache"] = exp.cache_experiment()
            record["loads"] = [mixed("warmup", "mixed", 5), mixed("mixed-normal", "mixed", 15)]
            exp.erp_mode("trickle")
            try:
                record["loads"].append(mixed("mixed-erp-degraded", "degraded", 15))
            finally:
                exp.erp_mode("normal")
            recovered_instances: set[str] = set()

            def erp_recovered() -> bool:
                status, body, headers = exp.query("/v1/stores/1/availability/SKU-001")
                if status == 200 and body == {"store_id": 1, "sku": "SKU-001", "available": 21}:
                    recovered_instances.add(
                        {key.lower(): value for key, value in headers.items()}["x-instance-id"]
                    )
                return len(recovered_instances) == 2

            ops.wait_until("ERP recuperado nas duas réplicas", erp_recovered, timeout=30)
            record["recovery"] = mixed("mixed-recovered", "mixed", 10)
            exp.scale(1)
            mixed("warmup-one", "mixed", 5)
            record["loads"].append(mixed("quota-one", "quota", 10))
            exp.scale(2)
            mixed("warmup-two", "mixed", 5)
            record["loads"].append(mixed("quota-two", "quota", 10))
            record["loads"].append(mixed("tenant-isolation", "isolation", 10))
            record["dependencies"] = exp.dependency_experiments()
            record["pressure"] = exp.pressure_experiment()
            record["revocation"] = exp.revocation()
            save()
        if args.scenario in ("all", "alerts"):
            ops.alert_demo()
        run("trace-correlation", [sys.executable, str(ROOT / "scripts/trace_evidence.py")])
        record["final_targets"] = ops.api_target_snapshot()
        assert len(record["final_targets"]) == 2
        assert all(target["health"] == "up" for target in record["final_targets"])
        record["final_incidents"] = ops.incidents()
        assert not any(item["status"] == "firing" for item in record["final_incidents"])
        with urllib.request.urlopen(ops.LOCAL_URLS["receiver"], timeout=3) as central:
            html = central.read(512000).decode("utf-8")
        for service in ("grafana", "jaeger", "prometheus"):
            assert f'href="/tools/{service}/' in html
        (output / "central.html").write_text(html, encoding="utf-8")
        fixture = exp.query("/v1/stores/7/summary?start=2026-01-01&end=2026-01-01", "probe")
        assert (
            fixture[0] == 200
            and fixture[1]["store_id"] == 7
            and fixture[1]["currency"] == "BRL"
            and fixture[1]["revenue_cents"] == 12500
            and fixture[1]["order_count"] == 2
            and fixture[1]["average_ticket_cents"] == 6250
            and fixture[1]["coverage"]["complete"] is True
        )
        record["fixture_final"] = fixture[1]
        record["resources_after"] = run(
            "resources-after",
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{json .}}",
                *ops.compose("ps", "-q").splitlines(),
            ],
        )
        record["demo_containers_after"] = run("demo-after", demo_filter).splitlines()
        assert sorted(record["demo_containers_before"]) == sorted(record["demo_containers_after"])
        secrets = [value.encode() for value in exp.TOKENS.values()]
        for name in ("cursor-key", "webhook-token"):
            secrets.append(ops.compose("exec", "-T", "api", "cat", "/secrets/" + name).encode())
        published = [path for path in output.rglob("*") if path.is_file()]
        leaks = [
            path.relative_to(output).as_posix()
            for path in published
            if any(secret in path.read_bytes() for secret in secrets)
        ]
        record["secret_scan"] = {"files": len(published), "matching_paths": leaks}
        assert not leaks, "Segredo encontrado nos artefatos: " + ", ".join(leaks)
        record["source_unchanged"] = fingerprint() == record["source_files_sha256"]
        assert record["source_unchanged"], "Fontes mudaram durante a medição; repita a execução."
        record["status"] = "passed"
    except BaseException as exc:
        record["status"] = "failed"
        record["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        (output / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")
        try:
            run("failure-api-logs", local("logs", "--no-color", "--tail=200", "api"))
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            pass
        raise
    finally:
        record["verification_finished_at"] = datetime.now(UTC).isoformat()
        # Both names were generated here, never supplied by caller or taken from demo.
        with record_cleanup_outcome(record, save):
            try:
                run("cleanup-tests", [*tests, "down", "--volumes", "--remove-orphans"])
            finally:
                cleanup = local(
                    "--profile",
                    "observability",
                    "--profile",
                    "tools",
                    "down",
                    "--volumes",
                    "--remove-orphans",
                )
                if args.keep and record["status"] == "cleanup_pending":
                    record["cleanup_command"] = cleanup
                    print(
                        "Stack preservada por --keep; cleanup_command está em run.json.",
                        flush=True,
                    )
                else:
                    run("cleanup-lab", cleanup)
    print(f"Evidências: {output}", flush=True)


if __name__ == "__main__":
    main()
