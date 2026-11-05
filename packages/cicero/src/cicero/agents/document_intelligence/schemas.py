"""Structured output contract for the Document Intelligence Agent.

Every factual item carries ``evidence_ids`` referencing keys in the evidence
registry built from verified RAG EvidencePacks (``<execution>/<evidence_id>``).
Python validates those references deterministically after generation; the
model cannot invent a source location.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PartyInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    evidence_ids: list[str] = Field(default_factory=list)


class ObligationInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party: str
    obligation: str
    clause_reference: str
    due_date: str | None = None
    status: Literal["met", "at risk", "breached", "unclear"]
    evidence_ids: list[str] = Field(default_factory=list)


class FactInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: str
    category: str
    evidence_ids: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    event: str
    significance: str
    evidence_ids: list[str] = Field(default_factory=list)


class BreachInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    clause_reference: str
    severity: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(default_factory=list)


class ContradictionInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    clause_references: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class CaseIntelligence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    parties: list[PartyInfo] = Field(default_factory=list)
    facts: list[FactInfo] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    obligations: list[ObligationInfo] = Field(default_factory=list)
    relevant_clauses: list[str] = Field(default_factory=list)
    defined_terms: list[str] = Field(default_factory=list)
    potential_breaches: list[BreachInfo] = Field(default_factory=list)
    contradictions: list[ContradictionInfo] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)


def _strip_refs(item: BaseModel, valid_keys: set[str], issues: list[str]) -> None:
    kept = [ref for ref in item.evidence_ids if ref in valid_keys]
    dropped = [ref for ref in item.evidence_ids if ref not in valid_keys]
    if dropped:
        issues.append(
            f"{type(item).__name__} cited unknown evidence: {sorted(dropped)}"
        )
    item.evidence_ids = kept


def validate_intelligence(
    intelligence: CaseIntelligence, valid_keys: set[str]
) -> tuple[CaseIntelligence, list[str]]:
    """Drop evidence references the model cannot substantiate.

    Returns the cleaned intelligence plus a list of validation issues. Items
    are never dropped themselves — only unsubstantiated references are removed
    so downstream agents can see exactly what survived verification.
    """
    issues: list[str] = []
    for collection in (
        intelligence.parties,
        intelligence.facts,
        intelligence.timeline,
        intelligence.obligations,
        intelligence.potential_breaches,
        intelligence.contradictions,
    ):
        for item in collection:
            _strip_refs(item, valid_keys, issues)
    surviving: set[str] = set()
    for collection in (
        intelligence.parties,
        intelligence.facts,
        intelligence.timeline,
        intelligence.obligations,
        intelligence.potential_breaches,
        intelligence.contradictions,
    ):
        for item in collection:
            surviving.update(item.evidence_ids)
    declared = [ref for ref in intelligence.evidence_references if ref in valid_keys]
    unknown_declared = [
        ref for ref in intelligence.evidence_references if ref not in valid_keys
    ]
    if unknown_declared:
        issues.append(
            f"evidence_references cited unknown evidence: {sorted(unknown_declared)}"
        )
    intelligence.evidence_references = sorted(surviving | set(declared))
    return intelligence, issues
