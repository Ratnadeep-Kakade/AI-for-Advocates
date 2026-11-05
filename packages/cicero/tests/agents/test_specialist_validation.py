from cicero.agents.argument.schemas import (
    ArgumentOutput,
    Proposition,
    validate_argument_output,
)
from cicero.agents.counterargument.schemas import (
    Challenge,
    CounterargumentOutput,
    validate_counterargument_output,
)
from cicero.agents.evaluator.agent import deterministic_checks
from cicero.agents.legal_researcher.schemas import (
    AuthorityInfo,
    ResearchFindings,
    validate_findings,
)


def test_validate_findings_strips_unknown_sources() -> None:
    findings = ResearchFindings(
        authorities=[
            AuthorityInfo(
                title="Limitation Act",
                kind="statute",
                stance="favourable",
                proposition="Six-year limitation applies.",
                source_ids=["SRC_ok", "SRC_nope"],
            )
        ],
        source_ids=["SRC_ok", "SRC_nope"],
    )
    cleaned, issues = validate_findings(findings, {"SRC_ok"})
    assert cleaned.authorities[0].source_ids == ["SRC_ok"]
    assert cleaned.source_ids == ["SRC_ok"]
    assert issues


def test_validate_argument_output_strips_unknown_refs() -> None:
    output = ArgumentOutput(
        propositions=[
            Proposition(
                proposition="The founders breached the non-compete.",
                reasoning="Clause 4.2 prohibits competition.",
                evidence_ids=["EV_ok", "EV_nope"],
                authority_ids=["SRC_ok", "SRC_nope"],
            )
        ],
        evidence_references=["EV_ok", "EV_nope"],
    )
    cleaned, issues = validate_argument_output(output, {"EV_ok"}, {"SRC_ok"})
    assert cleaned.propositions[0].evidence_ids == ["EV_ok"]
    assert cleaned.propositions[0].authority_ids == ["SRC_ok"]
    assert cleaned.evidence_references == ["EV_ok"]
    assert issues


def test_validate_counterargument_output_strips_unknown_refs() -> None:
    output = CounterargumentOutput(
        challenges=[
            Challenge(
                target="Proposition 1",
                challenge="The clause permits advisory roles.",
                evidence_ids=["EV_ok", "EV_nope"],
                severity="high",
            )
        ],
        evidence_references=["EV_nope"],
    )
    cleaned, issues = validate_counterargument_output(output, {"EV_ok"}, set())
    assert cleaned.challenges[0].evidence_ids == ["EV_ok"]
    assert cleaned.evidence_references == ["EV_ok"]
    assert issues


def test_deterministic_checks_flag_unknown_references() -> None:
    argument = {"evidence_references": ["EV_ok", "EV_missing"]}
    items = [
        {"key": "EV_ok", "quote": "short quote", "full_quote": "The full quote text."}
    ]
    checks = deterministic_checks(argument, None, items)
    assert checks["argument"]["references"]["unknown"] == ["EV_missing"]
    assert checks["argument"]["references"]["existing"] == ["EV_ok"]
