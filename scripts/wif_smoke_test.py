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


@app.function(
    image=image,
    name="fastapi_app",
    timeout=120,
)
def wif_smoke_test():
    from google.auth.transport.requests import Request

    from cicero.config import Settings
    from cicero.db.connection import DatabaseManager

    settings = Settings(
        _env_file=None,
        database_wif_project_number="116460390489",
        database_wif_pool_id="cicero-modal-pool",
        database_wif_provider_id="modal-oidc",
        database_wif_service_account_email=(
            "cicero-backend@project-d05a24bb-cf47-4351-b6e.iam.gserviceaccount.com"
        ),
    )

    manager = DatabaseManager(settings)

    credentials = manager._load_google_credentials()

    # Forces the actual Google STS exchange and service-account impersonation.
    credentials.refresh(Request())

    return {
        "status": "SUCCESS",
        "authenticated": credentials.valid,
        "credential_type": type(credentials).__name__,
        "expiry": (
            credentials.expiry.isoformat()
            if credentials.expiry
            else None
        ),
    }