"""Shared structured-generation plumbing for specialist agents.

Agents ask the Model Gateway for JSON, Python parses and schema-validates it,
and one corrective retry is allowed with the error fed back. Providers stay
interchangeable (Spark, DeepSeek, mock) because structure is harness-managed.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel

from cicero.llm.contracts import ChatMessage, GenerationRequest, ModelRole


class Gateway(Protocol):
    async def generate(self, request: GenerationRequest) -> Any: ...


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


class StructuredOutputError(RuntimeError):
    """Raised when a model cannot produce schema-valid JSON after retry."""


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the JSON object from a model response (fences tolerated)."""
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


async def collect_evidence_items(
    rag: RagRetriever | None,
    *,
    organization_id: str,
    case_id: str,
    inputs: dict[str, Any],
    objective: str,
) -> list[dict[str, Any]]:
    """Resolve the evidence items an agent reasons over.

    Preference order: items supplied by the harness/previous agent, items
    embedded in the case-intelligence payload, then fresh targeted retrieval
    through the RAG tool (when the agent is permitted and equipped for it).
    """
    provided = inputs.get("evidence_items")
    if provided:
        return list(provided)
    intelligence = inputs.get("case_intelligence") or {}
    if intelligence.get("evidence_items"):
        return list(intelligence["evidence_items"])
    if rag is None:
        return []
    # Lazy import: document_intelligence.agent imports agents.common consumers.
    from cicero.agents.document_intelligence.agent import (
        build_evidence_registry,
        retrieval_queries,
    )

    registry: dict[str, dict[str, Any]] = {}
    for query, top_k in retrieval_queries(objective)[:3]:
        pack = await rag.retrieve(
            organization_id=organization_id,
            case_id=case_id,
            query=query,
            top_k=top_k,
            token_budget=6000,
        )
        registry.update(build_evidence_registry([pack]))
    return list(registry.values())


async def generate_structured[SchemaT: BaseModel](
    gateway: Gateway,
    *,
    role: ModelRole,
    system_prompt: str,
    user_prompt: str,
    schema: type[SchemaT],
    max_output_tokens: int = 8192,
    affinity_key: str | None = None,
) -> tuple[SchemaT, dict[str, Any]]:
    """Generate + validate structured output with one corrective retry."""
    feedback = ""
    last_error = ""
    for _attempt in range(2):
        prompt = user_prompt
        if feedback:
            prompt += (
                "\n\nYour previous response was invalid and was rejected: "
                f"{feedback}\nReturn corrected JSON only."
            )
        result = await gateway.generate(
            GenerationRequest(
                role=role,
                messages=[
                    ChatMessage(role="system", content=system_prompt),
                    ChatMessage(role="user", content=prompt),
                ],
                max_output_tokens=max_output_tokens,
                routing_affinity_key=affinity_key,
            )
        )
        try:
            payload = extract_json_object(result.text)
            instance = schema.model_validate(payload)
            return instance, {"model": result.model, "attempts": _attempt + 1}
        except ValueError as exc:
            last_error = str(exc)
            feedback = last_error
    raise StructuredOutputError(
        f"Model for role '{role.value}' failed structured output: {last_error}"
    )
