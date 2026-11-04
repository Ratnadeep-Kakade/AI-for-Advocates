"""Argument Agent (DeepSeek-R1-Distill-Llama-70B).

Builds the user's case from Document Intelligence output, Researcher findings
and (optionally) freshly retrieved case evidence. Python validates every
evidence/authority reference before the output may flow downstream.
"""

from __future__ import annotations

import logging
from typing import Any

from cicero.agents.argument.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_prompt
from cicero.agents.argument.schemas import ArgumentOutput, validate_argument_output
from cicero.agents.base import AgentContext, AgentResult, BaseAgent
from cicero.agents.common import (
    Gateway,
    RagRetriever,
    collect_evidence_items,
    generate_structured,
)
from cicero.models.contracts import ModelRole

logger = logging.getLogger(__name__)


class ArgumentAgent(BaseAgent):
    agent_id = "argument"

    def __init__(self, gateway: Gateway, rag: RagRetriever | None = None) -> None:
        self.gateway = gateway
        self.rag = rag

    async def execute(
        self, context: AgentContext, inputs: dict[str, Any]
    ) -> AgentResult:
        objective = inputs.get("objective") or context.objective or "Construct the legal arguments."
        position = inputs.get("position") or "the user's position as stated in the objective"
        intelligence = inputs.get("case_intelligence") or {}
        intel_data = intelligence.get("case_intelligence", intelligence)
        findings_wrap = inputs.get("research_findings") or {}
        findings = findings_wrap.get("research_findings", findings_wrap)
        sources = list(
            inputs.get("sources") or findings_wrap.get("sources") or []
        )
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

        output, meta = await generate_structured(
            self.gateway,
            role=ModelRole.ARGUMENT,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_prompt(
                objective=str(objective),
                position=str(position),
                case_intelligence=intel_data or None,
                research_findings=findings or None,
                evidence_items=evidence_items,
                sources=sources,
            ),
            schema=ArgumentOutput,
            max_output_tokens=8192,
            affinity_key=context.case_id,
        )
        output, issues = validate_argument_output(output, valid_evidence, valid_authorities)
        return AgentResult(
            execution_id=context.execution_id,
            task_id=context.task_id,
            case_id=context.case_id,
            agent_id=self.agent_id,
            status="partial" if issues else "completed",
            output_data={
                "argument_output": output.model_dump(),
                "evidence_items": evidence_items,
                "sources": sources,
            },
            input_references=[str(objective)],
            evidence_references=list(output.evidence_references),
            uncertainty=list(output.unresolved_issues),
            validation_status="failed" if issues else "passed",
            execution_metadata={
                "prompt_version": PROMPT_VERSION,
                "model": meta["model"],
                "validation_issues": issues,
            },
        )
