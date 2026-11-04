"""Live smoke test for Meta and the self-hosted vLLM endpoint.

Makes two model requests. Use only short synthetic prompts; never test with
confidential client documents.
"""
import asyncio

from cicero.models.contracts import ChatMessage, GenerationRequest, ModelRole
from cicero.models.gateway import ModelGateway


async def main() -> None:
    gateway = ModelGateway.from_settings()
    for role in (ModelRole.INTERPRETER, ModelRole.DOCUMENT_INTELLIGENCE):
        result = await gateway.generate(
            GenerationRequest(
                role=role,
                messages=[
                    ChatMessage(
                        role="developer",
                        content="You are performing a connectivity test. Reply briefly.",
                    ),
                    ChatMessage(role="user", content="Reply with exactly: CICERO READY"),
                ],
                max_output_tokens=64,
            )
        )
        print(
            f"{role.value}: provider={result.provider}, model={result.model}, "
            f"tokens={result.usage.total_tokens}, latency_ms={result.duration_ms}"
        )
        print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
