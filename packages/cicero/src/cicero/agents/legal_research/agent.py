"""Legal Researcher Agent (DeepSeek-R1-Distill-Llama-70B).

Pipeline: query generation (DeepSeek) -> Python Gemini Grounding adapter ->
primary-source fetch + quote verification -> analysis (DeepSeek) -> validated
Research Findings. Web content never reaches the model except through the
adapter's collected source bundles.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from cicero.agents.base import AgentContext, AgentResult, BaseAgent
from cicero.agents.common import Gateway, generate_structured
from cicero.agents.legal_researcher.prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    PROMPT_VERSION,
    QUERY_SYSTEM_PROMPT,
    build_analysis_prompt,
)
from cicero.agents.legal_researcher.schemas import ResearchFindings, validate_findings
from cicero.models.contracts import ModelRole
from cicero.tools.web_search import SearchBundle

logger = logging.getLogger(__name__)

MAX_QUERIES = 5


class SearchAdapter(Protocol):
    async def search(self, query: str) -> SearchBundle: ...


class _QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[str]


class LegalResearcherAgent(BaseAgent):
    agent_id = "legal_researcher"

    def __init__(self, gateway: Gateway, search: SearchAdapter | None) -> None:
        self.gateway = gateway
        self.search = search

    async def execute(
        self, context: AgentContext, inputs: dict[str, Any]
    ) -> AgentResult:
        objective = (
            inputs.get("objective")
            or context.objective
            or "Research the applicable legal authorities."
        )
        legal_questions = list(inputs.get("legal_questions") or [])
        metadata: dict[str, Any] = {"prompt_version": PROMPT_VERSION}

        if self.search is None:
            findings = ResearchFindings(
                research_gaps=[
                    "Web research unavailable: Gemini Grounding is not configured."
                ]
            )
            return AgentResult(
                execution_id=context.execution_id,
                task_id=context.task_id,
                case_id=context.case_id,
                agent_id=self.agent_id,
                status="partial",
                output_data={
                    "research_findings": findings.model_dump(),
                    "sources": [],
                },
                uncertainty=findings.research_gaps,
                validation_status="passed",
                execution_metadata=metadata,
            )

        query_plan, query_meta = await generate_structured(
            self.gateway,
            role=ModelRole.LEGAL_RESEARCHER,
            system_prompt=QUERY_SYSTEM_PROMPT,
            user_prompt=(
                f"Objective: {objective}\n"
                f"Legal questions: {legal_questions or 'derive from the objective'}"
            ),
            schema=_QueryPlan,
            max_output_tokens=1024,
            affinity_key=context.case_id,
        )
        queries = [q.strip() for q in query_plan.queries if q.strip()][:MAX_QUERIES]
        if not queries:
            queries = [str(objective)]
        metadata["search_queries"] = queries
        metadata["query_model"] = query_meta["model"]

        bundles: list[SearchBundle] = []
        sources_by_id: dict[str, dict[str, Any]] = {}
        for query in queries:
            bundle = await self.search.search(query)
            bundles.append(bundle)
            for source in bundle.sources:
                sources_by_id.setdefault(source.source_id, source.model_dump())
        metadata["sources_collected"] = len(sources_by_id)
        metadata["sources_verified"] = sum(
            1
            for s in sources_by_id.values()
            if s.get("verification_status") == "verified"
        )

        findings, analysis_meta = await generate_structured(
            self.gateway,
            role=ModelRole.LEGAL_RESEARCHER,
            system_prompt=ANALYSIS_SYSTEM_PROMPT,
            user_prompt=build_analysis_prompt(
                objective=str(objective),
                legal_questions=legal_questions,
                sources=list(sources_by_id.values()),
            ),
            schema=ResearchFindings,
            max_output_tokens=8192,
            affinity_key=context.case_id,
        )
        findings, issues = validate_findings(findings, set(sources_by_id))
        metadata["model"] = analysis_meta["model"]
        return AgentResult(
            execution_id=context.execution_id,
            task_id=context.task_id,
            case_id=context.case_id,
            agent_id=self.agent_id,
            status="partial" if issues or findings.research_gaps else "completed",
            output_data={
                "research_findings": findings.model_dump(),
                "sources": list(sources_by_id.values()),
                "search_bundles": [b.model_dump() for b in bundles],
            },
            input_references=[str(objective)],
            uncertainty=findings.unresolved_questions + findings.research_gaps,
            validation_status="failed" if issues else "passed",
            execution_metadata={**metadata, "validation_issues": issues},
        )
