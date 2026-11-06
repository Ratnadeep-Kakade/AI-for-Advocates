from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero_api.deps import DemoIdentity, get_demo_identity, get_transactional_db_session
from cicero_api.schemas import CaseCreate, CaseRead, CaseUpdate

try:
    from cicero.persistence.models.cases import Case, CaseMember, CaseParty
    from cicero.persistence.models.documents import (
        Document,
        DocumentChunk,
        DocumentExtraction,
        DocumentProcessingRun,
        DocumentVersion,
    )
    from cicero.persistence.models.agents import AgentResultRecord, ExecutionRecord, ExecutionTaskRecord
    from cicero.persistence.repositories.case import CaseRepository
    from cicero.persistence.repositories.organization import OrganizationRepository
except ImportError:
    from cicero.db.models.cases import Case, CaseMember, CaseParty
    from cicero.db.models.documents import (
        Document,
        DocumentChunk,
        DocumentExtraction,
        DocumentProcessingRun,
        DocumentVersion,
    )
    from cicero.db.models.agents import AgentResultRecord, ExecutionRecord, ExecutionTaskRecord
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


@router.patch("/{case_id}", response_model=CaseRead)
async def update_case(
    case_id: UUID,
    payload: CaseUpdate,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> CaseRead:
    """Update or rename a case."""
    await _require_organization_membership(session, identity)
    repository = CaseRepository(session)
    case = await repository.get_by_id(case_id, organization_id=identity.organization_id)
    if case is None or await repository.get_member(case_id, identity.organization_id, identity.user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

    if payload.case_name is not None:
        case.case_name = payload.case_name
    if payload.case_description is not None:
        case.case_description = payload.case_description
    if payload.jurisdiction is not None:
        case.jurisdiction = payload.jurisdiction
    if payload.court is not None:
        case.court = payload.court
    if payload.case_type is not None:
        case.case_type = payload.case_type
    if payload.status is not None:
        case.status = payload.status

    case.updated_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    await session.refresh(case)
    return CaseRead.model_validate(case)


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_case(
    case_id: UUID,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> None:
    """Permanently delete a case and all associated Postgres rows and pgvector data."""
    await _require_organization_membership(session, identity)
    repository = CaseRepository(session)
    case = await repository.get_by_id(case_id, organization_id=identity.organization_id)
    if case is None or await repository.get_member(case_id, identity.organization_id, identity.user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found.")

    # 1. Subquery for all document_ids in this case
    doc_ids_subquery = select(Document.document_id).where(
        Document.case_id == case_id,
        Document.organization_id == identity.organization_id,
    )

    # Delete all chunks and embeddings (pgvector data)
    await session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.document_id.in_(doc_ids_subquery),
            DocumentChunk.organization_id == identity.organization_id,
        )
    )

    # Delete all extractions
    await session.execute(
        delete(DocumentExtraction).where(
            DocumentExtraction.document_id.in_(doc_ids_subquery),
            DocumentExtraction.organization_id == identity.organization_id,
        )
    )

    # Delete all processing runs
    await session.execute(
        delete(DocumentProcessingRun).where(
            DocumentProcessingRun.document_id.in_(doc_ids_subquery),
            DocumentProcessingRun.organization_id == identity.organization_id,
        )
    )

    # Delete all document versions
    await session.execute(
        delete(DocumentVersion).where(
            DocumentVersion.document_id.in_(doc_ids_subquery),
            DocumentVersion.organization_id == identity.organization_id,
        )
    )

    # Delete documents
    await session.execute(
        delete(Document).where(
            Document.case_id == case_id,
            Document.organization_id == identity.organization_id,
        )
    )

    # 2. Subquery for all executions in this case
    exec_ids_subquery = select(ExecutionRecord.execution_id).where(
        ExecutionRecord.case_id == case_id,
        ExecutionRecord.organization_id == identity.organization_id,
    )

    # Delete agent results
    await session.execute(
        delete(AgentResultRecord).where(
            AgentResultRecord.execution_id.in_(exec_ids_subquery)
        )
    )

    # Delete execution tasks
    await session.execute(
        delete(ExecutionTaskRecord).where(
            ExecutionTaskRecord.execution_id.in_(exec_ids_subquery)
        )
    )

    # Delete executions
    await session.execute(
        delete(ExecutionRecord).where(
            ExecutionRecord.case_id == case_id,
            ExecutionRecord.organization_id == identity.organization_id,
        )
    )

    # 3. Delete case parties and members
    await session.execute(
        delete(CaseParty).where(CaseParty.case_id == case_id)
    )
    await session.execute(
        delete(CaseMember).where(
            CaseMember.case_id == case_id,
            CaseMember.organization_id == identity.organization_id,
        )
    )

    # 4. Delete the case itself
    await session.execute(
        delete(Case).where(
            Case.case_id == case_id,
            Case.organization_id == identity.organization_id,
        )
    )
    await session.flush()
