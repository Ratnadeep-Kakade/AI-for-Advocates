from fastapi import FastAPI

from cicero import __version__
from cicero.config import get_settings


def create_app() -> FastAPI:
    """Application factory used by local development, tests, and Modal."""
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Cicero backend API.",
    )

    @application.get("/", tags=["system"])
    async def root() -> dict[str, str]:
        return {
            "service": "cicero-api",
            "status": "ok",
            "version": __version__,
            "environment": settings.environment,
            "health": "/health",
        }

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        # Liveness only. Dependency readiness checks belong in a later milestone.
        return {
            "service": "cicero-api",
            "status": "ok",
            "version": __version__,
        }

    return application


app = create_app()
