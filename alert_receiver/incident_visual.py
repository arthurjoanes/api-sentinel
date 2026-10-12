"""Visualize saved incident endpoints without inferring current service health."""

from datetime import UTC, datetime, timedelta
from html import escape

from alert_receiver.contracts import Incident


def _utc(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    try:
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def _time(value: datetime | None) -> str:
    instant = _utc(value)
    if instant is None:
        return '<span class="period-missing">Horário indisponível</span>'
    return (
        f'<time datetime="{escape(instant.isoformat(), quote=True)}">'
        f"{instant.strftime('%d/%m/%Y · %H:%M:%S UTC')}</time>"
    )


def _interval(value: timedelta) -> str:
    seconds = int(value.total_seconds())
    if value.total_seconds() > 0 and seconds == 0:
        return "menos de 1 s"
    if seconds < 60:
        return f"{seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h" + (f" {minutes} min" if minutes else "")
    days, hours = divmod(hours, 24)
    return f"{days} d" + (f" {hours} h" if hours else "")


def period_graphic(incident: Incident) -> str:
    """Return the full saved period, separate from the receiver's event timeline.

    Resolved alerts use their reported recovery time. Administrative closure uses
    its recorded closure time. An active occurrence ends this drawing at the last
    received delivery, which does not assert continuous outage or current health.
    """
    administrative = bool(incident.annotations.get("reconciliation"))
    end_value: datetime | None
    if incident.status == "firing":
        end_value = incident.last_received_at
        end_label = "Última entrega"
        tone = "active"
        scope = "Início informado pelo alerta até a última entrega recebida."
    elif administrative:
        end_value = incident.ends_at
        end_label = "Encerramento administrativo"
        tone = "administrative"
        scope = "Início informado pelo alerta até o encerramento pelo operador."
    else:
        end_value = incident.ends_at
        end_label = "Recuperação informada"
        tone = "recovered"
        scope = "Início e recuperação informados pelo alerta."
    start, end = _utc(incident.starts_at), _utc(end_value)
    endpoints = (
        '<dl class="period-endpoints"><div><dt>Início informado</dt>'
        f"<dd>{_time(incident.starts_at)}</dd></div>"
        f"<div><dt>{escape(end_label)}</dt><dd>{_time(end_value)}</dd></div></dl>"
    )
    if start is None or end is None or end < start:
        return (
            '<figure class="incident-period period-unavailable">'
            '<figcaption class="period-caption">Período indisponível</figcaption>'
            + endpoints
            + '<p class="period-scope">Os horários registrados não permitem '
            "representar o período.</p>"
            "</figure>"
        )
    interval = _interval(end - start)
    key = f"incident-period-{incident.id}"
    left, right = (360, 360) if start == end else (32, 688)
    marker = (
        f'<rect class="period-end" x="{right - 8}" y="24" width="16" height="16" '
        'rx="2" fill="none" stroke="currentColor" stroke-width="3"/>'
        if administrative and incident.status != "firing"
        else f'<circle class="period-end" cx="{right}" cy="32" r="8" '
        f'fill="{"none" if tone == "active" else "currentColor"}" '
        'stroke="currentColor" stroke-width="3"/>'
    )
    return (
        f'<figure class="incident-period period-{tone}">'
        '<figcaption class="period-caption"><strong>Período registrado</strong>'
        f'<span class="period-duration">Intervalo registrado: {escape(interval)}</span>'
        "</figcaption>"
        '<svg class="period-svg" viewBox="0 0 720 64" role="img" '
        f'aria-labelledby="{key}-title" aria-describedby="{key}-scope" '
        'preserveAspectRatio="xMidYMid meet">'
        f'<title id="{key}-title">Período registrado: início '
        f"{start.strftime('%d/%m/%Y · %H:%M:%S UTC')}; "
        f"{escape(end_label.lower())} {end.strftime('%d/%m/%Y · %H:%M:%S UTC')}.</title>"
        f'<desc id="{key}-scope">{escape(scope)} Intervalo entre os horários registrados: '
        f"{escape(interval)}.</desc>"
        f'<line class="period-line" x1="{left}" y1="32" x2="{right}" y2="32" '
        'stroke="currentColor" stroke-width="3"/>'
        f'<circle class="period-start" cx="{left}" cy="32" r="6" fill="currentColor"/>'
        + marker
        + "</svg>"
        + endpoints
        + "</figure>"
    )
