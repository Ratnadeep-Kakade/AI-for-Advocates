"""Central Least-Privilege Permission Enforcement for Cicero Agents."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Set
import yaml

from cicero.harness.manifest import AgentManifest

logger = logging.getLogger(__name__)

DEFAULT_GRANTS: Dict[str, Set[str]] = {
    "legal_research": {"retrieve_case_evidence", "gemini_grounded_search", "case_search", "web_search", "evidence_store"},
    "document_intelligence": {"retrieve_case_evidence", "case_search", "evidence_store"},
    "argument": {"retrieve_case_evidence", "case_search", "evidence_store"},
    "counterargument": {"retrieve_case_evidence", "case_search", "evidence_store"},
    "evaluator": {"retrieve_case_evidence", "verify_citations", "citation_verification"},
}


class PermissionPolicy:
    """Enforces: active_tools = manifest.requested_tools ∩ permissions.yaml."""

    def __init__(self, grants: Dict[str, Set[str]] | None = None) -> None:
        self._grants = grants or DEFAULT_GRANTS

    @classmethod
    def from_yaml(cls, path: Path | str) -> PermissionPolicy:
        p = Path(path)
        if not p.exists():
            logger.warning("Permissions config '%s' not found, using default grants.", path)
            return cls(DEFAULT_GRANTS)

        with open(p, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        raw_grants = data.get("grants", {})
        parsed = {k: set(v) for k, v in raw_grants.items()}
        return cls(parsed)

    def resolve_effective_tools(self, manifest: AgentManifest) -> List[str]:
        agent_id = manifest.agent_id
        requested = set(manifest.get_effective_tools())
        granted = self._grants.get(agent_id, set())

        # Enforce intersection
        effective = requested.intersection(granted)
        dropped = requested - granted

        if dropped:
            logger.warning(
                "Security policy dropped ungranted tools for '%s': %s",
                agent_id,
                dropped,
            )

        return sorted(list(effective))

    def validate_manifest(self, manifest: AgentManifest) -> List[str]:
        """Return list of unauthorized tool requests (empty if valid)."""
        agent_id = manifest.agent_id
        requested = set(manifest.get_effective_tools())
        granted = self._grants.get(agent_id, set())
        unauthorized = requested - granted
        if unauthorized:
            return [f"Agent '{agent_id}' requested ungranted tools: {sorted(list(unauthorized))}"]
        return []
