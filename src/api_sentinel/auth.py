import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from api_sentinel.db import Database
from api_sentinel.errors import Problem
from api_sentinel.metrics import DB_QUERIES
from api_sentinel.models import credentials, tenants

ALLOWED_SCOPES = frozenset({"stores:read", "sales:read", "inventory:read"})


@dataclass(frozen=True, slots=True)
class Principal:
    tenant_id: int
    store_ids: tuple[int, ...]
    scopes: tuple[str, ...]
    quota_per_second: int
    is_probe: bool


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def authenticate(db: Database, token: str) -> Principal:
    if not token.startswith("sentinel_") or not 40 <= len(token) <= 256:
        raise Problem(401, "invalid_credential", "Credencial ausente, inválida ou expirada.")
    statement = (
        select(
            credentials.c.tenant_id,
            credentials.c.store_ids,
            credentials.c.scopes,
            tenants.c.quota_per_second,
            tenants.c.is_probe,
        )
        .join(tenants, tenants.c.id == credentials.c.tenant_id)
        .where(
            credentials.c.token_hash == token_digest(token),
            credentials.c.revoked_at.is_(None),
            credentials.c.expires_at > datetime.now(UTC),
        )
    )
    async with db.connection(kind="auth") as connection:
        DB_QUERIES.labels(operation="auth").inc()
        row = (await connection.execute(statement)).mappings().one_or_none()
    if row is None:
        raise Problem(401, "invalid_credential", "Credencial ausente, inválida ou expirada.")
    return Principal(
        tenant_id=row["tenant_id"],
        store_ids=tuple(row["store_ids"]),
        scopes=tuple(row["scopes"]),
        quota_per_second=row["quota_per_second"],
        is_probe=row["is_probe"],
    )


def authorize(principal: Principal, scope: str, store_id: int | None = None) -> None:
    if scope not in principal.scopes:
        raise Problem(403, "insufficient_scope", "A credencial não permite esta operação.")
    if store_id is not None and store_id not in principal.store_ids:
        raise Problem(403, "store_forbidden", "A credencial não permite consultar esta loja.")
