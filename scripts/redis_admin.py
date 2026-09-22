"""Redis maintenance for controlled experiments; read its credential only inside tools."""

import argparse
import asyncio
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from redis.asyncio import Redis

from api_sentinel.config import Settings


def experiment_client(db: int = 1) -> Redis:
    password = Path("/redis-admin/experiment-password").read_text(encoding="ascii").strip()
    parsed = urlsplit(Settings().redis_url)
    url = urlunsplit((parsed.scheme, parsed.netloc, f"/{db}", "", ""))
    return Redis.from_url(
        url,
        username="experiment",
        password=password,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=["cache-enable", "cache-disable", "cache-clear", "expire"]
    )
    parser.add_argument("key", nargs="?")
    arguments = parser.parse_args()
    redis = experiment_client()
    try:
        if arguments.operation in {"cache-enable", "cache-disable"}:
            permissions = (
                ["+get", "+set", "+del", "+eval", "+ping", "+select", "+client|setinfo"]
                if arguments.operation == "cache-enable"
                else ["-@all"]
            )
            await redis.execute_command("ACL", "SETUSER", "cache", *permissions)
        elif arguments.operation == "cache-clear":
            await redis.flushdb()
        elif arguments.key and arguments.key.startswith("summary:"):
            await redis.pexpire(arguments.key, 1)
        else:
            raise ValueError("expire requires a summary cache key")
    finally:
        await redis.aclose()
    print("Redis experiment operation completed")


if __name__ == "__main__":
    asyncio.run(main())
