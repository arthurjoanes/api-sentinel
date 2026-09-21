"""Experimentos restritos aos containers e endpoints locais do Sentinel."""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
COMPOSE_PROJECT = os.getenv("SENTINEL_LAB_PROJECT", "pf-api-sentinel")
IS_DISPOSABLE = bool(re.fullmatch(r"pf-api-sentinel-review-[a-z0-9-]+", COMPOSE_PROJECT))
if COMPOSE_PROJECT != "pf-api-sentinel" and not IS_DISPOSABLE:
    raise RuntimeError("Nome de projeto operacional inválido.")
ARTIFACTS = Path(os.getenv("SENTINEL_RUN_DIR", str(PROJECT / "artifacts"))).resolve()
if not ARTIFACTS.is_relative_to(PROJECT / "artifacts"):
    raise RuntimeError("As evidências devem permanecer dentro de artifacts/.")
ENV_FILE = (
    PROJECT / ".env"
    if not IS_DISPOSABLE and (PROJECT / ".env").exists()
    else PROJECT / ".env.example"
)
COMPOSE = [
    "docker",
    "compose",
    "-p",
    COMPOSE_PROJECT,
    "--project-directory",
    str(PROJECT),
    "--env-file",
    str(ENV_FILE),
    "-f",
    str(PROJECT / "compose.yml"),
]
if IS_DISPOSABLE:
    COMPOSE.extend(["-f", str(PROJECT / "compose.review.yml")])
sys.stdout.reconfigure(encoding="utf-8")


def command(*args: str) -> str:
    result = subprocess.run(args, cwd=PROJECT, text=True, encoding="utf-8", capture_output=True)
    if result.returncode:
        raise RuntimeError(f"Comando falhou: {args[0:3]}\n{result.stderr[-3000:]}")
    return result.stdout.strip()


def compose(*args: str) -> str:
    return command(*COMPOSE, *args)


def local_urls() -> dict[str, str]:
    if IS_DISPOSABLE:
        ports = {
            "proxy": 80,
            "receiver": 9184,
            "prometheus": 9090,
            "alertmanager": 9093,
            "jaeger": 16686,
            "grafana": 3000,
        }
        return {
            name: "http://" + compose("port", name, str(port)).splitlines()[0]
            for name, port in ports.items()
        }
    config = json.loads(compose("--profile", "observability", "config", "--format", "json"))
    return {
        name: f"http://127.0.0.1:{config['services'][name]['ports'][0]['published']}"
        for name in ("proxy", "receiver", "prometheus", "alertmanager", "jaeger", "grafana")
    }


LOCAL_URLS = local_urls()


def require_disposable() -> None:
    if not IS_DISPOSABLE:
        raise RuntimeError("Carga e falhas exigem ambiente descartável: python scripts/review.py")


def credentials() -> dict[str, str]:
    if IS_DISPOSABLE:
        return json.loads(compose("exec", "-T", "api", "cat", "/secrets/demo.json"))
    return json.loads((PROJECT / ".runtime/demo.json").read_text())


def request(url: str, token: str | None = None) -> tuple[int, dict, dict]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=4)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(1000000)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"body": body.decode(errors="replace")[:300]}
        return response.status, payload, dict(response.headers)


