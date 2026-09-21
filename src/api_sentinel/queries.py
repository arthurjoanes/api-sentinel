from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TypedDict
from zoneinfo import ZoneInfo

from sqlalchemy import Select, distinct, func, literal, select, tuple_
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from api_sentinel.auth import Principal, authorize
from api_sentinel.cursor import CursorScope, SalePosition, decode_cursor, encode_cursor
from api_sentinel.db import Database
from api_sentinel.errors import Problem
from api_sentinel.metrics import DB_QUERIES
from api_sentinel.models import datasets, products, sale_items, stores

BUSINESS_TIMEZONE = ZoneInfo("America/Sao_Paulo")
MAX_PERIOD_DAYS = 90


class DatasetInfo(TypedDict):
    version: str
    updated_at: str
    starts_on: str
    ends_on: str


def period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    if end < start or (end - start).days >= MAX_PERIOD_DAYS:
        raise Problem(
            422, "invalid_period", "O período deve conter de 1 a 90 dias, em ordem crescente."
        )
    if end == date.max:
        raise Problem(
            422, "invalid_period", "A data final não permite calcular o limite do período."
        )
    lower = datetime.combine(start, time.min, BUSINESS_TIMEZONE).astimezone(UTC)
    upper = datetime.combine(end + timedelta(days=1), time.min, BUSINESS_TIMEZONE).astimezone(UTC)
    return lower, upper


