from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cicero import __version__
from cicero_api.routes.agents import router as agents_router
from cicero_api.routes.cases import router as cases_router
from cicero_api.routes.chat import router as chat_router
from cicero_api.routes.documents import router as documents_router
from cicero_api.routes.evidence import router as evidence_router
from cicero.core.config import Settings, get_settings
from cicero.persistence.database import DatabaseManager
from cicero.llm.gateway import ModelGateway
from cicero.storage.manager import StorageManager


def create_app(
    *,
    settings: Settings | None = None,
    model_gateway: ModelGateway | None = None,
) -> FastAPI:
    """Application factory used by local development, tests, and Modal."""
    settings = settings or get_settings()
    database_manager = DatabaseManager(settings)
    storage_manager = StorageManager(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # Cloud SQL is optional during early local development. If its settings
        # are supplied, initialise the Connector and SQLAlchemy pool at startup.
        await database_manager.start()
        try:
            yield
        finally:
            await database_manager.close()
            storage_manager.close()

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Cicero backend API.",
        lifespan=lifespan,
    )
    allowed_origins = [
        origin.strip().rstrip("/")
        for origin in settings.cors_allowed_origins.split(",")
        if origin.strip()
    ]
    if allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Accept"],
        )

    application.state.settings = settings
    application.state.model_gateway = model_gateway or ModelGateway.from_settings(settings)
    application.state.database_manager = database_manager
    application.state.storage_manager = storage_manager
    application.include_router(cases_router)
    application.include_router(documents_router)
    application.include_router(evidence_router)
    application.include_router(agents_router)
    application.include_router(chat_router)

    @application.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "service": "cicero-api",
            "status": "ok",
            "version": __version__,
            "environment": settings.environment,
            "health": "/health",
            "database_health": "/health/database",
        }

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        # Liveness only. Database readiness is checked separately.
        return {
            "service": "cicero-api",
            "status": "ok",
            "version": __version__,
        }

    @application.get("/health/database", tags=["system"])
    async def database_health():
        manager: DatabaseManager = application.state.database_manager
        if not manager.is_configured:
            return JSONResponse(
                status_code=503,
                content={"service": "cicero-database", "status": "not_configured"},
            )
        if not manager.is_started:
            return JSONResponse(
                status_code=503,
                content={"service": "cicero-database", "status": "not_ready"},
            )
        try:
            await manager.ping()
        except Exception:
            return JSONResponse(
                status_code=503,
                content={"service": "cicero-database", "status": "unavailable"},
            )
        return {"service": "cicero-database", "status": "ok"}

    return application


app = create_app()
