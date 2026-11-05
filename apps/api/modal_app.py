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
        "google-cloud-pubsub>=2.25,<3.0",
        "httpx>=0.27,<1.0",
        "pgvector>=0.3,<1.0",
        "pydantic-settings>=2.6,<3.0",
        "pyyaml>=6.0,<7.0",
        "sqlalchemy[asyncio]>=2.0.36,<3.0",
    )
    .add_local_python_source("cicero")
    # Agent capability manifests (agent.yaml) are not Python source, so the
    # package upload above omits them; ship them explicitly or the registry
    # loads empty and executions fail.
    .add_local_dir("src/cicero/agents", remote_path="/root/cicero/agents")
)

# Keep model credentials and Google Cloud database credentials in separate
# Modal Secrets. Both secrets must exist before deploying this API.
model_gateway_secret = modal.Secret.from_name("cicero-model-gateway")
# Attached last so its CICERO_RAG_SERVICE_TOKEN (the worker's own copy) wins
# over any stale copy in the database secret: the backend must present the
# exact token the RAG worker verifies.
rag_secret = modal.Secret.from_name("cicero-rag")
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


@app.function(
    image=image,
    secrets=[model_gateway_secret, database_secret, rag_secret],
    timeout=900,
    scaledown_window=300,
)
@modal.asgi_app()
def fastapi_app():
    from cicero.api.app import create_app

    return create_app()


@app.function(
    image=image,
    secrets=[model_gateway_secret, database_secret, rag_secret],
    timeout=1500,
)
async def run_execution(execution_id: str, organization_id: str, case_id: str) -> None:
    """Run one persisted multi-agent execution to a terminal state.

    Spawned by POST /executions: Starlette BackgroundTasks do not survive
    Modal's ASGI request lifecycle, and the full agent chain takes minutes,
    so it gets a dedicated function with its own timeout.
    """
    from uuid import UUID

    from cicero.api.app import create_app
    from cicero.api.routes.agents import _run_execution
    from cicero.registry.loader import load_registry

    application = create_app()
    application.state.capability_registry = load_registry()
    manager = application.state.database_manager
    await manager.start()
    try:
        await _run_execution(
            application,
            execution_id=UUID(execution_id),
            organization_id=UUID(organization_id),
            case_id=UUID(case_id),
        )
    finally:
        await manager.close()
