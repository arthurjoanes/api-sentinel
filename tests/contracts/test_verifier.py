"""Tool safety without contracts extras; real HTTP rejection when extras are installed."""

import importlib
import json
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
ADAPTER = importlib.import_module("contracts_adapter")
TOOL = importlib.import_module("verify_contracts")
ATTEMPT = "pf-api-sentinel-review-control"
TOKEN = "sentinel_" + "x" * 43
SCHEMA = {
    "openapi": "3.1.0",
    "info": {"title": "Control", "version": "1"},
    "paths": {
        "/v1/stores": {
            "get": {
                "responses": {
                    "200": {
                        "description": "Store list",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["items"],
                                    "properties": {
                                        "items": {"type": "array", "items": {"type": "integer"}}
                                    },
                                }
                            }
                        },
                    }
                }
            }
        }
    },
}


@pytest.fixture
def control_server() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/trickle":
                try:
                    # Keep the socket active while taking much longer than the total budget.
                    for chunk in (
                        b"HTTP/1.1 200 OK\r\n",
                        b"Content-Type: ",
                        b"application/json\r\n",
                    ):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        time.sleep(0.2)
                except OSError:
                    pass
                return
            payload = SCHEMA if self.path == "/openapi.json" else {"items": "wrong type"}
            if self.path == "/v1/stores?scalar=true":
                payload = ["invalid root type"]
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def fixture_file(tmp_path: Path, base_url: str) -> Path:
    path = tmp_path / "private.json"
    payload = {
        "attempt": ATTEMPT,
        "allowed_base_urls": [base_url],
        "quota_policy": "fixed-window",
        "burst_capacity": 10,
        "contract": {
            "token": TOKEN,
            "store_id": 8,
            "quota_per_second": 30,
            "start": "2026-01-01",
            "end": "2026-01-01",
        },
        "tenant_b": {"token": TOKEN, "store_id": 4},
        "tenant_a": {"token": TOKEN, "store_id": 1},
        "probe": {"token": TOKEN, "store_id": 7, "date": "2026-01-01"},
        "low_quota": {"token": TOKEN, "store_id": 9, "quota_per_second": 1},
        "stale_cursor": "old.signed",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_budget_rejects_count_and_deadline_exhaustion() -> None:
    count = ADAPTER.Budget(1, 5, 10)
    count.take()
    with pytest.raises(ADAPTER.Incomplete):
        count.take()
    deadline = ADAPTER.Budget(10, 5, 0)
    with pytest.raises(ADAPTER.Incomplete):
        deadline.take()
    assert deadline.used == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "http://localhost",
        "https://127.0.0.1",
        "http://user:password@127.0.0.1",
        "http://127.0.0.1?credential=x",
    ],
)
def test_arbitrary_targets_and_credential_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError):
        ADAPTER.restrict_destination(url, ATTEMPT, {"allowed_base_urls": [url]})


def test_proxy_requires_attempt_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = {"allowed_base_urls": ["http://proxy"]}
    monkeypatch.setenv("SENTINEL_LAB_PROJECT", "other-attempt")
    with pytest.raises(ValueError):
        ADAPTER.restrict_destination("http://proxy", ATTEMPT, fixture)
    monkeypatch.setenv("SENTINEL_LAB_PROJECT", ATTEMPT)
    assert ADAPTER.restrict_destination("http://proxy", ATTEMPT, fixture) == "http://proxy"


def test_schema_cannot_trigger_external_reference_reads() -> None:
    ADAPTER.local_references_only({"items": [{"$ref": "#/components/schemas/Store"}]})
    with pytest.raises(ValueError):
        ADAPTER.local_references_only({"items": [{"$ref": "http://external.test/schema"}]})


def test_output_sanitizes_auth_cookies_and_credential_urls() -> None:
    payload = {
        "Authorization": TOKEN,
        "cookie": "private=session",
        "nested": [
            TOKEN,
            "http://operator:secret@example.test/private",
            "sentinel_other-private-token",
        ],
    }
    safe = json.dumps(ADAPTER.sanitize(payload, [TOKEN]))
    assert TOKEN not in safe
    assert "operator:secret" not in safe
    assert "private=session" not in safe
    assert "sentinel_other" not in safe


def test_missing_dependency_fails_dedicated_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable() -> None:
        raise ADAPTER.ToolUnavailable

    monkeypatch.setattr(TOOL, "dependencies", unavailable)
    args = TOOL.parser().parse_args(
        [
            "--base-url",
            "http://proxy",
            "--attempt",
            ATTEMPT,
            "--credentials-file",
            str(tmp_path / "missing"),
            "--report",
            str(tmp_path / "report.json"),
        ]
    )
    report = TOOL.verify(args)
    assert report["status"] == "failed"
    assert "dependency is missing" in report["reason"]


