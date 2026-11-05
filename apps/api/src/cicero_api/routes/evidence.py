"""Case-scoped evidence retrieval: the RAG tool boundary for the orchestrator.

The Modal API never exposes the Cloud Run RAG service token to the browser.
Agents (via the orchestrator) call this endpoint server-side; it authorizes
case access, then proxies to the Cloud Run worker through ``RagClient`` and
returns the verified EvidencePack produced by the retrieval pipeline.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.api.dependencies import DemoIdentity, get_demo_identity
from cicero.db.dependencies import get_transactional_db_session
from cicero.db.repositories.case import CaseRepository
from cicero.rag.client import RagClient, RagServiceUnavailable

router = APIRouter(prefix="/api/cases/{case_id}/evidence", tags=["evidence"])


class EvidenceRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=8, ge=1, le=20)
    token_budget: int | None = Field(default=None, ge=500, le=12000)
    document_ids: list[UUID] | None = None


@router.post("")
async def retrieve_evidence(
    case_id: UUID,
    payload: EvidenceRequest,
    request: Request,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> dict[str, Any]:
    membership = await CaseRepository(session).get_member(
        case_id, identity.organization_id, identity.user_id
    )
    case = await CaseRepository(session).get_by_id(
        case_id, organization_id=identity.organization_id
    )
    if case is None or membership is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    client = RagClient(request.app.state.settings)
    try:
        return await client.retrieve(
            organization_id=str(identity.organization_id),
            case_id=str(case_id),
            query=payload.query,
            top_k=payload.top_k,
            token_budget=payload.token_budget,
            document_ids=[str(d) for d in payload.document_ids]
            if payload.document_ids
            else None,
        )
    except RagServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="RAG retrieval is unavailable.") from exc
