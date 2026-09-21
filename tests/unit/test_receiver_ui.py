from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser

import pytest

from alert_receiver import ui
from alert_receiver.contracts import Incident, IncidentEvent, IncidentPage
from alert_receiver.probe import ProbeResult, ProbeState


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
    assert "Probe OK" not in document


def test_stale_probe_does_not_reuse_last_success_as_current_health() -> None:
    probe = ProbeState()
    probe.result = "success"
    probe.checked_at = datetime.now(UTC) - timedelta(seconds=30)
    document = ui.home(page(), probe, "all")
    assert "Resultado desatualizado" in document
    assert "Probe OK" not in document


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
    assert 'href="/incidents/12"' in document
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
    assert "Probe OK" not in document
    assert "Ver no Prometheus" in document
    assert "Réplicas observadas" in document
    assert "Veja os targets do Prometheus" in document


def test_timestamp_without_timezone_is_not_current_evidence() -> None:
    probe = ProbeState(result="success", checked_at=datetime(2026, 1, 1))
    document = ui.home(page(), probe, "all")
    assert "Resultado indisponível" in document
    assert "Probe OK" not in document


def test_fresh_result_has_bounded_display_lifetime_without_navigation() -> None:
    observed = datetime.now(UTC)
    probe = ProbeState(result="success", checked_at=observed, stale_after_seconds=120)
    document = ui.probe_observation(probe, observed + timedelta(seconds=20))
    assert 'data-expires-in-ms="100000"' in document
    assert "Probe OK" in document
    assert "não confirma a saúde de todo o sistema" not in document


def test_retention_and_loaded_count_are_distinct_from_filtered_total() -> None:
    document = ui.home(page(resolved=103), ProbeState(), "resolved")
    assert "0 de 103 incidentes · limite de 100" in document
    assert "Resolvidos: últimos 30 dias · Em andamento: sem expiração" in document
    assert "última entrega ou reconciliação operacional dos resolvidos" in document
    assert "não à data de início" in document


def test_empty_active_filter_offers_actual_resolved_history() -> None:
    document = ui.home(page(resolved=21), ProbeState(), "firing")
    assert 'href="/?status=resolved">Ver 21 incidentes resolvidos' in document
    assert "<strong>0 em andamento</strong>" in document
    disclosures = [attrs for tag, attrs in Elements(document).tags if tag == "details"]
    assert len(disclosures) == 2
    assert all("open" not in attrs for attrs in disclosures)


def test_empty_history_does_not_invent_resolved_records() -> None:
    document = ui.home(page(), ProbeState(), "resolved")
    assert "Nenhum incidente resolvido no período" in document
    assert "Ver 0 incidentes resolvidos" not in document


def test_history_read_error_offers_retry_without_an_empty_success_state() -> None:
    document = ui.problem_page(503, "Histórico indisponível", "Tente consultar novamente.")
    assert "Histórico indisponível" in document
    assert "Nenhum incidente" not in document
    assert 'href="/"' in document
