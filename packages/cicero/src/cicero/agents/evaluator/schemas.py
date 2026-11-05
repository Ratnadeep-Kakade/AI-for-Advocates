"""Structured output contract for the Evaluator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    side: Literal["argument", "counterargument"]
    factual_support: Literal["strong", "moderate", "weak", "unsupported"]
    authority_support: Literal["strong", "moderate", "weak", "unsupported"]
    notes: str = ""


class EvaluationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_assessment: str = ""
    stronger_side: Literal["argument", "counterargument", "balanced"] = "balanced"
    claim_assessments: list[ClaimAssessment] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    contradictions_found: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommendation: str = ""
