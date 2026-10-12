import re
from datetime import UTC, datetime, timedelta
from html import escape
from urllib.parse import parse_qsl, urlencode, urlsplit

from alert_receiver.code_format import code_block
from alert_receiver.contracts import Incident, IncidentEvent, IncidentPage
from alert_receiver.incident_visual import period_graphic
from alert_receiver.probe import ProbeState
from alert_receiver.visual_summary import overview_charts

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


def compact_timestamp(value: datetime | None) -> str:
    if value is None or value.tzinfo is None:
        return timestamp(value)
    return value.astimezone(UTC).strftime("%d/%m/%Y · %H:%M UTC")


def central_url(status: str, incident_id: int | None = None) -> str:
    status = status if status in {"all", "firing", "resolved"} else "all"
    target = f"/?status={status}"
    if incident_id is not None and 1 <= incident_id <= 2**63 - 1:
        target += f"#incidente-{incident_id}"
    return target


def tool_context(value: str, status: str, incident_id: int) -> str:
    target = urlsplit(value)
    query = dict(parse_qsl(target.query))
    query.update(sentinel_status=status, sentinel_incident=str(incident_id))
    return target.path + "?" + urlencode(query)


def incident_lookup(status: str, *, error: str | None = None, value: str = "") -> str:
    error_markup = (
        f'<p class="field-error" id="incident-id-error" role="alert">{escape_html(error)}</p>'
        if error
        else ""
    )
    invalid = ' aria-invalid="true" aria-describedby="incident-id-error"' if error else ""
    return f'''<form id="buscar-incidente" class="incident-lookup"
action="/incident-lookup" method="get">
<input type="hidden" name="status" value="{escape_html(status)}">
<div class="lookup-fields"><label class="visually-hidden" for="incident-id">
Abrir incidente por ID</label>
<input id="incident-id" name="incident_id" type="text" inputmode="numeric" pattern="[0-9]{{1,19}}"
maxlength="19" autocomplete="off" spellcheck="false" required placeholder="ID do incidente"
value="{escape_html(value)}"{invalid}>
<button class="button secondary" type="submit" aria-label="Abrir incidente">Abrir →</button>
</div>{error_markup}
<p>Fora da lista? Use o ID da ocorrência.</p>
</form>'''


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
<meta name="theme-color" content="#14334b">
<title>{escape_html(title)} · API Sentinel</title>
<link rel="icon" href="/assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/styles.css">{script}</head><body>
<a class="skip-link" href="#conteudo">Pular para o conteúdo</a>
<header class="masthead">
<a class="brand" href="/" aria-label="API Sentinel: incidentes">
<img class="brand-mark" src="/assets/mark-light.svg" width="32" height="32" alt="">
<span>API <strong>Sentinel</strong></span></a>
<nav class="primary-nav" aria-label="Navegação principal">
<a href="/"{incidents_current}>Incidentes</a>
<a href="/runbooks"{runbooks_current}>Runbooks</a></nav>
<p class="environment">Laboratório local<span>Dados sintéticos</span></p></header>
<div class="utility-bar"><p>Receiver de alertas</p>
<nav class="tools-nav" aria-label="Investigar"><span class="nav-label">Investigar</span>
<a href="/tools/grafana/d/sentinel/api-sentinel">Métricas <span>Grafana ↗</span></a>
<a href="/tools/jaeger/">Traces <span>Jaeger ↗</span></a>
<a href="/tools/prometheus/targets">Coleta <span>Prometheus ↗</span></a></nav>
</div><div class="workspace">
<main id="conteudo" tabindex="-1">{content}</main>
<footer><span>API de vendas · operação e recuperação</span>
<span>Horários em UTC</span><a href="/runbooks/telemetry">Sobre a observação</a></footer></div>
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
<div class="row-state"><span class="badge {tone}">{state}</span>
<span class="row-severity">{escape_html(severity)}</span></div>
<div class="row-description">
<h3><span class="row-reference"><span class="visually-hidden">Incidente </span>#{incident.id}</span>
{escape_html(incident.annotations["summary"])}</h3>
<details class="row-metadata"><summary>Identificação e entregas</summary>
<p class="row-impact">
{escape_html(incident.annotations.get("impact", "Impacto não informado."))}</p>
<dl class="row-facts"><div><dt>Referência</dt><dd>Incidente #{incident.id}</dd></div>
<div><dt>Serviço</dt><dd>{escape_html(incident.labels.get("service", "api-sentinel"))}</dd></div>
<div><dt>Entregas recebidas</dt>
<dd>{incident.deliveries} entrega{"s" if incident.deliveries != 1 else ""}</dd>
</div></dl></details></div>
<div class="row-recent"><p class="row-start"><span>Início</span>
<time datetime="{escape_html(incident.starts_at.isoformat())}"
title="{escape_html(timestamp(incident.starts_at))}">
{escape_html(compact_timestamp(incident.starts_at))}</time></p>
<p><span>{resolution_label(incident)}</span>
<time title="{escape_html(timestamp(observed))}">
{escape_html(compact_timestamp(observed))}</time></p></div>
<a class="incident-action" href="{escape_html(detail_url)}"
aria-label="Investigar ocorrência {incident.id}">Investigar</a></li>"""


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
        deadline = probe.checked_at + timedelta(seconds=probe.stale_after_seconds)
        expires = (
            f' data-expires-in-ms="{max(0, int(remaining * 1000))}"'
            f' data-observed-at-ms="{int(observed_at.timestamp() * 1000)}"'
            f' data-expires-at-ms="{int(deadline.timestamp() * 1000)}"'
        )
    else:
        title, description = unavailable[observation]
        tone = "neutral" if observation in {"pending", "disabled"} else "warn"
    return f'''<section class="observation" aria-label="Consulta de referência"{expires}>
<span class="status-dot {tone}" aria-hidden="true"></span>
<div class="observation-result" aria-live="polite"><h2 data-observation-title>{title}</h2>
<p data-observation-description>{description}</p></div>
<div class="observation-time"><span>Última consulta</span>
<time>{escape_html(timestamp(probe.checked_at))}</time>
</div></section>'''


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
    return f"""<section class="empty"><div><h3>{title}</h3>
