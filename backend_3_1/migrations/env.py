from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from cicero.db.base import Base
# Importing the package registers all existing ORM tables on Base.metadata.
import cicero.db.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

TARGET_SCHEMAS = {
    "auth",
    "cases",
    "documents",
    "intelligence",
    "research",
    "agents",
    "evidence",
    "memory",
}
VERSION_TABLE = "alembic_version"
VERSION_SCHEMA = "public"


def include_name(
    name: str | None,
    type_: str,
    parent_names: dict[str, Any],
) -> bool:
    """Restrict autogeneration to Cicero schemas and its Alembic version table."""
    if type_ == "schema":
        # Include public only for Alembic's own version table.
        return name in TARGET_SCHEMAS or name == VERSION_SCHEMA

    if type_ == "table":
        schema_name = parent_names.get("schema_name")
        if schema_name in TARGET_SCHEMAS:
            return True
        return schema_name == VERSION_SCHEMA and name == VERSION_TABLE

    return True


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Never treat Alembic's bookkeeping table as application metadata."""
    if type_ == "table" and name == VERSION_TABLE:
        return False
    return True


def configure_context(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        # Server-default comparison is deliberately deferred until the first
        # live parity report. PostgreSQL normalizes equivalent expressions
        # differently, so enabling it prematurely creates noisy diffs.
        compare_server_default=False,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_SCHEMA,
        # Do not let autogenerate propose schema creation/drop operations.
        version_table_pk=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    url = os.environ.get("CICERO_ALEMBIC_DATABASE_URL") or config.get_main_option(
        "sqlalchemy.url"
    )
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
        compare_server_default=False,
        version_table=VERSION_TABLE,
        version_table_schema=VERSION_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = os.environ.get("CICERO_ALEMBIC_DATABASE_URL")
    if not url:
        url = config.get_main_option("sqlalchemy.url")

    section = config.get_section(config.config_ini_section, {}) or {}
    section["sqlalchemy.url"] = url
    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(configure_context)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    # Preferred production path: the caller supplies a synchronous SQLAlchemy
    # Connection obtained from DatabaseManager.engine.run_sync(). This keeps
    # Cloud SQL Connector + Modal WIF as the single credential/connection path.
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure_context(supplied_connection)
        return

    # Convenience path for local development with a direct asyncpg URL.
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
