from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.api.dependencies import DemoIdentity, get_demo_identity
from cicero.api.schemas import CaseCreate, CaseRead
from cicero.db.dependencies import get_transactional_db_session
from cicero.db.models.cases import Case
from cicero.db.repositories.case import CaseRepository
from cicero.db.repositories.organization import OrganizationRepository

router = APIRouter(prefix="/api/cases", tags=["cases"])


async def _require_organization_membership(
    session: AsyncSession, identity: DemoIdentity
):
    membership = await OrganizationRepository(session).get_membership(
        identity.organization_id, identity.user_id
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The configured demo user is not a member of the demo organization.",
        )
    return membership


@router.get("", response_model=list[CaseRead])
async def list_cases(
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> list[CaseRead]:
    """List only cases assigned to the configured demo user in their organization."""
    await _require_organization_membership(session, identity)
    cases = await CaseRepository(session).list_for_user_in_organization(
        identity.organization_id, identity.user_id
    )
    return [CaseRead.model_validate(case) for case in cases]


@router.get("/{case_id}", response_model=CaseRead)
async def get_case(
    case_id: UUID,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> list[CaseRead]:
    """Fetch a case only when the demo user is a member of that case."""
    await _require_organization_membership(session, identity)
    repository = CaseRepository(session)
    case = await repository.get_by_id(case_id, organization_id=identity.organization_id)
    if case is None or await repository.get_member(
        case_id, identity.organization_id, identity.user_id
    ) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")
    return CaseRead.model_validate(case)


@router.post("", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreate,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> list[CaseRead]:
    """Create a case for the demo tenant; only owner/admin/lawyer roles may create."""
    membership = await _require_organization_membership(session, identity)
    if membership.role not in {"owner", "admin", "lawyer"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your organization role cannot create cases.",
        )

    repository = CaseRepository(session)
    case = repository.add(
        Case(
            organization_id=identity.organization_id,
            case_name=payload.case_name.strip(),
            case_description=payload.case_description,
            jurisdiction=payload.jurisdiction,
            court=payload.court,
            case_type=payload.case_type,
            status="active",
            created_by=identity.user_id,
        )
    )
    await session.flush()
    repository.add_member(
        case.case_id,
        identity.organization_id,
        identity.user_id,
        role="owner",
    )
    await session.flush()
    await session.refresh(case)
    return CaseRead.model_validate(case)
