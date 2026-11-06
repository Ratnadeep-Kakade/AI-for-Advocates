"""Fault recovery and partial result policies for the Cicero Harness."""

from __future__ import annotations

import logging
from typing import Any, Dict

from cicero.domain.contracts import AgentResult

logger = logging.getLogger(__name__)


class RecoveryPolicy:
    """Defines retry budgets and graceful fallback behavior on agent errors."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def should_retry(self, attempt: int, error: Exception | str) -> bool:
        if attempt >= self.max_retries:
            return False
        # Do not retry fatal syntax/schema validation errors
        err_str = str(error).lower()
        if "syntax" in err_str or "unauthorized" in err_str:
            return False
        return True

    def create_partial_result(
        self,
        task_id: str,
        agent_id: str,
        error: str,
        partial_data: Dict[str, Any] | None = None,
    ) -> AgentResult:
        """Constructs a structured AgentResult recording the failure for downstream review."""
        logger.warning("Producing partial result for task '%s' (%s): %s", task_id, agent_id, error)
        return AgentResult(
            task_id=task_id,
            agent_id=agent_id,
            success=False,
            data=partial_data or {},
            error_message=error,
            turns_used=1,
            tokens_consumed=0,
        )
