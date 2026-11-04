"""Modal deployment entrypoint for Cicero's CPU API backend."""

import modal

app = modal.App("cicero-backend")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "asyncpg>=0.30,<1.0",
        "cloud-sql-python-connector[asyncpg]>=1.18,<2.0",
        "fastapi>=0.115,<1.0",
        "google-auth>=2.35,<3.0",
        "google-cloud-storage>=3.0,<4.0",
        "httpx>=0.27,<1.0",
        "pydantic-settings>=2.6,<3.0",
        "sqlalchemy[asyncio]>=2.0.36,<3.0",
    )
    .add_local_python_source("cicero")
)

# Keep model credentials and Google Cloud database credentials in separate
# Modal Secrets. Both secrets must exist before deploying this API.
model_gateway_secret = modal.Secret.from_name("cicero-model-gateway")
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


@app.function(image=image, secrets=[model_gateway_secret, database_secret])
@modal.asgi_app()
def fastapi_app():
    from cicero.api.app import create_app

    return create_app()
