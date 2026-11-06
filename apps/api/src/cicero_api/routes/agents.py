"""Agent execution endpoints.

POST /api/cases/{case_id}/analyze runs Document Intelligence directly.
POST /api/cases/{case_id}/executions starts a full multi-agent execution
(Interpreter -> Orchestrator plan -> harness -> synthesis) in the background;
GET the execution to poll progress and the final response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.agents.base import AgentContext, AgentResult
from cicero.agents.document_intelligence.agent import DocumentIntelligenceAgent
from cicero.agents.factory import build_agents
from cicero_api.deps import DemoIdentity, get_demo_identity, get_transactional_db_session
from cicero.persistence.repositories.case import CaseRepository
from cicero.persistence.repositories.executions import ExecutionRepository
from cicero.harness.engine import HarnessEngine
from cicero.orchestrator.planner import Interpreter, OrchestratorPlanner, OrchestratorSynthesizer
from cicero.orchestrator.schemas import PlanTask
from cicero.rag.retrieval.client import RagClient, RagServiceUnavailable
from cicero.harness.registry_loader import RuntimeRegistry, load_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cases/{case_id}", tags=["agents"])


def _registry(request: Request) -> RuntimeRegistry:
    registry = getattr(request.app.state, "capability_registry", None)
    if registry is None:
        registry = load_registry()
        request.app.state.capability_registry = registry
    return registry


class AnalyzeRequest(BaseModel):
    objective: str | None = Field(default=None, max_length=2000)
    document_ids: list[UUID] | None = None


def to_case_intel(result: Any, case_id: str) -> dict[str, Any]:
    """Map the AgentResult or AgentResultRecord payload to the frontend CaseIntel contract."""
    output = getattr(result, "output_data", {}) or {}
    if not output and isinstance(result, dict):
        output = result.get("output_data", result)
    data = output.get("case_intelligence") or output

    obligations: list[str] = []
    for o in data.get("obligations", []):
        if isinstance(o, str):
            obligations.append(o)
            continue
        if isinstance(o, dict):
            text = f"{o.get('party', '')}: {o.get('obligation', '')}".strip(": ")
            if o.get("clause_reference"):
                text += f" [{o['clause_reference']}]"
            if o.get("status"):
                text += f" — {o['status']}"
            obligations.append(text)
    if not obligations and data.get("contractual_obligations"):
        obligations = list(data.get("contractual_obligations", []))

    material_facts: list[str] = []
    for f in data.get("facts", []):
        if isinstance(f, str):
            material_facts.append(f)
        elif isinstance(f, dict):
            material_facts.append(f.get("fact", ""))
    if not material_facts and data.get("material_facts"):
        material_facts = list(data.get("material_facts", []))

    important_dates: list[dict[str, str]] = []
    for t in data.get("timeline", []):
        if isinstance(t, dict):
            important_dates.append({
                "label": t.get("event") or t.get("label", ""),
                "date": t.get("date", ""),
            })
    if not important_dates and data.get("important_dates"):
        important_dates = list(data.get("important_dates", []))

    legal_issues: list[str] = []
    for b in data.get("potential_breaches", []):
        if isinstance(b, dict) and b.get("description"):
            legal_issues.append(b["description"])
        elif isinstance(b, str):
            legal_issues.append(b)
    for c in data.get("contradictions", []):
        if isinstance(c, dict) and c.get("description"):
            legal_issues.append(c["description"])
        elif isinstance(c, str):
            legal_issues.append(c)
    if not legal_issues and data.get("legal_issues"):
        legal_issues = list(data.get("legal_issues", []))

    contradictions: list[str] = []
    for c in data.get("contradictions", []):
        if isinstance(c, dict) and c.get("description"):
            contradictions.append(c["description"])
        elif isinstance(c, str):
            contradictions.append(c)

    evidence_refs = getattr(result, "evidence_references", None)
    if evidence_refs is None and isinstance(result, dict):
        evidence_refs = result.get("evidence_references", [])
    if not evidence_refs and data.get("evidence_references"):
        evidence_refs = data.get("evidence_references", [])

    return {
        "case_id": case_id,
        "summary": data.get("summary", ""),
        "parties": [
            {
                "name": p.get("name", "") if isinstance(p, dict) else str(p),
                "role": p.get("role") or None if isinstance(p, dict) else None,
            }
            for p in data.get("parties", [])
        ],
        "contractual_obligations": obligations,
        "material_facts": material_facts,
        "important_dates": important_dates,
        "legal_issues": legal_issues,
        "contradictions": contradictions,
        "missing_information": list(data.get("missing_information", [])),
        "evidence_references": list(evidence_refs or []),
    }


@router.post("/analyze")
async def analyze_case(
    case_id: UUID,
    request: Request,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
    payload: AnalyzeRequest | None = None,
) -> dict[str, Any]:
    repository = CaseRepository(session)
    membership = await repository.get_member(
        case_id, identity.organization_id, identity.user_id
    )
    case = await repository.get_by_id(case_id, organization_id=identity.organization_id)
    if case is None or membership is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    settings = request.app.state.settings
    try:
        rag = RagClient(settings)
    except RagServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="RAG retrieval is unavailable.") from exc
    payload = payload or AnalyzeRequest()
    agent = DocumentIntelligenceAgent(request.app.state.model_gateway, rag)
    objective = payload.objective or f"Analyse the documents in case '{case.case_name}'."
    context = AgentContext(
        organization_id=str(identity.organization_id),
        case_id=str(case_id),
        execution_id=f"EXEC_{uuid4().hex[:8]}",
        task_id="T_ANALYZE",
        objective=objective,
    )
    try:
        result = await asyncio.wait_for(
            agent.execute(
                context,
                {
                    "objective": objective,
                    "document_ids": [str(d) for d in payload.document_ids]
                    if payload.document_ids
                    else None,
                },
            ),
            timeout=240.0,
        )
    except asyncio.TimeoutError:
        logger.warning("Document intelligence analysis timed out for case %s", case_id)
        raise HTTPException(status_code=504, detail="Document analysis timed out.")
    except RagServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="RAG retrieval is unavailable.") from exc
    except Exception as exc:
        logger.exception("Document intelligence agent failed for case %s: %s", case_id, exc)
        raise HTTPException(status_code=500, detail=f"Document analysis error: {exc}")
    if result.status == "failed":
        raise HTTPException(status_code=502, detail="Document analysis failed.")

    # Persist the execution and agent result to Postgres so analysis is permanently saved
    try:
        exec_repo = ExecutionRepository(session)
        exec_record = await exec_repo.create_execution(
            organization_id=identity.organization_id,
            case_id=case_id,
            user_request=objective,
            position=None,
        )
        await exec_repo.save_result(
            result,
            execution_id=exec_record.execution_id,
            organization_id=identity.organization_id,
        )
        summary = (
            result.output_data.get("case_intelligence", {}).get("summary", "")
            if isinstance(result.output_data, dict)
            else ""
        )
        await exec_repo.set_status(
            exec_record,
            status="completed",
            final_response=summary,
        )
        await session.commit()
    except Exception as exc:
        logger.warning("Failed to persist document intelligence result to DB: %s", exc)

    return to_case_intel(result, str(case_id))


@router.get("/intel")
@router.get("/analyze")
async def get_case_intel(
    case_id: UUID,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> dict[str, Any] | None:
    repository = CaseRepository(session)
    membership = await repository.get_member(
        case_id, identity.organization_id, identity.user_id
    )
    case = await repository.get_by_id(case_id, organization_id=identity.organization_id)
    if case is None or membership is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    exec_repo = ExecutionRepository(session)
    latest_result = await exec_repo.get_latest_result(
        case_id=case_id,
        organization_id=identity.organization_id,
        agent_id="document_intelligence",
    )
    if latest_result is None or not latest_result.output_data:
        return None
    return to_case_intel(latest_result, str(case_id))


class CreateExecutionRequest(BaseModel):
    user_request: str | None = Field(default=None, max_length=8000)
    message: str | None = Field(default=None, max_length=8000)
    position: str | None = Field(default=None, max_length=2000)


class _DbRecorder:
    """Harness recorder persisting task state and AgentResults."""

    def __init__(self, factory: Any, organization_id: UUID) -> None:
        self.factory = factory
        self.organization_id = organization_id

    async def task_started(self, execution_id: str, task: PlanTask) -> None:
        async with self.factory() as session:
            async with session.begin():
                await ExecutionRepository(session).mark_task_started(
                    UUID(execution_id), task.task_id
                )

    async def task_finished(
        self, execution_id: str, task: PlanTask, result: AgentResult
    ) -> None:
        async with self.factory() as session:
            async with session.begin():
                await ExecutionRepository(session).save_result(
                    result,
                    execution_id=UUID(execution_id),
                    organization_id=self.organization_id,
                )


_active_tasks: set[asyncio.Task[Any]] = set()


async def _run_execution(
    app: Any, *, execution_id: UUID, organization_id: UUID, case_id: UUID
) -> None:
    """Background multi-agent execution (Interpreter -> plan -> harness -> synthesis)."""
    factory = app.state.database_manager.session_factory
    settings = app.state.settings
    gateway = app.state.model_gateway
    registry: RuntimeRegistry = getattr(app.state, "capability_registry", None) or load_registry()

    async def _update(status: str, **kwargs: Any) -> Any:
        async with factory() as session:
            async with session.begin():
                repo = ExecutionRepository(session)
                record = await repo.get_execution(execution_id, organization_id, case_id)
                if record is None:
                    return None
                await repo.set_status(record, status, **kwargs)
                return record

    try:
        record = await _update("interpreting")
        if record is None:
            return
        user_request, position = record.user_request, record.position
        interpreter = Interpreter(gateway, registry)
        spec = await interpreter.interpret(
            user_request=user_request, case_id=str(case_id)
        )
        async with factory() as session:
            async with session.begin():
                repo = ExecutionRepository(session)
                stored = await repo.get_execution(execution_id, organization_id, case_id)
                if stored is not None:
                    stored.task_spec = spec.model_dump()
        if spec.needs_clarification:
            await _update("waiting_for_input")
            return
        if position and not spec.position:
            spec.position = position

        await _update("planning")
        plan = await OrchestratorPlanner(gateway, registry).plan(spec)
        async with factory() as session:
            async with session.begin():
                repo = ExecutionRepository(session)
                stored = await repo.get_execution(execution_id, organization_id, case_id)
                if stored is not None:
                    await repo.save_plan(stored, plan)
        await _update("running")

        try:
            rag = RagClient(settings)
        except RagServiceUnavailable:
            rag = None  # type: ignore[assignment]
        agents = build_agents(gateway, settings=settings, rag=rag)
        engine = HarnessEngine(
            registry, agents, recorder=_DbRecorder(factory, organization_id)
        )
        results = await engine.execute(
            organization_id=str(organization_id),
            case_id=str(case_id),
            execution_id=str(execution_id),
            spec=spec,
            plan=plan,
        )
        await _update("validating")
        final = await OrchestratorSynthesizer(gateway).synthesize(
            user_request=user_request,
            spec=spec,
            results={k: v.model_dump() for k, v in results.items()},
            case_id=str(case_id),
        )
        await _update("completed", final_response=final)
    except Exception as exc:  # noqa: BLE001 - persisted for the polling client
        logger.exception("Execution %s failed", execution_id)
        await _update("failed", error_message=f"{type(exc).__name__}: {exc}")


@router.post("/executions", status_code=202)
async def create_execution(
    case_id: UUID,
    payload: CreateExecutionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> dict[str, Any]:
    repository = CaseRepository(session)
    membership = await repository.get_member(
        case_id, identity.organization_id, identity.user_id
    )
    case = await repository.get_by_id(case_id, organization_id=identity.organization_id)
    if case is None or membership is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    user_request = (payload.user_request or payload.message or "").strip()
    if not user_request:
        raise HTTPException(status_code=422, detail="A user request is required.")
    _registry(request)
    record = await ExecutionRepository(session).create_execution(
        organization_id=identity.organization_id,
        case_id=case_id,
        user_request=user_request,
        position=payload.position,
    )
    status = record.status
    await session.commit()

    # Run the execution as an active background task within this ASGI process.
    # The client polls every 3s, keeping the Modal ASGI container alive.
    # Spawning a separate Modal function fails WIF authorization because Google STS
    # restricts tokens to function_name='fastapi_app'.
    task = asyncio.create_task(
        _run_execution(
            request.app,
            execution_id=record.execution_id,
            organization_id=identity.organization_id,
            case_id=case_id,
        )
    )
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)

    return {"execution_id": str(record.execution_id), "status": status}


@router.get("/executions/{execution_id}")
async def get_execution(
    case_id: UUID,
    execution_id: UUID,
    identity: Annotated[DemoIdentity, Depends(get_demo_identity)],
    session: Annotated[AsyncSession, Depends(get_transactional_db_session)],
) -> dict[str, Any]:
    repo = ExecutionRepository(session)
    record = await repo.get_execution(execution_id, identity.organization_id, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Execution not found.")
    tasks = await repo.list_tasks(execution_id)
    results = await repo.list_results(execution_id)
    spec = record.task_spec or {}
    return {
        "execution_id": str(record.execution_id),
        "case_id": str(record.case_id),
        "status": record.status,
        "user_request": record.user_request,
        "final_response": record.final_response,
        "error": record.error_message,
        "clarification_questions": spec.get("clarification_questions", []),
        "tasks": [
            {
                "task_id": task.task_id,
                "agent_id": task.agent_id,
                "status": task.status,
                "depends_on": task.depends_on,
            }
            for task in tasks
        ],
        "results": {
            result.task_id: {
                "agent_id": result.agent_id,
                "status": result.status,
                "validation_status": result.validation_status,
                "output_data": result.output_data,
                "evidence_references": result.evidence_references,
            }
            for result in results
        },
    }
