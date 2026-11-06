"""Evaluator Agent (DeepSeek-R1-Distill-Llama-70B).

Runs deterministic Python verification first (evidence-reference existence and
exact quote matching against the original evidence), then asks the model to
assess both sides using those verdicts as ground truth. Same-model agreement
is never treated as independent verification.
"""

from __future__ import annotations

import logging
from typing import Any

from cicero.agents.base import AgentContext, AgentResult, BaseAgent
from cicero.agents.common import (
    Gateway,
    RagRetriever,
    collect_evidence_items,
    generate_structured,
)
from cicero.agents.evaluator.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_prompt
from cicero.agents.evaluator.schemas import EvaluationOutput
from cicero.llm.contracts import ModelRole
from cicero.tools.citation_verification import (
    check_reference_existence,
    verify_quote_references,
)

logger = logging.getLogger(__name__)


def deterministic_checks(
    argument_output: dict[str, Any] | None,
    counterargument_output: dict[str, Any] | None,
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Python-side verification both sides' references must survive."""
    sources_by_id = {
        item["key"]: item.get("full_quote") or item.get("quote", "")
        for item in evidence_items
    }
    available = set(sources_by_id)
    checks: dict[str, Any] = {}
    for label, output in (
        ("argument", argument_output),
        ("counterargument", counterargument_output),
    ):
        if not output:
            continue
        refs = list(output.get("evidence_references") or [])
        # Propositions/challenges may cite quotes directly; verify them too.
        quote_refs: list[dict[str, str]] = []
        for entry in output.get("propositions") or output.get("challenges") or []:
            for quote in entry.get("quotes") or []:
                quote_refs.append(
                    {"source_id": entry.get("evidence_ids", [""])[0], "quote": quote}
                )
        checks[label] = {
            "references": check_reference_existence(refs, available),
            "quotes": verify_quote_references(quote_refs, sources_by_id)
            if quote_refs
            else [],
        }
    return checks


class EvaluatorAgent(BaseAgent):
    agent_id = "evaluator"

    def __init__(self, gateway: Gateway, rag: RagRetriever | None = None) -> None:
        self.gateway = gateway
        self.rag = rag

    async def execute(
        self, context: AgentContext, inputs: dict[str, Any]
    ) -> AgentResult:
        objective = inputs.get("objective") or context.objective or "Evaluate the arguments."
        intelligence = inputs.get("case_intelligence") or {}
        intel_data = intelligence.get("case_intelligence", intelligence)
        argument_output = (inputs.get("argument_output") or {}).get(
            "argument_output"
        ) or inputs.get("argument_output")
        counter_wrap = inputs.get("counterargument_output") or {}
        counter_output = counter_wrap.get("counterargument_output") or counter_wrap or None
        sources = list(
            inputs.get("sources")
            or (inputs.get("research_findings") or {}).get("sources")
            or []
        )
        evidence_items = await collect_evidence_items(
            self.rag,
            organization_id=context.organization_id,
            case_id=context.case_id,
            inputs=inputs,
            objective=str(objective),
        )
        checks = deterministic_checks(argument_output, counter_output, evidence_items)
        unknown_refs = sum(
            len(side["references"]["unknown"])
            for side in checks.values()
            if isinstance(side, dict)
        )

        output, meta = await generate_structured(
            self.gateway,
            role=ModelRole.EVALUATOR,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_prompt(
                objective=str(objective),
                case_intelligence=intel_data or None,
                argument_output=argument_output,
                counterargument_output=counter_output,
                evidence_items=evidence_items,
                sources=sources,
                deterministic_checks=checks,
            ),
            schema=EvaluationOutput,
            max_output_tokens=8192,
            affinity_key=context.case_id,
        )
        return AgentResult(
            execution_id=context.execution_id,
            task_id=context.task_id,
            case_id=context.case_id,
            agent_id=self.agent_id,
            status="completed",
            output_data={
                "evaluation": output.model_dump(),
                "deterministic_checks": checks,
                "evidence_items": evidence_items,
                "sources": sources,
            },
            input_references=[str(objective)],
            evidence_references=sorted(
                {item["key"] for item in evidence_items}
            ),
            uncertainty=list(output.missing_evidence),
            validation_status="passed" if unknown_refs == 0 else "failed",
            execution_metadata={
                "prompt_version": PROMPT_VERSION,
                "model": meta["model"],
                "unknown_references_found": unknown_refs,
            },
        )
