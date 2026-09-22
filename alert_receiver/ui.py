import re
from datetime import UTC, datetime
from html import escape
from urllib.parse import urlsplit

from alert_receiver.contracts import Incident, IncidentEvent, IncidentPage
from alert_receiver.probe import ProbeState

SEVERITY_LABELS = {"critical": "Crítico", "warning": "Atenção", "info": "Informativo"}
RUNBOOKS = {
    "unavailable": ("Consulta indisponível", "Investigar a jornada autenticada pelo proxy."),
    "replica": ("Perda de réplica", "Conferir descoberta, coleta e capacidade disponível."),
    "error-budget": ("Falhas nas consultas", "Separar erros de serviço de recusas previstas."),
    "latency": ("Respostas lentas", "Localizar espera no pool, SQL, cache ou ERP."),
    "saturation": ("Saturação", "Entender a pressão e restaurar o atendimento."),
    "erp": ("Dependência ERP", "Conferir prazos, circuito e isolamento das consultas."),
    "telemetry": (
        "Coleta e entrega de alertas",
        "Investigar probe, métricas e histórico de entregas.",
    ),
}


def escape_html(value: object) -> str:
    return escape(str(value), quote=True)


def timestamp(value: datetime | None) -> str:
    if value is None:
        return "Sem registro"
    if value.tzinfo is None:
        return "Horário sem fuso"
    return value.astimezone(UTC).strftime("%d/%m/%Y · %H:%M:%S UTC")


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


def layout(title: str, content: str, *, snapshot: bool = False, section: str = "incidents") -> str:
    script = '<script src="/snapshot.js" defer></script>' if snapshot else ""
    incidents_current = ' aria-current="location"' if section == "incidents" else ""
    runbooks_current = ' aria-current="location"' if section == "runbooks" else ""
    return f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{escape_html(title)} · API Sentinel</title>
<link rel="stylesheet" href="/styles.css">{script}</head><body>
<a class="skip-link" href="#conteudo">Pular para o conteúdo</a>
<header class="masthead">
<a class="brand" href="/" aria-label="API Sentinel: incidentes">
<span class="brand-mark" aria-hidden="true">S</span>
<span>API <strong>Sentinel</strong><small>Vendas · integrações · operação</small></span></a>
<nav class="primary-nav" aria-label="Navegação principal">
<a href="/"{incidents_current}>Incidentes</a>
<a href="/runbooks"{runbooks_current}>Runbooks</a></nav>
<p class="environment">Laboratório local<span>Dados sintéticos</span></p></header>
<div class="utility-bar"><p>Operação da API <span aria-hidden="true">/</span>
<strong>{escape_html(title)}</strong></p>
<nav class="tools-nav" aria-label="Investigar"><span class="nav-label">Investigar em</span>
<a href="/tools/grafana/d/sentinel/api-sentinel">Métricas <span>Grafana ↗</span></a>
<a href="/tools/jaeger/">Traces <span>Jaeger ↗</span></a>
<a href="/tools/prometheus/targets">Coleta <span>Prometheus ↗</span></a></nav>
</div><div class="workspace">
<main id="conteudo" tabindex="-1">{content}</main>
<footer><span>API de vendas · operação e recuperação</span>
<span>Horários em UTC</span><a href="/runbooks/telemetry">Sobre a observação →</a></footer></div>
</body></html>'''


def incident_state(incident: Incident) -> tuple[str, str]:
    if incident.status == "firing":
        return "Em andamento", "bad"
    if incident.annotations.get("reconciliation"):
        return "Encerrado pelo operador", "neutral"
    return "Resolvido", "good"


def resolution_label(incident: Incident) -> str:
    if incident.status == "firing":
        return "Última entrega"
    if incident.annotations.get("reconciliation"):
        return "Encerrado pelo operador"
    return "Recuperação"


def incident_row(incident: Incident, status: str = "all") -> str:
    state, tone = incident_state(incident)
    observed = incident.last_received_at if incident.status == "firing" else incident.ends_at
    severity = SEVERITY_LABELS.get(incident.labels.get("severity", ""), "Atenção")
    detail_url = f"/incidents/{incident.id}?status={status}"
    return f"""<li class="incident-row {tone}" id="incidente-{incident.id}" tabindex="-1">
<div class="row-description"><div class="row-state"><span class="badge {tone}">{state}</span>
<span class="row-severity">{escape_html(severity)}</span></div>
<h3>{escape_html(incident.annotations["summary"])}</h3>
<p>{escape_html(incident.annotations.get("impact", "Impacto não informado."))}</p>
</div><div class="row-next"><p class="row-recent"><span>{resolution_label(incident)}</span>
<time>{escape_html(timestamp(observed))}</time></p>
<a class="incident-action" href="{escape_html(detail_url)}"
aria-label="Investigar ocorrência {incident.id}">Investigar →</a></div>
<details class="row-metadata"><summary>Identificação e entregas</summary>
<dl class="row-facts"><div><dt>Referência</dt><dd>Incidente #{incident.id}</dd></div>
<div><dt>Serviço</dt><dd>{escape_html(incident.labels.get("service", "api-sentinel"))}</dd></div>
<div><dt>Entregas recebidas</dt>
<dd>{incident.deliveries} entrega{"s" if incident.deliveries != 1 else ""}</dd>
</div></dl></details></li>"""


def probe_observation(probe: ProbeState, observed_at: datetime) -> str:
    observation = probe.observation_status(observed_at)
    unavailable = {
        "disabled": ("Probe desativado", "A consulta de referência não está sendo executada."),
        "configuration": ("Consulta indisponível", "Confira a configuração do probe."),
        "pending": ("Aguardando o primeiro teste", "Ainda não há uma consulta concluída."),
        "unavailable": ("Resultado indisponível", "O horário da observação não é válido."),
        "stale": ("Resultado desatualizado", "O resultado do probe venceu. Atualize a leitura."),
    }
    expires = ""
    if observation == "fresh":
        success = probe.result == "success"
        title = "Consulta de referência validada" if success else "Falha no probe"
        tone = "good" if success else "bad"
        description = (
            "Status, formato e valores esperados conferidos pelo proxy."
            if success
            else "A consulta não foi validada. Abra os detalhes da observação."
        )
        assert probe.checked_at is not None
        remaining = probe.stale_after_seconds - (observed_at - probe.checked_at).total_seconds()
        expires = f' data-expires-in-ms="{max(0, int(remaining * 1000))}"'
    else:
        title, description = unavailable[observation]
        tone = "neutral" if observation in {"pending", "disabled"} else "warn"
    return f'''<section class="observation" aria-label="Consulta de referência"{expires}>
