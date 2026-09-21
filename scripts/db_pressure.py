"""Bloqueio de tabela por 15s: falha controlada, sem mudar linhas de demonstração."""

import asyncio
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_size=1, max_overflow=0)
    marker = Path("/faults/db-lock-ready")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            await connection.execute(text("LOCK TABLE sale_items IN ACCESS EXCLUSIVE MODE"))
            marker.write_text("locked")
            await asyncio.sleep(15)
    finally:
        marker.unlink(missing_ok=True)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
