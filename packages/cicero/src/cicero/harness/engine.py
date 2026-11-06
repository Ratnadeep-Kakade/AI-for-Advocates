"""Harness engine: executes a validated plan DAG through the agents.

Python owns ordering, parallelism, input wiring and failure isolation. Agents
receive structured inputs assembled from dependency AgentResults (references
and payloads, never conversation history). A failed task does not halt the
DAG: dependents run with the failure recorded so the Evaluator and
Orchestrator can report it honestly.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from cicero.agents.base import AgentContext, AgentResult, BaseAgent
from cicero.orchestrator.schemas import ExecutionPlan, PlanTask, TaskSpecification
from cicero.harness.registry_loader import RuntimeRegistry

logger = logging.getLogger(__name__)


class ExecutionRecorder(Protocol):
    async def task_started(self, execution_id: str, task: PlanTask) -> None: ...

    async def task_finished(
        self, execution_id: str, task: PlanTask, result: AgentResult
    ) -> None: ...


def build_task_inputs(
    task: PlanTask,
    results: dict[str, AgentResult],
    spec: TaskSpecification,
) -> dict[str, Any]:
    """Assemble an agent's inputs from its dependencies' AgentResults."""
    inputs: dict[str, Any] = {
        "objective": task.objective,
        "position": spec.position,
        "legal_questions": list(spec.objectives),
    }
    for dependency_id in task.depends_on:
        dependency = results.get(dependency_id)
        if dependency is None:
            continue
        data = dependency.output_data
        if dependency.agent_id == "document_intelligence":
            inputs["case_intelligence"] = data
            inputs.setdefault("evidence_items", data.get("evidence_items", []))
        elif dependency.agent_id == "legal_researcher":
            inputs["research_findings"] = data
            inputs.setdefault("sources", data.get("sources", []))
        elif dependency.agent_id == "argument":
            inputs["argument_output"] = data
        elif dependency.agent_id == "counterargument":
            inputs["counterargument_output"] = data
    return inputs


class HarnessEngine:
    def __init__(
        self,
        registry: RuntimeRegistry,
        agents: dict[str, BaseAgent],
        recorder: ExecutionRecorder | None = None,
        max_parallel: int = 4,
    ) -> None:
        self.registry = registry
        self.agents = agents
        self.recorder = recorder
        self.max_parallel = max(1, max_parallel)

    async def execute(
        self,
        *,
        organization_id: str,
        case_id: str,
        execution_id: str,
        spec: TaskSpecification,
        plan: ExecutionPlan,
    ) -> dict[str, AgentResult]:
        results: dict[str, AgentResult] = {}
        completed: set[str] = set()
        pending: dict[str, PlanTask] = {t.task_id: t for t in plan.tasks}
        while pending:
            ready = [
                task
                for task in pending.values()
                if set(task.depends_on) <= completed
            ]
            if not ready:
                raise RuntimeError(
                    "Execution plan has unsatisfiable dependencies "
                    f"(remaining: {sorted(pending)})."
                )
            batch = ready[: self.max_parallel]
            outcomes = await asyncio.gather(
                *(
                    self._run_task(
                        task,
                        organization_id=organization_id,
                        case_id=case_id,
                        execution_id=execution_id,
                        spec=spec,
                        results=results,
                    )
                    for task in batch
                ),
                return_exceptions=True,
            )
            for task, outcome in zip(batch, outcomes, strict=True):
                if isinstance(outcome, BaseException):
                    result = AgentResult(
                        execution_id=execution_id,
                        task_id=task.task_id,
                        case_id=case_id,
                        agent_id=task.agent_id,
                        status="failed",
                        output_data={},
                        validation_status="failed",
                        execution_metadata={"error": str(outcome)[:500]},
                    )
                else:
                    result = outcome
                results[task.task_id] = result
                completed.add(task.task_id)
                pending.pop(task.task_id, None)
        return results

    async def _run_task(
        self,
        task: PlanTask,
        *,
        organization_id: str,
        case_id: str,
        execution_id: str,
        spec: TaskSpecification,
        results: dict[str, AgentResult],
    ) -> AgentResult:
        agent = self.agents.get(task.agent_id)
        if agent is None:
            raise RuntimeError(f"No agent implementation for '{task.agent_id}'.")
        if self.recorder is not None:
            await self.recorder.task_started(execution_id, task)
        context = AgentContext(
            organization_id=organization_id,
            case_id=case_id,
            execution_id=execution_id,
            task_id=task.task_id,
            objective=task.objective,
        )
        inputs = build_task_inputs(task, results, spec)
        result = await agent.execute(context, inputs)
        if self.recorder is not None:
            await self.recorder.task_finished(execution_id, task, result)
        return result
