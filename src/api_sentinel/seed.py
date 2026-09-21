import hashlib
import json
import os
import random
import secrets
import stat
import tempfile
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from api_sentinel.auth import ALLOWED_SCOPES, token_digest
from api_sentinel.models import credentials, datasets, products, sale_items, stores, tenants

SEED_START = date(2026, 1, 1)
SEED_DAYS = 60
SEED_NUMBER = 20260101
DEFAULT_ORDERS_PER_DAY = 30
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "manual-sales.json"


def commercial_items(orders_per_day: int) -> Iterator[dict[str, object]]:
    if not 1 <= orders_per_day <= 1000:
        raise ValueError("Use de 1 a 1000 pedidos por loja/dia.")
    generator = random.Random(SEED_NUMBER)
    for store_id in range(1, 7):
        for day in range(SEED_DAYS):
            for order in range(orders_per_day):
                sold_at = datetime(2026, 1, 1, 11, tzinfo=UTC) + timedelta(
                    days=day, seconds=order * 30
                )
                for line in range(generator.randint(1, 3)):
                    product_id = generator.randint(1, 40)
                    yield {
                        "id": store_id * 1_000_000_000_000
                        + day * 10_000_000
                        + order * 10
                        + line
                        + 1,
                        "tenant_id": 1 if store_id <= 3 else 2,
                        "store_id": store_id,
                        "order_id": day * 10_000 + order + 1,
                        "sold_at": sold_at,
                        "product_id": product_id,
                        "quantity": generator.randint(1, 3),
                        "unit_price_cents": 1000 + product_id * 137,
                    }


def manual_items() -> list[dict[str, object]]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return [
        {
            **item,
            "tenant_id": fixture["tenant_id"],
            "store_id": fixture["store_id"],
            "sold_at": datetime.fromisoformat(item["sold_at"]),
        }
        for item in fixture["items"]
    ]


def seed_manifest(orders_per_day: int) -> dict[str, object]:
    digest = hashlib.sha256()
    count = 0
    for item in commercial_items(orders_per_day):
        digest.update(json.dumps(item, sort_keys=True, default=str, separators=(",", ":")).encode())
        count += 1
    for item in manual_items():
        digest.update(json.dumps(item, sort_keys=True, default=str, separators=(",", ":")).encode())
        count += 1
    return {
        "generator": "sentinel-v1",
        "seed": SEED_NUMBER,
        "days": SEED_DAYS,
        "starts_on": SEED_START.isoformat(),
        "ends_on": (SEED_START + timedelta(days=SEED_DAYS - 1)).isoformat(),
        "commercial_tenants": 2,
        "commercial_stores": 6,
        "probe_stores": 1,
        "products": 40,
        "orders_per_store_day": orders_per_day,
        "item_count": count,
        "sha256": digest.hexdigest(),
    }


def new_token() -> str:
    return "sentinel_" + secrets.token_urlsafe(32)


