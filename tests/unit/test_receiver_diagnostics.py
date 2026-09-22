import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alert_receiver import ui
from alert_receiver.app import create_app
from alert_receiver.config import Settings


def test_investigation_redirects_to_this_execution_and_not_demo(tmp_path: Path) -> None:
    links = tmp_path / "links.json"
    links.write_text(json.dumps({"grafana": "http://127.0.0.1:45678"}))
    application = create_app(
        Settings(database_path=tmp_path / "alerts.db", probe_enabled=False, public_urls_file=links)
    )
    client = TestClient(application)
    response = client.get("/tools/grafana/d/sentinel?from=now-5m", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "http://127.0.0.1:45678/d/sentinel?from=now-5m"
    links.unlink()
    response = client.get("/tools/grafana/d/sentinel", follow_redirects=False)
    assert response.status_code == 503 and "location" not in response.headers
    assert client.get("/tools/unknown/", follow_redirects=False).status_code == 404


def test_alert_annotations_are_local_navigation_not_external_redirects() -> None:
    assert ui.local_link("http://localhost:3104/d/sentinel", "/") == "/tools/grafana/d/sentinel"
    assert ui.local_link("http://localhost:9184//evil.invalid/path", "/") == "/evil.invalid/path"
    assert ui.local_link("https://evil.invalid:3104/path", "/") == "/"


@pytest.mark.parametrize(
    ("service", "status"), [("grafana", 503), ("jaeger", 503), ("unknown", 404)]
)
def test_missing_tool_keeps_browser_navigation_and_api_problem(
    tmp_path: Path, service: str, status: int
) -> None:
    application = create_app(Settings(probe_enabled=False, public_urls_file=tmp_path / "missing"))
    client = TestClient(application)
    browser = client.get(
        f"/tools/{service}/", headers={"Accept": "text/html"}, follow_redirects=False
    )
    assert browser.status_code == status
    assert "text/html" in browser.headers["content-type"]
    assert "Voltar à central" in browser.text
    assert "location" not in browser.headers
    api = client.get(f"/tools/{service}/", follow_redirects=False)
    assert api.status_code == status
    assert api.headers["content-type"] == "application/problem+json"
