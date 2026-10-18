from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Literal, cast

import pytest

from alert_receiver.contracts import Incident, IncidentPage
from alert_receiver.visual_summary import overview_charts

_NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def incident(
    starts_at: datetime, *, identifier: int = 1, status: Literal["firing", "resolved"] = "firing"
) -> Incident:
    return Incident(
        id=identifier,
        fingerprint="abc12345",
        starts_at=starts_at,
        status=status,
        ends_at=starts_at if status == "resolved" else None,
        first_received_at=starts_at,
        last_received_at=starts_at,
        deliveries=1,
        labels={"alertname": "SentinelReplicaLost"},
        annotations={"summary": "Réplica ausente", "reconciliation": "Ação administrativa"},
    )


def page(
    records: list[Incident] | None = None,
    *,
    counts: dict[str, int] | None = None,
    observed: datetime = _NOW,
) -> IncidentPage:
    return IncidentPage(
        records=records or [],
        counts=counts if counts is not None else {"firing": 0, "resolved": 0},
        generated_at=observed,
        cutoff_at=_NOW - timedelta(days=30),
        retention_days=30,
        limit=100,
    )


class Document(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.labels: dict[str, str] = {}
        self.label_id: str | None = None
        self.row: list[str] | None = None
        self.cell: str | None = None
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))
        if tag in {"title", "desc"}:
            self.label_id = dict(attrs).get("id")
            if self.label_id is not None:
                self.labels[self.label_id] = ""
        if tag == "table":
            self.tables.append([])
        elif tag == "tr":
            self.row = []
        elif tag in {"th", "td"}:
            self.cell = ""

    def handle_endtag(self, tag: str) -> None:
        if tag in {"title", "desc"}:
            self.label_id = None
        if tag in {"th", "td"} and self.row is not None and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.tables[-1].append(self.row)
            self.row = None

    def handle_data(self, data: str) -> None:
        if self.label_id is not None:
            self.labels[self.label_id] += data
        if self.cell is not None:
            self.cell += data


def values(document: str, table: int) -> dict[str, str]:
    return dict(Document(document).tables[table][1:])


def test_totals_use_the_unfiltered_snapshot_and_do_not_claim_recovery() -> None:
    document = overview_charts(
        page([incident(_NOW, status="resolved")], counts={"firing": 5, "resolved": 8}),
        "resolved",
    )
    assert values(document, 0) == {"Em andamento": "5", "Finalizados": "8"}
    assert values(document, 1)["2026-10-12 UTC"] == "1"
    assert "Filtro: Finalizados" in document
    assert "Finalizados inclui encerramentos administrativos" in document
    assert "Recuperados" not in document
    assert "Finalizados: 30 dias · ativos: sem expiração" in document


@pytest.mark.parametrize("days", [1, 7, 30])
def test_retained_activity_uses_complete_aggregate_instead_of_loaded_records(days: int) -> None:
    snapshot = replace(
        page([incident(_NOW)], counts={"firing": 125, "resolved": 0}),
        activity_counts={"2026-10-12": 125},
        activity_days=days,
    )
    document = overview_charts(snapshot, "firing")
    assert len(values(document, 1)) == days
    assert values(document, 1)["2026-10-12 UTC"] == "125"
    assert "Independente da página da fila" in document
    assert "125 inícios retidos" in document
    assert "Amostra parcial" not in document


def test_empty_aggregate_is_distinct_from_unavailable_data() -> None:
    snapshot = replace(page([incident(_NOW - timedelta(days=20))]), activity_counts={})
    assert "Nenhum início no período selecionado" in overview_charts(snapshot)
    assert set(values(overview_charts(snapshot), 1).values()) == {"0"}
    invalid = replace(snapshot, activity_counts={"2026-10-12": -1})
    assert "Datas de início indisponíveis" in overview_charts(invalid)
    assert set(values(overview_charts(invalid), 1).values()) == {"Sem dado"}


def test_seven_days_use_utc_and_the_saved_read_clock() -> None:
    records = [
        incident(datetime(2026, 10, 5, 23, 59, tzinfo=UTC)),
        incident(datetime(2026, 10, 6, tzinfo=UTC)),
        incident(datetime(2026, 10, 9, 10, tzinfo=UTC)),
        incident(datetime(2026, 10, 12, 0, 30, tzinfo=timezone(timedelta(hours=2)))),
        incident(datetime(2026, 10, 12, 8, tzinfo=UTC)),
        incident(_NOW),
    ]
    snapshot = page(records)
    document = overview_charts(snapshot)
    assert values(document, 1) == {
        "2026-10-06 UTC": "1",
        "2026-10-07 UTC": "0",
        "2026-10-08 UTC": "0",
        "2026-10-09 UTC": "1",
        "2026-10-10 UTC": "0",
        "2026-10-11 UTC": "1",
        "2026-10-12 UTC": "2",
    }
    assert "6 itens deste filtro" in document
    assert "Não representa todo o histórico" in document
    assert document == overview_charts(snapshot)
    assert snapshot.generated_at == _NOW


def test_activity_is_bounded_to_the_first_100_loaded_records() -> None:
    records = [incident(_NOW - timedelta(days=3), identifier=n + 1) for n in range(100)]
    records.append(incident(_NOW, identifier=101))
    document = overview_charts(page(records, counts={"firing": 1005, "resolved": 0}), "firing")
    assert values(document, 0)["Em andamento"] == "1005"
    assert values(document, 1)["2026-10-09 UTC"] == "100"
    assert values(document, 1)["2026-10-12 UTC"] == "0"
    assert "100 itens deste filtro" in document
    assert "Filtro: Em andamento" in document