<p class="panel-label">Consulta de referência</p>
<span class="status-dot {tone}" aria-hidden="true"></span>
<div class="observation-result" aria-live="polite"><h2 data-observation-title>{title}</h2>
<p data-observation-description>{description}</p></div>
<div class="observation-time"><span>Última consulta</span>
<time>{escape_html(timestamp(probe.checked_at))}</time>
<a href="#observacao">Detalhes da observação ↓</a></div></section>'''


def incident_filters(counts: dict[str, int], status: str) -> str:
    choices = (
        ("all", "Todos", sum(counts.values())),
        ("firing", "Em andamento", counts["firing"]),
        ("resolved", "Finalizados", counts["resolved"]),
    )
    return "".join(
        f'<a class="filter {"selected" if status == code else ""}" '
        f'{"aria-current=page" if status == code else ""} href="/?status={code}">'
        f'<span class="filter-label">{label}</span><strong>{count}</strong></a>'
        for code, label, count in choices
    )


def empty_incidents(status: str, resolved_count: int) -> str:
    title = {
        "firing": "Nenhum incidente em andamento",
        "resolved": "Nenhum incidente finalizado no período",
        "all": "Nenhum incidente no período",
    }[status]
    action = (
        '<a class="text-link" href="/?status=resolved">'
        f"Ver {resolved_count} incidentes finalizados →</a>"
        if status == "firing" and resolved_count
        else (
            '<a class="text-link" href="/tools/prometheus/alerts">'
            "Conferir regras no Prometheus ↗</a>"
        )
    )
    return f"""<section class="empty"><span class="empty-symbol" aria-hidden="true">—</span>
<h3>{title}</h3><p>Esta lista mostra as ocorrências registradas pelo receiver.
Para verificar a jornada da API, confira a observação do probe.</p>{action}</section>"""


def observation_details(page: IncidentPage, probe: ProbeState) -> str:
    duration = (
        f"{probe.duration_seconds * 1000:.0f} ms"
        if probe.duration_seconds is not None
        else "Não medida"
    )
    desired = probe.expected_replicas if probe.expected_replicas is not None else "Não lido"
    return f"""<section class="diagnostics" aria-label="Escopo desta leitura">
<details id="observacao">
<summary>Detalhes da observação <span>Consulta autenticada pelo proxy</span></summary>
<div class="disclosure-content"><p>O probe confere uma consulta com dados próprios.
Seu resultado não comprova a disponibilidade de todas as réplicas nem a entrega dos alertas.</p>
<dl class="facts facts-grid"><div><dt>Valores esperados</dt>
<dd>R$ 125,00 · 2 pedidos · ticket médio de R$ 62,50</dd></div>
<div><dt>Duração da última consulta</dt><dd>{duration}</dd></div>
<div><dt>Resultado registrado</dt>
<dd><code>{escape_html(probe.result or "ainda não executado")}</code></dd></div>
<div><dt>Validade do resultado</dt><dd>{probe.stale_after_seconds:g} segundos</dd></div>
<div><dt>Réplicas desejadas</dt><dd>{desired}</dd></div>
<div><dt>Réplicas observadas</dt><dd>Veja os targets do Prometheus.
<a href="/tools/prometheus/targets">Ver no Prometheus ↗</a></dd></div></dl>
<a class="text-link" href="/runbooks/telemetry">Investigar falhas na observação →</a>
</div></details>
<details><summary>Período e histórico <span>Como ler esta lista</span></summary>
<div class="disclosure-content">
<p>Incidentes em andamento não expiram. A retenção de {page.retention_days} dias é aplicada
à última entrega ou reconciliação operacional dos finalizados, não à data de início.</p>
<p>Janela: {escape_html(timestamp(page.cutoff_at))} até
{escape_html(timestamp(page.generated_at))}.</p>
<p>Um incidente agrupa entregas do mesmo alerta e início. Totais e lista usam a mesma leitura;
a lista mostra até {page.limit} registros, com os ativos primeiro e os mais recentes em seguida.</p>
<p>O filtro Finalizados reúne recuperações recebidas e encerramentos pelo operador,
identificados em cada ocorrência. Entregas acumuladas podem exceder os eventos disponíveis
no histórico.</p>
</div></details></section>"""


def home(page: IncidentPage, probe: ProbeState, status: str) -> str:
    counts = page.counts
    entries = "".join(incident_row(incident, status) for incident in page.records)
    inbox = (
        f'<ol class="incident-list">{entries}</ol>'
        if entries
        else empty_incidents(status, counts["resolved"])
    )
    filtered_total = page.total if status == "all" else counts[status]
    list_title = {
        "all": "Todas as ocorrências",
        "firing": "Em andamento",
        "resolved": "Finalizados",
    }[status]
    content = f"""<div class="page-heading">
<div><h1>Incidentes</h1><p class="reading-meta">Atualização manual</p></div>
<a class="button secondary" href="/?status={escape_html(status)}">↻ Atualizar leitura</a></div>
<nav class="filters" aria-label="Filtrar incidentes">{incident_filters(counts, status)}</nav>
<div class="triage-layout"><section class="inbox" aria-label="Incidentes">
<div class="inbox-toolbar"><h2>{list_title}</h2><div class="list-scope"><span class="list-count">
{len(page.records)} de {filtered_total} incidentes · limite de {page.limit}</span>
<a class="probe-shortcut" href="#observacao">Ver probe ↓</a></div>
</div>{inbox}
<p class="retention">
Finalizados: últimos {page.retention_days} dias · Em andamento: sem expiração</p></section>
<aside class="triage-aside" aria-label="Observação e escopo">
{probe_observation(probe, datetime.now(UTC))}
{observation_details(page, probe)}</aside></div>"""
    return layout("Incidentes", content, snapshot=True)


def incident_runbook(incident: Incident, status: str) -> str:
    annotations = incident.annotations
    runbook = local_link(
        annotations.get("runbook_url", annotations.get("runbook", "")), "/runbooks/telemetry"
    )
    # A runbook annotation selects a known local procedure, never a return destination.
    slug = urlsplit(runbook).path.removeprefix("/runbooks/")
    if slug not in RUNBOOKS:
        slug = "telemetry"
    return f"/runbooks/{slug}?incident_id={incident.id}&status={status}"


def incident_card(incident: Incident) -> str:
    annotations = incident.annotations
    dashboard = local_link(
        annotations.get("dashboard_url", annotations.get("dashboard", "")),
        "/tools/grafana/d/sentinel/api-sentinel",
    )
    return f'''<section class="incident-context" aria-label="Condição e investigação">
