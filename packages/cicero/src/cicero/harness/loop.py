"""Budgeted Tool Loop Execution Primitive."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional
from time import monotonic

logger = logging.getLogger(__name__)


class LoopBudgetExceeded(RuntimeError):
    """Raised when an autonomous agent loop exceeds its configured turn or token limit."""


class BudgetedToolLoop:
    """Executes an autonomous agent tool loop under strict turn, token, and time budgets."""

    def __init__(
        self,
        *,
        max_turns: int = 8,
        token_budget: int = 60000,
        timeout_s: float = 300.0,
    ) -> None:
        self.max_turns = max_turns
        self.token_budget = token_budget
        self.timeout_s = timeout_s

    async def run(
        self,
        *,
        step_fn: Callable[[int, List[Dict[str, Any]]], Coroutine[Any, Any, Dict[str, Any]]],
        tool_executor: Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Any]],
        initial_context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Runs the loop until completion, budget exhaustion, or timeout."""
        start_time = monotonic()
        turns = 0
        tokens_consumed = 0
        history: List[Dict[str, Any]] = [initial_context] if initial_context else []

        while turns < self.max_turns:
            elapsed = monotonic() - start_time
            if elapsed > self.timeout_s:
                logger.warning("Tool loop exceeded timeout of %0.1fs at turn %d", self.timeout_s, turns)
                break

            turns += 1
            step_result = await step_fn(turns, history)
            tokens_consumed += step_result.get("tokens_used", 0)

            if tokens_consumed >= self.token_budget:
                logger.warning("Tool loop exhausted token budget (%d >= %d)", tokens_consumed, self.token_budget)
                return {
                    "completed": False,
                    "reason": "token_budget_exceeded",
                    "turns": turns,
                    "tokens_consumed": tokens_consumed,
                    "output": step_result.get("output"),
                }

            tool_calls = step_result.get("tool_calls", [])
            if not tool_calls:
                # Terminal output reached
                return {
                    "completed": True,
                    "turns": turns,
                    "tokens_consumed": tokens_consumed,
                    "output": step_result.get("output"),
                    "data": step_result.get("data", {}),
                }

            # Execute tool calls
            for call in tool_calls:
                tool_name = call["name"]
                tool_args = call.get("args", {})
                tool_output = await tool_executor(tool_name, tool_args)
                history.append({
                    "role": "tool",
                    "name": tool_name,
                    "output": tool_output,
                })

        return {
            "completed": False,
            "reason": "max_turns_reached",
            "turns": turns,
            "tokens_consumed": tokens_consumed,
            "output": history[-1] if history else None,
        }
