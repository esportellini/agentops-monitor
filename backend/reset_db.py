#!/usr/bin/env python3
"""
Drops the public schema, re-runs all migrations, and re-seeds.
USE WITH CAUTION — this destroys all data.

    python reset_db.py
"""
import asyncio
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.logging import setup_logging
from app.seed import main as seed_main

setup_logging()


async def drop_and_recreate() -> None:
    url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()
    print("Schema dropped and recreated.")


def run_migrations() -> None:
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=False,
    )
    if result.returncode != 0:
        print("Migration failed.", file=sys.stderr)
        sys.exit(1)
    print("Migrations applied.")


async def main() -> None:
    await drop_and_recreate()
    run_migrations()
    await seed_main()


if __name__ == "__main__":
    asyncio.run(main())
