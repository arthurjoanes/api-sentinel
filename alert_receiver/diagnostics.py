"""Resolve operator links for this execution, never from an alert-supplied host."""

import json
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_URLS = {
    "grafana": "http://localhost:3104",
    "jaeger": "http://localhost:16684",
    "prometheus": "http://localhost:9104",
    "alertmanager": "http://localhost:9194",
}


def tool_url(service: str, path: str, query: str, configuration: Path | None) -> str:
    if service not in DEFAULT_URLS:
        raise KeyError(service)
    urls = json.loads(configuration.read_text(encoding="utf-8")) if configuration else DEFAULT_URLS
    if not isinstance(urls, dict):
        raise ValueError("Configuração de destinos inválida.")
    value = urls.get(service)
    if not isinstance(value, str):
        raise ValueError("Destino de investigação ausente.")
    target = urlsplit(value)
    if (
        target.scheme not in {"http", "https"}
        or target.hostname not in {"localhost", "127.0.0.1"}
        or not target.port
        or target.username
        or target.password
        or target.path not in {"", "/"}
        or target.query
        or target.fragment
    ):
        raise ValueError("O destino de investigação precisa ser uma origem loopback explícita.")
    return value.rstrip("/") + "/" + path.lstrip("/") + ("?" + query if query else "")
