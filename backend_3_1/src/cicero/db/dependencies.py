from collections.abc import AsyncIterator

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cicero.db.connection import DatabaseManager


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
    """Provide a session without implicitly committing its work.

    Use this dependency when a service explicitly manages its transaction. Any
    uncommitted changes are rolled back when the session is closed.
    """
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        yield session


async def get_transactional_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one request-scoped transaction.

    Successful dependency completion commits; an exception rolls back. Do not
    combine this with a second ``session.begin()`` in the endpoint or service.
    """
    session_factory = _get_session_factory(request)
    async with session_factory() as session:
        async with session.begin():
            yield session
