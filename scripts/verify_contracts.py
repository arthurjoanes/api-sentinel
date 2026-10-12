"""Generate bounded schema cases through an attempt's disposable HTTP proxy."""

import argparse
import hashlib
import json
import multiprocessing
import shlex
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from contracts_adapter import (
    OPERATIONS,
    Budget,
    Incomplete,
    ToolUnavailable,
    Verifier,
    check_names,
    dependencies,
    http_request,
    load_credentials,
    local_references_only,
    restrict_destination,
    sanitize,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--base-url", required=True)
    command.add_argument("--attempt", required=True)
    command.add_argument("--credentials-file", type=Path, required=True)
    command.add_argument("--report", type=Path, required=True)
    command.add_argument("--seed", type=int, default=20261012)
    command.add_argument("--examples-per-operation", type=int, default=30)
    command.add_argument("--rate", type=float, default=5)
    command.add_argument("--max-cases", type=int, default=180)
    command.add_argument("--deadline", type=float, default=90)
    command.add_argument("--replay-report", type=Path)
    command.add_argument("--replay-case", type=int, default=0)
    return command


def request(
    label: str,
    operation: str,
    store: int | None = None,
    query: dict | None = None,
    credential: str = "contract",
    status: int | None = 200,
    code: str | None = None,
    category: str = "positive",
    sku: str | None = None,
) -> dict:
    fields: dict = {"label": label, "operation": operation, "credential": credential}
    fields.update(expected_status=status, expected_code=code, category=category)
    if store is not None:
        fields["path_parameters"] = {"store_id": store}
        if sku is not None:
            fields["path_parameters"]["sku"] = sku
    if query is not None:
        fields["query"] = query
    return fields


def suite(verifier: Verifier, args: argparse.Namespace, hypothesis: object) -> None:
    fixture = verifier.fixture
    healthy = fixture["contract"]
    store = healthy["store_id"]
    period = {"start": healthy["start"], "end": healthy["end"]}
    positive = [
        request("stores-positive", OPERATIONS[0]),
        request("summary-positive", OPERATIONS[1], store, period),
        request("sales-positive", OPERATIONS[2], store, period | {"limit": 1}),
        request("availability-positive", OPERATIONS[3], store, sku="SKU-001"),
    ]
    cursor = None
    for sample in positive:
        response = verifier.execute(sample)
        if sample["operation"] == OPERATIONS[2]:
            cursor = response["body"].get("next_cursor")
    if not isinstance(cursor, str) or not cursor:
        raise ValueError("The healthy sales fixture must have at least two eligible rows.")
    verifier.execute(
        request("sales-valid-cursor", OPERATIONS[2], store, period | {"cursor": cursor})
    )
    for sample in positive:
        for role in ("missing", "invalid"):
            verifier.execute(
                sample
                | {
                    "label": sample["label"] + "-auth-" + role,
                    "credential": role,
                    "category": "authentication",
                    "expected_status": 401,
                    "expected_code": "invalid_credential",
                }
            )
    verifier.execute(
        request(
            "duplicate-authorization",
            OPERATIONS[0],
            credential="duplicate",
            status=400,
            category="authentication",
        )
        | {"expected_codes": ["ambiguous_credential", "proxy_request"]}
    )
    for operation in OPERATIONS[1:3]:
        for label, dates, code in (
            ("inverted-period", {"start": "2026-01-02", "end": "2026-01-01"}, "invalid_period"),
            (
                "outside-coverage",
                {"start": "2025-12-31", "end": "2025-12-31"},
                "data_outside_coverage",
            ),
        ):
            verifier.execute(
                request(label, operation, store, dates, status=422, code=code, category="domain")
            )
    for label, value, code in (
        ("malformed-cursor", "malformed", "invalid_cursor"),
        ("previous-version-cursor", fixture["stale_cursor"], "invalid_cursor"),
        ("oversize-cursor", "x" * 2049, "invalid_request"),
    ):
        verifier.execute(
            request(
                label,
                OPERATIONS[2],
                store,
                period | {"cursor": value},
                status=422,
                code=code,
                category="domain",
            )
        )
    verifier.execute(
        request(
            "invalid-sku",
            OPERATIONS[3],
            store,
            sku="SKU-ABC",
            status=422,
            code="invalid_sku",
            category="domain",
        )
    )
    for role, foreign in (
        ("contract", fixture["tenant_b"]["store_id"]),
        ("tenant_b", store),
        ("tenant_a", fixture["tenant_b"]["store_id"]),
    ):
        for operation in OPERATIONS[1:]:
            verifier.execute(
                request(
                    "tenant-isolation-" + role,
                    operation,
                    foreign,
                    period if operation != OPERATIONS[3] else None,
                    credential=role,
                    status=403,
                    code="store_forbidden",
                    category="isolation",
                    sku="SKU-001",
                )
            )
    probe = fixture["probe"]
    verifier.execute(
        request(
            "technical-fixture",
            OPERATIONS[1],
            probe["store_id"],
            {"start": probe["date"], "end": probe["date"]},
            credential="probe",
        )
        | {"expected_revenue": 12500}
    )
    for index, operation_path in enumerate(OPERATIONS):
        operation = verifier.schema[operation_path]["GET"]
        overrides: dict = {}
        if operation_path != OPERATIONS[0]:
            overrides["path_parameters"] = {"store_id": store}
        if operation_path in OPERATIONS[1:3]:
            overrides["query"] = period
            if operation_path == OPERATIONS[2]:
                # Opaque cursors require a valid signed value; they have explicit negatives above.
                overrides["query"] = period | {"cursor": cursor}
        strategy = operation.as_strategy(**overrides)

        @hypothesis.seed(args.seed + index)
        @hypothesis.settings(
            max_examples=args.examples_per_operation,
            deadline=None,
            database=None,
            phases=[hypothesis.Phase.generate],
            report_multiple_bugs=False,
            suppress_health_check=[hypothesis.HealthCheck.too_slow],
        )
        @hypothesis.given(strategy)
        def generated(case: object) -> None:
            sample = request("schema-fuzz", case.path, category="fuzz")
            sample.update(path_parameters=case.path_parameters, query=case.query)
            verifier.execute(sample, generated_case=case)

        # Hypothesis stderr may include a case repr after failure; collect only safe types.
        with hypothesis.reporting.with_reporter(lambda _: None):
            generated()
    quota_seen = False
    limit = min(30, fixture.get("burst_capacity", 10) + 10)
    for _ in range(limit):
        response = verifier.execute(
            request(
                "dedicated-quota",
                OPERATIONS[0],
                credential="low_quota",
                status=None,
                category="quota",
            )
            | {"allowed_statuses": [200, 429]}
        )
        if response["status"] == 429:
            quota_seen = True
            break
    if not quota_seen:
        raise ValueError("The known low-quota fixture did not produce a dedicated 429.")
    verifier.execute(
        request(
            "technical-fixture-after",
            OPERATIONS[1],
            probe["store_id"],
            {"start": probe["date"], "end": probe["date"]},
            credential="probe",
        )
        | {"expected_revenue": 12500}
    )


def initial_report(args: argparse.Namespace) -> dict:
    return {
        "schema_version": 1,
        "attempt": args.attempt,
        "started_at": datetime.now(UTC).isoformat(),
        "status": "incomplete",
        "seed": args.seed,
        "budget": {
            "examples_per_operation": args.examples_per_operation,
            "max_cases": args.max_cases,
            "rate_per_second": args.rate,
            "deadline_seconds": args.deadline,
        },
        "checks": [
            "not_a_server_error",
            "status_code_conformance",
            "content_type_conformance",
            "response_schema_conformance",
            "response_headers_conformance",
        ],
        "results": [],
        "failures": [],
    }


def verify(args: argparse.Namespace) -> dict:
    report = initial_report(args)
    fixture: dict = {}
    verifier = None
    budget = None
    try:
        schemathesis, hypothesis = dependencies()
        report["schemathesis_version"] = version("schemathesis")
        if not (
            1 <= args.examples_per_operation <= 30
            and 0 < args.rate <= 5
            and 1 <= args.max_cases <= 1000
            and 0 < args.deadline <= 300
        ):
            raise ValueError("Invalid bounded contracts configuration.")
        fixture = load_credentials(args.credentials_file, args.attempt)
        base_url = restrict_destination(args.base_url, args.attempt, fixture)
        report.update(
            base_url=base_url,
            quota_policy=fixture["quota_policy"],
            burst_capacity=fixture["burst_capacity"],
        )
        budget = Budget(args.max_cases, args.rate, args.deadline)
        import requests

        response = http_request(
            requests.Request("GET", base_url + "/openapi.json").prepare(), budget
        )
        if response.status_code != 200:
            raise ValueError("OpenAPI schema did not respond successfully.")
        raw_schema = response.json()
        local_references_only(raw_schema)
        report["schema_sha256"] = hashlib.sha256(
            json.dumps(raw_schema, sort_keys=True).encode()
        ).hexdigest()
        # Schema servers cannot redirect transport away from the attempt URL.
        raw_schema.pop("servers", None)
        schema = schemathesis.openapi.from_dict(raw_schema)
        verifier = Verifier(schema, base_url, fixture, budget)
        if args.replay_report:
            replay = json.loads(args.replay_report.read_text(encoding="utf-8"))
            if replay["attempt"] != args.attempt:
                raise ValueError("The replay report belongs to another disposable attempt.")
            verifier.execute(replay["failures"][args.replay_case]["request"])
            report["mode"] = "replay"
        else:
            suite(verifier, args, hypothesis)
            positive = {
                item["request"]["operation"]
                for item in verifier.results
                if item["status"] == "passed"
                and item["http_status"] == 200
                and item["request"]["category"] == "positive"
            }
            if positive != set(OPERATIONS):
                raise ValueError("All four business operations require a validated HTTP 200.")
        if time.monotonic() - budget.started >= budget.seconds:
            raise Incomplete("The total deadline expired while validating or generating cases.")
        report["status"] = "failed" if verifier.failures else "passed"
    except Incomplete:
        report["reason"] = "Request budget or total deadline exhausted; the gate is incomplete."
    except ToolUnavailable:
        report.update(status="failed", reason="The dedicated contracts dependency is missing.")
    except Exception as exc:
        report.update(
            status="failed",
            reason="Contracts gate could not complete the required checks.",
            error_types=check_names(exc),
        )
    finally:
        if verifier is not None:
            report.update(results=verifier.results, failures=verifier.failures)
        if budget is not None:
            report["requests_sent"] = budget.used
            report["elapsed_seconds"] = time.monotonic() - budget.started
        report["finished_at"] = datetime.now(UTC).isoformat()
        report["summary"] = {
            operation: {
                "cases": sum(
                    item["request"]["operation"] == operation for item in report["results"]
                ),
                "validated_200": sum(
                    item["request"]["operation"] == operation
                    and item["status"] == "passed"
                    and item["http_status"] == 200
                    for item in report["results"]
                ),
            }
            for operation in OPERATIONS
        }
        for index, failure in enumerate(report["failures"]):
            failure["reproduction"] = shlex.join(
                [
                    "python",
                    "scripts/verify_contracts.py",
                    "--base-url",
                    args.base_url,
                    "--attempt",
                    args.attempt,
                    "--credentials-file",
                    str(args.credentials_file),
                    "--report",
                    str(args.report.with_name("contracts-replay.json")),
                    "--replay-report",
                    str(args.report),
                    "--replay-case",
                    str(index),
                ]
            )
    return sanitize(
        report,
        [
            value["token"]
            for value in fixture.values()
            if isinstance(value, dict) and "token" in value
        ],
    )


def worker(args: argparse.Namespace, sender: object) -> None:
    try:
        sender.send(verify(args))
    except BaseException as exc:
        report = initial_report(args)
        report.update(
            status="failed",
            reason="The contracts worker could not return its final report.",
            error_types=check_names(exc),
            summary={operation: {"cases": 0, "validated_200": 0} for operation in OPERATIONS},
        )
        sender.send(report)
    finally:
        sender.close()


def supervised_verify(args: argparse.Namespace) -> dict:
    """Bound imports, schema generation and all HTTP work with a separate worker."""
    if not 0 < args.deadline <= 300:
        return verify(args)
    started = time.monotonic()
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=worker, args=(args, sender))
    process.start()
    sender.close()
    try:
        remaining = max(0.0, args.deadline - (time.monotonic() - started))
        if receiver.poll(remaining):
            try:
                return receiver.recv()
            except EOFError:
                report = initial_report(args)
                report.update(
                    status="failed", reason="The contracts worker exited without a report."
                )
        else:
            report = initial_report(args)
            report.update(
                reason="Total deadline exhausted; worker terminated before the final report. "
                "Partial requests are unavailable; no approval was recorded.",
                partial_results_unavailable=True,
            )
        report.update(
            finished_at=datetime.now(UTC).isoformat(),
            elapsed_seconds=time.monotonic() - started,
            summary={operation: {"cases": 0, "validated_200": 0} for operation in OPERATIONS},
        )
        return report
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=0.5)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.5)
        process.close()


def main() -> None:
    args = parser().parse_args()
    report = supervised_verify(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"HTTP contracts: {report['status']}; seed={args.seed}; "
        f"requests={report.get('requests_sent', 0)}/{args.max_cases}; "
        f"quota={report.get('quota_policy', 'unknown')}; report={args.report}"
    )
    for operation, outcome in report["summary"].items():
        print(
            f"GET {operation}: cases={outcome['cases']}, validated_200={outcome['validated_200']}"
        )
    if report.get("reason"):
        print(report["reason"])
    raise SystemExit({"passed": 0, "failed": 1, "incomplete": 2}[report["status"]])


if __name__ == "__main__":
    main()
