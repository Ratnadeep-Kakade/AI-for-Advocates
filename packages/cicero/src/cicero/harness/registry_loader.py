"""Loader and runtime view for the Platform Capability Registry.

At startup Python loads every ``agents/*/agent.yaml`` manifest, validates it
against the registered model roles, the known tool catalogue, and the central
tool-permission policy, then builds a read-only registry. The Interpreter and
Orchestrator receive only the registry summary — never filesystem paths,
deployment details, or credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from cicero.models.contracts import ModelRole
from cicero.registry.models import AgentManifest

# Central tool-permission policy: the maximum tools each agent may declare.
# Manifests may only request tools listed here for their agent.
TOOL_PERMISSIONS: dict[str, frozenset[str]] = {
    "interpreter": frozenset(),
    "orchestrator": frozenset(),
    "document_intelligence": frozenset({"retrieve_case_evidence"}),
    "legal_researcher": frozenset({"retrieve_case_evidence", "gemini_grounded_search"}),
    "argument": frozenset({"retrieve_case_evidence"}),
    "counterargument": frozenset({"retrieve_case_evidence"}),
    "evaluator": frozenset({"retrieve_case_evidence", "verify_citations"}),
}

KNOWN_TOOLS: frozenset[str] = frozenset().union(*TOOL_PERMISSIONS.values())

_VALID_ROLES = frozenset(role.value for role in ModelRole)


class RegistryError(RuntimeError):
    """Raised when an agent manifest fails validation."""


class RuntimeRegistry:
    """Read-only runtime view over validated agent manifests."""

    def __init__(self, manifests: dict[str, AgentManifest]) -> None:
        self._manifests = dict(manifests)

    def get(self, agent_id: str) -> AgentManifest:
        try:
            return self._manifests[agent_id]
        except KeyError:
            raise RegistryError(f"Unknown agent_id: {agent_id}") from None

    def agent_ids(self) -> list[str]:
        return sorted(self._manifests)

    def permitted_tools(self, agent_id: str) -> frozenset[str]:
        self.get(agent_id)
        return TOOL_PERMISSIONS.get(agent_id, frozenset())

    def assert_tool_permitted(self, agent_id: str, tool: str) -> None:
        if tool not in self.permitted_tools(agent_id):
            raise RegistryError(
                f"Agent '{agent_id}' is not permitted to use tool '{tool}'."
            )

    def summary(self) -> dict[str, Any]:
        """Compact platform description exposed to Interpreter/Orchestrator."""
        return {
            "agents": [
                {
                    "agent_id": m.agent_id,
                    "name": m.name,
                    "description": m.description,
                    "capabilities": list(m.capabilities),
                    "model_role": m.model_role,
                    "tools": list(m.tools),
                    "inputs": list(m.inputs),
                    "outputs": list(m.outputs),
                    "can_run_in_parallel": m.can_run_in_parallel,
                }
                for m in (self._manifests[k] for k in self.agent_ids())
            ]
        }


def default_agents_root() -> Path:
    return Path(__file__).resolve().parent.parent / "agents"


def load_registry(root: Path | None = None) -> RuntimeRegistry:
    """Load and validate all manifests under ``root`` (default: the agents package)."""
    root = root or default_agents_root()
    manifests: dict[str, AgentManifest] = {}
    for manifest_path in sorted(root.glob("*/agent.yaml")):
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest = AgentManifest.model_validate(raw)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise RegistryError(f"Invalid manifest {manifest_path}: {exc}") from exc
        if manifest.agent_id in manifests:
            raise RegistryError(f"Duplicate agent_id: {manifest.agent_id}")
        if manifest.agent_id != manifest_path.parent.name:
            raise RegistryError(
                f"Manifest agent_id '{manifest.agent_id}' does not match its "
                f"directory '{manifest_path.parent.name}'."
            )
        if manifest.model_role not in _VALID_ROLES:
            raise RegistryError(
                f"Agent '{manifest.agent_id}' references unknown model role "
                f"'{manifest.model_role}'."
            )
        unknown_tools = set(manifest.tools) - KNOWN_TOOLS
        if unknown_tools:
            raise RegistryError(
                f"Agent '{manifest.agent_id}' requests unknown tools: "
                f"{sorted(unknown_tools)}."
            )
        forbidden = set(manifest.tools) - TOOL_PERMISSIONS.get(manifest.agent_id, frozenset())
        if forbidden:
            raise RegistryError(
                f"Agent '{manifest.agent_id}' requests tools outside its "
                f"permission policy: {sorted(forbidden)}."
            )
        manifests[manifest.agent_id] = manifest
    if not manifests:
        raise RegistryError(f"No agent manifests found under {root}.")
    return RuntimeRegistry(manifests)
