"""Verify Cloud SQL connectivity using the application's configured credentials."""

import asyncio

from cicero.config import get_settings
from cicero.db.connection import DatabaseConfigurationError, DatabaseManager


async def main() -> int:
    settings = get_settings()
    if not settings.database_configured:
        raise DatabaseConfigurationError(
            "Cloud SQL is not configured. Populate the CICERO_DATABASE_* variables in .env."
        )

    manager = DatabaseManager(settings)
    try:
        await manager.start()
        details = await manager.diagnostics()
        print("Cloud SQL connection successful.")
        print(f"Database: {details['database_name']}")
        print(f"Database user: {details['database_user']}")
        print(f"Server: {details['server_version']}")
        return 0
    finally:
        await manager.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
