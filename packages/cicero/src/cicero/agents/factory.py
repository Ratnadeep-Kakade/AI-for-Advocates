"""Agent construction: wires gateway, RAG and search tools into the agents."""

from __future__ import annotations

from cicero.agents.argument.agent import ArgumentAgent
from cicero.agents.base import BaseAgent
from cicero.agents.common import Gateway, RagRetriever
from cicero.agents.counterargument.agent import CounterargumentAgent
from cicero.agents.document_intelligence.agent import DocumentIntelligenceAgent
from cicero.agents.evaluator.agent import EvaluatorAgent
from cicero.agents.legal_research.agent import LegalResearcherAgent
from cicero.core.config import Settings
from cicero.tools.web_search import GeminiGroundingAdapter


def build_agents(
    gateway: Gateway, *, settings: Settings, rag: RagRetriever | None
) -> dict[str, BaseAgent]:
    """Construct the five specialist agents for one execution context."""
    search: GeminiGroundingAdapter | None = None
    if settings.gemini_api_key is not None:
        search = GeminiGroundingAdapter(
            settings.gemini_api_key.get_secret_value(),
            model=settings.gemini_model,
        )
    agents: dict[str, BaseAgent] = {
        "document_intelligence": DocumentIntelligenceAgent(gateway, rag),  # type: ignore[arg-type]
        "legal_researcher": LegalResearcherAgent(gateway, search),
        "argument": ArgumentAgent(gateway, rag),
        "counterargument": CounterargumentAgent(gateway, rag),
        "evaluator": EvaluatorAgent(gateway, rag),
    }
    return agents
