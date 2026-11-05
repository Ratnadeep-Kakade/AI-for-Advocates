"""Structured output contract for the Argument Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Proposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposition: str
    reasoning: str
    evidence_ids: list[str] = Field(default_factory=list)
    authority_ids: list[str] = Field(default_factory=list)
    strength: Literal["strong", "moderate", "weak"] = "moderate"


class ArgumentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position: str = ""
    summary: str = ""
    propositions: list[Proposition] = Field(default_factory=list)
    vulnerabilities: list[str] = Field(default_factory=list)
    unresolved_issues: list[str] = Field(default_factory=list)
    evidence_references: list[str] = Field(default_factory=list)


def validate_argument_output(
    output: ArgumentOutput,
    valid_evidence_ids: set[str],
    valid_authority_ids: set[str],
) -> tuple[ArgumentOutput, list[str]]:
    """Strip evidence/authority references that do not resolve."""
    issues: list[str] = []
    surviving: set[str] = set()
    for prop in output.propositions:
        kept_e = [e for e in prop.evidence_ids if e in valid_evidence_ids]
        dropped_e = [e for e in prop.evidence_ids if e not in valid_evidence_ids]
        if dropped_e:
            issues.append(
                f"Proposition cited unknown evidence: {sorted(dropped_e)}"
            )
        prop.evidence_ids = kept_e
        kept_a = [a for a in prop.authority_ids if a in valid_authority_ids]
        dropped_a = [a for a in prop.authority_ids if a not in valid_authority_ids]
        if dropped_a:
            issues.append(
                f"Proposition cited unknown authorities: {sorted(dropped_a)}"
            )
        prop.authority_ids = kept_a
        surviving.update(kept_e)
    declared = [r for r in output.evidence_references if r in valid_evidence_ids]
    unknown = [r for r in output.evidence_references if r not in valid_evidence_ids]
    if unknown:
        issues.append(f"Output cited unknown evidence: {sorted(unknown)}")
    output.evidence_references = sorted(surviving | set(declared))
    return output, issues
