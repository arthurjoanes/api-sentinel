"""Render explicit synthetic UI cases without starting the API or changing its storage."""

import argparse
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from alert_receiver import ui
from alert_receiver.contracts import Incident, IncidentEvent, IncidentPage
from alert_receiver.probe import ProbeState

ROOT = Path(__file__).resolve().parent.parent


def render(output: Path, renderer: ModuleType = ui) -> None:
    output.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    erp = Incident(
        id=43,
        fingerprint="12345678abcdef43",
        starts_at=now - timedelta(minutes=8),
        ends_at=None,
        first_received_at=now - timedelta(minutes=8),
        last_received_at=now - timedelta(seconds=35),
        deliveries=3,
        status="firing",
        labels={"severity": "warning", "service": "api-sentinel"},
        annotations={
            "summary": "Circuito da integração ERP aberto",
            "impact": "Consulta de SKU indisponível. Resumos e vendas usam PostgreSQL.",
            "condition": "Pelo menos uma réplica mantém o circuito do ERP aberto.",
            "window": "20 segundos no perfil de demonstração",
            "action": "Confira falhas do ERP; restaure o simulador e valide as consultas.",
            "runbook_url": "http://localhost:9184/runbooks/erp",
            "dashboard_url": "http://localhost:3104/d/sentinel/api-sentinel",
        },
    )
    recovered = erp.model_copy(
        deep=True,
        update={
            "id": 42,
            "fingerprint": "12345678abcdef42",
            "status": "resolved",
            "deliveries": 4,
            "starts_at": now - timedelta(hours=1),
            "first_received_at": now - timedelta(hours=1),
            "ends_at": now - timedelta(minutes=45),
            "last_received_at": now - timedelta(minutes=44),
            "annotations": {
                "summary": "Consultas OK acima de 500 ms",
                "impact": "Clientes esperam mais que o objetivo de latência.",
                "condition": "Mais de 5% das respostas bem-sucedidas excederam 500 ms.",
                "window": "Janela curta do perfil de demonstração",
                "action": "Compare pool, SQL e cache; abra um trace do período.",
                "runbook_url": "http://localhost:9184/runbooks/latency",
            },
        },
    )
    manual = recovered.model_copy(
        deep=True,
        update={
            "id": 41,
            "fingerprint": "12345678abcdef41",
            "deliveries": 2,
            "starts_at": now - timedelta(hours=3),
            "first_received_at": now - timedelta(hours=3),
            "ends_at": now - timedelta(hours=2),
            "last_received_at": now - timedelta(hours=3),
            "annotations": {
                "summary": "Menos réplicas disponíveis que o esperado",
                "impact": "Menos réplicas para atender às consultas.",
                "condition": "Targets disponíveis abaixo da quantidade esperada.",
                "window": "Perfil de demonstração",
                "action": "Confira descoberta, targets e consulta pelo proxy.",
                "runbook_url": "http://localhost:9184/runbooks/replica",
                "reconciliation": "Demonstração: encerramento administrativo sem entrega resolved.",
            },
        },
    )
    records = [erp, recovered, manual]

    def page(items: list[Incident], firing: int = 1, resolved: int = 2) -> IncidentPage:
        return IncidentPage(
            items, {"firing": firing, "resolved": resolved}, now, now - timedelta(days=30), 30, 100
        )

    probe = ProbeState(
        result="success", checked_at=now, duration_seconds=0.014, expected_replicas=2
    )
    long_incident = erp.model_copy(deep=True)
    long_incident.labels["service"] = "servico-" + "identificador-longo-" * 20
    long_incident.annotations["summary"] = "Falha de observação " + "com contexto extenso " * 20
    cases = {
        "index.html": renderer.home(page(records), probe, "all"),
        "firing.html": renderer.home(page([erp]), probe, "firing"),
        "resolved.html": renderer.home(page([recovered, manual]), probe, "resolved"),
        "empty.html": renderer.home(page([], 0, 0), ProbeState(), "all"),
        "no-active.html": renderer.home(page([], 0, 2), probe, "firing"),
        "stale.html": renderer.home(
            page(records),
            ProbeState(result="success", checked_at=now - timedelta(minutes=2)),
            "all",
        ),
        "disabled.html": renderer.home(page(records), ProbeState(enabled=False), "all"),
        "failure.html": renderer.home(
            page(records), ProbeState(result="network", checked_at=now), "all"
        ),
        "error.html": renderer.problem_page(
            503, "Histórico indisponível", "Confira o armazenamento e tente consultar novamente."
        ),
        "long.html": renderer.home(page([long_incident], 1, 0), probe, "all"),
        "incidents/43/index.html": renderer.incident_detail(
            erp,
            [
                IncidentEvent(
                    received_at=erp.last_received_at,
                    delivered_status="firing",
                    transition="repeated",
                ),
                IncidentEvent(
                    received_at=erp.first_received_at,
                    delivered_status="firing",
                    transition="created",
                ),
            ],
        ),
        "incidents/42/index.html": renderer.incident_detail(
            recovered,
            [
                IncidentEvent(
                    received_at=recovered.last_received_at,
                    delivered_status="firing",
                    transition="late_firing_ignored",
                ),
                IncidentEvent(
                    received_at=recovered.ends_at,
                    delivered_status="resolved",
                    transition="recovered",
                ),
                IncidentEvent(
                    received_at=recovered.first_received_at,
                    delivered_status="firing",
                    transition="created",
                ),
            ],
        ),
        "incidents/41/index.html": renderer.incident_detail(
            manual,
            [
                IncidentEvent(
                    received_at=manual.ends_at,
                    delivered_status="resolved",
                    transition="operator_reconciled",
                ),
                IncidentEvent(
                    received_at=manual.first_received_at,
                    delivered_status="firing",
                    transition="created",
                ),
            ],
        ),
    }
    if hasattr(renderer, "runbook_index"):
        cases["runbooks/index.html"] = renderer.runbook_index()
    for path in (ROOT / "docs/runbooks").glob("*.md"):
        cases[f"runbooks/{path.stem}/index.html"] = renderer.runbook_page(
            path.stem, path.read_text(encoding="utf-8")
        )
    for name, document in cases.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        document = document.replace(
            '<main id="conteudo" tabindex="-1">',
            '<main id="conteudo" tabindex="-1"><p class="review-note">'
            "Prévia da interface · ocorrências sintéticas para revisão; "
            "não é o estado da stack.</p>",
        )
        target.write_text(document, encoding="utf-8", newline="\n")
    for name in ("styles.css", "snapshot.js"):
        (output / name).write_bytes((ROOT / "alert_receiver" / name).read_bytes())
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "generated_at": now.isoformat(),
                "synthetic": True,
                "cases": list(cases),
                "description": "Prévia sintética da interface, sem executar carga ou alertas.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"{len(cases)} páginas de revisão geradas em {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/ui-preview")
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    renderer = ui
    if args.baseline:
        spec = importlib.util.spec_from_file_location("baseline_ui", args.baseline)
        if spec is None or spec.loader is None:
            raise ValueError("Renderizador de referência inválido")
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
    render(args.output, renderer)


if __name__ == "__main__":
    main()
