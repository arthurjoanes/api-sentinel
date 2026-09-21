import argparse
import asyncio
import json
import os
import secrets
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from api_sentinel.auth import ALLOWED_SCOPES, token_digest
from api_sentinel.models import credentials, datasets, stores, tenants
from api_sentinel.queries import period_bounds
from api_sentinel.seed import DEFAULT_ORDERS_PER_DAY, new_token, seed_demo


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Administração local do API Sentinel")
    actions = command.add_subparsers(dest="action", required=True)
    seed = actions.add_parser("seed", help="Criar ou conferir dados e credenciais de teste")
    seed.add_argument("--orders-per-day", type=int, default=DEFAULT_ORDERS_PER_DAY)
    seed.add_argument(
        "--secrets-file",
        type=Path,
        default=Path(os.getenv("DEMO_SECRETS_FILE", "/secrets/demo.json")),
    )
    issue = actions.add_parser("issue", help="Emitir credencial; o token aparece uma vez")
    issue.add_argument("--tenant", type=int, required=True)
    issue.add_argument("--name", required=True)
    issue.add_argument("--stores", nargs="+", type=int)
    issue.add_argument(
        "--scopes", nargs="+", choices=sorted(ALLOWED_SCOPES), default=sorted(ALLOWED_SCOPES)
    )
    issue.add_argument("--expires-hours", type=int, default=24 * 30)
    revoke = actions.add_parser("revoke", help="Revogar por nome ou token")
    identity = revoke.add_mutually_exclusive_group(required=True)
    identity.add_argument("--name")
    identity.add_argument("--token")
    actions.add_parser(
        "advance-version", help="Avançar a versão dos dados e invalidar cache e cursores"
    )
    explain = actions.add_parser("explain", help="Executar EXPLAIN ANALYZE do resumo")
    explain.add_argument("--tenant", type=int, default=1)
    explain.add_argument("--store", type=int, default=1)
    explain.add_argument("--start", type=date.fromisoformat, default=date(2026, 1, 1))
    explain.add_argument("--end", type=date.fromisoformat, default=date(2026, 1, 31))
    return command


async def issue_credential(engine: AsyncEngine, args: argparse.Namespace) -> dict[str, object]:
    if not 1 <= len(args.name) <= 100 or not 1 <= args.expires_hours <= 24 * 366:
        raise ValueError(
            "Nome precisa de 1 a 100 caracteres; validade deve ser de 1 hora a 366 dias."
        )
    token = new_token()
    now = datetime.now(UTC)
    async with engine.begin() as connection:
        tenant = (
            (await connection.execute(select(tenants).where(tenants.c.id == args.tenant)))
            .mappings()
            .one_or_none()
        )
        if tenant is None:
            raise ValueError("Tenant inexistente.")
        allowed = list(
            (
                await connection.execute(
                    select(stores.c.id).where(stores.c.tenant_id == args.tenant)
                )
            ).scalars()
        )
        selected = sorted(set(args.stores if args.stores else allowed))
        if not selected or not set(selected).issubset(allowed):
            raise ValueError("Todas as lojas devem pertencer ao tenant.")
        if await connection.scalar(select(credentials.c.id).where(credentials.c.name == args.name)):
            raise ValueError("Já existe uma credencial com esse nome.")
        await connection.execute(
            insert(credentials).values(
                id=secrets.token_hex(16),
                name=args.name,
                tenant_id=args.tenant,
                store_ids=selected,
                scopes=sorted(set(args.scopes)),
                token_hash=token_digest(token),
                created_at=now,
                expires_at=now + timedelta(hours=args.expires_hours),
                revoked_at=None,
            )
        )
    return {
        "name": args.name,
        "token": token,
        "tenant_id": args.tenant,
        "store_ids": selected,
        "quota_per_second": tenant["quota_per_second"],
        "expires_at": (now + timedelta(hours=args.expires_hours)).isoformat(),
    }


async def execute(args: argparse.Namespace) -> dict[str, object]:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("Defina DATABASE_URL com a credencial administrativa local.")
    engine = create_async_engine(
        url,
        pool_size=1,
        max_overflow=0,
        connect_args={
            "server_settings": {"statement_timeout": "30000", "application_name": "sentinel-tools"}
        },
    )
    try:
        if args.action == "seed":
            return await seed_demo(engine, args.secrets_file, args.orders_per_day)
        if args.action == "issue":
            return await issue_credential(engine, args)
        async with engine.begin() as connection:
            if args.action == "revoke":
                condition = (
                    credentials.c.name == args.name
                    if args.name
                    else credentials.c.token_hash == token_digest(args.token)
                )
                row = (
                    await connection.execute(
                        update(credentials)
                        .where(condition)
                        .values(revoked_at=datetime.now(UTC))
                        .returning(credentials.c.name)
                    )
                ).scalar_one_or_none()
                if row is None:
                    raise ValueError("Credencial não encontrada; nada foi revogado.")
                return {"name": row, "status": "revogada"}
            if args.action == "advance-version":
                version = "v1-" + secrets.token_hex(16)
                changed = (
                    await connection.execute(
                        update(datasets)
                        .where(datasets.c.id == 1)
                        .values(version=version)
                        .returning(datasets.c.id)
                    )
                ).scalar_one_or_none()
                if changed is None:
                    raise ValueError("Massa ainda não criada.")
                return {
                    "dataset_version": version,
                    "status": "versão avançada; dados e data_updated_at preservados",
                }
            lower, upper = period_bounds(args.start, args.end)
            result = await connection.execute(
                text("""
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT COALESCE(SUM(quantity * unit_price_cents), 0) AS revenue_cents,
                       COUNT(DISTINCT (store_id, order_id)) AS order_count
                FROM sale_items
                WHERE tenant_id = :tenant AND store_id = :store
                  AND sold_at >= :lower AND sold_at < :upper
            """),
                {"tenant": args.tenant, "store": args.store, "lower": lower, "upper": upper},
            )
            return {
                "query": "summary",
                "tenant": args.tenant,
                "store": args.store,
                "start": args.start.isoformat(),
                "end": args.end.isoformat(),
                "plan": result.scalar_one(),
            }
    finally:
        await engine.dispose()


def main() -> None:
    args = parser().parse_args()
    try:
        result = asyncio.run(execute(args))
    except (ValueError, OSError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except SQLAlchemyError as exc:
        print(
            "Erro de banco; confira migração, conexão e papel administrativo. "
            "Nenhum sucesso foi registrado.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