<p>Ausência de registros não confirma disponibilidade. Confira a observação do probe.</p>
</div>{action}</section>"""


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


def home(
    page: IncidentPage,
    probe: ProbeState,
    status: str,
    *,
    lookup_error: str | None = None,
    lookup_value: str = "",
) -> str:
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
    columns = (
        '<div class="queue-columns" aria-hidden="true"><span>Estado</span>'
        "<span>Ocorrência</span><span>Período registrado</span><span>Ação</span></div>"
        if entries
        else ""
    )
    content = f"""<div class="incident-central"><div class="page-heading"><div><h1>Incidentes</h1>
<p class="reading-meta snapshot-meta">Leitura de {escape_html(timestamp(page.generated_at))}
· Atualização manual</p></div>
<a class="button secondary" href="/?status={escape_html(status)}">Atualizar leitura</a></div>
{overview_charts(page, status)}
<div class="triage-workspace">
<section class="observation-workspace" aria-label="Observação e escopo">
{probe_observation(probe, datetime.now(UTC))}
<details class="observation-disclosure"><summary>Escopo da leitura</summary>
{observation_details(page, probe)}</details></section>
<section class="inbox" aria-label="Incidentes">
<div class="queue-heading"><h2>Investigar ocorrências</h2>
{incident_lookup(status, error=lookup_error, value=lookup_value)}</div>
<div class="queue-controls">
<nav class="filters" aria-label="Filtrar incidentes">{incident_filters(counts, status)}</nav>
<div class="list-scope"><h2 class="visually-hidden">{list_title}</h2><span class="list-count">
{len(page.records)} de {filtered_total} incidentes · limite de {page.limit}</span>
<a href="#observacao">Ver probe</a>
</div></div>{columns}{inbox}
<p class="retention">
Finalizados: últimos {page.retention_days} dias · Em andamento: sem expiração · Atualização manual
</p></section></div></div>"""
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


def evidence_period(incident: Incident) -> tuple[datetime, datetime] | None:
    """Bound historical links to saved UTC evidence; never infer a current observation."""
    start = incident.starts_at
    end = incident.ends_at if incident.status == "resolved" else incident.last_received_at
    if end is None or start.tzinfo is None or end.tzinfo is None or end < start:
        return None
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    if start.timestamp() < 0 or end.timestamp() < 0:
        return None
    return max(start, end - timedelta(hours=24)), end + timedelta(seconds=end == start)


def incident_card(incident: Incident, status: str = "all") -> str:
    annotations = incident.annotations
    dashboard = local_link(
        annotations.get("dashboard_url", annotations.get("dashboard", "")),
        "/tools/grafana/d/sentinel/api-sentinel",
    )
    if not dashboard.startswith("/tools/grafana/"):
        dashboard = "/tools/grafana/d/sentinel/api-sentinel"
    period = evidence_period(incident)
    if period is None:
        evidence = '<p class="evidence-scope">Período da evidência indisponível.</p>'
    else:
        start, end = period
        dashboard_target = urlsplit(dashboard)
        parameters = dict(parse_qsl(dashboard_target.query))
        parameters.update(
            from_=str(int(start.timestamp() * 1000)), to=str(int(end.timestamp() * 1000))
        )
        parameters["from"] = parameters.pop("from_")
        metrics = tool_context(
            dashboard_target.path + "?" + urlencode(parameters), status, incident.id
        )
        traces = tool_context(
            "/tools/jaeger/search?"
            + urlencode(
                {
                    "service": "api-sentinel",
                    "start": int(start.timestamp() * 1_000_000),
                    "end": int(end.timestamp() * 1_000_000),
                    "lookback": "custom",
                    "limit": 20,
                }
            ),
            status,
            incident.id,
        )
        recut = (
            "Recorte de até 24 horas, até o último registro. " if start > incident.starts_at else ""
        )
        evidence = f'''<div class="evidence-links">
<a href="{escape_html(metrics)}">Métricas do período no Grafana ↗</a>
<a href="{escape_html(traces)}">Traces do período no Jaeger ↗</a></div>
<p class="evidence-scope">{recut}{escape_html(timestamp(start))} até {escape_html(timestamp(end))}.
Traces são amostrados; a ausência de resultados não comprova ausência de chamadas.</p>'''
    rules = tool_context("/tools/prometheus/alerts", status, incident.id)
    return f'''<section class="incident-context" aria-label="Condição e investigação">
<div class="context-block"><details><summary>Condição do alerta</summary>
<div class="disclosure-content">
<p>{escape_html(annotations.get("condition", "Veja a regra no Prometheus."))}</p>
<p class="muted">Janela: {escape_html(annotations.get("window", "Veja a configuração ativa."))}</p>
</div></details></div>
<div class="context-block investigation"><h2>Evidências do período</h2>
{evidence}
<a href="{escape_html(rules)}">Regras atuais no Prometheus ↗</a>
<p class="evidence-scope">Regras atuais podem diferir das condições desta ocorrência.</p>
</div></section>'''


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
<div class="event-heading"><time>{escape_html(timestamp(event.received_at))}</time>
<h3>{escape_html(title)}</h3></div>
<details class="event-detail"><summary>Origem e interpretação</summary>
<p>{escape_html(description)}</p><span class="event-source">{escape_html(source)}</span>
</details></li>"""


