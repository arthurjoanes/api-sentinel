import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from alert_receiver import ui
from alert_receiver.contracts import Incident, IncidentEvent, IncidentPage
from alert_receiver.probe import ProbeResult, ProbeState


def test_exported_preview_includes_referenced_public_assets(tmp_path: Path) -> None:
    from scripts.render_ui_preview import ROOT, render

    render(tmp_path)
    for name in (
        "favicon.svg",
        "mark-light.svg",
        "plex-sans-regular.woff2",
        "plex-sans-semibold.woff2",
    ):
        assert (tmp_path / "assets" / name).read_bytes() == (
            ROOT / "alert_receiver" / "assets" / name
        ).read_bytes()
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "assets",
        "disabled.html",
        "empty.html",
        "error.html",
        "failure.html",
        "firing.html",
        "incidents",
        "index.html",
        "long.html",
        "manifest.json",
        "no-active.html",
        "resolved.html",
        "runbooks",
        "snapshot.js",
        "stale.html",
        "styles.css",
    ]


def page(
    *, firing: int = 0, resolved: int = 0, records: list[Incident] | None = None
) -> IncidentPage:
    now = datetime.now(UTC)
    return IncidentPage(
        records=records or [],
        counts={"firing": firing, "resolved": resolved},
        generated_at=now,
        cutoff_at=now - timedelta(days=30),
        retention_days=30,
        limit=100,
    )


