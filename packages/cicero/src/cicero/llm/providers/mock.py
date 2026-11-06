from collections.abc import Sequence
from uuid import uuid4

from cicero.llm.contracts import ChatMessage, TokenUsage


class MockGeneration:
    def __init__(self, *, text: str, request_id: str) -> None:
        self.text = text
        self.usage = TokenUsage(input_tokens=0, output_tokens=0, total_tokens=0)
        self.finish_reason = "stop"
        self.request_id = request_id


class MockModelProvider:
    """Deterministic, zero-cost provider for integration development and tests.

    This provider does not perform reasoning and must not be used for legal work.
    """

    name = "mock"

    async def generate(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        max_output_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        routing_affinity_key: str | None = None,
    ) -> MockGeneration:
        del max_output_tokens, temperature, reasoning_effort, routing_affinity_key
        last_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "No user message supplied.",
        )
        return MockGeneration(
            text=f"[MOCK:{model}] Gateway connectivity confirmed. Input: {last_user_message[:240]}",
            request_id=f"mock-{uuid4().hex[:12]}",
        )
