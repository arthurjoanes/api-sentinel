"""Derive expected HTTP results from raw rows, without importing application queries."""

import asyncio
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    output: dict = {"start": "2026-01-01", "end": "2026-03-01", "tenants": {}}
    digest = hashlib.sha256()
    try:
        async with engine.connect() as connection:
            for tenant, store in (("tenant_a", 1), ("tenant_b", 4)):
                revenue = 0
                orders: set[int] = set()
                first_items = []
                rows = await connection.stream(
                    text("""
                    SELECT s.id,s.order_id,s.sold_at,p.sku,s.quantity,s.unit_price_cents
                    FROM sale_items s JOIN products p ON p.id=s.product_id
                    WHERE s.store_id=:store AND s.sold_at >= '2026-01-01T03:00:00Z'
                        AND s.sold_at < '2026-03-02T03:00:00Z'
                    ORDER BY s.sold_at DESC,s.id DESC
                """),
                    {"store": store},
                )
                count = 0
                async for row in rows.mappings():
                    item = dict(row)
                    item["sold_at"] = item["sold_at"].isoformat()
                    item["line_total_cents"] = item["quantity"] * item["unit_price_cents"]
                    digest.update(json.dumps(item, sort_keys=True).encode())
                    revenue += item["line_total_cents"]
                    orders.add(item["order_id"])
                    count += 1
                    if len(first_items) < 5:
                        first_items.append(item)
                # Positive cents: exact integer half-up, independent of application Decimal.
                ticket = (2 * revenue + len(orders)) // (2 * len(orders))
                output["tenants"][tenant] = {
                    "store": store,
                    "stores": list(range(store, store + 3)),
                    "revenue_cents": revenue,
                    "order_count": len(orders),
                    "average_ticket_cents": ticket,
                    "raw_items": count,
                    "sales": first_items,
                    "available": 20 + store,
                }
            output["dataset_version"] = await connection.scalar(
                text("SELECT version FROM datasets WHERE id=1")
            )
    finally:
        await engine.dispose()
    output["raw_rows_sha256"] = digest.hexdigest()
    output["method"] = (
        "Rows streamed from PostgreSQL; Python integer sum/distinct orders; "
        "no application aggregate/seed import."
    )
    Path("/artifacts/oracle.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps({"oracle": "oracle.json", "raw_rows_sha256": digest.hexdigest()}))


if __name__ == "__main__":
    asyncio.run(main())
