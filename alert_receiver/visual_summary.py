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
    days = (
        page.activity_days
        if type(page.activity_days) is int and page.activity_days in (1, 7, 30)
        else 7
    )
    complete = page.activity_counts is not None
    records = page.records[:_SAMPLE_LIMIT]
    items = "item" if len(records) == 1 else "itens"
    period = "Hoje, UTC" if days == 1 else f"{days} dias UTC"
    caption = (
        f"{period} · registros retidos"
        if complete
        else f"{period} · {len(records)} {items} deste filtro"
    )
    table_caption = (
        f"Inícios nos registros retidos. Filtro: {_FILTERS.get(status, 'Todos')}. "
        "Independente da página da fila."
        if complete
        else f"Inícios somente nos {len(records)} registros carregados (limite de 100). "
        f"Filtro: {_FILTERS.get(status, 'Todos')}. Não representa todo o histórico."
    )
    observed = _utc(page.generated_at)
    try:
        first_day = observed.date() - timedelta(days=days - 1) if observed else None
    except OverflowError:
        first_day = None
    if observed is None or first_day is None:
        return _figure(
            title,
            caption,
            '<p class="chart-empty">Período indisponível.</p>',
            _table(table_caption, "Dia UTC", [("Período indisponível", None)]),
        )
    counts: dict[date, int] = {first_day + timedelta(days=index): 0 for index in range(days)}
    invalid = 0
    valid = 0
    if page.activity_counts is not None:
        for day_key, value in page.activity_counts.items():
            try:
                parsed = date.fromisoformat(day_key)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if parsed not in counts or _count(value) is None:
                invalid += 1
                continue
            counts[parsed] = value
            valid += 1
        unknown = bool(invalid)
    else:
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
    total = sum(counts.values())
    total_label = "início" if total == 1 else "inícios"
    if complete:
        caption = f"{period} · {total} {'início retido' if total == 1 else 'inícios retidos'}"
    bars = []
    labels = []
    for index, (day, value) in enumerate(counts.items()):
        count_label = "início" if value == 1 else "inícios"
        width = min(28, 330 / days)
        x = 440 * (index + 0.5) / days - width / 2
        height = 96 * value / maximum
        bars.append(
            f"<g><title>{day.isoformat()} UTC: {value} {count_label} "
            f"{'nos registros retidos' if complete else 'na amostra'}</title>"
            f'<rect class="chart-bar-activity" x="{x:.3f}" y="{106 - height:.3f}" '
            f'width="{width:.3f}" height="{height:.3f}" rx="3" fill="#155BA6"/>'
            "</g>"
        )
        if days <= 7 or index in (0, days // 2, days - 1):
            labels.append(
                f'<div class="chart-day"><strong class="chart-value">{value}</strong>'
                f'<span class="visually-hidden">{count_label}</span>'
                f'<time class="chart-tick" datetime="{day.isoformat()}" '
                f'title="{day.isoformat()} UTC">{day:%d/%m}</time></div>'
            )
    description = (
        f"De {first_day.isoformat()} até {observed.date().isoformat()}, em UTC. "
        + (
            f"{total} {total_label} nos registros retidos deste filtro. "
            "Contagem independente da paginação; zero indica "
            if complete
            else f"{total} {total_label} em {len(records)} {items} deste filtro. "
            "Amostra parcial dos registros carregados; zero indica "
        )
        + "nenhum início com data válida contado; datas indisponíveis não são contadas."
    )
    note = "Nenhum início no período selecionado." if complete and not total else ""
    if invalid:
        note = (
            f"{invalid} data de início sem leitura."
            if invalid == 1
            else f"{invalid} datas de início sem leitura."
        )
    graphic = _svg("summary-activity", title, description, "".join(bars))
    graphic += (
        f'<div class="chart-activity-labels activity-days-{days}">' + "".join(labels) + "</div>"
    )
    return _figure(title, caption, graphic, table, note)


def overview_charts(page: IncidentPage, status: str = "all") -> str:
    """Render retained totals and a UTC activity window from the same saved read.

    Older standalone fixtures without aggregates retain their explicit partial-sample scope.
    These are incident records, not service health, delivery rates or recovery SLIs.
    The read timestamp is the sole clock; invalid clocks never manufacture a fresh period.
    """
    return '<div class="visual-summary">' + _states(page) + _activity(page, status) + "</div>"