def wait_until(description: str, predicate, timeout: float = 90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = predicate()
        except (OSError, urllib.error.URLError):
            result = None
        if result:
            return result
        time.sleep(0.5)
    raise TimeoutError(f"Prazo de {timeout}s excedido: {description}")


def incidents() -> list[dict]:
    return request(LOCAL_URLS["receiver"] + "/api/incidents")[1]["incidents"]


def api_target_snapshot() -> list[dict]:
    status, payload, _ = request(LOCAL_URLS["prometheus"] + "/api/v1/targets")
    assert status == 200 and payload["status"] == "success"
    return sorted(
        (
            {key: item[key] for key in ("scrapeUrl", "health", "lastScrape")}
            for item in payload["data"]["activeTargets"]
            if item["labels"]["job"] == "api"
        ),
        key=lambda item: item["scrapeUrl"],
    )


def healthy_targets() -> list[str]:
    return sorted(item["scrapeUrl"] for item in api_target_snapshot() if item["health"] == "up")


def owned_container(container: str) -> None:
    project = command(
        "docker",
        "inspect",
        "--format",
        '{{index .Config.Labels "com.docker.compose.project"}}',
        container,
    )
    if project != COMPOSE_PROJECT:
        raise RuntimeError("Container não pertence ao projeto; operação recusada.")


def incident_cycle(name: str, stop, restore) -> dict:
    before = {item["id"] for item in incidents()}
    started = time.monotonic()
    firing = None
    try:
        stop()
        print(f"Falha aplicada: {name}; aguardando entrega real.", flush=True)

        def find_firing():
            return next(
                (
                    item
                    for item in incidents()
                    if item["id"] not in before
                    and item["labels"]["alertname"] == name
                    and item["status"] == "firing"
                ),
                None,
            )

        firing = wait_until(f"entrega {name}", find_firing)
        detection = time.monotonic() - started
        print(f"{name} recebido em {detection:.2f}s; restaurando componente.", flush=True)
    finally:
        restore()
    assert firing is not None
    recovery_started = time.monotonic()
    resolved = wait_until(
        f"recuperação {name}",
        lambda: next(
            (
                item
                for item in incidents()
                if item["id"] == firing["id"] and item["status"] == "resolved"
            ),
            None,
        ),
    )
    recovery = time.monotonic() - recovery_started
    occurrences = [
        item
        for item in incidents()
        if (item["fingerprint"], item["starts_at"]) == (firing["fingerprint"], firing["starts_at"])
    ]
    assert len(occurrences) == 1
    assert resolved["deliveries"] >= 2
    wait_until(
        f"recuperação de todas as ocorrências criadas durante {name}",
        lambda: not any(
            item["id"] not in before and item["status"] == "firing" for item in incidents()
        ),
    )
    created_incidents = [item for item in incidents() if item["id"] not in before]
    print(f"{name} resolvido em {recovery:.2f}s, uma ocorrência persistida.", flush=True)
    return {
        "alert": name,
        "detection_seconds": round(detection, 3),
        "recovery_seconds": round(recovery, 3),
        "firing": firing,
        "resolved": resolved,
        "occurrence_count": len(occurrences),
        "created_incidents": created_incidents,
    }


def alert_demo() -> None:
    require_disposable()
    wait_until("duas réplicas coletadas", lambda: len(healthy_targets()) == 2)
    ids = compose("ps", "-q", "api").splitlines()
    assert len(ids) == 2
    for container in ids:
        owned_container(container)
    results = [
        incident_cycle(
            "SentinelReplicaLost",
            lambda: command("docker", "stop", "--time", "8", ids[-1]),
            lambda: command("docker", "start", ids[-1]),
        )
    ]
    wait_until("réplicas recuperadas", lambda: len(healthy_targets()) == 2)
    results.append(
        incident_cycle(
            "SentinelUnavailable",
            lambda: compose("stop", "--timeout", "8", "api"),
            lambda: compose("start", "api"),
        )
    )
    wait_until("réplicas após recuperação total", lambda: len(healthy_targets()) == 2)
    old_targets = api_target_snapshot()
    old_ids = sorted(compose("ps", "-q", "api").splitlines())
    recreate_started = datetime.now(UTC)
    compose("up", "-d", "--no-deps", "--force-recreate", "--scale", "api=2", "api")
    recreate_completed = datetime.now(UTC)
    new_ids = sorted(compose("ps", "-q", "api").splitlines())
    assert len(new_ids) == 2 and set(new_ids).isdisjoint(old_ids)
    for container in new_ids:
        owned_container(container)

    def fresh_targets() -> list[dict] | None:
        targets = api_target_snapshot()
        if len(targets) == 2 and all(
            item["health"] == "up"
            and datetime.fromisoformat(item["lastScrape"]) > recreate_completed
            for item in targets
        ):
            return targets
        return None

    new_targets = wait_until("scrape das duas réplicas após recriação concluída", fresh_targets)
    output = {
        "executed_at": datetime.now(UTC).isoformat(),
        "cycles": results,
        "dns_before": [item["scrapeUrl"] for item in old_targets],
        "dns_after_recreate": [item["scrapeUrl"] for item in new_targets],
        "recreation": {
            "started_at": recreate_started.isoformat(),
            "completed_at": recreate_completed.isoformat(),
            "container_ids_before": old_ids,
            "container_ids_after": new_ids,
            "targets_before": old_targets,
            "targets_after": new_targets,
        },
        "receiver_independent": True,
    }
    ARTIFACTS.mkdir(exist_ok=True)
    (ARTIFACTS / "alerts-real.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=["alerts"])
    args = parser.parse_args()
    if args.scenario == "alerts":
        alert_demo()


if __name__ == "__main__":
    main()
