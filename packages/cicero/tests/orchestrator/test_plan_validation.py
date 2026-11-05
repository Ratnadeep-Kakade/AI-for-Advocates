from cicero.orchestrator.plan import validate_plan
from cicero.orchestrator.schemas import (
    ExecutionPlan,
    PlanTask,
    TaskSpecification,
    default_plan,
)
from cicero.registry.loader import load_registry


def _task(task_id: str, agent: str, deps: list[str] | None = None) -> PlanTask:
    return PlanTask(
        task_id=task_id, agent_id=agent, depends_on=deps or [], objective="Do work"
    )


def test_default_plan_is_valid() -> None:
    registry = load_registry()
    spec = TaskSpecification(user_intent="Analyse the shareholders agreement")
    assert validate_plan(default_plan(spec), registry) == []


def test_unknown_agent_rejected() -> None:
    registry = load_registry()
    plan = ExecutionPlan(tasks=[_task("T1", "super_lawyer")])
    assert any("unknown agent" in issue for issue in validate_plan(plan, registry))


def test_non_specialist_agent_rejected() -> None:
    registry = load_registry()
    plan = ExecutionPlan(tasks=[_task("T1", "interpreter")])
    assert any("not a" in issue for issue in validate_plan(plan, registry))


def test_dangling_dependency_rejected() -> None:
    registry = load_registry()
    plan = ExecutionPlan(tasks=[_task("T1", "argument", ["T9"])])
    assert any("unknown task" in issue for issue in validate_plan(plan, registry))


def test_cycle_rejected() -> None:
    registry = load_registry()
    plan = ExecutionPlan(
        tasks=[
            _task("T1", "argument", ["T2"]),
            _task("T2", "counterargument", ["T1"]),
        ]
    )
    assert any("cycle" in issue for issue in validate_plan(plan, registry))


def test_duplicate_task_ids_rejected() -> None:
    registry = load_registry()
    plan = ExecutionPlan(
        tasks=[_task("T1", "argument"), _task("T1", "evaluator")]
    )
    assert any("Duplicate" in issue for issue in validate_plan(plan, registry))
