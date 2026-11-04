import pytest
import yaml

from cicero.registry.loader import RegistryError, load_registry

EXPECTED_AGENTS = {
    "argument",
    "counterargument",
    "document_intelligence",
    "evaluator",
    "interpreter",
    "legal_researcher",
    "orchestrator",
}


def test_real_registry_loads_all_agents() -> None:
    registry = load_registry()
    assert set(registry.agent_ids()) == EXPECTED_AGENTS
    doc_intel = registry.get("document_intelligence")
    assert doc_intel.model_role == "document_intelligence"
    assert "retrieve_case_evidence" in doc_intel.tools
    summary = registry.summary()
    assert {a["agent_id"] for a in summary["agents"]} == EXPECTED_AGENTS


def test_permissions_are_central() -> None:
    registry = load_registry()
    assert registry.permitted_tools("interpreter") == frozenset()
    assert "gemini_grounded_search" in registry.permitted_tools("legal_researcher")
    with pytest.raises(RegistryError):
        registry.assert_tool_permitted("argument", "gemini_grounded_search")


def _write_manifest(root, agent_id: str, **overrides) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True)
    manifest = {
        "agent_id": agent_id,
        "name": "Test Agent",
        "version": "1.0",
        "description": "Test manifest.",
        "capabilities": ["Do test things"],
        "model_role": "argument",
        "tools": [],
        "inputs": [],
        "outputs": [],
        "can_run_in_parallel": False,
    }
    manifest.update(overrides)
    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")


def test_unknown_tool_rejected(tmp_path) -> None:
    _write_manifest(tmp_path, "argument", tools=["fly_to_moon"])
    with pytest.raises(RegistryError):
        load_registry(tmp_path)


def test_forbidden_tool_rejected(tmp_path) -> None:
    _write_manifest(tmp_path, "argument", tools=["gemini_grounded_search"])
    with pytest.raises(RegistryError):
        load_registry(tmp_path)


def test_unknown_role_rejected(tmp_path) -> None:
    _write_manifest(tmp_path, "argument", model_role="super_lawyer")
    with pytest.raises(RegistryError):
        load_registry(tmp_path)
