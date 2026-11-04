"""Run a read-only ORM-versus-PostgreSQL schema parity check on Modal.

Run from the backend root:
    uv run modal run scripts/check_schema_parity.py::check_schema_parity

The Modal function is deliberately named ``fastapi_app`` to satisfy the
existing Google Workload Identity Federation attribute condition.
"""

from __future__ import annotations

import json

import modal

app = modal.App("cicero-backend")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "asyncpg>=0.30,<1.0",
        "cloud-sql-python-connector[asyncpg]>=1.18,<2.0",
        "google-auth>=2.35,<3.0",
        "pydantic-settings>=2.6,<3.0",
        "sqlalchemy[asyncio]>=2.0.36,<3.0",
    )
    .add_local_python_source("cicero")
)

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


@app.function(name="fastapi_app", image=image, secrets=[database_secret], timeout=300)
async def check_schema_parity() -> dict:
    from sqlalchemy import text

    from cicero.config import get_settings
    from cicero.db.connection import DatabaseManager
    from cicero.db.schema_parity import build_schema_parity_report

    manager = DatabaseManager(get_settings())
    await manager.start()
    if manager.engine is None:
        raise RuntimeError("Cloud SQL is not configured or the database manager did not start.")

    try:
        async with manager.engine.connect() as connection:
            async with connection.begin():
                # PostgreSQL enforces read-only mode for every statement in this
                # transaction. The checker performs catalog inspection only.
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                report = await connection.run_sync(build_schema_parity_report)
                print(json.dumps(report, indent=2, default=str), flush=True)
                return report
    finally:
        await manager.close()
