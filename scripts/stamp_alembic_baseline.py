"""Safely stamp the existing Cicero Cloud SQL database at its baseline.

Run from the backend root:

    uv run modal run scripts/stamp_alembic_baseline.py::stamp_alembic_baseline

This creates public.alembic_version and records the baseline revision. It does
not execute the baseline upgrade() function or modify application tables.
"""

from __future__ import annotations

import json

import modal

app = modal.App("cicero-backend")

database_secret = modal.Secret.from_name(
    "cicero-database",
    required_keys=[
        "CICERO_DATABASE_INSTANCE_CONNECTION_NAME",
        "CICERO_DATABASE_NAME",
        "CICERO_DATABASE_USER",
        "CICERO_DATABASE_PASSWORD",
        "CICERO_DATABASE_WIF_PROJECT_NUMBER",
        "CICERO_DATABASE_WIF_POOL_ID",
        "CICERO_DATABASE_WIF_PROVIDER_ID",
        "CICERO_DATABASE_WIF_SERVICE_ACCOUNT_EMAIL",
    ],
)

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "alembic>=1.14,<2.0",
        "asyncpg>=0.30,<1.0",
        "cloud-sql-python-connector[asyncpg]>=1.18,<2.0",
        "google-auth>=2.35,<3.0",
        "pgvector>=0.3,<1.0",
        "pydantic-settings>=2.6,<3.0",
        "sqlalchemy[asyncio]>=2.0.36,<3.0",
    )
    .add_local_python_source("cicero")
    .add_local_file("alembic.ini", remote_path="/root/alembic.ini")
    .add_local_dir("migrations", remote_path="/root/migrations")
)

BASELINE_REVISION = "20261104_0001"


@app.function(
    image=image,
    secrets=[database_secret],
    name="fastapi_app",
    timeout=180,
)
async def stamp_alembic_baseline() -> dict[str, str]:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from cicero.config import get_settings
    from cicero.db.connection import DatabaseManager

    settings = get_settings()
    manager = DatabaseManager(settings)

    try:
        await manager.start()
        if manager.engine is None:
            raise RuntimeError("Cloud SQL is not configured or the database manager did not start.")

        async with manager.engine.connect() as connection:
            # Refuse to overwrite or silently adopt an existing Alembic history.
            preflight = (
                await connection.execute(
                    text(
                        "SELECT current_database() AS database_name, "
                        "to_regclass('public.alembic_version') AS version_table"
                    )
                )
            ).mappings().one()

            actual_database = str(preflight["database_name"])
            expected_database = str(settings.database_name)
            if actual_database != expected_database:
                raise RuntimeError(
                    f"Connected to database {actual_database!r}, "
                    f"but configuration expects {expected_database!r}. Refusing to stamp."
                )

            if preflight["version_table"] is not None:
                raise RuntimeError(
                    "public.alembic_version already exists. Refusing to stamp over "
                    "an existing migration history; inspect it first."
                )

            def run_stamp(sync_connection):
                alembic_config = Config("/root/alembic.ini")
                alembic_config.set_main_option("script_location", "/root/migrations")
                alembic_config.attributes["connection"] = sync_connection
                command.stamp(alembic_config, BASELINE_REVISION)

            # env.py consumes the supplied synchronous connection, preserving
            # the existing Cloud SQL Connector + Modal WIF authentication path.
            await connection.run_sync(run_stamp)

            recorded = (
                await connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                )
            ).scalar_one()

            if recorded != BASELINE_REVISION:
                raise RuntimeError(
                    f"Baseline stamp verification failed: expected "
                    f"{BASELINE_REVISION!r}, got {recorded!r}."
                )

            result = {
                "status": "SUCCESS",
                "database": actual_database,
                "version_table": "public.alembic_version",
                "revision": str(recorded),
                "application_tables_modified": "false",
            }
            print("ALEMBIC BASELINE RESULT:", json.dumps(result, indent=2), flush=True)
            return result
    finally:
        await manager.close()
