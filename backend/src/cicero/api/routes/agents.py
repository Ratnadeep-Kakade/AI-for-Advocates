"""Agent execution endpoints.

POST /api/cases/{case_id}/analyze runs Document Intelligence directly.
POST /api/cases/{case_id}/executions starts a full multi-agent execution
(Interpreter -> Orchestrator plan -> harness -> synthesis) in the background;
GET the execution to poll progress and the final response.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.agents.base import AgentContext, AgentResult
from cicero.agents.document_intelligence.agent import DocumentIntelligenceAgent
from cicero.agents.factory import build_agents
from cicero.api.dependencies import DemoIdentity, get_demo_identity
from cicero.db.dependencies import get_transactional_db_session
from cicero.db.repositories.case import CaseRepository
from cicero.db.repositories.executions import ExecutionRepository
from cicero.harness.engine import HarnessEngine
from cicero.orchestrator.plan import Interpreter, OrchestratorPlanner, OrchestratorSynthesizer
from cicero.orchestrator.schemas import PlanTask
from cicero.rag.client import RagClient, RagServiceUnavailable
from cicero.registry.loader import RuntimeRegistry, load_registry

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
    """Map the AgentResult payload to the frontend CaseIntel contract."""
    data = result.output_data.get("case_intelligence", {})
    obligations: list[str] = []
    for o in data.get("obligations", []):
        text = f"{o.get('party', '')}: {o.get('obligation', '')}".strip(": ")
        if o.get("clause_reference"):
            text += f" [{o['clause_reference']}]"
        if o.get("status"):
            text += f" — {o['status']}"
        obligations.append(text)
    return {
        "case_id": case_id,
        "summary": data.get("summary", ""),
        "parties": [
            {"name": p.get("name", ""), "role": p.get("role") or None}
            for p in data.get("parties", [])
        ],
        "contractual_obligations": obligations,
        "material_facts": [f.get("fact", "") for f in data.get("facts", [])],
        "important_dates": [
            {"label": t.get("event", ""), "date": t.get("date", "")}
            for t in data.get("timeline", [])
        ],
        "legal_issues": [
            b.get("description", "") for b in data.get("potential_breaches", [])
        ]
        + [c.get("description", "") for c in data.get("contradictions", [])],
        "contradictions": [
            c.get("description", "") for c in data.get("contradictions", [])
        ],
        "missing_information": list(data.get("missing_information", [])),
        "evidence_references": list(result.evidence_references),
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
        result = await agent.execute(
            context,
            {
                "objective": objective,
                "document_ids": [str(d) for d in payload.document_ids]
                if payload.document_ids
                else None,
            },
        )
    except RagServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail="RAG retrieval is unavailable.") from exc
    if result.status == "failed":
        raise HTTPException(status_code=502, detail="Document analysis failed.")
    return to_case_intel(result, str(case_id))


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


async def _run_execution(
    app: Any, *, execution_id: UUID, organization_id: UUID, case_id: UUID
) -> None:
    """Background multi-agent execution (Interpreter -> plan -> harness -> synthesis)."""
    factory = app.state.database_manager.session_factory
    settings = app.state.settings
    gateway = app.state.model_gateway
    registry: RuntimeRegistry = app.state.capability_registry

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
    # Modal's ASGI runtime does not keep Starlette BackgroundTasks alive
    # after the response (executions stuck at "pending"), and running the
    # whole chain inline makes the POST last many minutes. Spawn the
    # dedicated Modal function instead; fall back to inline execution where
    # Modal is unavailable (local development).
    spawned = False
    try:
        import modal

        runner = modal.Function.from_name("cicero-backend", "run_execution")
        runner.spawn(
            str(record.execution_id),
            str(identity.organization_id),
            str(case_id),
        )
        spawned = True
    except Exception:
        logger.warning("Execution runner spawn unavailable; running inline", exc_info=True)
    if not spawned:
        await _run_execution(
            request.app,
            execution_id=record.execution_id,
            organization_id=identity.organization_id,
            case_id=case_id,
        )
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
