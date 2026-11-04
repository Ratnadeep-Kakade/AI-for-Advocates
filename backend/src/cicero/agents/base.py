"""Common agent interface and the standard AgentResult envelope.

Agents never exchange conversational histories. Every agent consumes a typed
context plus input references and returns the same AgentResult envelope, which
Python validates (schema, evidence references, case ownership) before any
dependent agent may consume it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str
    case_id: str
    execution_id: str
    task_id: str
    objective: str = ""


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    execution_id: str
    task_id: str
    case_id: str
    agent_id: str
    status: Literal["completed", "partial", "failed", "insufficient_evidence"]
    output_data: dict[str, Any]
    input_references: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)
    confidence: float | None = None
    uncertainty: list[str] = Field(default_factory=list)
    validation_status: Literal["pending", "passed", "failed"] = "pending"
    execution_metadata: dict[str, Any] = Field(default_factory=dict)


class BaseAgent(ABC):
    """Provider-agnostic agent interface; agents call the Model Gateway only."""

    agent_id: str = ""

    @abstractmethod
    async def execute(
        self, context: AgentContext, inputs: dict[str, Any]
    ) -> AgentResult:
        raise NotImplementedError
