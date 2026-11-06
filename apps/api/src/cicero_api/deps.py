from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cicero.core.config import Settings
from cicero.llm.gateway import ModelGateway
from cicero.persistence.database import DatabaseManager


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


def get_database_manager(request: Request) -> DatabaseManager:
    return request.app.state.database_manager


def _get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    manager: DatabaseManager = request.app.state.database_manager
    if manager.session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not configured.",
        )
    return manager.session_factory


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide a session without implicitly committing its work."""
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        yield session


async def get_transactional_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one request-scoped transaction."""
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        async with session.begin():
            yield session