class Elements(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def test_operator_can_read_and_keep_focus_without_timed_navigation() -> None:
    document = ui.home(page(), ProbeState(), "all")
    assert "Atualização manual" in document
    assert not any(
        tag == "meta" and attrs.get("http-equiv") == "refresh"
        for tag, attrs in Elements(document).tags
    )
    assert 'href="#conteudo"' in document
    assert 'id="conteudo" tabindex="-1"' in document


@pytest.mark.parametrize("status", ["all", "firing", "resolved"])
def test_filter_selection_is_exposed_to_assistive_technology(status: str) -> None:
    document = ui.home(page(), ProbeState(), status)
    selected = [
        attrs["href"]
        for tag, attrs in Elements(document).tags
        if tag == "a" and attrs.get("aria-current") == "page"
    ]
    assert selected == [f"/?status={status}"]


def test_no_active_incidents_does_not_claim_service_health() -> None:
    document = ui.home(page(resolved=12), ProbeState(), "firing")
    assert "Nenhum incidente em andamento" in document
    assert "Aguardando o primeiro teste" in document
    assert "Valores esperados" in document
    assert "Fixture validada" not in document
    assert "Consulta de referência validada" not in document


def test_stale_probe_does_not_reuse_last_success_as_current_health() -> None:
    probe = ProbeState()
    probe.result = "success"
    probe.checked_at = datetime.now(UTC) - timedelta(seconds=30)
    document = ui.home(page(), probe, "all")
    assert "Resultado desatualizado" in document
    assert "Consulta de referência validada" not in document


def test_compact_row_preserves_state_and_escapes_alert_metadata() -> None:
    observed = datetime(2026, 9, 21, 3, 20, tzinfo=UTC)
    incident = Incident(
        id=12,
        fingerprint="abc12345",
        starts_at=observed - timedelta(minutes=2),
        ends_at=observed,
        first_received_at=observed - timedelta(minutes=2),
        last_received_at=observed,
        status="resolved",
        deliveries=3,
        labels={"severity": "critical", "service": '<img src="bad">'},
        annotations={"summary": "<script>bad()</script>", "impact": "<b>Impacto</b>"},
    )
    document = ui.incident_row(incident)
    assert "Resolvido" in document and "Crítico" in document
    assert "21/09/2026 · 03:20:00 UTC" in document
    assert "3 entregas" in document
    assert 'href="/incidents/12?status=all"' in document
    assert "<script>" not in document and "<img " not in document
    assert "&lt;script&gt;" in document and "&lt;b&gt;Impacto&lt;/b&gt;" in document


def test_navigation_error_offers_recovery_without_rendering_markup() -> None:
    document = ui.problem_page(404, "Ocorrência inexistente", "<script>bad()</script>")
    assert "Voltar à central" in document
    assert "HTTP 404" in document
    assert "<script>" not in document


def test_operational_reconciliation_is_not_presented_as_a_received_webhook() -> None:
    observed = datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    incident = Incident(
        id=14,
        fingerprint="abc12345",
        starts_at=observed - timedelta(minutes=2),
        ends_at=observed,
        first_received_at=observed - timedelta(minutes=2),
        last_received_at=observed - timedelta(minutes=2),
        status="resolved",
        deliveries=1,
        labels={"severity": "warning"},
        annotations={
            "summary": "Réplicas recuperadas",
            "reconciliation": "<script>auditoria</script>",
        },
    )
    event = IncidentEvent(
        received_at=observed, delivered_status="resolved", transition="operator_reconciled"
    )
    document = ui.incident_detail(incident, [event])
    assert "Encerrado pelo operador" in document
    assert "sem webhook de recuperação" in document
    assert "1 entrega · histórico" in document
    assert "&lt;script&gt;auditoria&lt;/script&gt;" in document
    assert "<script>" not in document


@pytest.mark.parametrize("status", ["firing", "resolved", "manual"])
def test_current_next_step_respects_state_and_preserves_original_instruction(status: str) -> None:
    observed = datetime.now(UTC)
    incident = Incident(
        id=15,
        fingerprint="abcdef15",
        starts_at=observed - timedelta(minutes=2),
        ends_at=observed if status != "firing" else None,
        first_received_at=observed - timedelta(minutes=2),
        last_received_at=observed,
        status="firing" if status == "firing" else "resolved",
        deliveries=2,
        labels={},
        annotations={
            "summary": "Consulta indisponível",
            "action": "Restaure <o serviço> e valide a consulta.",
            **({"reconciliation": "Conferido pelo operador."} if status == "manual" else {}),
        },
    )
    document = ui.incident_detail(incident, [], "resolved")
    decision = document.split('<div class="decision-strip">', 1)[1].split(
        '<details class="incident-metadata"', 1
    )[0]
    assert '<details class="decision-explanation">' in decision
    assert "Restaure &lt;o serviço&gt; e valide a consulta." in document
    if status == "firing":
        assert "Restaure &lt;o serviço&gt;" in decision
        assert "Orientação original do alerta" not in document
    else:
        assert "Restaure" not in decision
        assert "Orientação original do alerta" in document
        assert 'href="/?status=resolved#observacao"' in decision
        assert "Impacto registrado" in decision
        if status == "manual":
            assert "Confira o motivo do encerramento" in decision
            assert "não confirma a recuperação da API" in document
            assert "O Alertmanager entregou a recuperação" not in document
        else:
            assert "antes de iniciar outra intervenção" in decision
            assert "O Alertmanager entregou a recuperação" in document


@pytest.mark.parametrize(
    ("result", "enabled", "age", "expected"),
    [
        (None, False, None, "Probe desativado"),
        ("configuration", True, None, "Consulta indisponível"),
        ("success", True, None, "Resultado indisponível"),
        ("success", True, -3600, "Resultado indisponível"),
        ("network", True, 0, "Falha no probe"),
    ],
)
def test_probe_states_never_claim_more_than_the_observation(
    result: ProbeResult | None,
    enabled: bool,
    age: int | None,
    expected: str,
) -> None:
    probe = ProbeState(enabled=enabled)
    probe.result = result
    probe.checked_at = None if age is None else datetime.now(UTC) - timedelta(seconds=age)
    document = ui.home(page(), probe, "all")
    assert expected in document
    assert "Consulta de referência validada" not in document
    assert "Ver no Prometheus" in document
    assert "Réplicas observadas" in document
    assert "Veja os targets do Prometheus" in document


def test_timestamp_without_timezone_is_not_current_evidence() -> None:
    probe = ProbeState(result="success", checked_at=datetime(2026, 1, 1))
    document = ui.home(page(), probe, "all")
    assert "Resultado indisponível" in document
    assert "Consulta de referência validada" not in document


def test_fresh_result_has_bounded_display_lifetime_without_navigation() -> None:
    observed = datetime.now(UTC)
    probe = ProbeState(result="success", checked_at=observed, stale_after_seconds=120)
    document = ui.probe_observation(probe, observed + timedelta(seconds=20))
    assert 'data-expires-in-ms="100000"' in document
    assert "Consulta de referência validada" in document
    assert "não confirma a saúde de todo o sistema" not in document


def test_retention_and_loaded_count_are_distinct_from_filtered_total() -> None:
    document = ui.home(page(resolved=103), ProbeState(), "resolved")
    assert "0 de 103 incidentes · limite de 100" in document
    assert "Finalizados: últimos 30 dias · Em andamento: sem expiração" in document
    assert "última entrega ou reconciliação operacional dos finalizados" in document
    assert "não à data de início" in document


def test_empty_active_filter_offers_actual_resolved_history() -> None:
    document = ui.home(page(resolved=21), ProbeState(), "firing")
    assert 'href="/?status=resolved">Ver 21 incidentes finalizados' in document
    assert "Em andamento</span><strong>0</strong>" in document
    disclosures = [attrs for tag, attrs in Elements(document).tags if tag == "details"]
    assert any(attrs.get("id") == "observacao" for attrs in disclosures)
    assert all("open" not in attrs for attrs in disclosures)


def test_empty_history_does_not_invent_resolved_records() -> None:
    document = ui.home(page(), ProbeState(), "resolved")
    assert "Nenhum incidente finalizado no período" in document
    assert "Ver 0 incidentes finalizados" not in document


def test_history_read_error_offers_retry_without_an_empty_success_state() -> None:
    document = ui.problem_page(503, "Histórico indisponível", "Tente consultar novamente.")
    assert "Histórico indisponível" in document
    assert "Nenhum incidente" not in document
    assert 'href="/"' in document


def test_manual_closure_is_neutral_in_the_incident_list() -> None:
    now = datetime.now(UTC)
    incident = Incident(
        id=1,
        fingerprint="abcdef12",
        starts_at=now,
        ends_at=now,
        first_received_at=now,
        last_received_at=now,
        status="resolved",
        deliveries=1,
        labels={},
        annotations={"summary": "Réplica ausente", "reconciliation": "Conferida"},
    )
    document = ui.incident_row(incident)
    assert 'class="badge neutral">Encerrado pelo operador' in document
    assert 'class="badge good"' not in document
    assert "Recuperação" not in document


def test_late_event_keeps_delivery_and_effect_distinct() -> None:
    event = IncidentEvent(
        received_at=datetime.now(UTC), delivered_status="firing", transition="late_firing_ignored"
    )
    document = ui.event_item(event)
    assert "Entrega firing" in document
    assert "sem reabrir a ocorrência" in document
    assert "Recuperação confirmada" not in document


def test_runbook_preserves_code_lists_and_safe_section_navigation() -> None:
    document = ui.runbook_page(
        "telemetry",
        "# Diagnóstico\n## Confira <script>\n1. Veja `up`\n2. Confira & repita\n"
        "\n```sh\n<script>não executar</script>\n```\n## Recuperação\n- Confirmar a entrega",
    )
    assert "<ol><li>Veja <code>up</code></li><li>Confira &amp; repita</li></ol>" in document
    assert "<script>" not in document
    assert "&lt;script&gt;não executar&lt;/script&gt;" in document
    elements = Elements(document).tags
    section_ids = {attrs["id"] for tag, attrs in elements if tag == "h2"}
    links = {
        attrs["href"][1:]
        for tag, attrs in elements
        if tag == "a" and (attrs.get("href") or "").startswith("#etapa-")
    }
    assert links == section_ids == {"etapa-1", "etapa-2"}


def evidence_incident(*, active: bool = False, hours: int = 1) -> Incident:
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    end = start + timedelta(hours=hours)
    return Incident(
        id=42,
        fingerprint="abcdef42",
        starts_at=start,
        ends_at=None if active else end,
        status="firing" if active else "resolved",
        first_received_at=start,
        last_received_at=end,
        deliveries=2,
        labels={},
        annotations={"summary": "Ocorrência sintética"},
    )


def test_snapshot_heading_and_probe_precede_queue_and_lookup_has_visible_entry() -> None:
    document = ui.home(page(), ProbeState(), "firing")
    assert document.index('class="page-heading"') < document.index('class="triage-workspace"')
    assert document.index('class="observation-workspace"') < document.index('class="inbox"')
    assert "Leitura de" in document and "Atualização manual" in document
    assert 'placeholder="ID do incidente"' in document
    assert document.index('id="buscar-incidente"') < document.index('class="queue-controls"')
    assert (
        'id="buscar-incidente"' in document and 'action="/incident-lookup" method="get"' in document
    )
    assert 'pattern="[0-9]{1,19}"' in document and 'maxlength="19"' in document


def test_row_exposes_id_and_both_dates_in_the_same_recent_cell() -> None:
    record = evidence_incident()
    document = ui.incident_row(record)
    assert '<h3><span class="row-reference">' in document
    assert '<span class="visually-hidden">Incidente </span>#42</span>' in document
    recent = document.split('<div class="row-recent">', 1)[1].split("</div>", 1)[0]
    assert "Início" in recent and "Recuperação" in recent
    assert "01/10/2026 · 12:00:00 UTC" in recent and "01/10/2026 · 13:00:00 UTC" in recent


@pytest.mark.parametrize("active,hours", [(False, 1), (True, 1), (False, 72)])
def test_evidence_links_use_saved_period_correct_units_and_bounded_recrop(
    active: bool, hours: int
) -> None:
    record = evidence_incident(active=active, hours=hours)
    document = ui.incident_card(record, "resolved")
    links = [attrs["href"] for tag, attrs in Elements(document).tags if tag == "a"]
    metrics = parse_qs(urlsplit(next(link for link in links if "/grafana/" in link)).query)
    traces = parse_qs(urlsplit(next(link for link in links if "/jaeger/" in link)).query)
    end = record.last_received_at
    start = max(record.starts_at, end - timedelta(hours=24))
    assert metrics["from"] == [str(int(start.timestamp() * 1000))]
    assert metrics["to"] == [str(int(end.timestamp() * 1000))]
    assert traces["start"] == [str(int(start.timestamp() * 1_000_000))]
    assert traces["end"] == [str(int(end.timestamp() * 1_000_000))]
    assert traces["service"] == ["api-sentinel"] and traces["limit"] == ["20"]
    assert traces["sentinel_status"] == ["resolved"] and traces["sentinel_incident"] == ["42"]
    assert "Traces são amostrados" in document and "Regras atuais" in document
    assert ("Recorte de até 24 horas" in document) == (hours > 24)


def test_unknown_period_does_not_invent_historical_evidence() -> None:
    record = evidence_incident()
    record.ends_at = None
    document = ui.incident_card(record)
    assert "Período da evidência indisponível" in document
    assert "/tools/jaeger/search" not in document and "from=" not in document


def test_detail_shows_saved_period_and_snapshot_before_actions() -> None:
    record = evidence_incident(hours=72)
    document = ui.incident_detail(record, [], generated_at=datetime.now(UTC))
    assert document.index('class="detail-period"') < document.index('class="decision-strip"')
    assert "01/10/2026 · 12:00:00 UTC" in document and "04/10/2026 · 12:00:00 UTC" in document
    assert "Atualizar ocorrência" in document and "Leitura de" in document


def test_probe_deadline_is_recorded_from_server_observation() -> None:
    checked = datetime(2026, 10, 1, 12, tzinfo=UTC)
    probe = ProbeState(result="success", checked_at=checked, stale_after_seconds=15)
    document = ui.probe_observation(probe, checked + timedelta(seconds=5))
    assert (
        f'data-expires-at-ms="{int((checked + timedelta(seconds=15)).timestamp() * 1000)}"'
        in document
    )
    assert (
        f'data-observed-at-ms="{int((checked + timedelta(seconds=5)).timestamp() * 1000)}"'
        in document
    )
    assert 'data-expires-in-ms="10000"' in document
    assert "Última consulta" in document and "01/10/2026 · 12:00:00 UTC" in document
    assert 'href="#observacao"' not in document
    home = ui.home(page(), probe, "all")
    assert 'href="#observacao">Ver probe' in home and '<details id="observacao">' in home


def test_javascript_expiry_counts_slow_navigation_and_never_revives_on_restore() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Browser/Node gate exercises the external snapshot script.")
    script = Path(ui.__file__).with_name("snapshot.js")
    program = r"""
const vm = require('node:vm');
const source = require('node:fs').readFileSync(process.argv[1], 'utf8');
function check(elapsed, wall, nav=true, fields=true) {
  const nodes = {title:{textContent:'fresh'}, description:{textContent:''}, dot:{className:'good'}};
  const observation = {
    dataset: fields ? {expiresInMs:'10000', observedAtMs:'100000', expiresAtMs:'110000'} :
      {expiresInMs:'10000'},
    querySelector: sel => sel.includes('title') ? nodes.title :
      sel.includes('description') ? nodes.description : nodes.dot
  };
  const handlers = {}; let timer;
  const listen = (name,fn) => (handlers[name] ??= []).push(fn);
  const clock = {elapsed, wall};
  const context = {
    document: {querySelector:sel=>sel==='[data-expires-in-ms]'?observation:null,
      addEventListener:listen},
    window: {location:{hash:''},addEventListener:listen},
    performance: {now:()=>clock.elapsed,getEntriesByType:()=>nav?[{startTime:0}]:[]},
    Date:{now:()=>clock.wall},setTimeout:fn=>timer=fn
  };
  vm.runInNewContext(source, context);
  return {nodes,handlers,clock,timer};
}
function assert(value) { if(!value) throw Error('snapshot expiry contract'); }
assert(check(12000,100001).nodes.title.textContent==='Resultado desatualizado');
assert(check(1,110001).nodes.title.textContent==='Resultado desatualizado');
assert(check(1,100001,false).nodes.title.textContent==='Resultado desatualizado');
assert(check(1,100001,true,false).nodes.title.textContent==='Resultado desatualizado');
const recent=check(500,100500); assert(recent.nodes.title.textContent==='fresh');
recent.clock.elapsed=10001; recent.clock.wall=90000;
recent.handlers.pageshow.forEach(fn=>fn());
assert(recent.nodes.title.textContent==='Resultado desatualizado');
recent.clock.elapsed=100; recent.handlers.visibilitychange.forEach(fn=>fn());
assert(recent.nodes.title.textContent==='Resultado desatualizado');
"""
    result = subprocess.run(
        [node, "-e", program, str(script)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
