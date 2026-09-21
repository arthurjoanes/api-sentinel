from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit

from alert_receiver.contracts import Incident, IncidentEvent, IncidentPage
from alert_receiver.probe import ProbeState

SEVERITY_LABELS = {"critical": "Crítico", "warning": "Atenção", "info": "Informativo"}


def escape_html(value: object) -> str:
    return escape(str(value), quote=True)


def timestamp(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%d/%m/%Y · %H:%M:%S UTC") if value else "Sem registro"


def local_link(value: str, fallback: str) -> str:
    try:
        url = urlsplit(value)
        if (
            url.scheme in {"http", "https"}
            and url.hostname in {"localhost", "127.0.0.1"}
            and url.port in {3104, 9184, 9104, 9194, 16684}
            and not url.username
            and not url.password
        ):
            service = {
                3104: "grafana",
                16684: "jaeger",
                9104: "prometheus",
                9194: "alertmanager",
            }.get(url.port or 0)
            prefix = "/tools/" + service if service else ""
            return prefix + "/" + url.path.lstrip("/") + ("?" + url.query if url.query else "")
    except ValueError:
        pass
    return fallback


def layout(title: str, content: str, *, snapshot: bool = False) -> str:
    script = '<script src="/snapshot.js" defer></script>' if snapshot else ""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{escape_html(title)} · API Sentinel</title>
<link rel="stylesheet" href="/styles.css">
{script}
</head>
<body>
<a class="skip-link" href="#conteudo">Pular para o conteúdo</a>
<header class="topbar">
<div class="topbar-inner">
<a class="brand" href="/" aria-label="API Sentinel: alertas">
<span class="brand-mark" aria-hidden="true">S</span>
<span>API <strong>Sentinel</strong></span>
</a>
<nav aria-label="Ferramentas">
<a class="nav-current" href="/">Central de alertas</a>
<a href="/tools/grafana/d/sentinel/api-sentinel">Grafana ↗</a>
<a href="/tools/jaeger/">Traces ↗</a>
</nav>
</div>
</header>
<main id="conteudo" tabindex="-1">{content}</main>
<footer>
<span>API Sentinel</span>
<span>Horários em UTC</span>
</footer>
</body>
</html>"""


def incident_card(incident: Incident) -> str:
    annotations = incident.annotations
    active = incident.status == "firing"
    severity = SEVERITY_LABELS.get(incident.labels.get("severity", ""), "Atenção")
    runbook = local_link(
        annotations.get("runbook_url", annotations.get("runbook", "")), "/runbooks/telemetry"
    )
    dashboard = local_link(
        annotations.get("dashboard_url", annotations.get("dashboard", "")),
        "/tools/grafana/d/sentinel/api-sentinel",
    )
    condition = annotations.get("condition", "Veja a regra no Prometheus.")
    window = annotations.get("window", "Veja a configuração ativa.")
    action = annotations.get("action", "Abra o runbook.")
    return f"""<article class="incident {"active" if active else "recovered"}">
<div class="incident-top">
<span class="badge {"bad" if active else "good"}">
{"● Em andamento" if active else "✓ Resolvido"}</span>
<span class="severity">{escape_html(severity)} ·
{escape_html(incident.labels.get("service", "api-sentinel"))}</span>
<span class="incident-number">Incidente #{incident.id}</span>
</div>
<h2>
<a href="/incidents/{incident.id}">{escape_html(annotations["summary"])}</a>
</h2>
<p class="impact">
{escape_html(annotations.get("impact", "Impacto não informado. Veja o runbook."))}</p>
<div class="condition">
<p>{escape_html(condition)}</p>
<small>Janela: {escape_html(window)}</small>
</div>
<dl class="times">
<div>
<dt>Início</dt>
<dd>{escape_html(timestamp(incident.starts_at))}</dd>
</div>
<div>
<dt>{resolution_label(incident)}</dt>
<dd>{escape_html(timestamp(incident.last_received_at if active else incident.ends_at))}</dd>
</div>
</dl>
<div class="action">
<p>{escape_html(action)}</p>
</div>
<div class="incident-bottom">
<a class="button" href="{escape_html(runbook)}">Abrir runbook <span aria-hidden="true">→</span>
</a>
<a class="text-link" href="{escape_html(dashboard)}">Métricas ↗</a>
<a class="delivery-link" href="/incidents/{incident.id}">
{incident.deliveries} entrega{"s" if incident.deliveries != 1 else ""} · histórico</a>
</div>
</article>"""


def incident_row(incident: Incident) -> str:
    active = incident.status == "firing"
    summary = incident.annotations["summary"]
    state = "Em andamento" if active else "Resolvido"
    observed = incident.last_received_at if active else incident.ends_at
    severity = SEVERITY_LABELS.get(incident.labels.get("severity", ""), "Atenção")
    return f"""<li class="incident-row {"active" if active else "recovered"}">
<div class="row-reference"><span>#{incident.id}</span>
<span class="badge {"bad" if active else "good"}">{state}</span></div>
<div class="row-description">
<h3><a href="/incidents/{incident.id}">{escape_html(summary)}</a></h3>
<p>{escape_html(incident.annotations.get("impact", "Impacto não informado."))}</p>
<span class="row-service">{escape_html(severity)} ·
{escape_html(incident.labels.get("service", "api-sentinel"))}</span>
</div>
<div class="row-observation">
<span>{resolution_label(incident)}</span>
<time>{escape_html(timestamp(observed))}</time>
<a href="/incidents/{incident.id}" aria-label="Ver histórico do incidente {incident.id}">
{incident.deliveries} entrega{"s" if incident.deliveries != 1 else ""}
· ver histórico →</a>
</div>
</li>"""


def resolution_label(incident: Incident) -> str:
    if incident.status == "firing":
        return "Última entrega"
    if incident.annotations.get("reconciliation"):
        return "Encerrado pelo operador"
    return "Recuperação"


def probe_observation(probe: ProbeState, observed_at: datetime) -> str:
    observation = probe.observation_status(observed_at)
    unavailable = {
        "disabled": (
            "Probe desativado",
            "Probe desativado neste receiver.",
        ),
        "configuration": ("Consulta indisponível", "Confira a configuração do probe."),
        "pending": (
            "Aguardando o primeiro teste",
            "Sem resultado do probe.",
        ),
        "unavailable": ("Resultado indisponível", "Resultado sem horário válido."),
        "stale": (
            "Resultado desatualizado",
            "O resultado do probe venceu.",
        ),
    }
    expires = ""
    if observation == "fresh":
        success = probe.result == "success"
        title = "Probe OK" if success else "Falha no probe"
        tone = "good" if success else "bad"
        description = (
            "Status, formato e valores corretos."
            if success
            else "Resultado inesperado. Veja o diagnóstico."
        )
        assert probe.checked_at is not None
        remaining = probe.stale_after_seconds - (observed_at - probe.checked_at).total_seconds()
        expires = f' data-expires-in-ms="{max(0, int(remaining * 1000))}"'
    else:
        title, description = unavailable[observation]
        tone = "neutral" if observation in {"pending", "disabled"} else "warn"
    return f"""<section class="observation" aria-label="Probe"{expires}>
<h2><span class="status-dot {tone}" aria-hidden="true"></span>
<span data-observation-title>{title}</span></h2>
<p data-observation-description>{description}</p>
<p class="observation-time">Consultado em {escape_html(timestamp(probe.checked_at))}.</p>
</section>"""


def incident_filters(counts: dict[str, int], status: str) -> str:
    choices = (
        ("all", "Todos", sum(counts.values())),
        ("firing", "Em andamento", counts["firing"]),
        ("resolved", "Resolvidos", counts["resolved"]),
    )
    return "".join(
        f'<a class="filter {"selected" if status == code else ""}" '
        f'{"aria-current=page" if status == code else ""} href="/?status={code}">'
        f"{label}<span>{count}</span></a>"
        for code, label, count in choices
    )


def empty_incidents(status: str, resolved_count: int) -> str:
    title, description = {
        "firing": (
            "Nenhum incidente em andamento",
            "",
        ),
        "resolved": (
            "Nenhum incidente resolvido no período",
            "",
        ),
        "all": (
            "Nenhum incidente no período",
            "",
        ),
    }[status]
    action = (
        '<a class="text-link" href="/?status=resolved">'
        f"Ver {resolved_count} incidentes resolvidos →</a>"
        if status == "firing" and resolved_count
        else '<a class="text-link" href="/tools/prometheus/alerts">Ver regras ↗</a>'
    )
    return f'<section class="empty"><h3>{title}</h3>{action}</section>'


def observation_details(page: IncidentPage, probe: ProbeState) -> str:
    duration = (
        f"{probe.duration_seconds * 1000:.0f} ms"
        if probe.duration_seconds is not None
        else "Não medida"
    )
    desired = probe.expected_replicas if probe.expected_replicas is not None else "Não lido"
    return f"""<div class="diagnostics">
<details>
<summary>Detalhes do teste</summary>
<div class="disclosure-content">
<p>Probe autenticado pelo proxy, com dados próprios.</p>
<dl class="facts">
<div><dt>Valores esperados</dt>
<dd>R$ 125,00 · 2 pedidos · ticket médio de R$ 62,50</dd></div>
<div><dt>Duração</dt><dd>{duration}</dd></div>
<div><dt>Resultado</dt>
<dd><code>{escape_html(probe.result or "ainda não executado")}</code></dd></div>
<div><dt>Validade do resultado</dt><dd>{probe.stale_after_seconds:g} segundos</dd></div>
</dl>
<a class="text-link" href="/runbooks/telemetry">Falhas no probe →</a>
</div>
</details>
<details>
<summary>Monitoramento</summary>
<div class="disclosure-content">
<dl class="facts">
<div><dt>Coleta do Prometheus</dt><dd>Veja no Prometheus.
<a class="text-link" href="/tools/prometheus/targets">Ver targets ↗</a></dd></div>
<div><dt>Réplicas desejadas</dt><dd>{desired}</dd></div>
<div><dt>Réplicas observadas</dt>
<dd>Veja os targets do Prometheus.</dd></div>
<div><dt>Período dos resolvidos</dt><dd>Última entrega ou reconciliação operacional de
{escape_html(timestamp(page.cutoff_at))} até {escape_html(timestamp(page.generated_at))}.</dd></div>
</dl>
<p>Incidentes em andamento não expiram. A retenção de {page.retention_days} dias é aplicada
à última entrega ou reconciliação operacional dos resolvidos, não à data de início.</p>
<p>Um incidente agrupa entregas do mesmo alerta e início. Totais e lista usam a mesma leitura;
a lista mostra até {page.limit} registros, com os ativos primeiro e os mais recentes em seguida.</p>
<a class="text-link" href="/tools/grafana/d/sentinel/api-sentinel">Métricas ↗</a>
</div>
</details>
</div>"""


def home(page: IncidentPage, probe: ProbeState, status: str) -> str:
    counts = page.counts
    entries = "".join(incident_row(incident) for incident in page.records)
    inbox = (
        f'<ol class="incident-list">{entries}</ol>'
        if entries
        else empty_incidents(status, counts["resolved"])
    )
    filtered_total = page.total if status == "all" else counts[status]
    content = f"""<div class="page-heading">
<div><h1>Central de alertas</h1>
<p class="lead"><strong>{counts["firing"]} em andamento</strong> ·
{counts["resolved"]} resolvidos no período</p></div>
<a class="refresh" href="/?status={escape_html(status)}">↻ Atualizar</a>
</div>
<p class="snapshot-time">Leitura de {escape_html(timestamp(page.generated_at))}
· Atualização manual</p>
{probe_observation(probe, datetime.now(UTC))}
<p class="collection-status"><strong>Coleta de métricas:</strong>
<a class="text-link" href="/tools/prometheus/targets">Ver no Prometheus ↗</a></p>
<section class="inbox" aria-label="Incidentes">
<div class="section-heading"><h2>Incidentes</h2>
<span>{len(page.records)} de {filtered_total} incidentes · limite de {page.limit}</span>
</div>
<p class="retention">
Resolvidos: últimos {page.retention_days} dias · Em andamento: sem expiração</p>
<nav class="filters" aria-label="Filtrar incidentes">{incident_filters(counts, status)}</nav>
{inbox}
</section>
{observation_details(page, probe)}"""
    return layout("Central de alertas", content, snapshot=True)


def incident_detail(incident: Incident, events: list[IncidentEvent]) -> str:
    reconciliation = incident.annotations.get("reconciliation")
    notice = (
        '<div class="condition"><strong>Encerrado pelo operador</strong>'
        f"<p>{escape_html(reconciliation)}</p></div>"
        if reconciliation
        else ""
    )
    transitions = {
        "created": "Incidente registrado",
        "recovered": "Recuperação confirmada",
        "repeated": "Entrega repetida; mesmo incidente",
        "late_firing_ignored": "Firing atrasado ignorado; incidente já resolvido",
        "operator_reconciled": "Encerrado pelo operador; sem webhook de recuperação",
    }
    rows = "".join(
        f"<tr><td>{escape_html(timestamp(event.received_at))}</td>"
        f"<td>{'Em andamento' if event.delivered_status == 'firing' else 'Resolvido'}</td>"
        f"<td>{escape_html(transitions.get(event.transition, event.transition))}</td></tr>"
        for event in events
    )
    return layout(
        "Histórico do incidente",
        f"""<a class="back" href="/">← Voltar à central</a>
<div class="detail-heading">
<h1>Incidente #{incident.id}</h1>
</div>{notice}{incident_card(incident)}<section class="history">
<h2>Histórico do incidente</h2>
<p>Até 100 eventos recentes.</p>
<div class="table-scroll" role="region" aria-label="Entregas do incidente" tabindex="0">
<table>
<caption>Entregas e ações do operador</caption>
<thead>
<tr>
<th scope="col">Registrado em</th>
<th scope="col">Estado</th>
<th scope="col">Resultado</th>
</tr>
</thead>
<tbody>{rows}</tbody>
</table>
</div>
<details><summary>Fingerprint e início</summary>
<p class="muted">Fingerprint: <code>{escape_html(incident.fingerprint)}</code>
· Início: {escape_html(timestamp(incident.starts_at))}</p></details>
</section>""",
    )


def runbook_page(slug: str, markdown: str) -> str:
    parts: list[str] = []
    code: list[str] | None = None
    for line in markdown.splitlines():
        if line.startswith("```"):
            if code is None:
                code = []
            else:
                parts.append("<pre><code>" + escape_html("\n".join(code)) + "</code></pre>")
                code = None
        elif code is not None:
            code.append(line)
        elif line.startswith("### "):
            parts.append(f"<h3>{escape_html(line[4:])}</h3>")
        elif line.startswith("## "):
            parts.append(f"<h2>{escape_html(line[3:])}</h2>")
        elif line.startswith("# "):
            parts.append(f"<h1>{escape_html(line[2:])}</h1>")
        elif line.strip():
            parts.append(f"<p>{escape_html(line)}</p>")
    if code is not None:
        parts.append("<pre><code>" + escape_html("\n".join(code)) + "</code></pre>")
    return layout(
        f"Runbook: {slug}",
        '<a class="back" href="/">← Voltar à central</a><article class="runbook">'
        + "".join(parts)
        + "</article>",
    )


def problem_page(status: int, title: str, detail: str) -> str:
    return layout(
        title,
        f'<section class="empty error-page"><p class="eyebrow">HTTP {status}</p>'
        f"<h1>{escape_html(title)}</h1><p>{escape_html(detail)}</p>"
        '<a class="button" href="/">Voltar à central</a></section>',
    )
