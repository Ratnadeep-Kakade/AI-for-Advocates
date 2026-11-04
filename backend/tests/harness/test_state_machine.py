import pytest

from cicero.harness.state_machine import (
    InvalidTransition,
    assert_execution_transition,
    assert_task_transition,
)


def test_execution_happy_path_transitions() -> None:
    assert_execution_transition("pending", "interpreting")
    assert_execution_transition("interpreting", "planning")
    assert_execution_transition("planning", "running")
    assert_execution_transition("running", "validating")
    assert_execution_transition("validating", "completed")


def test_execution_terminal_states_are_final() -> None:
    with pytest.raises(InvalidTransition):
        assert_execution_transition("completed", "running")
    with pytest.raises(InvalidTransition):
        assert_execution_transition("failed", "pending")


def test_task_transitions() -> None:
    assert_task_transition("pending", "running")
    assert_task_transition("running", "completed")
    with pytest.raises(InvalidTransition):
        assert_task_transition("completed", "running")
