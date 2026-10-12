"""Bounded HTTP transport and schema checks for the optional contracts tool."""

import http.client
import importlib
import ipaddress
import json
import os
import re
import socket
import stat
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

OPERATIONS = (
    "/v1/stores",
    "/v1/stores/{store_id}/summary",
    "/v1/stores/{store_id}/sales",
    "/v1/stores/{store_id}/availability/{sku}",
)


class Incomplete(Exception):
    """The evidence budget ended before the requested checks completed."""


class ToolUnavailable(Exception):
    """The dedicated gate requires its separately installed, locked dependencies."""


def dependencies() -> tuple:
    try:
        return importlib.import_module("schemathesis"), importlib.import_module("hypothesis")
    except ImportError as exc:
        raise ToolUnavailable("Install the locked contracts group in the dedicated image.") from exc


def load_credentials(path: Path, attempt: str) -> dict:
    if not re.fullmatch(r"pf-api-sentinel-(?:review|ci)-[a-z0-9-]+", attempt):
        raise ValueError("A unique disposable attempt is required.")
    if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError("The credentials file must be private (0600 or stricter).")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("attempt") != attempt:
        raise ValueError("Credentials belong to another attempt.")
    for role in ("contract", "tenant_a", "tenant_b", "probe", "low_quota"):
        if not re.fullmatch(r"sentinel_[A-Za-z0-9_-]{32,128}", payload[role]["token"]):
            raise ValueError("Invalid private credential document.")
    if payload["contract"]["quota_per_second"] < 5:
        raise ValueError("The healthy fixture quota must support the planned five requests/s.")
    if payload["low_quota"]["quota_per_second"] != 1:
        raise ValueError("The dedicated 429 fixture must have quota one request/s.")
    return payload


def restrict_destination(base_url: str, attempt: str, fixture: dict) -> str:
    target = urlsplit(base_url)
    if (
        target.scheme != "http"
        or target.username is not None
        or target.password is not None
        or target.path not in ("", "/")
        or target.query
        or target.fragment
        or not target.hostname
    ):
        raise ValueError("Use the plain HTTP proxy URL for this disposable attempt.")
    if target.hostname == "proxy":
        if target.port not in (None, 80) or os.getenv("SENTINEL_LAB_PROJECT") != attempt:
            raise ValueError("The proxy service must belong to the active disposable attempt.")
    else:
        try:
            local = ipaddress.ip_address(target.hostname).is_loopback
        except ValueError:
            local = False
        if not local:
            raise ValueError("External destinations are refused.")
    normalized = base_url.rstrip("/")
    if normalized not in fixture.get("allowed_base_urls", []):
        raise ValueError("The private fixture must bind this exact proxy URL to the attempt.")
    return normalized


def local_references_only(value: object) -> None:
    """Do not let a schema trigger HTTP reads outside the attempt via remote references."""
    if isinstance(value, dict):
        if "$ref" in value and not str(value["$ref"]).startswith("#/"):
            raise ValueError("Only references within the fetched schema are permitted.")
        for item in value.values():
            local_references_only(item)
    elif isinstance(value, list):
        for item in value:
            local_references_only(item)


@dataclass
class Budget:
    max_cases: int
    rate: float
    seconds: float
    started: float = 0
    next_request: float = 0
    used: int = 0

    def __post_init__(self) -> None:
        self.started = time.monotonic()
        self.next_request = self.started

    def take(self) -> float:
        remaining = self.seconds - (time.monotonic() - self.started)
        pause = max(0.0, self.next_request - time.monotonic())
        if self.used >= self.max_cases or remaining <= pause:
            raise Incomplete("Request count or total deadline exhausted.")
        if pause:
            time.sleep(pause)
        self.used += 1
        self.next_request = time.monotonic() + 1 / self.rate
        return min(3.0, self.seconds - (time.monotonic() - self.started))


def http_request(prepared: object, budget: Budget, duplicate_auth: bool = False) -> object:
    """Never follow redirects or use environment proxies; bound the full body read."""
    import requests
    from urllib3 import HTTPResponse
    from urllib3._collections import HTTPHeaderDict

    allowance = budget.take()
    started = time.monotonic()
    target = urlsplit(prepared.url)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=allowance)
    expired = threading.Event()
    watchdog = None
    try:
        connection.connect()
        active_socket = connection.sock

        def expire() -> None:
            expired.set()
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        watchdog = threading.Timer(max(0, allowance - (time.monotonic() - started)), expire)
        watchdog.daemon = True
        watchdog.start()
        path = target.path + ("?" + target.query if target.query else "")
        connection.putrequest("GET", path, skip_accept_encoding=True)
        for name, value in prepared.headers.items():
            connection.putheader(name, value)
            if duplicate_auth and name.lower() == "authorization":
                connection.putheader(name, value)
        connection.endheaders()
        incoming = connection.getresponse()
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining = allowance - (time.monotonic() - started)
            if remaining <= 0:
                raise Incomplete("The bounded HTTP request deadline expired.")
            # getresponse may detach the socket for HTTP/1.0; the body owns it then.
            body_socket = connection.sock or getattr(
                getattr(incoming.fp, "raw", None), "_sock", None
            )
            if body_socket is not None:
                body_socket.settimeout(remaining)
            chunk = incoming.read1(65536)
            size += len(chunk)
            if size > 524288:
                raise ValueError("Response exceeds the contracts tool body limit.")
            if not chunk:
                break
            chunks.append(chunk)
        if expired.is_set() or time.monotonic() - started >= allowance:
            raise Incomplete("The bounded HTTP request deadline expired.")
        response = requests.Response()
        response.status_code = incoming.status
        response.headers.update(incoming.getheaders())
        response._content = b"".join(chunks)
        response.request = prepared
        response.url = prepared.url
        response.elapsed = timedelta(seconds=time.monotonic() - started)
        # Schemathesis reads the raw multi-value headers when converting requests responses.
        response.raw = HTTPResponse(
            body=response.content,
            headers=HTTPHeaderDict(incoming.getheaders()),
            status=incoming.status,
            version=incoming.version,
        )
        return response
    except (OSError, http.client.HTTPException) as exc:
        if expired.is_set():
            raise Incomplete("The bounded HTTP request deadline expired.") from exc
        raise
    finally:
        if watchdog is not None:
            watchdog.cancel()
        connection.close()


