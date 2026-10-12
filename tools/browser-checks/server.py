"""Serve an isolated receiver fixture from a frozen source tree on loopback."""

import argparse
import hashlib
import importlib
import json
import math
import os
import secrets
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

FIXTURE_NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
NOTICE = (
    '<p class="review-note">Prévia local · dados sintéticos. '
    "Referência dos dados: 12/10/2026, 06:00 UTC.</p>"
)


class FixtureDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FIXTURE_NOW.astimezone(tz) if tz is not None else FIXTURE_NOW.replace(tzinfo=None)


def fingerprint(source: Path) -> dict[str, str]:
    files = []
    for directory in ("alert_receiver", "src", "docs/runbooks"):
        files.extend(
            path
            for path in (source / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
    return {
        path.relative_to(source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(files)
    }


def build_app(source: Path, run_dir: Path):
    sys.path[:0] = [str(source), str(source / "src")]
    # Clock replacement belongs solely to this fixture process. Browser timers,
    # time.monotonic and the production files remain unchanged.
    ui = importlib.import_module("alert_receiver.ui")
    storage = importlib.import_module("alert_receiver.storage")
    probe_module = importlib.import_module("alert_receiver.probe")
    for module in (ui, storage, probe_module):
        if hasattr(module, "datetime"):
            module.datetime = FixtureDatetime
    receiver = importlib.import_module("alert_receiver.app")
    Settings = importlib.import_module("alert_receiver.config").Settings
    contracts = importlib.import_module("alert_receiver.contracts")
    from fastapi.responses import HTMLResponse, Response

    private = run_dir / "private"
    private.mkdir(mode=0o700)
    token = private / "webhook-token"
    token.write_text(secrets.token_urlsafe(48), encoding="ascii")
    token.chmod(0o600)
    app = receiver.create_app(
        Settings(
            database_path=private / "alerts.sqlite3",
            webhook_token_file=token,
            probe_enabled=False,
            public_urls_file=private / "unconfigured-tools.json",
            runbooks_path=source / "docs/runbooks",
        )
    )
    original_layout = ui.layout

    def fixture_layout(title, content, **kwargs):
        return original_layout(title, NOTICE + content, **kwargs)

    ui.layout = fixture_layout
    store = app.state.store
    store.initialize()

    def payload(number: int, status: str = "firing"):
        return contracts.Webhook.model_validate(
            {
                "version": "4",
                "receiver": "browser-checks-fixture",
                "status": status,
                "alerts": [
                    {
                        "fingerprint": f"abcdef12345678{number:02}",
                        "status": status,
                        "startsAt": (FIXTURE_NOW - timedelta(minutes=number * 20)).isoformat(),
                        "endsAt": (FIXTURE_NOW - timedelta(minutes=2)).isoformat()
                        if status == "resolved"
                        else "0001-01-01T00:00:00Z",
                        "labels": {
                            "alertname": {
                                1: "SentinelERP",
                                2: "SentinelLatency",
                                3: "SentinelReplicaLost",
                            }[number],
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
                                1: "Consulta de SKU indisponível. "
                                "Resumos e vendas usam PostgreSQL.",
                                2: "Clientes esperam mais que o objetivo de latência.",
                                3: "Menos réplicas para atender às consultas.",
                            }[number],
                            "condition": "Ocorrência sintética para verificar a apresentação.",
                            "window": "Janela do cenário sintético",
                            "action": "Confira o procedimento e valide a observação antes de agir.",
                            "runbook_url": "http://localhost:9184/runbooks/"
                            + {1: "erp", 2: "latency", 3: "replica"}[number],
                        },
                    }
                ],
            }
        )

    for number in (1, 2, 3):
        store.persist(payload(number))
    store.persist(payload(1))
    store.persist(payload(2, "resolved"))
    store.persist(payload(2))
    store.reconcile_replica(3, "Fixture sintética: encerramento pelo operador, sem resolved.")

    @app.middleware("http")
    async def fixture_readonly(request, call_next):
        if request.method not in {"GET", "HEAD"}:
            return Response(status_code=405, headers={"Allow": "GET, HEAD"})
        return await call_next(request)

    @app.get("/__review/assets/{stylesheet}")
    def review_stylesheet(stylesheet: str, sizes: str = ""):
        if stylesheet == "text-spacing.css":
            css = (
                "html.review-text-spacing * { line-height:1.5 !important; "
                "letter-spacing:.12em !important; word-spacing:.16em !important; }"
                "html.review-text-spacing p { margin-bottom:2em !important; }"
            )
        elif stylesheet == "text-enlarge.css":
            try:
                values = sorted({float(value) for value in sizes.split(",")})
            except ValueError:
                return Response(status_code=400)
            if len(values) > 64 or any(
                not math.isfinite(value) or not 1 <= value <= 100 for value in values
            ):
                return Response(status_code=400)
            # Numeric-only selectors preserve the production CSP. The audit tags
            # text parents with their measured original size, then requests this
            # self-hosted stylesheet to double each size without nested doubling.
            css = "".join(
                f'[data-review-font-size="{value:g}"]'
                + "{font-size:"
                + f"{value * 2:g}px !important;}}"
                for value in values
            )
        else:
            return Response(status_code=404)
        return Response(css, media_type="text/css", headers={"Cache-Control": "no-store"})

    @app.get("/__review/{case}", response_class=HTMLResponse)
    def review_case(case: str):
        records = store.page().records
        active = [item for item in records if item.status == "firing"]
        fresh = probe_module.ProbeState(
            enabled=True,
            result="success",
            checked_at=FIXTURE_NOW,
            duration_seconds=0.014,
            expected_replicas=2,
        )
        probe = fresh
        items, counts, status = records, {"firing": 1, "resolved": 2}, "all"
        if case == "empty":
            items, counts, probe = [], {"firing": 0, "resolved": 0}, probe_module.ProbeState()
        elif case == "no-active":
            items, status = [], "firing"
        elif case in {"disabled", "no-sli"}:
            probe = probe_module.ProbeState(enabled=False)
        elif case == "stale":
            probe = probe_module.ProbeState(
                enabled=True, result="success", checked_at=FIXTURE_NOW - timedelta(minutes=2)
            )
        elif case == "failure":
            probe = probe_module.ProbeState(enabled=True, result="network", checked_at=FIXTURE_NOW)
        elif case in {"error", "update-failure"}:
            return HTMLResponse(
                ui.problem_page(
                    503,
                    "Histórico indisponível",
                    "Falha sintética de leitura. Tente consultar novamente.",
                ),
                status_code=503,
            )
        elif case == "expired-trace":
            return HTMLResponse(
                ui.problem_page(
                    410,
                    "Trace expirado no ensaio",
                    "Fixture: o trace deste período não está disponível. "
                    "O incidente e o runbook continuam acessíveis.",
                ),
                status_code=410,
            )
        elif case == "long":
            item = active[0].model_copy(deep=True)
            item.labels["service"] = "servico-" + "identificador-longo-" * 80
            item.annotations["summary"] = "Observação extensa " * 80
            item.annotations["impact"] = (
                "Conteúdo <script>inseguro</script> tratado como texto. " * 20
            )
            items, counts = [item], {"firing": 1, "resolved": 0}
        elif case == "volume":
            items = [active[0].model_copy(update={"id": number}) for number in range(100, 200)]
            counts = {"firing": 100, "resolved": 0}
        elif case not in {"index", "fresh"}:
            return HTMLResponse(
                ui.problem_page(404, "Cenário não encontrado", "Volte à central."),
                status_code=404,
            )
        page = contracts.IncidentPage(
            items, counts, FIXTURE_NOW, FIXTURE_NOW - timedelta(days=30), 30, 100
        )
        return ui.home(page, probe, status)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--source-commit", default="snapshot")
    args = parser.parse_args()
    source, run_dir = args.source.resolve(), args.run_dir.resolve()
    if not (source / "alert_receiver/app.py").is_file() or not 0 <= args.port <= 65535:
        parser.error("A valid frozen source tree and port are required.")
    run_dir.mkdir(parents=True, exist_ok=False)
    before = fingerprint(source)
    app = build_app(source, run_dir)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)
    port = sock.getsockname()[1]
    import uvicorn

    info = {
        "pid": os.getpid(),
        "url": f"http://127.0.0.1:{port}",
        "port": port,
        "source": str(source),
        "source_commit": args.source_commit,
        "fixture_time": FIXTURE_NOW.isoformat(),
        "synthetic": True,
        "readonly_http": True,
        "source_files_sha256_before": before,
    }

    class FixtureServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                info["status"] = "ready"
                (run_dir / "server.json").write_text(
                    json.dumps(info, indent=2) + "\n", encoding="utf-8", newline="\n"
                )
                print(
                    json.dumps({"status": "ready", "pid": os.getpid(), "url": info["url"]}),
                    flush=True,
                )

    server = FixtureServer(uvicorn.Config(app, access_log=False, log_level="warning"))
    try:
        server.run(sockets=[sock])
    finally:
        info["source_files_sha256_after"] = fingerprint(source)
        info["source_unchanged"] = before == info["source_files_sha256_after"]
        info["status"] = "stopped"
        (run_dir / "server.json").write_text(
            json.dumps(info, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        sock.close()


if __name__ == "__main__":
    main()
