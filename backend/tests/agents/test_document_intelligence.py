import json

from cicero.agents.base import AgentContext
from cicero.agents.document_intelligence.agent import (
    DocumentIntelligenceAgent,
    build_evidence_registry,
    extract_json_object,
)
from cicero.agents.document_intelligence.schemas import (
    CaseIntelligence,
    ObligationInfo,
    validate_intelligence,
)

PACK = {
    "execution_id": "EXEC_aaa",
    "insufficient_evidence": False,
    "evidence": [
        {
            "evidence_id": "EV_001",
            "document_id": "DOC_1",
            "page": 3,
            "clause_label": "Section 4.2",
            "why_included": "matched",
            "original_source_text": "The Founders shall not compete.",
            "derived_annotations": {"filename": "sha.pdf"},
            "score": 0.91,
        }
    ],
}


def test_registry_keys_are_execution_scoped() -> None:
    registry = build_evidence_registry([PACK])
    assert set(registry) == {"EXEC_aaa/EV_001"}
    assert registry["EXEC_aaa/EV_001"]["filename"] == "sha.pdf"


def test_insufficient_pack_contributes_nothing() -> None:
    registry = build_evidence_registry(
        [{"execution_id": "EXEC_x", "insufficient_evidence": True, "evidence": []}]
    )
    assert registry == {}


def test_validate_intelligence_strips_unknown_refs() -> None:
    intel = CaseIntelligence(
        obligations=[
            ObligationInfo(
                party="Founders",
                obligation="Non-compete",
                clause_reference="Section 4.2",
                status="breached",
                evidence_ids=["EXEC_aaa/EV_001", "EXEC_aaa/EV_999"],
            )
        ],
        evidence_references=["EXEC_aaa/EV_001", "EXEC_aaa/EV_999"],
    )
    cleaned, issues = validate_intelligence(intel, {"EXEC_aaa/EV_001"})
    assert cleaned.obligations[0].evidence_ids == ["EXEC_aaa/EV_001"]
    assert cleaned.evidence_references == ["EXEC_aaa/EV_001"]
    assert issues


def test_extract_json_object_tolerates_fences() -> None:
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('prefix {"a": 2} suffix') == {"a": 2}


class _FakeRag:
    async def retrieve(self, **kwargs):
        return PACK


class _FakeGateway:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def generate(self, request):
        self.calls += 1

        class _Result:
            text = json.dumps(self.payload)
            model = "muse-spark-1.3"

        return _Result()


async def test_agent_end_to_end_with_fakes() -> None:
    payload = {
        "obligations": [
            {
                "party": "Founders",
                "obligation": "Non-compete",
                "clause_reference": "Section 4.2",
                "status": "breached",
                "evidence_ids": ["EXEC_aaa/EV_001"],
            }
        ],
        "evidence_references": ["EXEC_aaa/EV_001"],
    }
    agent = DocumentIntelligenceAgent(_FakeGateway(payload), _FakeRag())
    result = await agent.execute(
        AgentContext(
            organization_id="ORG_1",
            case_id="CASE_1",
            execution_id="EXEC_test",
            task_id="T1",
        ),
        {"objective": "Analyse the agreement"},
    )
    assert result.status == "completed"
    assert result.validation_status == "passed"
    assert result.evidence_references == ["EXEC_aaa/EV_001"]
    assert result.output_data["evidence_items"][0]["filename"] == "sha.pdf"


async def test_agent_insufficient_evidence() -> None:
    class _EmptyRag:
        async def retrieve(self, **kwargs):
            return {"execution_id": "EXEC_x", "insufficient_evidence": True, "evidence": []}

    agent = DocumentIntelligenceAgent(_FakeGateway({}), _EmptyRag())
    result = await agent.execute(
        AgentContext(
            organization_id="ORG_1",
            case_id="CASE_1",
            execution_id="EXEC_test",
            task_id="T1",
        ),
        {},
    )
    assert result.status == "insufficient_evidence"
