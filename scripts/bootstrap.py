import asyncio
import hashlib
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def prepare_redis(
    credentials: Path = Path("/redis-credentials"),
    server: Path = Path("/redis-auth"),
    admin: Path = Path("/redis-admin"),
) -> None:
    """Create project-specific Redis credentials; preserve them across container restarts."""
    for directory in (credentials, server, admin):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755 if directory != admin else 0o700)
    hashes = {}
    for role, directory in (
        ("quota", credentials),
        ("cache", credentials),
        ("health", server),
        ("experiment", admin),
    ):
        path = directory / f"{role}-password"
        if not path.exists():
            with path.open("x", encoding="ascii") as handle:
                handle.write(secrets.token_urlsafe(48))
        password = path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{64}", password):
            raise ValueError(f"Invalid Redis credential file for {role}; refusing to replace it.")
        path.chmod(0o600 if directory == admin else 0o644)
        hashes[f"{role}_hash"] = hashlib.sha256(password.encode("ascii")).hexdigest()
    template = Path(__file__).resolve().parents[1] / "deploy" / "redis" / "users.acl"
    acl = server / "users.acl"
    staged = server / "users.acl.new"
    staged.write_text(template.read_text(encoding="ascii").format(**hashes), encoding="ascii")
    staged.chmod(0o644)
    staged.replace(acl)


async def grant_reader() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("""DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sentinel_app') THEN
                    CREATE ROLE sentinel_app LOGIN PASSWORD 'sentinel-read-local-only';
                END IF;
                END $$""")
            )
            await connection.execute(text("GRANT CONNECT ON DATABASE sentinel TO sentinel_app"))
            await connection.execute(text("GRANT USAGE ON SCHEMA public TO sentinel_app"))
            await connection.execute(
                text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO sentinel_app")
            )
    finally:
        await engine.dispose()


def main() -> None:
    directory = Path("/secrets")
    directory.mkdir(exist_ok=True)
    for name in ("cursor-key", "webhook-token"):
        path = directory / name
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48))
    (directory / "expected-replicas").write_text(os.getenv("REPLICAS", "2"))
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    subprocess.run(["python", "-m", "api_sentinel.cli", "seed"], check=True)
    asyncio.run(grant_reader())
    for path in directory.iterdir():
        path.chmod(0o644)
    os.chown("/receiver-data", 10001, 10001)
    # SQLite volume is initialized independently from PostgreSQL.
    print("Migração, seed e permissões: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--redis-only"]:
        prepare_redis()
        print("Redis ACL and project credentials: ready")
    elif sys.argv[1:]:
        raise SystemExit("Use bootstrap.py [--redis-only]")
    else:
        main()
