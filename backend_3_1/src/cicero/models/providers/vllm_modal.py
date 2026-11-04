import httpx
from pydantic import SecretStr

from cicero.models.providers.openai_compatible import OpenAICompatibleProvider


class VLLMModalProvider(OpenAICompatibleProvider):
    """Adapter for Cicero's self-hosted vLLM OpenAI-compatible API on Modal."""

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
