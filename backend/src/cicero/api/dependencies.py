from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request, status

from cicero.config import Settings
from cicero.models.gateway import ModelGateway


@dataclass(frozen=True, slots=True)
class DemoIdentity:
    """Configured single-tenant demo identity; not a substitute for authentication."""

    user_id: UUID
    organization_id: UUID


def get_model_gateway(request: Request) -> ModelGateway:
    """Retrieve the process-wide gateway from FastAPI application state."""
    return request.app.state.model_gateway


def get_demo_identity(request: Request) -> DemoIdentity:
    """Return the explicitly configured demo identity or fail closed."""
    settings: Settings = request.app.state.settings
    if not settings.demo_identity_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Demo API is disabled or its demo identity is not configured.",
        )
    assert settings.demo_user_id is not None
    assert settings.demo_organization_id is not None
    return DemoIdentity(
        user_id=settings.demo_user_id,
        organization_id=settings.demo_organization_id,
    )
