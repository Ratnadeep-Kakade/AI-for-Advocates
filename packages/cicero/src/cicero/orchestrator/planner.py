"""Execution-plan validation and the Orchestrator's LLM components.

``validate_plan`` is pure and deterministic: unknown agents, dangling or cyclic
dependencies, duplicate task ids and non-specialist task agents are rejected
before the harness runs anything.
"""

from __future__ import annotations

import json
from typing import Any

from cicero.agents.common import Gateway, StructuredOutputError, generate_structured
from cicero.llm.contracts import ChatMessage, GenerationRequest, ModelRole
from cicero.orchestrator.schemas import ExecutionPlan, TaskSpecification, default_plan
from cicero.harness.registry_loader import RuntimeRegistry

NON_TASK_AGENTS = frozenset({"interpreter", "orchestrator"})


def validate_plan(plan: ExecutionPlan, registry: RuntimeRegistry) -> list[str]:
    """Return plan issues; an empty list means the plan is executable."""
    issues: list[str] = []
    known_agents = set(registry.agent_ids())
    task_ids = [task.task_id for task in plan.tasks]
    if len(task_ids) != len(set(task_ids)):
        issues.append("Duplicate task_id values in plan.")
    task_id_set = set(task_ids)
    for task in plan.tasks:
        if task.agent_id not in known_agents:
            issues.append(f"Task {task.task_id} uses unknown agent '{task.agent_id}'.")
        elif task.agent_id in NON_TASK_AGENTS:
            issues.append(
                f"Task {task.task_id} targets '{task.agent_id}', which is not a "
                "specialist task agent."
            )
        for dependency in task.depends_on:
            if dependency not in task_id_set:
                issues.append(
                    f"Task {task.task_id} depends on unknown task '{dependency}'."
                )
            if dependency == task.task_id:
                issues.append(f"Task {task.task_id} depends on itself.")
    # Cycle detection (iterative DFS over the dependency graph).
    graph = {task.task_id: list(task.depends_on) for task in plan.tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            issues.append(f"Dependency cycle detected at task '{node}'.")
            return
        visiting.add(node)
        for nxt in graph.get(node, []):
            if nxt in graph:
                visit(nxt, stack + [node])
        visiting.discard(node)
        visited.add(node)

    for task_id in task_ids:
        visit(task_id, [])
    return issues


class Interpreter:
    """Muse Spark component: raw request -> validated Task Specification."""

    def __init__(self, gateway: Gateway, registry: RuntimeRegistry) -> None:
        self.gateway = gateway
        self.registry = registry

    async def interpret(
        self, *, user_request: str, case_id: str
    ) -> TaskSpecification:
        summary = json.dumps(self.registry.summary(), indent=1)
        spec, _meta = await generate_structured(
            self.gateway,
            role=ModelRole.INTERPRETER,
            system_prompt=(
                "You are Cicero's Request Interpreter. Convert the user's legal "
                "request into a Task Specification using only the platform "
                "capabilities listed below. Do not invent agents, tools or "
                "capabilities. If the request is ambiguous, set "
                "needs_clarification and ask precise questions. Respond with a "
                "single JSON object matching the schema. No prose outside JSON.\n\n"
                f"Platform Capability Registry summary:\n{summary}"
            ),
            user_prompt=f"Case: {case_id}\nUser request: {user_request}",
            schema=TaskSpecification,
            max_output_tokens=8192,
            affinity_key=case_id,
        )
        return spec


class OrchestratorPlanner:
    """Muse Spark component: Task Specification -> proposed Execution Plan."""

    def __init__(self, gateway: Gateway, registry: RuntimeRegistry) -> None:
        self.gateway = gateway
        self.registry = registry

    async def plan(
        self, spec: TaskSpecification, *, execution_fallback: bool = True
    ) -> ExecutionPlan:
        try:
            plan, _meta = await generate_structured(
                self.gateway,
                role=ModelRole.ORCHESTRATOR,
                system_prompt=(
                    "You are Cicero's Central Orchestrator. Build an execution "
                    "plan (DAG of specialist tasks) from the Task Specification. "
                    "Rules: use only document_intelligence, legal_researcher, "
                    "argument, counterargument, evaluator as task agents. "
                    "Document Intelligence and Legal Researcher have no "
                    "dependencies and may run in parallel. Argument and "
                    "Counterargument depend on both; Counterargument also "
                    "depends on Argument (challenge pass). Evaluator depends on "
                    "all prior tasks. Respond with a single JSON object "
                    "matching the schema. No prose outside JSON."
                ),
                user_prompt=(
                    "Task Specification:\n"
                    + json.dumps(spec.model_dump(), indent=1)
                ),
                schema=ExecutionPlan,
                max_output_tokens=8192,
            )
        except StructuredOutputError:
            if not execution_fallback:
                raise
            return default_plan(spec)
        issues = validate_plan(plan, self.registry)
        if issues:
            # Never execute an invalid LLM plan; fall back deterministically.
            return default_plan(spec)
        return plan


class OrchestratorSynthesizer:
    """Muse Spark component: agent results -> final user response."""

    def __init__(self, gateway: Gateway) -> None:
        self.gateway = gateway

    async def synthesize(
        self,
        *,
        user_request: str,
        spec: TaskSpecification,
        results: dict[str, dict[str, Any]],
        case_id: str,
    ) -> str:
        digest = {
            task_id: {
                "status": result.get("status"),
                "output_data": result.get("output_data"),
                "evidence_references": result.get("evidence_references"),
                "uncertainty": result.get("uncertainty"),
            }
            for task_id, result in results.items()
        }
        result = await self.gateway.generate(
            GenerationRequest(
                role=ModelRole.ORCHESTRATOR,
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "You are Cicero's Central Orchestrator writing the "
                            "final response to a corporate lawyer. Synthesize the "
                            "specialist results into a clear, structured answer: "
                            "executive summary, key findings, arguments, "
                            "counterarguments, evaluation and unresolved issues. "
                            "Preserve evidence references exactly as given. "
                            "Never invent citations or facts. Flag uncertainty "
                            "honestly."
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=(
                            f"User request: {user_request}\n\n"
                            f"Task Specification:\n{json.dumps(spec.model_dump(), indent=1)}\n\n"
                            f"Specialist results by task:\n{json.dumps(digest, indent=1)[:30000]}"
                        ),
                    ),
                ],
                max_output_tokens=8192,
                routing_affinity_key=case_id,
            )
        )
        return result.text
