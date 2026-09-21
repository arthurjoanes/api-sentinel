"""Correlaciona uma consulta local com campos permitidos; não exporta SQL nem headers."""

import json
import subprocess
import time
from datetime import UTC, datetime

from operations import ARTIFACTS, COMPOSE, LOCAL_URLS, PROJECT, credentials, request, wait_until


def main() -> None:
    tokens = credentials()
    recovered = set()

    def ready() -> bool:
        status, _, headers = request(
            LOCAL_URLS["proxy"] + "/v1/stores/1/availability/SKU-001", tokens["tenant_a"]
        )
        if status == 200:
            recovered.add({key.lower(): value for key, value in headers.items()}["x-instance-id"])
        return len(recovered) == 2

    wait_until("ERP normal nas duas réplicas antes da amostragem", ready, timeout=30)
    candidates = []
    for _ in range(16):
        status, _, headers = request(
            LOCAL_URLS["proxy"] + "/v1/stores/1/availability/SKU-001", tokens["tenant_a"]
        )
        assert status == 200
        normalized = {key.lower(): value for key, value in headers.items()}
        candidates.append((normalized["x-trace-id"], normalized["x-request-id"]))
        time.sleep(0.1)
    # O exportador tem atraso configurado de 1 s; somente uma janela pequena é lida.
    time.sleep(2)
    for trace_id, request_id in candidates:
        status, payload, _ = request(LOCAL_URLS["jaeger"] + "/api/traces/" + trace_id)
        if status != 200 or not payload.get("data"):
            continue
        trace = payload["data"][0]
        logs = subprocess.run(
            [*COMPOSE, "logs", "--no-color", "--since", "15s", "--tail", "40", "api"],
            cwd=PROJECT,
            text=True,
            capture_output=True,
            check=True,
        )
        matching = []
        allowed = (
            "timestamp",
            "request_id",
            "trace_id",
            "route",
            "method",
            "status",
            "duration_seconds",
            "error_category",
            "instance",
        )
        for line in logs.stdout.splitlines():
            if trace_id not in line or "{" not in line:
                continue
            record = json.loads(line[line.index("{") :])
            if record.get("request_id") == request_id:
                matching.append({key: record[key] for key in allowed})
        assert matching, "Trace amostrado deve ter log com request_id correspondente."
        spans = [
            {
                "operation": span["operationName"],
                "start_microseconds": span["startTime"],
                "duration_microseconds": span["duration"],
                "span_id": span["spanID"],
                "references": span["references"],
            }
            for span in trace["spans"]
        ]
        assert any(span["operation"].startswith("SELECT") for span in spans)
        assert any(span["operation"] == "EVAL" for span in spans)
        assert any(span["operation"] == "GET" for span in spans)
        result = {
            "executed_at": datetime.now(UTC).isoformat(),
            "trace_id": trace_id,
            "request_id": request_id,
            "logs": matching,
            "spans": spans,
            "scope": "Campos permitidos de uma consulta local; sem SQL, tokens ou headers.",
        }
        (ARTIFACTS / "trace-correlation.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(
            json.dumps({"trace_id": trace_id, "spans": len(spans), "matched_logs": len(matching)})
        )
        return
    raise AssertionError("Sem amostra. Repita a coleta.")


if __name__ == "__main__":
    main()
