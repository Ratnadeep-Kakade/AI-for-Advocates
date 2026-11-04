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
async def cloudsql_smoke_test():

    from cicero.config import get_settings
    from cicero.db.connection import DatabaseManager

    manager = DatabaseManager(get_settings())

    try:
        await manager.start()
        result = await manager.diagnostics()
        print("CLOUD SQL DIAGNOSTICS:", result, flush=True)
        response = {
    	        "status": "SUCCESS",
    	        "database": result["database_name"],
    	        "user": result["database_user"],
   	        "server": result["server_version"],
        }
        print("CONNECTION TEST RESULT:", response, flush=True)
        return response

    finally:
        await manager.close()