def test_exhausted_run_reports_incomplete_over_real_http(
    tmp_path: Path, control_server: str
) -> None:
    pytest.importorskip(
        "schemathesis", reason="Dedicated contracts selftest installs contracts group"
    )
    path = fixture_file(tmp_path, control_server)
    args = TOOL.parser().parse_args(
        [
            "--base-url",
            control_server,
            "--attempt",
            ATTEMPT,
            "--credentials-file",
            str(path),
            "--report",
            str(tmp_path / "report.json"),
            "--max-cases",
            "1",
        ]
    )
    report = TOOL.verify(args)
    assert report["status"] == "incomplete"
    assert report["requests_sent"] == 1
    assert report["results"] == []


def test_control_http_server_with_schema_violation_is_rejected(control_server: str) -> None:
    schemathesis = pytest.importorskip(
        "schemathesis", reason="Dedicated contracts selftest installs extras"
    )
    verifier = ADAPTER.Verifier(
        schemathesis.openapi.from_dict(SCHEMA),
        control_server,
        {"contract": {"token": TOKEN}},
        ADAPTER.Budget(2, 5, 10),
    )
    verifier.execute(TOOL.request("control-schema-violation", "/v1/stores"))
    assert len(verifier.failures) == 1
    assert verifier.failures[0]["http_status"] == 200
    assert "JsonSchemaError" in verifier.failures[0]["violations"]
    assert TOKEN not in json.dumps(verifier.failures)


def test_failed_case_has_safe_reproduction_and_http_replay(
    tmp_path: Path, control_server: str
) -> None:
    pytest.importorskip("schemathesis", reason="Dedicated contracts selftest installs extras")
    credentials = fixture_file(tmp_path, control_server)
    report_path = tmp_path / "report.json"
    args = TOOL.parser().parse_args(
        [
            "--base-url",
            control_server,
            "--attempt",
            ATTEMPT,
            "--credentials-file",
            str(credentials),
            "--report",
            str(report_path),
        ]
    )
    original = TOOL.verify(args)
    assert original["status"] == "failed"
    assert original["failures"][0]["violations"] == ["JsonSchemaError"]
    command = original["failures"][0]["reproduction"]
    assert "--replay-case 0" in command and "--credentials-file" in command
    assert TOKEN not in json.dumps(original)
    report_path.write_text(json.dumps(original), encoding="utf-8")
    args.replay_report = report_path
    replay = TOOL.verify(args)
    assert replay["mode"] == "replay"
    assert replay["status"] == "failed"
    assert replay["requests_sent"] == 2
    assert replay["failures"][0]["violations"] == ["JsonSchemaError"]


def test_non_object_response_retains_safe_failure_request(control_server: str) -> None:
    schemathesis = pytest.importorskip(
        "schemathesis", reason="Dedicated contracts selftest installs extras"
    )
    verifier = ADAPTER.Verifier(
        schemathesis.openapi.from_dict(SCHEMA),
        control_server,
        {"contract": {"token": TOKEN}},
        ADAPTER.Budget(2, 5, 10),
    )
    verifier.execute(TOOL.request("invalid-root", "/v1/stores", query={"scalar": "true"}))
    assert verifier.failures[0]["violations"] == ["JsonSchemaError"]
    assert verifier.failures[0]["request"]["label"] == "invalid-root"
    assert TOKEN not in json.dumps(verifier.failures)


def test_trickled_headers_obey_total_request_deadline(control_server: str) -> None:
    requests = pytest.importorskip("requests")
    started = time.monotonic()
    with pytest.raises(ADAPTER.Incomplete):
        ADAPTER.http_request(
            requests.Request("GET", control_server + "/trickle").prepare(),
            ADAPTER.Budget(2, 5, 0.3),
        )
    assert time.monotonic() - started < 0.55


def test_supervisor_bounds_import_and_generation_time(tmp_path: Path) -> None:
    args = TOOL.parser().parse_args(
        [
            "--base-url",
            "http://proxy",
            "--attempt",
            ATTEMPT,
            "--credentials-file",
            str(tmp_path / "missing"),
            "--report",
            str(tmp_path / "report.json"),
            "--deadline",
            "0.001",
        ]
    )
    started = time.monotonic()
    report = TOOL.supervised_verify(args)
    assert report["status"] == "incomplete"
    assert report["partial_results_unavailable"]
    assert "worker terminated" in report["reason"]
    assert time.monotonic() - started < 2