def check_names(exception: BaseException) -> list[str]:
    """Exception text may embed auth headers or a reproduction curl command."""
    nested = getattr(exception, "exceptions", None)
    if nested:
        return sorted({name for child in nested for name in check_names(child)})
    return [type(exception).__name__]


def sanitize(value: object, secrets: list[str]) -> object:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key.lower() in {"authorization", "cookie", "set-cookie", "token", "password"}
            else sanitize(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"sentinel_[A-Za-z0-9_-]+", "[REDACTED]", value)
        value = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", value)
        return value
    return value


class Verifier:
    def __init__(self, schema: object, base_url: str, fixture: dict, budget: Budget) -> None:
        self.schema = schema
        self.base_url = base_url
        self.fixture = fixture
        self.budget = budget
        self.results: list[dict] = []
        self.failures: list[dict] = []

    def execute(self, request: dict, generated_case: object = None) -> dict:
        import requests
        from schemathesis.checks import not_a_server_error
        from schemathesis.core.failures import FailureGroup
        from schemathesis.specs.openapi.checks import (
            content_type_conformance,
            response_headers_conformance,
            response_schema_conformance,
            status_code_conformance,
        )

        operation = self.schema[request["operation"]]["GET"]
        case = generated_case or operation.Case(
            path_parameters=request.get("path_parameters"), query=request.get("query")
        )
        role = request.get("credential", "contract")
        headers = {"Accept-Encoding": "identity"}
        if role != "missing":
            token = (
                "invalid-private-test-credential"
                if role == "invalid"
                else self.fixture["contract" if role == "duplicate" else role]["token"]
            )
            headers["Authorization"] = "Bearer " + token
        arguments = case.as_transport_kwargs(base_url=self.base_url, headers=headers)
        prepared = requests.Request(**arguments).prepare()
        if urlsplit(prepared.url).netloc != urlsplit(self.base_url).netloc:
            raise ValueError("Generated input attempted to escape the attempt proxy.")
        entry = {"request": request, "status": "passed"}
        started = time.monotonic()
        response = http_request(prepared, self.budget, duplicate_auth=role == "duplicate")
        entry.update(http_status=response.status_code, elapsed_seconds=time.monotonic() - started)
        violations: list[str] = []
        try:
            # Every transmitted response gets all substantive HTTP conformance checks.
            # Auth/domain checks below use the same counted transport instead of hidden resends.
            case.validate_response(
                response,
                checks=[
                    not_a_server_error,
                    status_code_conformance,
                    content_type_conformance,
                    response_schema_conformance,
                    response_headers_conformance,
                ],
            )
        except (Exception, FailureGroup) as exc:
            violations.extend(check_names(exc))
        expected = request.get("expected_status")
        if expected is not None and response.status_code != expected:
            violations.append("expected_status")
        if (
            request.get("allowed_statuses")
            and response.status_code not in request["allowed_statuses"]
        ):
            violations.append("allowed_statuses")
        if response.status_code >= 500:
            violations.append("unexpected_server_error")
        if any(
            value["token"].encode() in response.content
            for value in self.fixture.values()
            if isinstance(value, dict) and "token" in value
        ):
            violations.append("credential_disclosure")
        if response.status_code == 429 and request.get("category") != "quota":
            violations.append("unexpected_healthy_quota_rejection")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if request.get("expected_code") and body.get("code") != request["expected_code"]:
            violations.append("expected_domain_code")
        if request.get("expected_codes") and body.get("code") not in request["expected_codes"]:
            violations.append("expected_domain_code")
        if request.get("expected_revenue") is not None and (
            type(body.get("revenue_cents")) is not int
            or body.get("revenue_cents") != request["expected_revenue"]
        ):
            violations.append("technical_fixture_12500")
        if response.status_code == 429 and (
            body.get("code") != "tenant_quota_exceeded"
            or not re.fullmatch(r"[1-9][0-9]*", response.headers.get("Retry-After", ""))
        ):
            violations.append("quota_retry_contract")
        if violations:
            entry.update(status="failed", violations=sorted(set(violations)))
            self.failures.append(entry)
        self.results.append(entry)
        return {"status": response.status_code, "body": body}
