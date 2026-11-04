import json

import modal

app = modal.App("cicero-backend")

database_secret = modal.Secret.from_name(
    "cicero-database",
)

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


@app.function(
    image=image,
    secrets=[database_secret],
    name="fastapi_app",
    timeout=120,
)
async def inspect_database_schema():

    from sqlalchemy import inspect, text

    from cicero.config import get_settings
    from cicero.db.connection import DatabaseManager

    manager = DatabaseManager(get_settings())

    try:
        await manager.start()

        async with manager.engine.connect() as connection:

            def inspect_schema(sync_connection):

                inspector = inspect(sync_connection)

                target_schemas = [
                    "auth",
                    "cases",
                    "documents",
                    "intelligence",
                    "research",
                    "agents",
                    "evidence",
                    "memory",
                ]

                result = {}

                for schema in target_schemas:

                    if schema not in inspector.get_schema_names():
                        result[schema] = {"exists": False}
                        continue

                    tables = {}

                    for table_name in inspector.get_table_names(
                        schema=schema
                    ):

                        tables[table_name] = {
                            "columns": inspector.get_columns(
                                table_name,
                                schema=schema,
                            ),
                            "primary_key": inspector.get_pk_constraint(
                                table_name,
                                schema=schema,
                            ),
                            "foreign_keys": inspector.get_foreign_keys(
                                table_name,
                                schema=schema,
                            ),
                            "unique_constraints": inspector.get_unique_constraints(
                                table_name,
                                schema=schema,
                            ),
                            "check_constraints": inspector.get_check_constraints(
                                table_name,
                                schema=schema,
                            ),
                            "indexes": inspector.get_indexes(
                                table_name,
                                schema=schema,
                            ),
                        }

                    result[schema] = {
                        "exists": True,
                        "tables": tables,
                    }

                return result

            schema_data = await connection.run_sync(inspect_schema)

            extensions = (
                await connection.execute(
                    text(
                        """
                        SELECT extname, extversion
                        FROM pg_extension
                        ORDER BY extname
                        """
                    )
                )
            ).mappings().all()

            database_info = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            current_database() AS database_name,
                            current_user AS database_user,
                            version() AS server_version
                        """
                    )
                )
            ).mappings().one()

            output = {
                "database": dict(database_info),
                "extensions": [dict(row) for row in extensions],
                "schemas": schema_data,
            }

            print(
                json.dumps(
                    output,
                    indent=2,
                    default=str,
                ),
                flush=True,
            )

            return {
                "status": "SUCCESS",
                "schema_count": len(schema_data),
                "table_count": sum(
                    len(value.get("tables", {}))
                    for value in schema_data.values()
                ),
            }

    finally:
        await manager.close()