from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.dialects import postgresql

from api_sentinel.auth import Principal, authorize, token_digest
from api_sentinel.cursor import CursorScope, SalePosition, decode_cursor, encode_cursor
from api_sentinel.errors import Problem
from api_sentinel.queries import average_ticket, period_bounds, summary_statement
from api_sentinel.seed import commercial_items, manual_items, seed_manifest

SECRET = "cursor-key-of-at-least-thirty-two-characters"
SCOPE = CursorScope(1, 1, "2026-01-01", "2026-01-02", "fixture-v1")
POSITION = SalePosition(datetime(2026, 1, 1, 14, 3, tzinfo=UTC), 42)


def test_manual_fixture_has_independent_expected_totals() -> None:
    rows = manual_items()
    assert [row["quantity"] for row in rows] == [2, 1, 1]
    assert [row["unit_price_cents"] for row in rows] == [2500, 3500, 4000]
    assert [row["order_id"] for row in rows] == [101, 101, 102]
    assert average_ticket(12_500, 2) == 6250


@pytest.mark.parametrize("revenue,orders,expected", [(1, 2, 1), (5, 2, 3), (1, 3, 0), (0, 0, 0)])
def test_money_rounds_half_up_without_binary_float(
    revenue: int, orders: int, expected: int
) -> None:
    assert average_ticket(revenue, orders) == expected


def test_business_date_is_inclusive_in_sao_paulo_and_half_open_in_utc() -> None:
    lower, upper = period_bounds(date(2026, 1, 1), date(2026, 1, 1))
    assert lower == datetime(2026, 1, 1, 3, tzinfo=UTC)
    assert upper == datetime(2026, 1, 2, 3, tzinfo=UTC)
    period_bounds(date(2026, 1, 1), date(2026, 3, 31))
    with pytest.raises(Problem, match="90 dias"):
        period_bounds(date(2026, 1, 1), date(2026, 4, 1))
    with pytest.raises(Problem):
        period_bounds(date(2026, 1, 2), date(2026, 1, 1))


def test_cursor_round_trip_and_tamper() -> None:
    cursor = encode_cursor(SCOPE, POSITION, SECRET)
    assert decode_cursor(cursor, SCOPE, SECRET) == POSITION
    with pytest.raises(Problem):
        decode_cursor(cursor.replace(".", "A.", 1), SCOPE, SECRET)
    with pytest.raises(Problem):
        decode_cursor(cursor, SCOPE, "other-secret-with-at-least-thirty-two-characters")


@pytest.mark.parametrize(
    "scope",
    [
        replace(SCOPE, tenant_id=2),
        replace(SCOPE, store_id=2),
        replace(SCOPE, start="2026-01-02"),
        replace(SCOPE, end="2026-01-03"),
        replace(SCOPE, dataset_version="fixture-v2"),
    ],
)
def test_cursor_is_bound_to_every_scope_filter(scope: CursorScope) -> None:
    with pytest.raises(Problem) as failure:
        decode_cursor(encode_cursor(SCOPE, POSITION, SECRET), scope, SECRET)
    assert failure.value.code == "invalid_cursor"


@pytest.mark.parametrize("cursor", ["", "a.b.c", "💥.xx", "a" * 2049, "!!!!.!!!!"])
def test_invalid_cursor_returns_controlled_problem(cursor: str) -> None:
    with pytest.raises(Problem):
        decode_cursor(cursor, SCOPE, SECRET)


def test_scope_and_store_authorization_is_explicit() -> None:
    principal = Principal(1, (1,), ("stores:read",), 30, False)
    authorize(principal, "stores:read", 1)
    with pytest.raises(Problem) as failure:
        authorize(principal, "sales:read", 1)
    assert failure.value.code == "insufficient_scope"
    with pytest.raises(Problem) as failure:
        authorize(principal, "stores:read", 4)
    assert failure.value.code == "store_forbidden"


def test_sql_uses_bound_parameters_and_composite_order_identity() -> None:
    statement = summary_statement(1, 2, date(2026, 1, 1), date(2026, 1, 2))
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "count(DISTINCT (sale_items.store_id, sale_items.order_id))" in str(compiled)
    assert "tenant_id_1" in compiled.params
    assert "2026-01-01" not in str(compiled)


def test_generator_has_stable_ids_and_digest() -> None:
    manifest = seed_manifest(1)
    assert manifest == seed_manifest(1)
    assert manifest["days"] == 60
    rows = list(commercial_items(1))
    assert len({row["id"] for row in rows}) == len(rows)
    assert {row["store_id"] for row in rows} == {1, 2, 3, 4, 5, 6}
    assert {row["tenant_id"] for row in rows} == {1, 2}
    assert token_digest("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
