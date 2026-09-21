import argparse
import json
import os
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from api_sentinel.auth import authenticate
from api_sentinel.cli import issue_credential
from api_sentinel.db import Database
from api_sentinel.errors import Problem
from api_sentinel.models import credentials, datasets, metadata, sale_items
from api_sentinel.queries import list_stores, sales, summary
from api_sentinel.seed import seed_demo

DAY = date(2026, 1, 1)
CURSOR_SECRET = "integration-test-only-with-more-than-thirty-two-characters"


@dataclass
class DataLab:
    db: Database
    replica: Database
    admin: AsyncEngine
    tokens: dict[str, str]
    secrets_file: Path


@pytest.fixture
async def lab(tmp_path: Path) -> AsyncIterator[DataLab]:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL não configurada; requer PostgreSQL de testes isolado.")
    if "sentinel_test" not in url:
        raise RuntimeError("O teste exige banco explicitamente denominado sentinel_test.")
    schema = "data_test_" + secrets.token_hex(8)
    admin = create_async_engine(url, execution_options={"schema_translate_map": {None: schema}})
    db, replica = Database(url), Database(url)
    for engine in [db.engine, db.auth_engine, replica.engine, replica.auth_engine]:
        engine.update_execution_options(schema_translate_map={None: schema})
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(metadata.create_all)
        secrets_file = tmp_path / "demo.json"
        await seed_demo(admin, secrets_file, orders_per_day=1)
        yield DataLab(db, replica, admin, json.loads(secrets_file.read_text()), secrets_file)
    finally:
        await db.close()
        await replica.close()
        async with admin.begin() as connection:
            await connection.run_sync(metadata.drop_all)
            await connection.execute(text(f'DROP SCHEMA "{schema}"'))
        await admin.dispose()


async def test_manual_summary_correct_and_no_item_multiplication(lab: DataLab) -> None:
    principal = await authenticate(lab.db, lab.tokens["probe"])
    result = await summary(lab.db, principal, 7, DAY, DAY)
    assert result["revenue_cents"] == 12500
    assert result["order_count"] == 2
    assert result["average_ticket_cents"] == 6250
    assert result["coverage"] == {
        "complete": True,
        "starts_on": "2026-01-01",
        "ends_on": "2026-01-01",
    }


async def test_period_excludes_midnight_of_following_business_day(lab: DataLab) -> None:
    async with lab.admin.begin() as connection:
        await connection.execute(
            insert(sale_items).values(
                id=7999999999999,
                tenant_id=3,
                store_id=7,
                order_id=103,
                sold_at=datetime(2026, 1, 2, 3, tzinfo=UTC),
                product_id=1,
                quantity=10,
                unit_price_cents=10000,
            )
        )
    principal = await authenticate(lab.db, lab.tokens["probe"])
    result = await summary(lab.db, principal, 7, DAY, DAY)
    assert (result["revenue_cents"], result["order_count"]) == (12500, 2)


async def test_expired_and_revocation_are_seen_by_both_process_pools(lab: DataLab) -> None:
    with pytest.raises(Problem) as failure:
        await authenticate(lab.db, lab.tokens["expired"])
    assert failure.value.status == 401
    for db in (lab.db, lab.replica):
        assert (await authenticate(db, lab.tokens["tenant_a"])).tenant_id == 1
    async with lab.admin.begin() as connection:
        await connection.execute(
            update(credentials)
            .where(credentials.c.name == "tenant_a")
            .values(revoked_at=datetime.now(UTC))
        )
    for db in (lab.db, lab.replica):
        with pytest.raises(Problem) as failure:
            await authenticate(db, lab.tokens["tenant_a"])
        assert failure.value.status == 401


