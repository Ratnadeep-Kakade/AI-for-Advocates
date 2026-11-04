"""Structured output contract for the Counterargument Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Challenge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: str
    challenge: str
    evidence_ids: list[str] = Field(default_factory=list)
    authority_ids: list[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high"] = "medium"


class CounterargumentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opposing_position: str = ""
    summary: str = ""
    challenges: list[Challenge] = Field(default_factory=list)
    alternative_interpretations: list[str] = Field(default_factory=list)
    procedural_weaknesses: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    unsupported_assumptions: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)


def validate_counterargument_output(
    output: CounterargumentOutput,
    valid_evidence_ids: set[str],
    valid_authority_ids: set[str],
) -> tuple[CounterargumentOutput, list[str]]:
    """Strip evidence/authority references that do not resolve."""
    issues: list[str] = []
    surviving: set[str] = set()
    for challenge in output.challenges:
        kept_e = [e for e in challenge.evidence_ids if e in valid_evidence_ids]
        dropped_e = [e for e in challenge.evidence_ids if e not in valid_evidence_ids]
        if dropped_e:
            issues.append(f"Challenge cited unknown evidence: {sorted(dropped_e)}")
        challenge.evidence_ids = kept_e
        kept_a = [a for a in challenge.authority_ids if a in valid_authority_ids]
        dropped_a = [a for a in challenge.authority_ids if a not in valid_authority_ids]
        if dropped_a:
            issues.append(f"Challenge cited unknown authorities: {sorted(dropped_a)}")
        challenge.authority_ids = kept_a
        surviving.update(kept_e)
    declared = [r for r in output.evidence_references if r in valid_evidence_ids]
    unknown = [r for r in output.evidence_references if r not in valid_evidence_ids]
    if unknown:
        issues.append(f"Output cited unknown evidence: {sorted(unknown)}")
    output.evidence_references = sorted(surviving | set(declared))
    return output, issues
