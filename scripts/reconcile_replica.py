"""Reconcilia uma perda de réplica da demo sem inventar uma entrega resolved."""

import argparse
import json
import subprocess
import time
import urllib.parse
from datetime import UTC, datetime

from operations import ARTIFACTS, COMPOSE, LOCAL_URLS, PROJECT, api_target_snapshot, request


def prometheus_value(expression: str) -> float:
    query = urllib.parse.urlencode({"query": expression})
    status, body, _ = request(LOCAL_URLS["prometheus"] + "/api/v1/query?" + query)
    if status != 200 or body.get("status") != "success" or len(body["data"]["result"]) != 1:
        raise ValueError("Observação ausente; não é seguro reconciliar a ocorrência.")
    return float(body["data"]["result"][0]["value"][1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("incident_id", type=int)
    args = parser.parse_args()
    incident_url = LOCAL_URLS["receiver"] + f"/api/incidents/{args.incident_id}"
    status, before, _ = request(incident_url)
    if status != 200:
        raise ValueError("Ocorrência não encontrada; nada foi alterado.")
    targets = api_target_snapshot()
    expected = prometheus_value("max(sentinel_expected_replicas)")
    if expected not in (1, 2) or len(targets) != expected:
        raise ValueError("A quantidade observada de réplicas não coincide com a configuração.")
    if not all(
        target["health"] == "up"
        and 0 <= time.time() - datetime.fromisoformat(target["lastScrape"]).timestamp() < 15
        for target in targets
    ):
        raise ValueError("Há réplica ausente ou scrape antigo; reconciliação recusada.")
    if (
        prometheus_value("max(sentinel_probe_success)") != 1
        or prometheus_value("max(sentinel_probe_config_valid)") != 1
    ):
        raise ValueError("A consulta de referência não comprova recuperação.")
    probe_age = time.time() - prometheus_value("max(sentinel_probe_last_run_timestamp_seconds)")
    if not 0 <= probe_age < 15:
        raise ValueError("A consulta de referência está antiga; reconciliação recusada.")
    status, alerts, _ = request(LOCAL_URLS["alertmanager"] + "/api/v2/alerts")
    if status != 200 or alerts:
        raise ValueError("O Alertmanager ainda tem alertas ativos; reconciliação recusada.")
    observed_at = datetime.now(UTC).isoformat()
    observation = (
        f"Reconciliação operacional em {observed_at}: {int(expected)} réplicas com scrape "
        "recente, probe correto e Alertmanager sem alertas. Não houve webhook de recuperação; "
        "o horário registrado é o da confirmação operacional, não o início exato da recuperação."
    )
    code = (
        "import json,sys; from pathlib import Path; "
        "from alert_receiver.storage import AlertStore; value=json.load(sys.stdin); "
        "AlertStore(Path('/receiver-data/alerts.sqlite3')).reconcile_replica("
        "value['incident_id'],value['observation'])"
    )
    result = subprocess.run(
        [
            *COMPOSE,
            "run",
            "--rm",
            "-T",
            "-v",
            f"{PROJECT}:/app:ro",
            "--user",
            "10001",
            "tools",
            "python",
            "-c",
            code,
        ],
        cwd=PROJECT,
        input=json.dumps({"incident_id": args.incident_id, "observation": observation}),
        text=True,
        capture_output=True,
        check=True,
    )
    evidence = {
        "incident_id": args.incident_id,
        "observed_at": observed_at,
        "targets": targets,
        "before": before,
        "after": request(incident_url)[1],
        "probe_age_seconds": probe_age,
        "active_alerts": alerts,
        "transition": "operator_reconciled",
        "observation": observation,
        "command_exit_code": result.returncode,
    }
    (ARTIFACTS / f"reconciliation-{args.incident_id}.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Ocorrência {args.incident_id} reconciliada; entregas originais preservadas.")


if __name__ == "__main__":
    main()
