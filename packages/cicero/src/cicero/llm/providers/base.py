from collections.abc import Sequence
from typing import Protocol

from cicero.llm.contracts import ChatMessage, TokenUsage


class ProviderGeneration(Protocol):
    text: str
    usage: TokenUsage
    finish_reason: str | None
    request_id: str | None


class ModelProvider(Protocol):
    name: str

    async def generate(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        max_output_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        routing_affinity_key: str | None = None,
    ) -> ProviderGeneration: ...
