from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.persistence.models.auth import Organization, OrganizationMember
from cicero.persistence.repositories.base import BaseRepository


class OrganizationRepository(BaseRepository[Organization, UUID]):
    """Database operations for organizations and their membership records.

    Membership lookup is not authorization by itself. Services must check the
    member's role and the action being requested before exposing protected data.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Organization, "organization_id")

    async def list_for_user(self, user_id: UUID) -> list[Organization]:
        statement = (
            select(Organization)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Organization.organization_id,
            )
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.organization_name, Organization.organization_id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_membership(
        self, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember | None:
        statement = select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_members(self, organization_id: UUID) -> list[OrganizationMember]:
        statement = (
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(OrganizationMember.joined_at, OrganizationMember.user_id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    def add_member(
        self,
        organization_id: UUID,
        user_id: UUID,
        *,
        role: str = "member",
    ) -> OrganizationMember:
        """Stage a membership insert; database constraints validate references/role."""
        membership = OrganizationMember(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        self.session.add(membership)
        return membership

    async def remove_member(self, organization_id: UUID, user_id: UUID) -> bool:
        """Stage removal of a membership. Returns False when no row exists."""
        membership = await self.get_membership(organization_id, user_id)
        if membership is None:
            return False
        await self.session.delete(membership)
        return True

    async def change_member_role(
        self, organization_id: UUID, user_id: UUID, role: str
    ) -> OrganizationMember | None:
        """Change a stored role; caller must authorize this operation."""
        membership = await self.get_membership(organization_id, user_id)
        if membership is None:
            return None
        membership.role = role
        return membership
