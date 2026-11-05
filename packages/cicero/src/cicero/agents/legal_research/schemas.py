"""Structured output contract for the Legal Researcher.

Sources come from the Python Gemini Grounding adapter. The model classifies
and reasons over collected sources; it never considers a citation verified
merely because search returned it — verification_status is set by Python.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthorityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    kind: Literal["statute", "regulation", "judgment", "principle", "other"]
    stance: Literal["favourable", "adverse", "conflicting", "neutral"]
    proposition: str
    source_ids: list[str] = Field(default_factory=list)


class ResearchFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = ""
    authorities: list[AuthorityInfo] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


def validate_findings(
    findings: ResearchFindings, available_source_ids: set[str]
) -> tuple[ResearchFindings, list[str]]:
    """Strip source references that were never collected by the adapter."""
    issues: list[str] = []
    for authority in findings.authorities:
        kept = [s for s in authority.source_ids if s in available_source_ids]
        dropped = [s for s in authority.source_ids if s not in available_source_ids]
        if dropped:
            issues.append(
                f"Authority '{authority.title}' cited unknown sources: {sorted(dropped)}"
            )
        authority.source_ids = kept
    declared = [s for s in findings.source_ids if s in available_source_ids]
    unknown = [s for s in findings.source_ids if s not in available_source_ids]
    if unknown:
        issues.append(f"Findings cited unknown sources: {sorted(unknown)}")
    used = {s for a in findings.authorities for s in a.source_ids}
    findings.source_ids = sorted(set(declared) | used)
    return findings, issues
