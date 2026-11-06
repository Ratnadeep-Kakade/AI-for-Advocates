"""Document Intelligence Agent (Muse Spark).

Consumes verified RAG EvidencePacks — never raw documents — and produces
structured Case Intelligence. Python deterministically validates every
evidence reference the model cites before the result may flow downstream.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Protocol

from cicero.agents.base import AgentContext, AgentResult, BaseAgent
from cicero.agents.document_intelligence.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from cicero.agents.document_intelligence.schemas import (
    CaseIntelligence,
    validate_intelligence,
)
from cicero.llm.contracts import ChatMessage, GenerationRequest, ModelRole

logger = logging.getLogger(__name__)

MAX_QUOTE_CHARS = 1500


class RagRetriever(Protocol):
    async def retrieve(
        self,
        *,
        organization_id: str,
        case_id: str,
        query: str,
        top_k: int = 8,
        token_budget: int | None = None,
        document_ids: list[str] | None = None,
        ablation: dict | None = None,
    ) -> dict: ...


class Gateway(Protocol):
    async def generate(self, request: GenerationRequest) -> Any: ...


def retrieval_queries(objective: str) -> list[tuple[str, int]]:
    """Targeted evidence queries (objective first, then structural lenses)."""
    return [
        (objective, 8),
        ("parties to the agreement, their roles, scope and structure", 6),
        ("obligations of each party, duties, covenants and undertakings", 8),
        ("breach, default, termination, remedies and liability", 8),
        ("effective date, term, expiry, notice periods and key dates", 6),
        ("amendments, variations and inconsistencies between provisions", 6),
    ]


def build_evidence_registry(
    packs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Flatten EvidencePacks into key -> prompt-ready evidence item."""
    registry: dict[str, dict[str, Any]] = {}
    for pack in packs:
        if not isinstance(pack, dict) or pack.get("insufficient_evidence"):
            continue
        execution_id = pack.get("execution_id", "EXEC")
        for item in pack.get("evidence") or []:
            key = f"{execution_id}/{item.get('evidence_id', '')}"
            annotations = item.get("derived_annotations") or {}
            quote = item.get("original_source_text") or ""
            registry[key] = {
                "key": key,
                "document_id": item.get("document_id", ""),
                "filename": annotations.get("filename") or item.get("document_id", ""),
                "page": item.get("page"),
                "clause_label": item.get("clause_label") or "",
                "why_included": item.get("why_included", ""),
                "quote": quote[:MAX_QUOTE_CHARS],
                "full_quote": quote,
                "score": item.get("score"),
            }
    return registry


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the JSON object from a model response (fences and reasoning tags tolerated)."""
    if not text:
        raise ValueError("Model response is empty.")
    # Strip DeepSeek-R1 reasoning tags
    if "<think>" in text and "</think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    elif "<think>" in text:
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    try:
        parsed = json.loads(stripped)
    except ValueError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model response is not a JSON object.")
    return parsed


class DocumentIntelligenceAgent(BaseAgent):
    agent_id = "document_intelligence"

    def __init__(self, gateway: Gateway, rag: RagRetriever) -> None:
        self.gateway = gateway
        self.rag = rag

    async def execute(
        self, context: AgentContext, inputs: dict[str, Any]
    ) -> AgentResult:
        objective = (
            inputs.get("objective")
            or context.objective
            or "Analyse the case documents and produce structured case intelligence."
        )
        document_ids = inputs.get("document_ids")

        async def _fetch(q: str, k: int) -> dict[str, Any]:
            try:
                return await self.rag.retrieve(
                    organization_id=context.organization_id,
                    case_id=context.case_id,
                    query=q,
                    top_k=k,
                    token_budget=3000,
                    document_ids=document_ids,
                )
            except Exception as e:
                logger.warning("RAG retrieve query failed for '%s': %s", q, e)
                return {}

        packs = await asyncio.gather(
            *[_fetch(query, top_k) for query, top_k in retrieval_queries(str(objective))]
        )
        registry = build_evidence_registry(packs)

        metadata: dict[str, Any] = {
            "prompt_version": PROMPT_VERSION,
            "evidence_pack_executions": [
                p.get("execution_id") for p in packs if isinstance(p, dict)
            ],
            "evidence_items_available": len(registry),
        }

        if not registry:
            empty = CaseIntelligence(
                missing_information=[
                    "No verified evidence could be retrieved for this case."
                ]
            )
            return AgentResult(
                execution_id=context.execution_id,
                task_id=context.task_id,
                case_id=context.case_id,
                agent_id=self.agent_id,
                status="insufficient_evidence",
                output_data={"case_intelligence": empty.model_dump(), "evidence_items": []},
                uncertainty=["No retrievable evidence for the requested analysis."],
                validation_status="passed",
                execution_metadata=metadata,
            )

        intelligence, issues, model_id = await self._generate_validated(
            context, str(objective), registry
        )
        metadata["model"] = model_id
        used_items = [
            registry[key]
            for key in intelligence.evidence_references
            if key in registry
        ]
        return AgentResult(
            execution_id=context.execution_id,
            task_id=context.task_id,
            case_id=context.case_id,
            agent_id=self.agent_id,
            status="partial" if issues else "completed",
            output_data={
                "case_intelligence": intelligence.model_dump(),
                "evidence_items": used_items,
            },
            evidence_references=list(intelligence.evidence_references),
            uncertainty=list(intelligence.missing_information),
            validation_status="failed" if issues else "passed",
            execution_metadata={**metadata, "validation_issues": issues},
        )

    async def _generate_validated(
        self,
        context: AgentContext,
        objective: str,
        registry: dict[str, dict[str, Any]],
    ) -> tuple[CaseIntelligence, list[str], str]:
        """Generate Case Intelligence with one corrective retry.

        The model may only cite evidence keys present in the registry. Parse
        or reference failures are retried once with the error fed back; any
        remaining invalid references are stripped deterministically.
        """
        valid_keys = set(registry)
        # Select top 15 highest-scoring evidence items to ensure prompt stays well within limits
        prompt_items = sorted(
            list(registry.values()),
            key=lambda x: x.get("score") or 0.0,
            reverse=True,
        )[:15]
        feedback = ""
        last_error = ""
        for _attempt in range(2):
            user_prompt = build_user_prompt(objective=objective, evidence_items=prompt_items)
            if feedback:
                user_prompt += f"\n\nYour previous response was invalid: {feedback}"

            # Safely clamp max_output_tokens so (input + output) stays within 7600 (under 8192)
            total_chars = len(SYSTEM_PROMPT) + len(user_prompt)
            estimated_input_tokens = total_chars // 3.8
            safe_max_output = max(512, min(3000, int(7600 - estimated_input_tokens)))

            result = await self.gateway.generate(
                GenerationRequest(
                    role=ModelRole.DOCUMENT_INTELLIGENCE,
                    messages=[
                        ChatMessage(role="system", content=SYSTEM_PROMPT),
                        ChatMessage(role="user", content=user_prompt),
                    ],
                    max_output_tokens=safe_max_output,
                    routing_affinity_key=context.case_id,
                )
            )
            try:
                payload = extract_json_object(result.text)
                intelligence = CaseIntelligence.model_validate(payload)
            except ValueError as exc:
                last_error = f"Unparseable structured output: {exc}"
                feedback = last_error
                continue
            intelligence, issues = validate_intelligence(intelligence, valid_keys)
            # Return immediately on successful JSON validation; unsubstantiated refs are cleanly stripped
            return intelligence, issues, result.model
        logger.warning("document_intelligence_validation_retry_exhausted: %s", last_error)
        empty = CaseIntelligence(missing_information=[last_error or "Analysis output failed to parse"])
        return empty, [last_error], "failed"
