from typing import List, Optional
from pydantic import BaseModel, Field

class ValidationFailure(BaseModel):
    rule: str
    target: str
    message: str
    severity: str = "error"  # error | warning

class VerificationReport(BaseModel):
    task_id: str
    agent_id: str
    all_passed: bool
    failures: List[ValidationFailure] = Field(default_factory=list)
    quotes_checked: int = 0
    quotes_verified: int = 0
    citations_checked: int = 0
    citations_verified: int = 0
    evidence_refs_resolved: int = 0