def incident_detail(
    incident: Incident,
    events: list[IncidentEvent],
    status: str = "all",
    *,
    generated_at: datetime | None = None,
) -> str:
    state, tone = incident_state(incident)
    severity = SEVERITY_LABELS.get(incident.labels.get("severity", ""), "Atenção")
    reconciliation = incident.annotations.get("reconciliation")
    active = incident.status == "firing"
    alert_action = incident.annotations.get("action", "Abra o runbook desta ocorrência.")
    if active:
        next_step = alert_action
        state_description = "O receiver ainda não registrou recuperação nem encerramento."
    elif reconciliation:
        next_step = "Confira o motivo do encerramento e a observação atual antes de intervir."
        state_description = "Encerramento administrativo; não confirma a recuperação da API."
    else:
        next_step = "Confira a observação atual e as métricas antes de iniciar outra intervenção."
        state_description = "O Alertmanager entregou a recuperação desta ocorrência."
    original_action = (
        '<div class="original-action"><h3>Orientação original do alerta</h3>'
        f"<p>{escape_html(alert_action)}</p>"
        "<p>Registrada quando o alerta estava em andamento.</p></div>"
        if not active
        else ""
    )
    observation_link = (
        f'<a class="button" href="/?status={escape_html(status)}#observacao">'
        "Conferir observação atual</a>"
        if not active
        else ""
    )
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
    snapshot_time = (
        timestamp(generated_at) if generated_at is not None else "Instante não registrado"
    )
    return layout(
        f"Incidente #{incident.id}",
        f"""<a class="back" href="/?status={escape_html(status)}#incidente-{incident.id}">
← Voltar à central</a>
<div class="detail-heading {tone}"><div class="detail-labels">
<span class="badge {tone}">{state}</span><span>Incidente #{incident.id}</span>
<span>{escape_html(severity)}</span>
<span>{escape_html(incident.labels.get("service", "api-sentinel"))}</span></div>
<h1>{escape_html(incident.annotations["summary"])}</h1>
<p class="state-description">{state_description}</p>
<div class="detail-period"><p class="snapshot-meta">Leitura de {escape_html(snapshot_time)}
· Atualização manual</p>
<a class="text-link" href="/incidents/{incident.id}?status={escape_html(status)}">
Atualizar ocorrência</a></div>
{period_graphic(incident)}
<div class="decision-strip"><div><h2>{"Impacto" if active else "Impacto registrado"}</h2>
<p>{escape_html(incident.annotations.get("impact", "Impacto não informado. Veja o runbook."))}</p>
</div><div><h2>Investigar</h2>
<div class="decision-actions">
{observation_link}
<a class="{"button" if active else "text-link"}"
href="{escape_html(incident_runbook(incident, status))}">Abrir runbook</a>
</div><details class="decision-explanation"><summary>Ver orientação</summary>
<p>{escape_html(next_step)}</p></details></div></div>
<details class="incident-metadata"><summary>Datas e entregas</summary>
<dl class="incident-times"><div><dt>Início do alerta</dt>
<dd>{escape_html(timestamp(incident.starts_at))}</dd></div>
<div><dt>{resolution_label(incident)}</dt><dd>{escape_html(timestamp(observed))}</dd></div>
<div><dt>Entregas recebidas</dt><dd><a href="#historico">
{incident.deliveries} entrega{"s" if incident.deliveries != 1 else ""} · histórico ↓</a>
</dd></div></dl>{original_action}</details></div>
{notice}<div class="incident-workspace">
<section class="history" id="historico" tabindex="-1"><div class="section-heading">
<div><h2>Histórico do incidente</h2></div>
<span>{len(events)} evento{"s" if len(events) != 1 else ""}</span></div>
<p class="history-scope">Até 100 eventos · mais recentes primeiro · horários do receiver.</p>
<ol class="timeline">{history}</ol>
<details><summary>Identidade da ocorrência</summary><div class="disclosure-content">
<p>Fingerprint: <code>{escape_html(incident.fingerprint)}</code></p>
<p>Início: {escape_html(timestamp(incident.starts_at))}</p>
<a class="text-link" href="/api/incidents/{incident.id}">Abrir registro JSON →</a></div></details>
</section>{incident_card(incident, status)}</div>""",
    )


