"""Isolated synthetic receiver for browser review; never loads the demo database."""

import importlib.util
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.responses import HTMLResponse, Response

from alert_receiver import ui
from alert_receiver.app import create_app
from alert_receiver.config import Settings
from alert_receiver.contracts import Webhook
from scripts.render_ui_preview import render

REVIEW_NOTICE = (
    '<p class="review-note">Prévia da interface · ocorrências sintéticas para revisão; '
    "não é o estado da stack.</p>"
)

root = Path("/tmp/review")
root.mkdir(exist_ok=True)
(root / "alerts.db").unlink(missing_ok=True)
token = root / "token"
token.write_text(secrets.token_urlsafe(48))
app = create_app(
    Settings(
        database_path=root / "alerts.db",
        webhook_token_file=token,
        probe_enabled=False,
        public_urls_file=root / "missing-links.json",
    )
)
store = app.state.store
store.initialize()
now = datetime.now(UTC)


def payload(number, status="firing"):
    return Webhook.model_validate(
        {
            "version": "4",
            "receiver": "local",
            "status": status,
            "alerts": [
                {
                    "fingerprint": f"abcdef12345678{number:02}",
                    "status": status,
                    "startsAt": (now - timedelta(minutes=number * 20)).isoformat(),
                    "endsAt": (now - timedelta(minutes=2)).isoformat()
                    if status == "resolved"
                    else "0001-01-01T00:00:00Z",
                    "labels": {
                        "alertname": "SentinelReplicaLost" if number == 3 else "SentinelERP",
                        "environment": "demo",
                        "severity": "warning",
                        "service": "api-sentinel",
                    },
                    "annotations": {
                        "summary": {
                            1: "Circuito da integração ERP aberto",
                            2: "Consultas OK acima de 500 ms",
                            3: "Menos réplicas disponíveis que o esperado",
                        }[number],
                        "impact": {
                            1: "Consulta de SKU indisponível. Resumos e vendas usam PostgreSQL.",
                            2: "Clientes esperam mais que o objetivo de latência.",
                            3: "Menos réplicas para atender às consultas.",
                        }[number],
                        "runbook_url": "http://localhost:9184/runbooks/"
                        + {1: "erp", 2: "latency", 3: "replica"}[number],
                        "action": {
                            1: "Confira falhas do ERP e siga a recuperação do simulador.",
                            2: "Compare espera no pool, SQL e cache no período do alerta.",
                            3: "Confira os targets e valide a consulta pelo proxy.",
                        }[number],
                    },
                    "generatorURL": "http://prometheus:9090/graph",
                }
            ],
        }
    )


for number in (1, 2, 3):
    store.persist(payload(number))
store.persist(payload(1))
store.persist(payload(2, "resolved"))
store.persist(payload(2))
store.reconcile_replica(3, "Exemplo sintético; sem entrega de recuperação.")

original_layout = ui.layout


def review_layout(title, content, **kwargs):
    return original_layout(
        title,
        REVIEW_NOTICE + content,
        **kwargs,
    )


ui.layout = review_layout

spec = importlib.util.spec_from_file_location(
    "baseline_ui", Path(__file__).with_name("baseline_ui.py")
)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
baseline_layout = baseline.layout


def baseline_review_layout(title, content, **kwargs):
    banner = REVIEW_NOTICE
    return (
        baseline_layout(title, banner + content, **kwargs)
        .replace('href="/styles.css"', 'href="/__baseline/styles.css"')
        .replace('src="/snapshot.js"', 'src="/__baseline/snapshot.js"')
    )


baseline.layout = baseline_review_layout


@app.get("/__baseline", response_class=HTMLResponse)
def baseline_home(status: str = "resolved"):
    return baseline.home(store.page(None if status == "all" else status), app.state.probe, status)


@app.get("/__baseline/{asset}")
def baseline_asset(asset: str):
    name = {
        "styles.css": ("baseline.css", "text/css"),
        "snapshot.js": ("baseline.js", "application/javascript"),
    }.get(asset)
    if name is None:
        return Response(status_code=404)
    return Response(Path(__file__).with_name(name[0]).read_text(), media_type=name[1])


@app.get("/__review/{case}", response_class=HTMLResponse)
def synthetic_case(case: str):
    render(root / "states")
    allowed = {"empty", "no-active", "stale", "disabled", "failure", "error", "long", "index"}
    if case not in allowed:
        return HTMLResponse("Unknown review case", status_code=404)
    document = (root / "states" / f"{case}.html").read_text()
    banner = REVIEW_NOTICE
    # The static generator and this live wrapper both mark previews; display the notice once.
    return HTMLResponse(document.replace(banner, "", 1))


@app.get("/__baseline/incident/{incident_id}", response_class=HTMLResponse)
def baseline_detail(incident_id: int, status: str = "all"):
    return baseline.incident_detail(store.incident(incident_id), store.events(incident_id), status)


@app.get("/__volume", response_class=HTMLResponse)
def volume_case(baseline_view: bool = False):
    from alert_receiver.contracts import IncidentPage

    item = store.incident(1)
    page = IncidentPage(
        [item.model_copy(update={"id": n}) for n in range(100, 200)],
        {"firing": 100, "resolved": 0},
        now,
        now - timedelta(days=30),
        30,
        100,
    )
    renderer = baseline if baseline_view else ui
    return renderer.home(page, app.state.probe, "all")