def test_empty_and_old_samples_show_actual_zero_without_a_health_claim() -> None:
    for snapshot in [page(), page([incident(_NOW - timedelta(days=20))])]:
        document = overview_charts(snapshot)
        assert set(values(document, 1).values()) == {"0"}
        assert "zero indica nenhum início com data válida contado" in document
        assert "saudável" not in document.lower()
        assert "disponibilidade" not in document.lower()
        assert "nan" not in document.lower()
        assert "infinity" not in document.lower()


@pytest.mark.parametrize(
    "bad_clock", [None, _NOW.replace(tzinfo=None), datetime(1, 1, 1, tzinfo=UTC)]
)
def test_unknown_or_unusable_read_clock_never_invents_a_period(bad_clock: datetime | None) -> None:
    document = overview_charts(page([incident(_NOW)], observed=cast("datetime", bad_clock)))
    assert values(document, 1) == {"Período indisponível": "Sem dado"}
    assert "summary-activity-title" not in document
    assert "2026-10-12 UTC" not in document


@pytest.mark.parametrize("bad_count", [True, -1, 1.5, None, '<img src=x onerror="x">', 2**100])
def test_invalid_counts_are_unknown_instead_of_zero(bad_count: object) -> None:
    counts = cast("dict[str, int]", {"firing": bad_count, "resolved": 7})
    document = overview_charts(page(counts=counts))
    assert values(document, 0) == {"Em andamento": "Sem dado", "Finalizados": "7"}
    assert "Contagem indisponível" in document
    assert "summary-states-title" not in document
    assert "<img" not in document


def test_all_invalid_or_future_starts_do_not_masquerade_as_a_zero_series() -> None:
    invalid = [
        incident(_NOW.replace(tzinfo=None)),
        incident(_NOW + timedelta(seconds=1)),
        incident(_NOW).model_copy(update={"starts_at": None}),
    ]
    document = overview_charts(page(invalid))
    assert set(values(document, 1).values()) == {"Sem dado"}
    assert "Datas de início indisponíveis" in document
    assert "summary-activity-title" not in document


def test_partly_invalid_dates_show_valid_counts_and_the_missing_data_note() -> None:
    unreadable_start = (_NOW - timedelta(days=3)).replace(tzinfo=None)
    document = overview_charts(page([incident(_NOW), incident(unreadable_start)]))
    assert values(document, 1)["2026-10-12 UTC"] == "1"
    assert values(document, 1)["2026-10-09 UTC"] == "0"
    assert "1 data de início sem leitura" in document
    assert "2 itens deste filtro" in document
    assert "zero indica nenhum início com data válida contado" in document
    assert "datas indisponíveis não são contadas" in document
    assert "ausência de inícios nesta amostra" not in document


def test_graphics_have_accessible_names_closed_tables_and_no_executable_metadata() -> None:
    record = incident(_NOW).model_copy(
        update={
            "labels": {"tenant": "private-tenant"},
            "annotations": {"summary": "<script>x</script>"},
        }
    )
    document = overview_charts(
        page([record], counts={"firing": 1, "resolved": 0}), '<svg onload="x">'
    )
    parsed = Document(document)
    assert len(parsed.tables) == 2
    assert all(attrs.get("scope") in {"row", "col"} for tag, attrs in parsed.tags if tag == "th")
    svgs = [attrs for tag, attrs in parsed.tags if tag == "svg"]
    assert len(svgs) == 2
    ids = [attrs["id"] for _, attrs in parsed.tags if "id" in attrs]
    assert len(ids) == len(set(ids))
    descriptions = {}
    for svg in svgs:
        assert svg["role"] == "img"
        name_refs = str(svg["aria-labelledby"]).split()
        description_refs = str(svg["aria-describedby"]).split()
        assert len(name_refs) == len(description_refs) == 1
        assert name_refs[0] != description_refs[0]
        assert name_refs[0] in ids and description_refs[0] in ids
        name = parsed.labels[name_refs[0]]
        descriptions[name] = parsed.labels[description_refs[0]]
    assert set(descriptions) == {"Situação dos incidentes", "Inícios por dia"}
    assert "Em andamento: 1. Finalizados: 0" in descriptions["Situação dos incidentes"]
    assert (
        "Finalizados inclui encerramentos administrativos"
        in descriptions["Situação dos incidentes"]
    )
    assert "De 2026-10-06 até 2026-10-12, em UTC" in descriptions["Inícios por dia"]
    assert "1 início em 1 item deste filtro" in descriptions["Inícios por dia"]
    assert "datas indisponíveis não são contadas" in descriptions["Inícios por dia"]
    assert all("open" not in attrs for tag, attrs in parsed.tags if tag == "details")
    assert not any(tag == "text" for tag, _ in parsed.tags)
    assert len([tag for tag, _ in parsed.tags if tag == "time"]) == 7
    assert {attrs.get("datetime") for tag, attrs in parsed.tags if tag == "time"} == {
        label.removesuffix(" UTC") for label in values(document, 1)
    }
    assert not any(
        tag in {"script", "style", "a", "image", "foreignobject"} for tag, _ in parsed.tags
    )
    assert not any(key.startswith("on") for _, attrs in parsed.tags for key in attrs)
    assert "private-tenant" not in document
    assert "Filtro: Todos" in document