<div class="context-block"><h2>Condição do alerta</h2>
<p>{escape_html(annotations.get("condition", "Veja a regra no Prometheus."))}</p>
<p class="muted">Janela: {escape_html(annotations.get("window", "Veja a configuração ativa."))}</p>
</div>
<div class="context-block investigation"><h2>Investigar</h2>
<a href="{escape_html(dashboard)}">Métricas no Grafana ↗</a>
<a href="/tools/jaeger/">Traces no Jaeger ↗</a>
<a href="/tools/prometheus/alerts">Regras no Prometheus ↗</a></div></section>'''


def event_item(event: IncidentEvent) -> str:
    transitions = {
        "created": ("Incidente registrado", "Primeira entrega desta ocorrência."),
        "recovered": ("Recuperação confirmada", "Entrega de recuperação recebida do Alertmanager."),
        "repeated": ("Entrega repetida; mesmo incidente", "A ocorrência foi preservada."),
        "late_firing_ignored": (
            "Firing atrasado ignorado; incidente já resolvido",
            "A entrega foi registrada sem reabrir a ocorrência.",
        ),
        "operator_reconciled": (
            "Encerrado pelo operador; sem webhook de recuperação",
            "Ação administrativa; não acrescenta uma entrega ao contador.",
        ),
    }
    title, description = transitions.get(event.transition, (event.transition, "Evento registrado."))
    administrative = event.transition == "operator_reconciled"
    source = "Ação do operador" if administrative else f"Entrega {event.delivered_status}"
    tone = "good" if event.transition == "recovered" else "neutral"
    return f"""<li class="timeline-event {tone}">
<div class="event-heading"><h3>{escape_html(title)}</h3>
<time>{escape_html(timestamp(event.received_at))}</time></div>
<p>{escape_html(description)}</p><span class="event-source">{escape_html(source)}</span></li>"""


def incident_detail(incident: Incident, events: list[IncidentEvent], status: str = "all") -> str:
    state, tone = incident_state(incident)
    severity = SEVERITY_LABELS.get(incident.labels.get("severity", ""), "Atenção")
    reconciliation = incident.annotations.get("reconciliation")
    notice = (
        '<aside class="reconciliation"><strong>Encerrado pelo operador.</strong> '
        "Não foi recebida uma entrega de recuperação para esta ocorrência."
        f"<p>{escape_html(reconciliation)}</p></aside>"
        if reconciliation
        else ""
    )
    observed = incident.last_received_at if incident.status == "firing" else incident.ends_at
    history = "".join(event_item(event) for event in events)
    if not history:
        history = (
            '<li class="timeline-empty">Nenhum evento disponível nesta janela de retenção.</li>'
        )
    return layout(
        f"Incidente #{incident.id}",
        f"""<a class="back" href="/?status={escape_html(status)}#incidente-{incident.id}">
← Voltar à central</a>
<div class="detail-heading"><div class="detail-labels">
<span class="badge {tone}">{state}</span><span>Incidente #{incident.id}</span>
<span>{escape_html(severity)}</span>
<span>{escape_html(incident.labels.get("service", "api-sentinel"))}</span></div>
<h1>{escape_html(incident.annotations["summary"])}</h1>
<div class="decision-strip"><div><h2>Impacto</h2>
<p>{escape_html(incident.annotations.get("impact", "Impacto não informado. Veja o runbook."))}</p>
</div><div><h2>Próximo passo</h2>
<p>{escape_html(incident.annotations.get("action", "Abra o runbook desta ocorrência."))}</p>
<a class="button" href="{escape_html(incident_runbook(incident, status))}">Abrir runbook →</a>
</div></div><details class="incident-metadata"><summary>Datas e entregas</summary>
<dl class="incident-times"><div><dt>Início do alerta</dt>
<dd>{escape_html(timestamp(incident.starts_at))}</dd></div>
<div><dt>{resolution_label(incident)}</dt><dd>{escape_html(timestamp(observed))}</dd></div>
<div><dt>Entregas recebidas</dt><dd><a href="#historico">
{incident.deliveries} entrega{"s" if incident.deliveries != 1 else ""} · histórico ↓</a>
</dd></div></dl></details></div>
{notice}<div class="incident-workspace">
<section class="history" id="historico" tabindex="-1"><div class="section-heading">
<div><p class="eyebrow">Entregas e ações do operador</p><h2>Histórico do incidente</h2></div>
<span>{len(events)} evento{"s" if len(events) != 1 else ""}</span></div>
<p class="history-scope">Até 100 eventos recentes, do mais novo para o mais antigo.</p>
<ol class="timeline">{history}</ol>
<details><summary>Identidade da ocorrência</summary><div class="disclosure-content">
<p>Fingerprint: <code>{escape_html(incident.fingerprint)}</code></p>
<p>Início: {escape_html(timestamp(incident.starts_at))}</p>
<a class="text-link" href="/api/incidents/{incident.id}">Abrir registro JSON →</a></div></details>
</section>{incident_card(incident)}</div>""",
    )


def runbook_index() -> str:
    entries = "".join(
        f'<a class="runbook-entry" href="/runbooks/{slug}"><span class="runbook-number">'
        f"{index:02d}</span><div><h2>{escape_html(title)}</h2><p>{escape_html(description)}</p>"
        '<span class="text-link">Abrir procedimento →</span></div></a>'
        for index, (slug, (title, description)) in enumerate(RUNBOOKS.items(), 1)
    )
    return layout(
        "Runbooks",
        '<div class="page-heading"><div><p class="eyebrow">Investigar e recuperar</p>'
        '<h1>Runbooks</h1><p class="lead">Procedimentos para os alertas deste laboratório.</p>'
        '</div><a class="text-link" href="/">Ver incidentes →</a></div>'
        '<p class="runbook-intro">Comece pela condição registrada no incidente. Confira a causa, '
        "aplique o procedimento ao projeto correto e confirme a recuperação.</p>"
        f'<div class="runbook-list">{entries}</div>',
        section="runbooks",
    )


def inline_markdown(value: str) -> str:
    # Only inline code is supported; all text, including HTML and links, is escaped.
    return "".join(
        f"<code>{escape_html(part)}</code>" if index % 2 else escape_html(part)
        for index, part in enumerate(value.split("`"))
    )


def runbook_page(
    slug: str, markdown: str, *, incident_id: int | None = None, status: str = "all"
) -> str:
    parts: list[str] = []
    sections: list[str] = []
    code: list[str] | None = None
    list_tag: str | None = None
    for line in markdown.splitlines():
        ordered = re.match(r"^\d+\. (.+)", line)
        item_tag = "ol" if ordered else "ul" if line.startswith("- ") else None
        if list_tag is not None and (item_tag != list_tag or code is not None):
            parts.append(f"</{list_tag}>")
            list_tag = None
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
            anchor = f"etapa-{len(sections) + 1}"
            parts.append(f'<h2 id="{anchor}" tabindex="-1">{escape_html(line[3:])}</h2>')
            sections.append(f'<a href="#{anchor}">{escape_html(line[3:])}</a>')
        elif line.startswith("# "):
            parts.append(f"<h1>{escape_html(line[2:])}</h1>")
        elif item_tag is not None:
            if list_tag is None:
                list_tag = item_tag
                parts.append(f"<{list_tag}>")
            item = ordered.group(1) if ordered else line[2:]
            parts.append(f"<li>{inline_markdown(item)}</li>")
        elif line.strip():
            parts.append(f"<p>{inline_markdown(line)}</p>")
    if list_tag is not None:
        parts.append(f"</{list_tag}>")
    if code is not None:
        parts.append("<pre><code>" + escape_html("\n".join(code)) + "</code></pre>")
    title = RUNBOOKS.get(slug, (slug, ""))[0]
    back = (
        f'<a class="back" href="/incidents/{incident_id}?status={escape_html(status)}">'
        f"← Voltar ao incidente #{incident_id}</a>"
        if incident_id is not None
        else '<a class="back" href="/runbooks">← Todos os runbooks</a>'
    )
    central = f"/?status={status}" + (f"#incidente-{incident_id}" if incident_id else "")
    return layout(
        f"Runbook · {title}",
        back + '<div class="runbook-workspace"><article class="runbook">'
        '<p class="eyebrow">Procedimento operacional</p>'
        + "".join(parts)
        + '</article><aside class="runbook-outline"><nav aria-label="Neste procedimento">'
        '<p class="eyebrow">Neste procedimento</p>'
        + "".join(sections)
        + f'</nav><a class="text-link" href="{escape_html(central)}">'
        "Voltar à central →</a></aside></div>",
        section="runbooks",
    )


def problem_page(status: int, title: str, detail: str) -> str:
    return layout(
        title,
        f'<section class="empty error-page"><p class="eyebrow">HTTP {status}</p>'
        f"<h1>{escape_html(title)}</h1><p>{escape_html(detail)}</p>"
        '<a class="button" href="/">Voltar à central</a></section>',
    )