def average_ticket(revenue_cents: int, order_count: int) -> int:
    if order_count == 0:
        return 0
    return int(
        (Decimal(revenue_cents) / Decimal(order_count)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )


async def dataset_info(db: Database) -> DatasetInfo:
    async with db.connection() as connection:
        DB_QUERIES.labels(operation="dataset").inc()
        row = (
            (await connection.execute(select(datasets).where(datasets.c.id == 1)))
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise Problem(503, "dataset_unavailable", "Dados de demonstração indisponíveis.")
    return DatasetInfo(
        version=row["version"],
        updated_at=row["updated_at"].isoformat(),
        starts_on=row["starts_on"].isoformat(),
        ends_on=row["ends_on"].isoformat(),
    )


async def list_stores(db: Database, principal: Principal) -> dict[str, object]:
    authorize(principal, "stores:read")
    statement = (
        select(stores.c.id, stores.c.name, stores.c.coverage_starts_on, stores.c.coverage_ends_on)
        .where(stores.c.tenant_id == principal.tenant_id, stores.c.id.in_(principal.store_ids))
        .order_by(stores.c.id)
    )
    async with db.connection() as connection:
        DB_QUERIES.labels(operation="stores").inc()
        rows = (await connection.execute(statement)).mappings().all()
    return {
        "items": [
            {
                "id": row["id"],
                "name": row["name"],
                "coverage": {
                    "starts_on": row["coverage_starts_on"].isoformat(),
                    "ends_on": row["coverage_ends_on"].isoformat(),
                },
            }
            for row in rows
        ]
    }


async def _store_dataset(
    connection: AsyncConnection, principal: Principal, store_id: int, start: date, end: date
) -> RowMapping:
    statement = (
        select(
            datasets.c.version,
            datasets.c.updated_at,
            stores.c.coverage_starts_on,
            stores.c.coverage_ends_on,
        )
        .select_from(stores.join(datasets, datasets.c.id == 1))
        .where(stores.c.id == store_id, stores.c.tenant_id == principal.tenant_id)
    )
    DB_QUERIES.labels(operation="dataset").inc()
    row = (await connection.execute(statement)).mappings().one_or_none()
    if row is None:
        raise Problem(404, "store_unavailable", "Loja ou massa de demonstração indisponível.")
    if start < row["coverage_starts_on"] or end > row["coverage_ends_on"]:
        raise Problem(
            422,
            "data_outside_coverage",
            "Período fora da cobertura da loja: "
            f"{row['coverage_starts_on'].isoformat()} a {row['coverage_ends_on'].isoformat()}.",
        )
    return row


def coverage_info(info: RowMapping, start: date, end: date) -> dict[str, object]:
    # A massa cobre todo o período pedido; períodos fora da cobertura são recusados em
    # _store_dataset. Um dia sem venda dentro da cobertura é um zero real, não ausência.
    # complete é derivado dos limites: fica true aqui e reflete a realidade se a política
    # de cobertura passar a recortar em vez de recusar.
    starts_on, ends_on = info["coverage_starts_on"], info["coverage_ends_on"]
    return {
        "complete": start >= starts_on and end <= ends_on,
        "starts_on": starts_on.isoformat(),
        "ends_on": ends_on.isoformat(),
    }


def summary_statement(tenant_id: int, store_id: int, start: date, end: date) -> Select:
    lower, upper = period_bounds(start, end)
    return select(
        func.coalesce(func.sum(sale_items.c.quantity * sale_items.c.unit_price_cents), 0).label(
            "revenue_cents"
        ),
        func.count(distinct(tuple_(sale_items.c.store_id, sale_items.c.order_id))).label(
            "order_count"
        ),
    ).where(
        sale_items.c.tenant_id == tenant_id,
        sale_items.c.store_id == store_id,
        sale_items.c.sold_at >= lower,
        sale_items.c.sold_at < upper,
    )


async def summary(
    db: Database, principal: Principal, store_id: int, start: date, end: date
) -> dict[str, object]:
    authorize(principal, "sales:read", store_id)
    statement = summary_statement(principal.tenant_id, store_id, start, end)
    async with db.connection() as connection:
        info = await _store_dataset(connection, principal, store_id, start, end)
        DB_QUERIES.labels(operation="summary").inc()
        row = (await connection.execute(statement)).mappings().one()
    revenue, orders = int(row["revenue_cents"]), int(row["order_count"])
    return {
        "store_id": store_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "currency": "BRL",
        "revenue_cents": revenue,
        "order_count": orders,
        "average_ticket_cents": average_ticket(revenue, orders),
        "data_updated_at": info["updated_at"].isoformat(),
        "observed_at": datetime.now(UTC).isoformat(),
        "dataset_version": info["version"],
        "coverage": coverage_info(info, start, end),
    }


async def sales(
    db: Database,
    principal: Principal,
    store_id: int,
    start: date,
    end: date,
    limit: int,
    cursor: str | None,
    secret: str,
) -> dict[str, object]:
    authorize(principal, "sales:read", store_id)
    lower, upper = period_bounds(start, end)
    if not 1 <= limit <= 100:
        raise Problem(422, "invalid_page_limit", "A página deve conter de 1 a 100 itens.")
    async with db.connection() as connection:
        info = await _store_dataset(connection, principal, store_id, start, end)
        scope = CursorScope(
            principal.tenant_id, store_id, start.isoformat(), end.isoformat(), info["version"]
        )
        statement = (
            select(
                sale_items.c.id,
                sale_items.c.order_id,
                sale_items.c.sold_at,
                products.c.sku,
                sale_items.c.quantity,
                sale_items.c.unit_price_cents,
            )
            .join(products, sale_items.c.product_id == products.c.id)
            .where(
                sale_items.c.tenant_id == principal.tenant_id,
                sale_items.c.store_id == store_id,
                sale_items.c.sold_at >= lower,
                sale_items.c.sold_at < upper,
            )
        )
        if cursor:
            position = decode_cursor(cursor, scope, secret)
            statement = statement.where(
                tuple_(sale_items.c.sold_at, sale_items.c.id)
                < tuple_(literal(position.sold_at), literal(position.item_id))
            )
        statement = statement.order_by(sale_items.c.sold_at.desc(), sale_items.c.id.desc()).limit(
            limit + 1
        )
        DB_QUERIES.labels(operation="sales").inc()
        rows = (await connection.execute(statement)).mappings().all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = encode_cursor(scope, SalePosition(last["sold_at"], last["id"]), secret)
    return {
        "items": [
            {
                "id": row["id"],
                "order_id": row["order_id"],
                "sold_at": row["sold_at"].isoformat(),
                "sku": row["sku"],
                "quantity": row["quantity"],
                "unit_price_cents": row["unit_price_cents"],
                "line_total_cents": row["quantity"] * row["unit_price_cents"],
            }
            for row in page
        ],
        "next_cursor": next_cursor,
        "dataset_version": info["version"],
        "data_updated_at": info["updated_at"].isoformat(),
        "coverage": coverage_info(info, start, end),
    }
