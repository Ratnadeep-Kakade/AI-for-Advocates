from __future__ import annotations

from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)
IdentifierT = TypeVar("IdentifierT", UUID, str, int)


class BaseRepository(Generic[ModelT, IdentifierT]):
    """Small SQLAlchemy repository foundation.

    Repositories execute queries and stage changes in the supplied session. They
    deliberately do not commit or roll back: transaction ownership belongs to the
    service/request boundary, not to an individual repository method.
    """

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        id_attribute: str,
    ) -> None:
        if not hasattr(model, id_attribute):
            raise ValueError(
                f"{model.__name__} has no mapped identifier attribute {id_attribute!r}."
            )
        self.session = session
        self.model = model
        self.id_attribute = id_attribute

    async def get_by_id(self, entity_id: IdentifierT) -> ModelT | None:
        """Fetch one entity by its primary identifier, or return ``None``."""
        identifier_column: Any = getattr(self.model, self.id_attribute)
        statement = select(self.model).where(identifier_column == entity_id)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def add(self, entity: ModelT) -> ModelT:
        """Stage an entity for insertion; the caller controls the transaction."""
        self.session.add(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        """Stage an entity for deletion; the caller controls the transaction."""
        await self.session.delete(entity)

    async def flush(self) -> None:
        """Flush pending changes without committing the transaction."""
        await self.session.flush()

    async def refresh(self, entity: ModelT) -> ModelT:
        """Refresh an entity from the database within the current transaction."""
        await self.session.refresh(entity)
        return entity
