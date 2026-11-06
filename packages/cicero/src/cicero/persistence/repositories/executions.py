"""Repository for harness execution persistence (agents schema)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.agents.base import AgentResult
from cicero.persistence.models.agents import (
    AgentResultRecord,
    ExecutionRecord,
    ExecutionTaskRecord,
)
from cicero.orchestrator.schemas import ExecutionPlan


class ExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_execution(
        self,
        *,
        organization_id: UUID,
        case_id: UUID,
        user_request: str,
        position: str | None,
    ) -> ExecutionRecord:
        record = ExecutionRecord(
            execution_id=uuid4(),
            organization_id=organization_id,
            case_id=case_id,
            status="pending",
            user_request=user_request,
            position=position,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_execution(
        self, execution_id: UUID, organization_id: UUID, case_id: UUID
    ) -> ExecutionRecord | None:
        result = await self.session.execute(
            select(ExecutionRecord).where(
                ExecutionRecord.execution_id == execution_id,
                ExecutionRecord.organization_id == organization_id,
                ExecutionRecord.case_id == case_id,
            )
        )
        return result.scalars().first()

    async def set_status(
        self,
        record: ExecutionRecord,
        status: str,
        *,
        error_message: str | None = None,
        final_response: str | None = None,
    ) -> None:
        record.status = status
        record.updated_at = datetime.now(UTC)
        if error_message is not None:
            record.error_message = error_message[:2000]
        if final_response is not None:
            record.final_response = final_response
        if status in {"completed", "failed", "cancelled"}:
            record.completed_at = datetime.now(UTC)
        await self.session.flush()

    async def save_plan(self, record: ExecutionRecord, plan: ExecutionPlan) -> None:
        record.plan = plan.model_dump()
        for task in plan.tasks:
            self.session.add(
                ExecutionTaskRecord(
                    execution_id=record.execution_id,
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    status="pending",
                    depends_on=list(task.depends_on),
                )
            )
        await self.session.flush()

    async def list_tasks(self, execution_id: UUID) -> list[ExecutionTaskRecord]:
        result = await self.session.execute(
            select(ExecutionTaskRecord)
            .where(ExecutionTaskRecord.execution_id == execution_id)
            .order_by(ExecutionTaskRecord.task_id)
        )
        return list(result.scalars().all())

    async def list_results(self, execution_id: UUID) -> list[AgentResultRecord]:
        result = await self.session.execute(
            select(AgentResultRecord)
            .where(AgentResultRecord.execution_id == execution_id)
            .order_by(AgentResultRecord.created_at)
        )
        return list(result.scalars().all())

    async def get_latest_result(
        self,
        *,
        case_id: UUID,
        organization_id: UUID,
        agent_id: str = "document_intelligence",
    ) -> AgentResultRecord | None:
        result = await self.session.execute(
            select(AgentResultRecord)
            .where(
                AgentResultRecord.case_id == case_id,
                AgentResultRecord.organization_id == organization_id,
                AgentResultRecord.agent_id == agent_id,
            )
            .order_by(AgentResultRecord.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def mark_task_started(self, execution_id: UUID, task_id: str) -> None:
        task = await self._get_task(execution_id, task_id)
        if task is not None:
            task.status = "running"
            task.started_at = datetime.now(UTC)
            await self.session.flush()

    async def save_result(
        self, result: AgentResult, *, execution_id: UUID, organization_id: UUID
    ) -> None:
        self.session.add(
            AgentResultRecord(
                result_id=uuid4(),
                execution_id=execution_id,
                task_id=result.task_id,
                agent_id=result.agent_id,
                case_id=UUID(result.case_id),
                organization_id=organization_id,
                status=result.status,
                output_data=result.output_data,
                evidence_references=list(result.evidence_references),
                validation_status=result.validation_status,
                execution_metadata=result.execution_metadata,
            )
        )
        task = await self._get_task(execution_id, result.task_id)
        if task is not None:
            if result.status in {"completed", "insufficient_evidence"}:
                task.status = "completed" if result.status == "completed" else "partial"
            else:
                task.status = result.status
            task.completed_at = datetime.now(UTC)
        await self.session.flush()

    async def _get_task(
        self, execution_id: UUID, task_id: str
    ) -> ExecutionTaskRecord | None:
        result = await self.session.execute(
            select(ExecutionTaskRecord).where(
                ExecutionTaskRecord.execution_id == execution_id,
                ExecutionTaskRecord.task_id == task_id,
            )
        )
        return result.scalars().first()
