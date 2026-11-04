"""YAML manifest models for the Platform Capability Registry.

Manifests are deliberately declarative: an agent describes what it does, which
model role serves it, and which abstract tools it may use. It never contains
endpoints, credentials, provider settings, or implementation entry points.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    # Fine-grained capability names as plain strings for now; structured
    # capability objects arrive when the Interpreter needs richer matching.
    capabilities: list[str] = Field(min_length=1)
    model_role: str = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    can_run_in_parallel: bool = False
