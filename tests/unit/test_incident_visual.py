from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser

import pytest

from alert_receiver.contracts import Incident
from alert_receiver.incident_visual import period_graphic


class Elements(HTMLParser):
    def __init__(self, document: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(document)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))


def incident(**changes: object) -> Incident:
    start = datetime(2026, 10, 1, 10, tzinfo=UTC)
    original = Incident(
        id=7,
        fingerprint="abcdef12345678",
        starts_at=start,
        status="firing",
        ends_at=None,
        first_received_at=start + timedelta(minutes=5),
        last_received_at=start + timedelta(hours=2),
        deliveries=2,
        labels={"alertname": "SentinelERP"},
        annotations={"summary": "ERP indisponível"},
    )
    return original.model_copy(update=changes)


def times(document: str) -> list[str | None]:
    return [attrs.get("datetime") for tag, attrs in Elements(document).tags if tag == "time"]


def test_active_period_ends_at_saved_delivery_without_inventing_closure() -> None:
    current = incident(ends_at=datetime(2026, 10, 8, tzinfo=UTC))
    before = current.model_dump_json()
    document = period_graphic(current)
    assert times(document) == [current.starts_at.isoformat(), current.last_received_at.isoformat()]
    assert "Última entrega" in document and "Recuperação informada" not in document
    assert "Intervalo registrado: 2 h" in document
    assert "Última entrega recebida".lower() in document.lower()
    assert current.model_dump_json() == before


def test_recovery_uses_source_end_even_after_later_receiver_delivery() -> None:
    current = incident(status="resolved", ends_at=datetime(2026, 10, 1, 10, 30, tzinfo=UTC))
    document = period_graphic(current)
    assert times(document) == [current.starts_at.isoformat(), current.ends_at.isoformat()]
    assert current.last_received_at.isoformat() not in document
    assert "Recuperação informada" in document
    assert "Intervalo registrado: 30 min" in document


def test_administrative_end_is_distinct_and_does_not_render_operator_markup() -> None:
    current = incident(
        status="resolved",
        ends_at=datetime(2026, 10, 1, 11, tzinfo=UTC),
        annotations={"summary": "<svg onload=alert(1)>", "reconciliation": "<script>bad</script>"},
    )
    document = period_graphic(current)
    assert 'class="incident-period period-administrative"' in document
    assert "Encerramento administrativo" in document
    assert "Recuperação informada" not in document
    assert not any(
        tag == "script" or any(key.startswith("on") or key == "style" for key in attrs)
        for tag, attrs in Elements(document).tags
    )


def test_period_is_full_length_and_normalized_to_utc_without_24_hour_clipping() -> None:
    offset = timezone(timedelta(hours=-3))
    start = datetime(2026, 10, 1, 7, tzinfo=offset)
    end = datetime(2026, 10, 9, 10, tzinfo=offset)
    document = period_graphic(incident(status="resolved", starts_at=start, ends_at=end))
    assert times(document) == [start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()]
    assert "Intervalo registrado: 8 d 3 h" in document


@pytest.mark.parametrize(
    "changes",
    [
        {"starts_at": datetime(2026, 10, 1, 10)},
        {"last_received_at": datetime(2026, 10, 1, 12)},
        {"last_received_at": datetime(2026, 9, 30, tzinfo=UTC)},
        {"status": "resolved", "ends_at": None},
        {"status": "resolved", "ends_at": datetime(2026, 10, 1, 11)},
        {"starts_at": datetime.min.replace(tzinfo=timezone(timedelta(hours=1)))},
    ],
)
def test_insufficient_or_inconsistent_period_is_unknown(changes: dict[str, object]) -> None:
    document = period_graphic(incident(**changes))
    assert "Período indisponível" in document
    assert "<svg" not in document
    assert "Intervalo registrado:" not in document


def test_identical_endpoints_are_one_instant_and_svg_has_accessible_labels() -> None:
    start = datetime(2026, 10, 1, 10, tzinfo=UTC)
    document = period_graphic(incident(last_received_at=start))
    elements = Elements(document)
    svg = next(attrs for tag, attrs in elements.tags if tag == "svg")
    ids = {attrs.get("id") for _, attrs in elements.tags}
    line = next(attrs for tag, attrs in elements.tags if tag == "line")
    assert svg["role"] == "img"
    assert svg["aria-labelledby"] in ids and svg["aria-describedby"] in ids
    assert line["x1"] == line["x2"]
    assert "Intervalo registrado: 0 s" in document
