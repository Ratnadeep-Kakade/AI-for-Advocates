"""Run Cicero migrations on Modal through the existing WIF credential path.

For organizations that disable service-account keys, this replaces both
gcloud/ADC and direct-URL migration runs: Modal's OIDC identity is exchanged
through the project's Workload Identity Federation pool, exactly as the
deployed backend connects.

Run from the backend root:

    uv run modal run scripts/run_migrations_modal.py
    uv run modal run scripts/run_migrations_modal.py --bootstrap-fresh-db

Default: stamp the 20261104_0001 baseline if the base schema exists without
Alembic history, then upgrade to head. --bootstrap-fresh-db (empty database
only) creates the ORM schemas/tables first.
"""

from __future__ import annotations

import json

import modal

app = modal.App("cicero-migrations")

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
        "fastapi>=0.115,<1.0",
        "google-auth>=2.35,<3.0",
        "google-cloud-pubsub>=2.25,<3.0",
        "google-cloud-storage>=3.0,<4.0",
        "httpx>=0.27,<1.0",
        "pgvector>=0.3,<1.0",
        "pydantic-settings>=2.6,<3.0",
        "pyyaml>=6.0,<7.0",
        "sqlalchemy[asyncio]>=2.0.36,<3.0",
    )
    .add_local_python_source("cicero")
    .add_local_dir("src/cicero/agents", remote_path="/root/cicero/agents")
    .add_local_file("alembic.ini", remote_path="/root/alembic.ini")
    .add_local_dir("migrations", remote_path="/root/migrations")
)

BASELINE_REVISION = "20261104_0001"
ORM_SCHEMAS = ("auth", "cases", "documents", "agents")


@app.function(
    image=image,
    secrets=[
        database_secret,
        modal.Secret.from_name("cicero-model-gateway"),
        modal.Secret.from_name("cicero-rag"),
    ],
    timeout=1500,
)
async def run_migrations(
    bootstrap_fresh_db: bool = False,
    redrive_processing_run_id: str | None = None,
    redrive_organization_id: str | None = None,
    redrive_case_id: str | None = None,
    redrive_document_id: str | None = None,
    redrive_version_id: str | None = None,
    execution_id: str | None = None,
    execution_organization_id: str | None = None,
    execution_case_id: str | None = None,
) -> dict[str, str]:
    if redrive_processing_run_id:
        # Operator re-drive for a stuck processing run. Spawning the worker
        # needs no Google credentials, so this runs before any WIF exchange;
        # force_reclaim lets the worker take over the lease of a container
        # that died (OOM/stop/timeout).
        payload = {
            "organization_id": redrive_organization_id,
            "case_id": redrive_case_id,
            "document_id": redrive_document_id,
            "version_id": redrive_version_id,
            "processing_run_id": redrive_processing_run_id,
            "force_reclaim": True,
        }
        process_document = modal.Function.from_name("cicero-rag-worker", "process_document")
        call = process_document.spawn(payload)
        return {"status": "redriven", "function_call_id": call.object_id}

    if execution_id:
        # Drive one persisted agent execution to a terminal state from this
        # WIF-authorised runner (the dedicated cicero-backend/run_execution
        # function needs the pool condition widened to its function name).
        from types import SimpleNamespace
        from uuid import UUID

        import cicero.db.models  # noqa: F401  (registers ORM tables)
        from cicero.api.routes.agents import _run_execution
        from cicero.config import get_settings
        from cicero.db.connection import DatabaseManager
        from cicero.db.repositories.executions import ExecutionRepository
        from cicero.models.gateway import ModelGateway
        from cicero.registry.loader import load_registry

        settings = get_settings()
        manager = DatabaseManager(settings)
        await manager.start()
        try:
            stub_app = SimpleNamespace(
                state=SimpleNamespace(
                    database_manager=manager,
                    settings=settings,
                    model_gateway=ModelGateway.from_settings(settings),
                    capability_registry=load_registry(),
                )
            )
            await _run_execution(
                stub_app,
                execution_id=UUID(execution_id),
                organization_id=UUID(execution_organization_id),
                case_id=UUID(execution_case_id),
            )
            factory = manager.session_factory
            assert factory is not None
            async with factory() as session:
                record = await ExecutionRepository(session).get_execution(
                    UUID(execution_id),
                    UUID(execution_organization_id),
                    UUID(execution_case_id),
                )
            return {
                "status": record.status if record is not None else "missing",
                "execution_id": execution_id,
            }
        finally:
            await manager.close()

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    import cicero.db.models  # noqa: F401  (registers ORM tables)
    from cicero.config import get_settings
    from cicero.db.base import Base
    from cicero.db.connection import DatabaseManager

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
                        " WHERE table_schema IN ('auth','cases','documents')) "
                        "AS base_tables"
                    )
                )
            ).mappings().one()
            base_tables = int(state["base_tables"])
            if base_tables == 0 and not bootstrap_fresh_db:
                raise RuntimeError(
                    "No base tables found (fresh database). Re-run with "
                    "--bootstrap-fresh-db."
                )

            if bootstrap_fresh_db and base_tables == 0:
                for schema in ORM_SCHEMAS:
                    await connection.execute(
                        text(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                    )
                await connection.run_sync(
                    lambda sync_conn: Base.metadata.create_all(
                        sync_conn, checkfirst=True
                    )
                )
                await connection.commit()

            def _config(sync_connection) -> Config:
                config = Config("/root/alembic.ini")
                config.set_main_option("script_location", "/root/migrations")
                config.attributes["connection"] = sync_connection
                return config

            if state["version_table"] is None:
                await connection.run_sync(
                    lambda sync_conn: command.stamp(
                        _config(sync_conn), BASELINE_REVISION
                    )
                )

            await connection.run_sync(
                lambda sync_conn: command.upgrade(_config(sync_conn), "head")
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
            result = {
                "status": "SUCCESS",
                "database": str(state["db"]),
                "revision": str(revision),
                "application_tables": str(tables),
            }
            print("MIGRATION RESULT:", json.dumps(result, indent=2), flush=True)
            return result
    finally:
        await manager.close()


@app.local_entrypoint()
def main(
    bootstrap_fresh_db: bool = False,
    redrive_processing_run_id: str = "",
    redrive_organization_id: str = "",
    redrive_case_id: str = "",
    redrive_document_id: str = "",
    redrive_version_id: str = "",
    execution_id: str = "",
    execution_organization_id: str = "",
    execution_case_id: str = "",
) -> None:
    result = run_migrations.remote(
        bootstrap_fresh_db=bootstrap_fresh_db,
        redrive_processing_run_id=redrive_processing_run_id or None,
        redrive_organization_id=redrive_organization_id or None,
        redrive_case_id=redrive_case_id or None,
        redrive_document_id=redrive_document_id or None,
        redrive_version_id=redrive_version_id or None,
        execution_id=execution_id or None,
        execution_organization_id=execution_organization_id or None,
        execution_case_id=execution_case_id or None,
    )
    print(json.dumps(result, indent=2))
