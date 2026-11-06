"""Agent manifest models for the Cicero Harness."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(default="1.0")
    description: str = Field(default="")
    capabilities: list[str] = Field(default_factory=list)
    model_role: str = Field(min_length=1)
    execution_strategy: str = Field(default="single_shot")  # single_shot | tool_loop | map_reduce
    tools: list[str] = Field(default_factory=list)
    requested_tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    can_run_in_parallel: bool = False

    def get_effective_tools(self) -> list[str]:
        return self.requested_tools or self.tools
