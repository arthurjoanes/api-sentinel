"""Read-only Grafana access must not grant administration through default credentials."""

import os
import time
from collections.abc import Iterator

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_HTTP_TESTS") != "1", reason="Requer RUN_HTTP_TESTS=1 e observabilidade pronta."
)


@pytest.fixture(scope="module")
def grafana() -> Iterator[httpx.Client]:
    with httpx.Client(
        base_url=os.getenv("SENTINEL_GRAFANA_URL", "http://grafana:3000"),
        timeout=3,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                response = client.get("/api/health")
                if response.status_code == 200 and response.json().get("database") == "ok":
                    break
            except (httpx.RequestError, ValueError):
                pass
            time.sleep(0.5)
        else:
            pytest.fail("Grafana não ficou pronto em 90s.")
        yield client


def test_anonymous_dashboard_is_read_only(grafana: httpx.Client) -> None:
    response = grafana.get("/api/dashboards/uid/sentinel")
    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["dashboard"]["title"] == "API Sentinel"
    assert dashboard["meta"]["provisioned"] is True
    for permission in ("canSave", "canEdit", "canAdmin", "canDelete"):
        assert dashboard["meta"][permission] is False


def test_default_basic_credentials_cannot_read_admin_api(grafana: httpx.Client) -> None:
    assert grafana.get("/api/admin/stats").status_code in (401, 403)
    response = grafana.get("/api/admin/stats", auth=("admin", "admin"))
    assert response.status_code in (401, 403)


def test_password_login_is_disabled(grafana: httpx.Client) -> None:
    response = grafana.post("/login", json={"user": "admin", "password": "admin"})
    assert response.status_code == 400
    assert response.json()["messageId"] == "auth.client.notConfigured"
    assert "grafana_session" not in response.cookies
