import concurrent.futures
import json
import subprocess
import threading
import time
from datetime import UTC, datetime

from experiments import BASE, TOKENS, erp_mode
from operations import (
    ARTIFACTS,
    command,
    compose,
    owned_container,
    request,
    require_disposable,
    wait_until,
)


def main() -> None:
    require_disposable()
    containers = compose("ps", "-q", "api").splitlines()
    assert len(containers) == 2
    target = containers[-1]
    owned_container(target)
    instance = command("docker", "inspect", "--format", "{{.Config.Hostname}}", target)
    erp_mode("normal")
    recovered: set[str] = set()

    def erp_recovered() -> bool:
        status, _, headers = request(BASE + "/v1/stores/1/availability/SKU-001", TOKENS["tenant_a"])
        if status == 200:
            recovered.add(headers.get("x-instance-id", headers.get("X-Instance-ID", "unknown")))
        return len(recovered) == 2

    wait_until("ERP recuperado nas duas réplicas", erp_recovered)
    erp_mode("trickle")
    barrier = threading.Barrier(5)

    def call() -> dict:
        barrier.wait()
        started = time.monotonic()
        status, payload, headers = request(
            BASE + "/v1/stores/1/availability/SKU-001", TOKENS["tenant_a"]
        )
        return {
            "status": status,
            "elapsed": time.monotonic() - started,
            "problem": payload,
            "instance": headers.get("x-instance-id", headers.get("X-Instance-ID")),
        }

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            calls = [pool.submit(call) for _ in range(4)]
            barrier.wait()
            # Requests já concorrentes; pequeno offset antes do deadline de 900 ms.
            time.sleep(0.12)
            started = time.monotonic()
            command("docker", "stop", "--time", "8", target)
            stop_seconds = time.monotonic() - started
            results = [future.result() for future in calls]
        state = json.loads(command("docker", "inspect", "--format", "{{json .State}}", target))
        logs = subprocess.run(
            ["docker", "logs", "--tail", "30", target], capture_output=True, text=True, check=True
        )
        shutdown_log = [
            line
            for line in (logs.stdout + logs.stderr).splitlines()
            if "shutdown" in line.lower() or "Finished server process" in line
        ]
        # Uvicorn 0.35 reaplica SIGTERM após cleanup: 128+15=143 é o status esperado.
        assert state["ExitCode"] in (0, 143) and not state["OOMKilled"]
        assert any("Application shutdown complete" in line for line in shutdown_log)
        assert stop_seconds < 8
        assert any(item["instance"] == instance and item["status"] == 504 for item in results)
        assert all(item["status"] == 504 for item in results)
        output = {
            "executed_at": datetime.now(UTC).isoformat(),
            "target_instance": instance,
            "stop_seconds": stop_seconds,
            "exit_code": state["ExitCode"],
            "requests": results,
            "shutdown_log": shutdown_log,
        }
        (ARTIFACTS / "graceful-real.json").write_text(
            json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    finally:
        command("docker", "start", target)
        erp_mode("normal")
    wait_until("prontidão após SIGTERM", lambda: request(BASE + "/health/ready")[0] == 200)
    print("SIGTERM: requests concluídos e recursos liberados. Resultado: graceful-real.json")


if __name__ == "__main__":
    main()
