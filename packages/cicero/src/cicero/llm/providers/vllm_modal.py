import asyncio
import logging
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from cicero.models.contracts import ChatMessage
from cicero.models.errors import ModelProviderError
from .base import ProviderGeneration
from .openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class VLLMModalProvider(OpenAICompatibleProvider):
    """Adapter for Cicero's self-hosted vLLM OpenAI-compatible API on Modal.

    Includes extended retry resilience for Modal container warmup
    (503 'no upstreams available' during cold-starts or redeployments).
    """

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        base_url: str | None,
        timeout_seconds: float = 300.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            provider_name="vllm_modal",
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
        )

    async def generate(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        max_output_tokens: int,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        routing_affinity_key: str | None = None,
    ) -> ProviderGeneration:
        attempt = 0
        max_warmup_retries = 15

        while True:
            try:
                return await super().generate(
                    model=model,
                    messages=messages,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    routing_affinity_key=routing_affinity_key,
                )
            except ModelProviderError as exc:
                is_transient = (
                    exc.retryable
                    or exc.code in {"provider_server_error", "connection_error", "timeout"}
                    or (getattr(exc, "status_code", None) in {502, 503, 504})
                )
                if is_transient and attempt < max_warmup_retries:
                    attempt += 1
                    logger.info(
                        "Modal vLLM 503 / warmup waiting: attempt %d/%d, retrying in 3.0s...",
                        attempt,
                        max_warmup_retries,
                    )
                    await asyncio.sleep(3.0)
                    continue
                raise
