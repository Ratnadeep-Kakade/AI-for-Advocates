from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.persistence.models.auth import User
from cicero.persistence.repositories.base import BaseRepository


class UserRepository(BaseRepository[User, UUID]):
    """Database operations for users.

    This repository does not authenticate users or decide whether a user may
    access an organization or case. Those decisions belong in the service layer.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User, "user_id")

    async def get_by_firebase_uid(self, firebase_uid: str) -> User | None:
        statement = select(User).where(User.firebase_uid == firebase_uid)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Find a user by email, case-insensitively, matching the DB unique index."""
        normalized_email = email.strip().lower()
        statement = select(User).where(func.lower(User.email) == normalized_email)
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

