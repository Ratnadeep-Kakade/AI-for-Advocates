"""Apply Cicero migrations through the application's DatabaseManager.

Run from the backend root (Cloud Shell or local, ADC credentials):

    uv run python scripts/run_migrations.py [--bootstrap-fresh-db]

Default path: stamp the 20261104_0001 baseline when the base schema exists
but Alembic has no history yet, then `alembic upgrade head`. The baseline
contains no DDL by design (the schema pre-dates migrations).

With --bootstrap-fresh-db (brand-new empty database only): create the ORM
schemas/tables (auth, cases, documents, agents) first, stamp the baseline,
then upgrade. pgvector/pgcrypto extensions are created by migration 0002 or
manually in Cloud SQL Studio if the DB user lacks extension privileges.
"""

from __future__ import annotations

import argparse
import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import text

import cicero.db.models  # noqa: F401  (registers ORM tables)
from cicero.config import get_settings
from cicero.db.base import Base
from cicero.db.connection import DatabaseManager

BASELINE_REVISION = "20261104_0001"
ORM_SCHEMAS = ("auth", "cases", "documents", "agents")


def _alembic_config(connection) -> Config:
    config = Config("alembic.ini")
    config.attributes["connection"] = connection
    return config


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap-fresh-db",
        action="store_true",
        help="Create ORM schemas/tables first (empty database only).",
    )
    args = parser.parse_args()

    settings = get_settings()
    manager = DatabaseManager(settings)
    await manager.start()
    try:
        assert manager.engine is not None
        async with manager.engine.connect() as connection:
            state = (
                await connection.execute(
                    text(
                        "SELECT current_database() AS db, "
                        "to_regclass('public.alembic_version') AS version_table, "
                        "(SELECT count(*) FROM information_schema.tables "
                        " WHERE table_schema IN ('auth','cases','documents')) AS base_tables"
                    )
                )
            ).mappings().one()
            print(f"Database: {state['db']} (base tables found: {state['base_tables']})")
            if int(state["base_tables"]) == 0 and not args.bootstrap_fresh_db:
                raise SystemExit(
                    "No base tables found. This looks like a fresh database: "
                    "re-run with --bootstrap-fresh-db."
                )

            if args.bootstrap_fresh_db and int(state["base_tables"]) == 0:
                for schema in ORM_SCHEMAS:
                    await connection.execute(
                        text(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                    )
                await connection.run_sync(
                    lambda sync_conn: Base.metadata.create_all(sync_conn, checkfirst=True)
                )
                await connection.commit()
                print("Bootstrapped ORM schemas/tables for the fresh database.")

            if state["version_table"] is None:
                await connection.run_sync(
                    lambda sync_conn: command.stamp(
                        _alembic_config(sync_conn), BASELINE_REVISION
                    )
                )
                print(f"Stamped baseline {BASELINE_REVISION}.")

            await connection.run_sync(
                lambda sync_conn: command.upgrade(_alembic_config(sync_conn), "head")
            )
            await connection.commit()

            revision = (
                await connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                )
            ).scalar_one()
            tables = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema IN "
                        "('auth','cases','documents','intelligence','agents')"
                    )
                )
            ).scalar_one()
            print(f"SUCCESS: alembic revision = {revision}; application tables = {tables}")
            return 0
    finally:
        await manager.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
