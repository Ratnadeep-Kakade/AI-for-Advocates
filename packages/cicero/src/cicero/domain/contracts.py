from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class EvidenceRef(BaseModel):
    id: str
    document_id: str
    chunk_id: Optional[str] = None
    title: str
    citation: Optional[str] = None
    exact_quote: Optional[str] = None
    page_number: Optional[int] = None
    relevance_score: Optional[float] = None
    verified: bool = False

class TaskSpec(BaseModel):
    id: str
    agent_id: str
    description: str
    depends_on: List[str] = Field(default_factory=list)
    input_data: Dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = 300
    retries: int = 2

class ExecutionPlan(BaseModel):
    execution_id: str
    case_id: str
    user_prompt: str
    tasks: List[TaskSpec] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class AgentResult(BaseModel):
    task_id: str
    agent_id: str
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[EvidenceRef] = Field(default_factory=list)
    turns_used: int = 1
    tokens_consumed: int = 0
    error_message: Optional[str] = None
