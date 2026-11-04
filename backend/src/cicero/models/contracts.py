from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelRole(StrEnum):
    INTERPRETER = "interpreter"
    ORCHESTRATOR = "orchestrator"
    DOCUMENT_INTELLIGENCE = "document_intelligence"
    LEGAL_RESEARCHER = "legal_researcher"
    ARGUMENT = "argument"
    COUNTERARGUMENT = "counterargument"
    EVALUATOR = "evaluator"


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "developer", "user", "assistant"]
    content: str = Field(min_length=1)


class TokenUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelRole
    messages: list[ChatMessage] = Field(min_length=1)
    max_output_tokens: int = Field(default=2048, ge=16, le=131072)
    temperature: float | None = Field(default=None, ge=0, le=2)
    routing_affinity_key: str | None = Field(default=None, min_length=1, max_length=128)


class GenerationResult(BaseModel):
    text: str
    role: ModelRole
    provider: str
    model: str
    usage: TokenUsage
    finish_reason: str | None = None
    provider_request_id: str | None = None
    duration_ms: int
