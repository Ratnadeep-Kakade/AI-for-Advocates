"""Workflow state machine (persisted transitions; never LLM-controlled)."""

from __future__ import annotations

EXECUTION_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"interpreting", "failed", "cancelled"}),
    "interpreting": frozenset({"waiting_for_input", "planning", "failed"}),
    "waiting_for_input": frozenset({"planning", "cancelled"}),
    "planning": frozenset({"running", "failed"}),
    "running": frozenset({"validating", "failed", "cancelled"}),
    "validating": frozenset({"running", "completed", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"running", "cancelled"}),
    "running": frozenset({"completed", "partial", "failed", "retrying"}),
    "retrying": frozenset({"running", "failed"}),
    "completed": frozenset(),
    "partial": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


class InvalidTransition(RuntimeError):
    """Raised when a workflow state transition is not permitted."""


def assert_execution_transition(current: str, target: str) -> None:
    if target not in EXECUTION_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(
            f"Execution cannot move from '{current}' to '{target}'."
        )


def assert_task_transition(current: str, target: str) -> None:
    if target not in TASK_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(f"Task cannot move from '{current}' to '{target}'.")