def runbook_index() -> str:
    entries = "".join(
        f'<a class="runbook-entry" href="/runbooks/{slug}">'
        f"<h2>{escape_html(title)}</h2><p>{escape_html(description)}</p>"
        '<span class="text-link">Abrir procedimento</span></a>'
        for slug, (title, description) in RUNBOOKS.items()
    )
    return layout(
        "Runbooks",
        '<div class="page-heading"><div>'
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
    code_language = "text"
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
                code_language = (
                    line[3:].strip().split(maxsplit=1)[0] if line[3:].strip() else "text"
                )
            else:
                parts.append(code_block("\n".join(code), code_language))
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
        parts.append(code_block("\n".join(code), code_language))
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
        back + '<div class="runbook-workspace">'
        '<aside class="runbook-outline"><nav aria-label="Neste procedimento">'
        '<p class="eyebrow">Neste procedimento</p>'
        + "".join(sections)
        + f'</nav><a class="text-link" href="{escape_html(central)}">'
        "Voltar à central →</a></aside>"
        '<article class="runbook"><p class="eyebrow">Procedimento operacional</p>'
        + "".join(parts)
        + "</article></div>",
        section="runbooks",
    )


def problem_page(
    status: int,
    title: str,
    detail: str,
    *,
    incident_filter: str = "all",
    incident_id: int | None = None,
    retry_url: str | None = None,
) -> str:
    back = central_url(incident_filter, incident_id)
    if incident_filter == "all" and incident_id is None:
        back = "/"
    retry = ""
    if (
        retry_url
        and retry_url.startswith("/")
        and not retry_url.startswith("//")
        and "\\" not in retry_url
    ):
        retry = f'<a class="button" href="{escape_html(retry_url)}">Tentar novamente</a>'
    return layout(
        title,
        f'<section class="error-page"><p class="eyebrow">HTTP {status}</p>'
        f"<h1>{escape_html(title)}</h1><p>{escape_html(detail)}</p>"
        f'<div class="problem-actions">{retry}'
        f'<a class="button secondary" href="{escape_html(back)}">Voltar à central</a>'
        "</div></section>",
    )
