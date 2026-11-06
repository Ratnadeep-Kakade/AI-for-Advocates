import pytest
from cicero.harness.manifest import AgentManifest
from cicero.harness.permissions import PermissionPolicy
from cicero.harness.loop import BudgetedToolLoop
from cicero.harness.validation import run_deterministic_validation
from cicero.domain.contracts import EvidenceRef


def test_permission_policy_enforces_intersection():
    policy = PermissionPolicy({
        "legal_research": {"case_search", "web_search"},
    })

    manifest = AgentManifest(
        agent_id="legal_research",
        name="Legal Research",
        model_role="legal_researcher",
        requested_tools=["case_search", "web_search", "malicious_admin_tool"],
    )

    effective = policy.resolve_effective_tools(manifest)
    assert "case_search" in effective
    assert "web_search" in effective
    assert "malicious_admin_tool" not in effective
    assert len(effective) == 2


def test_permission_policy_reports_unauthorized_tools():
    policy = PermissionPolicy({
        "legal_research": {"case_search"},
    })

    manifest = AgentManifest(
        agent_id="legal_research",
        name="Legal Research",
        model_role="legal_researcher",
        requested_tools=["case_search", "unauthorized_tool"],
    )

    issues = policy.validate_manifest(manifest)
    assert len(issues) == 1
    assert "unauthorized_tool" in issues[0]


@pytest.mark.asyncio
async def test_budgeted_tool_loop_completes_on_terminal_output():
    loop = BudgetedToolLoop(max_turns=5, token_budget=10000)

    async def mock_step(turn, history):
        return {
            "output": "Terminal legal answer",
            "tokens_used": 150,
            "tool_calls": [],
        }

    async def mock_tool(name, args):
        return "tool output"

    res = await loop.run(step_fn=mock_step, tool_executor=mock_tool)
    assert res["completed"] is True
    assert res["turns"] == 1
    assert res["tokens_consumed"] == 150
    assert res["output"] == "Terminal legal answer"


@pytest.mark.asyncio
async def test_budgeted_tool_loop_respects_max_turns():
    loop = BudgetedToolLoop(max_turns=3, token_budget=10000)

    async def mock_step(turn, history):
        # Keep requesting tools
        return {
            "output": f"Turn {turn}",
            "tokens_used": 100,
            "tool_calls": [{"name": "search", "args": {"q": "test"}}],
        }

    async def mock_tool(name, args):
        return "search result"

    res = await loop.run(step_fn=mock_step, tool_executor=mock_tool)
    assert res["completed"] is False
    assert res["reason"] == "max_turns_reached"
    assert res["turns"] == 3


def test_deterministic_validation_produces_report():
    evidence = [
        EvidenceRef(
            id="ev-1",
            document_id="doc-123",
            title="Contract Exhibit",
            citation="Cal. Civ. Code § 1542",
            exact_quote="general release does not extend to claims",
        )
    ]
    sources = {
        "doc-123": "A general release does not extend to claims that the creditor does not know of."
    }

    report = run_deterministic_validation(
        agent_id="argument",
        task_id="task-1",
        evidence=evidence,
        source_texts=sources,
    )

    assert report.all_passed is True
    assert report.quotes_checked == 1
    assert report.quotes_verified == 1
    assert report.citations_checked == 1
    assert report.citations_verified == 1
    assert len(report.failures) == 0
