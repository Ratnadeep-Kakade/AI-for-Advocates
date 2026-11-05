from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.db.models.cases import Case, CaseMember, CaseParty
from cicero.db.repositories.base import BaseRepository


class CaseRepository(BaseRepository[Case, UUID]):
    """Database operations for cases, members, and parties.

    Case reads are always scoped by organization_id. This repository enforces
    query scoping, but services remain responsible for deciding whether the
    authenticated user is allowed to perform the requested action.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Case, "case_id")

    async def get_by_id(
        self, case_id: UUID, *, organization_id: UUID
    ) -> Case | None:
        """Fetch a case only when both its ID and organization match."""
        statement = select(Case).where(
            Case.case_id == case_id,
            Case.organization_id == organization_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id_and_organization(
        self, case_id: UUID, organization_id: UUID
    ) -> Case | None:
        """Explicitly named equivalent of the organization-scoped get_by_id."""
        return await self.get_by_id(case_id, organization_id=organization_id)

    async def list_for_organization(
        self, organization_id: UUID, *, status: str | None = None
    ) -> list[Case]:
        statement = select(Case).where(Case.organization_id == organization_id)
        if status is not None:
            statement = statement.where(Case.status == status)
        statement = statement.order_by(Case.updated_at.desc(), Case.case_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_for_user_in_organization(
        self, organization_id: UUID, user_id: UUID, *, status: str | None = None
    ) -> list[Case]:
        """List only cases for which the user has an explicit case membership."""
        statement = (
            select(Case)
            .join(
                CaseMember,
                (CaseMember.case_id == Case.case_id)
                & (CaseMember.organization_id == Case.organization_id),
            )
            .where(
                Case.organization_id == organization_id,
                CaseMember.user_id == user_id,
            )
        )
        if status is not None:
            statement = statement.where(Case.status == status)
        statement = statement.order_by(Case.updated_at.desc(), Case.case_id)
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_members(
        self, case_id: UUID, organization_id: UUID
    ) -> list[CaseMember]:
        """List members only if the case belongs to the supplied organization."""
        statement = (
            select(CaseMember)
            .join(
                Case,
                (Case.case_id == CaseMember.case_id)
                & (Case.organization_id == CaseMember.organization_id),
            )
            .where(
                Case.case_id == case_id,
                Case.organization_id == organization_id,
            )
            .order_by(CaseMember.assigned_at, CaseMember.user_id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_member(
        self, case_id: UUID, organization_id: UUID, user_id: UUID
    ) -> CaseMember | None:
        statement = select(CaseMember).where(
            CaseMember.case_id == case_id,
            CaseMember.organization_id == organization_id,
            CaseMember.user_id == user_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def add_member(
        self,
        case_id: UUID,
        organization_id: UUID,
        user_id: UUID,
        *,
        role: str = "viewer",
    ) -> CaseMember:
        """Stage a case membership insert; DB constraints validate its references."""
        membership = CaseMember(
            case_id=case_id,
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        self.session.add(membership)
        return membership

    async def remove_member(
        self, case_id: UUID, organization_id: UUID, user_id: UUID
    ) -> bool:
        membership = await self.get_member(case_id, organization_id, user_id)
        if membership is None:
            return False
        await self.session.delete(membership)
        return True

    async def change_member_role(
        self, case_id: UUID, organization_id: UUID, user_id: UUID, role: str
    ) -> CaseMember | None:
        membership = await self.get_member(case_id, organization_id, user_id)
        if membership is None:
            return None
        membership.role = role
        return membership

    async def list_parties(
        self, case_id: UUID, organization_id: UUID
    ) -> list[CaseParty]:
        """List parties through an organization-scoped case join."""
        statement = (
            select(CaseParty)
            .join(Case, Case.case_id == CaseParty.case_id)
            .where(
                Case.case_id == case_id,
                Case.organization_id == organization_id,
            )
            .order_by(CaseParty.created_at, CaseParty.party_id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    def add_party(
        self,
        case_id: UUID,
        *,
        party_name: str,
        party_type: str,
        party_position: str,
    ) -> CaseParty:
        """Stage a party insert. The service must first validate case access."""
        party = CaseParty(
            case_id=case_id,
            party_name=party_name,
            party_type=party_type,
            party_position=party_position,
        )
        self.session.add(party)
        return party

    async def delete_party(
        self, party_id: UUID, case_id: UUID, organization_id: UUID
    ) -> bool:
        """Delete a party only when its parent case belongs to the organization."""
        statement = (
            select(CaseParty)
            .join(Case, Case.case_id == CaseParty.case_id)
            .where(
                CaseParty.party_id == party_id,
                CaseParty.case_id == case_id,
                Case.organization_id == organization_id,
            )
        )
        result = await self.session.execute(statement)
        party = result.scalar_one_or_none()
        if party is None:
            return False
        await self.session.delete(party)
        return True