def write_private_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.stat() if path.exists() else None
    descriptor, filename = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if previous is not None:
            # O bootstrap habilita leitores do volume; repetir seed não revoga esse acesso.
            temporary.chmod(stat.S_IMODE(previous.st_mode))
            if hasattr(os, "chown"):
                os.chown(temporary, previous.st_uid, previous.st_gid)
        # mkstemp cria em 0600; a primeira gravação continua privada.
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def seed_demo(
    engine: AsyncEngine, secrets_file: Path, orders_per_day: int = DEFAULT_ORDERS_PER_DAY
) -> dict[str, object]:
    if os.getenv("SENTINEL_ENV", "demo") not in {"demo", "test"}:
        raise ValueError("O seed fictício só é permitido em SENTINEL_ENV=demo ou test.")
    manifest = seed_manifest(orders_per_day)
    configurations = {
        "tenant_a": (1, [1, 2, 3], sorted(ALLOWED_SCOPES), 30),
        "tenant_b": (2, [4, 5, 6], sorted(ALLOWED_SCOPES), 30),
        "probe": (3, [7], ["stores:read", "sales:read"], 10),
        "restricted": (1, [1], ["stores:read"], 30),
        "expired": (1, [1], sorted(ALLOWED_SCOPES), 30),
    }
    async with engine.begin() as connection:
        await connection.execute(text("SELECT pg_advisory_xact_lock(24608104)"))
        existing = (
            (await connection.execute(select(datasets).where(datasets.c.id == 1)))
            .mappings()
            .one_or_none()
        )
        if existing is not None and existing["seed_digest"] != manifest["sha256"]:
            raise ValueError(
                "Já existe uma massa diferente. "
                "Use um volume de demonstração novo para alterar o volume."
            )
        known_credentials = (
            (await connection.execute(select(credentials.c.name, credentials.c.token_hash)))
            .mappings()
            .all()
        )
        tokens: dict[str, str] = (
            json.loads(secrets_file.read_text()) if secrets_file.exists() else {}
        )
        for row in known_credentials:
            name = row["name"]
            if name in configurations and (
                name not in tokens or token_digest(tokens[name]) != row["token_hash"]
            ):
                raise ValueError(
                    "Arquivo de segredos ausente ou incompatível com o banco. "
                    "O seed não substitui credenciais existentes."
                )
        for name in configurations:
            tokens.setdefault(name, new_token())
        # Gravar primeiro permite repetir após interrupção sem perder os tokens emitidos.
        write_private_json(secrets_file, dict(tokens))
        now = datetime.now(UTC)
        if existing is None:
            await connection.execute(
                insert(tenants),
                [
                    {"id": 1, "name": "Rede Aurora", "is_probe": False, "quota_per_second": 30},
                    {"id": 2, "name": "Rede Horizonte", "is_probe": False, "quota_per_second": 30},
                    {
                        "id": 3,
                        "name": "Verificação técnica isolada",
                        "is_probe": True,
                        "quota_per_second": 10,
                    },
                ],
            )
            await connection.execute(
                insert(stores),
                [
                    {
                        "id": store_id,
                        "tenant_id": 1 if store_id <= 3 else (2 if store_id <= 6 else 3),
                        "name": f"Loja {store_id}" if store_id <= 6 else "Fixture do probe",
                        "coverage_starts_on": SEED_START,
                        "coverage_ends_on": SEED_START + timedelta(days=SEED_DAYS - 1)
                        if store_id <= 6
                        else SEED_START,
                    }
                    for store_id in range(1, 8)
                ],
            )
            await connection.execute(
                insert(products),
                [
                    {
                        "id": product_id,
                        "sku": f"SKU-{product_id:03d}",
                        "name": f"Produto sintético {product_id:02d}",
                    }
                    for product_id in range(1, 41)
                ],
            )
            batch: list[dict[str, object]] = []
            for item in commercial_items(orders_per_day):
                batch.append(item)
                if len(batch) == 1000:
                    await connection.execute(insert(sale_items), batch)
                    batch.clear()
            if batch:
                await connection.execute(insert(sale_items), batch)
            await connection.execute(insert(sale_items), manual_items())
            await connection.execute(
                insert(datasets).values(
                    id=1,
                    version="v1-" + str(manifest["sha256"])[:16],
                    updated_at=now,
                    starts_on=SEED_START,
                    ends_on=SEED_START + timedelta(days=SEED_DAYS - 1),
                    seed_orders_per_day=orders_per_day,
                    seed_digest=manifest["sha256"],
                )
            )
        known_names = {row["name"] for row in known_credentials}
        for name, (tenant_id, store_ids, scopes, _quota) in configurations.items():
            if name not in known_names:
                await connection.execute(
                    insert(credentials).values(
                        id=secrets.token_hex(16),
                        name=name,
                        token_hash=token_digest(tokens[name]),
                        tenant_id=tenant_id,
                        store_ids=store_ids,
                        scopes=scopes,
                        created_at=now,
                        expires_at=now + timedelta(days=-1 if name == "expired" else 365),
                        revoked_at=None,
                    )
                )
        actual = await connection.scalar(select(func.count()).select_from(sale_items))
        if actual != manifest["item_count"]:
            raise ValueError(
                "Contagem da massa diverge do manifesto; "
                "o seed não corrige mutações silenciosamente."
            )
    write_private_json(secrets_file.with_name("manifest.json"), manifest)
    return {**manifest, "status": "preservado" if existing is not None else "criado"}
