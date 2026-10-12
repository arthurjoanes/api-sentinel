"""Offline charts of saved receiver data, with the exact values available as tables."""

from datetime import UTC, date, datetime, timedelta
from html import escape

from alert_receiver.contracts import IncidentPage

_FILTERS = {"all": "Todos", "firing": "Em andamento", "resolved": "Finalizados"}
_SAMPLE_LIMIT = 100


def _count(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 2**63 - 1 else None


def _utc(value: object) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        return value.astimezone(UTC) if value.utcoffset() is not None else None
    except (OverflowError, ValueError):
        return None


def _table(caption: str, heading: str, rows: list[tuple[str, int | None]]) -> str:
    body = "".join(
        f'<tr><th scope="row">{escape(label)}</th>'
        f"<td>{value if value is not None else 'Sem dado'}</td></tr>"
        for label, value in rows
    )
    return (
        f"<table><caption>{escape(caption)}</caption><thead><tr>"
        f'<th scope="col">{escape(heading)}</th><th scope="col">Incidentes</th>'
        f"</tr></thead><tbody>{body}</tbody></table>"
    )


def _svg(name: str, title: str, description: str, body: str, height: int = 112) -> str:
    return (
        '<svg class="summary-chart-svg" xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 440 {height}" preserveAspectRatio="none" role="img" '
        f'aria-labelledby="{name}-title" aria-describedby="{name}-desc">'
        f'<title id="{name}-title">{escape(title)}</title>'
        f'<desc id="{name}-desc">{escape(description)}</desc>{body}</svg>'
    )


def _figure(title: str, caption: str, graphic: str, table: str, note: str = "") -> str:
    return (
        '<figure class="summary-chart"><figcaption>'
        f'<h2>{escape(title)}</h2><p class="chart-caption">{escape(caption)}</p>'
        "</figcaption>"
        + graphic
        + (f'<p class="chart-note">{escape(note)}</p>' if note else "")
        + '<details class="chart-data"><summary>Ver dados'
        + f'<span class="visually-hidden">: {escape(title)}</span></summary>{table}</details>'
        + "</figure>"
    )


def _states(page: IncidentPage) -> str:
    title = "Situação dos incidentes"
    rows = [
        ("Em andamento", _count(page.counts.get("firing"))),
        ("Finalizados", _count(page.counts.get("resolved"))),
    ]
    days = _count(page.retention_days)
    caption = (
        "Finalizados: "
        + (f"{days} dias" if days is not None and 1 <= days <= 365 else "retenção indisponível")
        + " · ativos: sem expiração"
    )
    table = _table(
        "Totais retidos na central, independentemente do filtro da fila", "Situação", rows
    )
    legend = (
        '<div class="chart-legend">'
        + "".join(
            '<div class="chart-legend-item"><span class="chart-state-label">'
            f'<span class="chart-key chart-key-{tone}" aria-hidden="true"></span>{escape(label)}'
            f'</span><strong class="chart-value">{value if value is not None else "Sem dado"}'
            "</strong></div>"
            for (label, value), tone in zip(rows, ("active", "finished"), strict=True)
        )
        + "</div>"
    )
    if any(value is None for _, value in rows):
        return _figure(
            title, caption, legend + '<p class="chart-empty">Contagem indisponível.</p>', table
        )
    total = sum(value or 0 for _, value in rows) or 1
    bars = ['<rect class="chart-track" x="0" y="8" width="440" height="26" rx="3" fill="#DFE8EE"/>']
    offset = 0.0
    for index, (label, value) in enumerate(rows):
        width = 440 * (value or 0) / total
        tone = "active" if index == 0 else "finished"
        fill = "#A52C35" if index == 0 else "#24556F"
        bars.append(
            f"<g><title>{escape(label)}: {value}</title>"
            f'<rect class="chart-bar-{tone}" x="{offset:.3f}" y="8" width="{width:.3f}" '
            f'height="26" fill="{fill}"/></g>'
        )
        offset += width
    description = ". ".join(f"{label}: {value}" for label, value in rows)
    description += ". Finalizados inclui encerramentos administrativos. Totais retidos."
    graphic = legend + _svg("summary-states", title, description, "".join(bars), height=42)
    return _figure(title, caption, graphic, table)


def _activity(page: IncidentPage, status: str) -> str:
    title = "Inícios por dia"
    records = page.records[:_SAMPLE_LIMIT]
    items = "item" if len(records) == 1 else "itens"
    caption = f"7 dias UTC · {len(records)} {items} deste filtro"
    table_caption = (
        f"Inícios somente nos {len(records)} registros carregados (limite de 100). "
        f"Filtro: {_FILTERS.get(status, 'Todos')}. Não representa todo o histórico."
    )
    observed = _utc(page.generated_at)
    try:
        first_day = observed.date() - timedelta(days=6) if observed else None
    except OverflowError:
        first_day = None
    if observed is None or first_day is None:
        return _figure(
            title,
            caption,
            '<p class="chart-empty">Período indisponível.</p>',
            _table(table_caption, "Dia UTC", [("Período indisponível", None)]),
        )
    counts: dict[date, int] = {first_day + timedelta(days=index): 0 for index in range(7)}
    invalid = 0
    valid = 0
    for incident in records:
        starts_at = _utc(incident.starts_at)
        if starts_at is None or starts_at > observed:
            invalid += 1
            continue
        valid += 1
        if starts_at.date() in counts:
            counts[starts_at.date()] += 1
    unknown = bool(records) and valid == 0
    table = _table(
        table_caption,
        "Dia UTC",
        [(f"{day.isoformat()} UTC", None if unknown else value) for day, value in counts.items()],
    )
    if unknown:
        return _figure(
            title, caption, '<p class="chart-empty">Datas de início indisponíveis.</p>', table
        )
    maximum = max(counts.values()) or 1
    bars = []
    labels = []
    for index, (day, value) in enumerate(counts.items()):
        x = 440 * (index + 0.5) / 7 - 14
        height = 96 * value / maximum
        bars.append(
            f"<g><title>{day.isoformat()} UTC: {value} inícios na amostra</title>"
            f'<rect class="chart-bar-activity" x="{x:.3f}" y="{106 - height:.3f}" '
            f'width="28" height="{height:.3f}" rx="3" fill="#155BA6"/>'
            "</g>"
        )
        labels.append(
            f'<div class="chart-day"><strong class="chart-value">{value}</strong>'
            '<span class="visually-hidden">inícios</span>'
            f'<time class="chart-tick" datetime="{day.isoformat()}" '
            f'title="{day.isoformat()} UTC">{day:%d/%m}</time></div>'
        )
    description = (
        f"De {first_day.isoformat()} até {observed.date().isoformat()}, em UTC. "
        f"{sum(counts.values())} inícios nos {len(records)} itens deste filtro. "
        "Amostra parcial dos registros carregados; zero indica "
        "nenhum início com data válida contado; datas indisponíveis não são contadas."
    )
    note = ""
    if invalid:
        note = (
            f"{invalid} data de início sem leitura."
            if invalid == 1
            else f"{invalid} datas de início sem leitura."
        )
    graphic = _svg("summary-activity", title, description, "".join(bars))
    graphic += '<div class="chart-activity-labels">' + "".join(labels) + "</div>"
    return _figure(title, caption, graphic, table, note)


def overview_charts(page: IncidentPage, status: str = "all") -> str:
    """Render retained totals and a bounded, filtered sample of starts on seven UTC days.

    These are saved incident records, not service health, delivery rates or recovery SLIs.
    The read timestamp is the sole clock; invalid clocks never manufacture a fresh period.
    """
    return '<div class="visual-summary">' + _states(page) + _activity(page, status) + "</div>"
