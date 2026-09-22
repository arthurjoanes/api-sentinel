import hashlib
import json
import secrets
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from alert_receiver.app import RUNBOOKS, create_app
from alert_receiver.config import Settings

checks = []
commands = [
    ["ruff", "check", "--no-cache", "."],
    ["ruff", "format", "--check", "--no-cache", "."],
    ["mypy", "--cache-dir=/tmp/mypy-cache"],
    ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/unit"],
]
for command in commands:
    run = subprocess.run(command, cwd="/app", capture_output=True, text=True)
    checks.append(
        {
            "command": command,
            "exit_code": run.returncode,
            "stdout": run.stdout,
            "stderr": run.stderr,
        }
    )
    if run.returncode:
        print(json.dumps({"checks": checks}, indent=2))
        raise SystemExit(run.returncode)

root = Path("/app")
files = [
    {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    for path in sorted(root.rglob("*"))
    if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
]
routes = []
with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    token = directory / "token"
    token.write_text(secrets.token_urlsafe(48))
    app = create_app(
        Settings(
            database_path=directory / "alerts.db",
            webhook_token_file=token,
            probe_enabled=False,
            public_urls_file=directory / "missing.json",
        )
    )
    with TestClient(app) as client:
        paths = [
            "/",
            "/?status=firing",
            "/?status=resolved",
            "/health/live",
            "/styles.css",
            "/snapshot.js",
            "/assets/mark-light.svg",
            "/assets/favicon.svg",
            "/assets/wordmark.svg",
            "/assets/plex-sans-regular.woff2",
            "/assets/plex-sans-semibold.woff2",
            "/runbooks",
        ]
        paths += [f"/runbooks/{slug}" for slug in sorted(RUNBOOKS)]
        paths += [
            "/runbooks/erp?incident_id=1&status=firing",
            "/runbooks/not-a-runbook",
            "/incidents/999",
            "/runbooks/erp?incident_id=0",
            "/tools/grafana/",
            "/tools/jaeger/",
        ]
        for path in paths:
            response = client.get(path, headers={"Accept": "text/html"}, follow_redirects=False)
            expected = (
                404
                if path in ["/runbooks/not-a-runbook", "/incidents/999"]
                else 422
                if "incident_id=0" in path
                else 503
                if path.startswith("/tools/")
                else 200
            )
            assert response.status_code == expected, (path, response.status_code)
            if path in ["/styles.css", "/snapshot.js"] or path.startswith("/assets/"):
                assert (
                    response.content
                    == (root / "alert_receiver" / path.removeprefix("/")).read_bytes()
                )
            if path.startswith("/runbooks/") and expected == 200:
                assert (
                    "<h1" in response.text
                    and "Runbook temporariamente indisponível" not in response.text
                )
            routes.append(
                {
                    "path": path,
                    "status": response.status_code,
                    "content_type": response.headers["content-type"],
                }
            )
print(
    json.dumps(
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "source_binds": False,
            "checks": checks,
            "files": files,
            "routes": routes,
        },
        ensure_ascii=False,
        indent=2,
    )
)
