import asyncio
import os
import secrets
import subprocess
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


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
    main()