async def test_cross_tenant_and_scope_rejected_before_business_query(lab: DataLab) -> None:
    principal = await authenticate(lab.db, lab.tokens["tenant_a"])
    stores = await list_stores(lab.db, principal)
    assert [row["id"] for row in stores["items"]] == [1, 2, 3]
    with pytest.raises(Problem) as failure:
        await summary(lab.db, principal, 4, DAY, DAY)
    assert failure.value.code == "store_forbidden"
    restricted = await authenticate(lab.db, lab.tokens["restricted"])
    with pytest.raises(Problem) as failure:
        await summary(lab.db, restricted, 1, DAY, DAY)
    assert failure.value.code == "insufficient_scope"


async def test_unknown_coverage_never_looks_like_zero(lab: DataLab) -> None:
    principal = await authenticate(lab.db, lab.tokens["probe"])
    with pytest.raises(Problem) as failure:
        await summary(lab.db, principal, 7, DAY, date(2026, 1, 2))
    assert failure.value.code == "data_outside_coverage"


async def test_cursor_tie_breaker_no_duplicates_and_limit(lab: DataLab) -> None:
    principal = await authenticate(lab.db, lab.tokens["probe"])
    cursor = None
    ids = []
    for _ in range(3):
        page = await sales(lab.db, principal, 7, DAY, DAY, 1, cursor, CURSOR_SECRET)
        assert len(page["items"]) == 1
        ids.append(page["items"][0]["id"])
        cursor = page["next_cursor"]
    assert ids == [7000000000003, 7000000000002, 7000000000001]
    assert cursor is None
    with pytest.raises(Problem):
        await sales(lab.db, principal, 7, DAY, DAY, 101, None, CURSOR_SECRET)


async def test_cursor_rejects_other_store_and_changed_dataset(lab: DataLab) -> None:
    principal = await authenticate(lab.db, lab.tokens["tenant_a"])
    page = await sales(lab.db, principal, 1, DAY, date(2026, 1, 2), 1, None, CURSOR_SECRET)
    assert page["next_cursor"]
    with pytest.raises(Problem) as failure:
        await sales(
            lab.db, principal, 2, DAY, date(2026, 1, 2), 1, page["next_cursor"], CURSOR_SECRET
        )
    assert failure.value.code == "invalid_cursor"
    async with lab.admin.begin() as connection:
        await connection.execute(update(datasets).values(version="changed"))
    with pytest.raises(Problem) as failure:
        await sales(
            lab.db, principal, 1, DAY, date(2026, 1, 2), 1, page["next_cursor"], CURSOR_SECRET
        )
    assert failure.value.code == "invalid_cursor"


async def test_seed_is_idempotent_and_preserves_revocation(lab: DataLab) -> None:
    async with lab.admin.begin() as connection:
        original_count = await connection.scalar(select(func.count()).select_from(sale_items))
        await connection.execute(
            update(credentials)
            .where(credentials.c.name == "tenant_a")
            .values(revoked_at=datetime.now(UTC))
        )
    result = await seed_demo(lab.admin, lab.secrets_file, orders_per_day=1)
    assert result["status"] == "preservado"
    assert result["item_count"] == original_count
    assert json.loads(lab.secrets_file.read_text()) == lab.tokens
    with pytest.raises(Problem):
        await authenticate(lab.replica, lab.tokens["tenant_a"])
    with pytest.raises(ValueError, match="massa diferente"):
        await seed_demo(lab.admin, lab.secrets_file, orders_per_day=2)
    with pytest.raises(ValueError, match="segredos ausente"):
        await seed_demo(lab.admin, lab.secrets_file.with_name("missing.json"), orders_per_day=1)


async def test_issue_prevents_foreign_stores_and_inherits_tenant_quota(lab: DataLab) -> None:
    args = argparse.Namespace(
        name="test-issued", tenant=1, stores=[4], scopes=["sales:read"], expires_hours=1
    )
    with pytest.raises(ValueError, match="tenant"):
        await issue_credential(lab.admin, args)
    args.stores = [1]
    issued = await issue_credential(lab.admin, args)
    principal = await authenticate(lab.db, issued["token"])
    assert principal.store_ids == (1,)
    assert principal.quota_per_second == 30
    assert principal.scopes == ("sales:read",)
