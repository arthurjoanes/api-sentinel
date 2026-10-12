"""Provision private contract fixtures only in a disposable review project."""

import argparse
import asyncio
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import create_async_engine

from api_sentinel.auth import ALLOWED_SCOPES, token_digest
from api_sentinel.cursor import CursorScope, SalePosition, encode_cursor
from api_sentinel.models import credentials, sale_items, stores, tenants
from api_sentinel.seed import new_token, write_private_json


async def provision(attempt: str, base_url: str) -> None:
    if not re.fullmatch(r"pf-api-sentinel-review-[a-z0-9-]+", attempt):
        raise ValueError("Contract fixtures require a disposable review project.")
    if os.getenv("SENTINEL_LAB_PROJECT") != attempt:
        raise ValueError("The fixture attempt must match the container project.")
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+", base_url):
        raise ValueError("Only this attempt's published loopback URL is accepted.")
    directory = Path("/secrets")
    target = directory / "contracts.json"
    if target.exists():
        raise ValueError("Contract credentials already exist; refusing to replace them.")
    demo = json.loads((directory / "demo.json").read_text())
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_size=1, max_overflow=0)
    identities = {}
    try:
        async with engine.begin() as connection:
            source = (
                (await connection.execute(select(sale_items).where(sale_items.c.store_id == 7)))
                .mappings()
                .all()
            )
            if len(source) < 2:
                raise ValueError("Technical fixture must exist before contract provisioning.")
            now = datetime.now(UTC)
            for name, tenant, store, quota in (("contract", 4, 8, 30), ("low_quota", 5, 9, 1)):
                token = new_token()
                await connection.execute(
                    insert(tenants).values(
                        id=tenant, name=f"Contract {name}", is_probe=False, quota_per_second=quota
                    )
                )
                await connection.execute(
                    insert(stores).values(
                        id=store,
                        tenant_id=tenant,
                        name=f"Contract {name}",
                        coverage_starts_on=date(2026, 1, 1),
                        coverage_ends_on=date(2026, 1, 1),
                    )
                )
                await connection.execute(
                    insert(sale_items),
                    [
                        {
                            **row,
                            "id": store * 1_000_000_000_000 + index,
                            "tenant_id": tenant,
                            "store_id": store,
                        }
                        for index, row in enumerate(source, 1)
                    ],
                )
                await connection.execute(
                    insert(credentials).values(
                        id=os.urandom(16).hex(),
                        name=f"contracts-{name}",
                        token_hash=token_digest(token),
                        tenant_id=tenant,
                        store_ids=[store],
                        scopes=sorted(ALLOWED_SCOPES),
                        created_at=now,
                        expires_at=now + timedelta(hours=24),
                        revoked_at=None,
                    )
                )
                identities[name] = {
                    "token": token,
                    "tenant_id": tenant,
                    "store_id": store,
                    "quota_per_second": quota,
                    "start": "2026-01-01",
                    "end": "2026-01-01",
                }
            stale = encode_cursor(
                CursorScope(4, 8, "2026-01-01", "2026-01-01", "previous-version"),
                SalePosition(source[0]["sold_at"], 8_000_000_000_001),
                (directory / "cursor-key").read_text().strip(),
            )
        write_private_json(
            target,
            {
                "attempt": attempt,
                "quota_policy": os.getenv("QUOTA_ALGORITHM", "fixed-window"),
                "burst_capacity": int(os.getenv("QUOTA_BURST_CAPACITY", "10")),
                "allowed_base_urls": ["http://proxy", base_url],
                **identities,
                "tenant_b": {"token": demo["tenant_b"], "store_id": 4},
                "tenant_a": {"token": demo["tenant_a"], "store_id": 1},
                "probe": {"token": demo["probe"], "store_id": 7, "date": "2026-01-01"},
                "stale_cursor": stale,
            },
        )
        target.chmod(0o600)
    finally:
        await engine.dispose()
    print("Private contract fixtures ready: tenants 4/5, stores 8/9; limiter active.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    asyncio.run(provision(args.attempt, args.base_url))
