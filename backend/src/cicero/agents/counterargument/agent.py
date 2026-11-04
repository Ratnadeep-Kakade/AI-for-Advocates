"""Counterargument Agent (DeepSeek-R1-Distill-Llama-70B).

Stage 1: independent opposing analysis from the original evidence (never
seeded with the Argument Agent's conclusions). Stage 2 (when the Argument
output is supplied): an explicit adversarial challenge pass. Runs in a
separate execution context from the Argument Agent by design.
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
from cicero.agents.counterargument.prompts import (
    CHALLENGE_SYSTEM_PROMPT,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_challenge_prompt,
    build_independent_prompt,
)
from cicero.agents.counterargument.schemas import (
    CounterargumentOutput,
    validate_counterargument_output,
)
from cicero.models.contracts import ModelRole

logger = logging.getLogger(__name__)


class CounterargumentAgent(BaseAgent):
    agent_id = "counterargument"

    def __init__(self, gateway: Gateway, rag: RagRetriever | None = None) -> None:
        self.gateway = gateway
        self.rag = rag

    async def execute(
        self, context: AgentContext, inputs: dict[str, Any]
    ) -> AgentResult:
        objective = inputs.get("objective") or context.objective or "Oppose the user's position."
        position = inputs.get("position") or "the user's position as stated in the objective"
        intelligence = inputs.get("case_intelligence") or {}
        intel_data = intelligence.get("case_intelligence", intelligence)
        findings_wrap = inputs.get("research_findings") or {}
        findings = findings_wrap.get("research_findings", findings_wrap)
        sources = list(inputs.get("sources") or findings_wrap.get("sources") or [])
        evidence_items = await collect_evidence_items(
            self.rag,
            organization_id=context.organization_id,
            case_id=context.case_id,
            inputs=inputs,
            objective=str(objective),
        )
        valid_evidence = {item["key"] for item in evidence_items} | set(
            intel_data.get("evidence_references") or []
        )
        valid_authorities = {s["source_id"] for s in sources if s.get("source_id")}

        # Stage 1: independent opposing analysis.
        independent, meta = await generate_structured(
            self.gateway,
            role=ModelRole.COUNTERARGUMENT,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_independent_prompt(
                objective=str(objective),
                position=str(position),
                case_intelligence=intel_data or None,
                research_findings=findings or None,
                evidence_items=evidence_items,
                sources=sources,
            ),
            schema=CounterargumentOutput,
            max_output_tokens=8192,
            affinity_key=context.case_id,
        )
        independent, issues = validate_counterargument_output(
            independent, valid_evidence, valid_authorities
        )

        # Stage 2 (optional): adversarial challenge of the Argument output.
        challenge_output: CounterargumentOutput | None = None
        argument_output = (inputs.get("argument_output") or {}).get(
            "argument_output"
        ) or inputs.get("argument_output")
        if argument_output:
            challenge_output, challenge_meta = await generate_structured(
                self.gateway,
                role=ModelRole.COUNTERARGUMENT,
                system_prompt=CHALLENGE_SYSTEM_PROMPT,
                user_prompt=build_challenge_prompt(
                    argument_output=argument_output,
                    case_intelligence=intel_data or None,
                    research_findings=findings or None,
                    evidence_items=evidence_items,
                    sources=sources,
                ),
                schema=CounterargumentOutput,
                max_output_tokens=8192,
                affinity_key=context.case_id,
            )
            challenge_output, challenge_issues = validate_counterargument_output(
                challenge_output, valid_evidence, valid_authorities
            )
            issues = issues + challenge_issues
            meta = {**meta, "challenge_model": challenge_meta["model"]}

        merged_refs = sorted(
            set(independent.evidence_references)
            | set(challenge_output.evidence_references if challenge_output else [])
        )
        uncertainty = list(independent.missing_evidence) + list(
            independent.unsupported_assumptions
        )
        return AgentResult(
            execution_id=context.execution_id,
            task_id=context.task_id,
            case_id=context.case_id,
            agent_id=self.agent_id,
            status="partial" if issues else "completed",
            output_data={
                "counterargument_output": independent.model_dump(),
                "challenge_output": challenge_output.model_dump()
                if challenge_output
                else None,
                "evidence_items": evidence_items,
                "sources": sources,
            },
            input_references=[str(objective)],
            evidence_references=merged_refs,
            uncertainty=uncertainty,
            validation_status="failed" if issues else "passed",
            execution_metadata={
                "prompt_version": PROMPT_VERSION,
                "model": meta["model"],
                "validation_issues": issues,
            },
        )
