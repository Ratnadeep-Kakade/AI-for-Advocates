"""Task Specification and Execution Plan contracts.

The Interpreter (Muse Spark) produces a Task Specification. The Orchestrator
(Muse Spark) proposes an Execution Plan. Python validates the plan before
anything executes: the LLM proposes, Python decides.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TaskSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_intent: str
    objectives: list[str] = Field(default_factory=list)
    requested_capabilities: list[str] = Field(default_factory=list)
    position: str | None = None
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list)


class PlanTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    objective: str = Field(min_length=1)


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[PlanTask] = Field(default_factory=list)


def default_plan(spec: TaskSpecification) -> ExecutionPlan:
    """Deterministic fallback plan used when LLM planning is unavailable."""
    objectives = spec.objectives or [spec.user_intent]
    main = objectives[0]
    return ExecutionPlan(
        tasks=[
            PlanTask(
                task_id="T1",
                agent_id="document_intelligence",
                objective=f"Analyse the case documents: {main}",
            ),
            PlanTask(
                task_id="T2",
                agent_id="legal_researcher",
                objective=f"Research applicable legal authorities: {main}",
            ),
            PlanTask(
                task_id="T3",
                agent_id="argument",
                depends_on=["T1", "T2"],
                objective=f"Construct arguments: {main}",
            ),
            PlanTask(
                task_id="T4",
                agent_id="counterargument",
                depends_on=["T1", "T2", "T3"],
                objective=f"Oppose and challenge: {main}",
            ),
            PlanTask(
                task_id="T5",
                agent_id="evaluator",
                depends_on=["T1", "T2", "T3", "T4"],
                objective=f"Evaluate both sides: {main}",
            ),
        ]
    )
