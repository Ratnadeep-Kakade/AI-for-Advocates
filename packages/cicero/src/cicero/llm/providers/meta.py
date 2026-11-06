import httpx
from pydantic import SecretStr

from .openai_compatible import OpenAICompatibleProvider


class MetaModelProvider(OpenAICompatibleProvider):
    """Muse Spark adapter using Meta Model API's OpenAI-compatible interface."""

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        base_url: str = "https://api.meta.ai/v1",
        timeout_seconds: float = 90.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            provider_name="meta",
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            transport=transport,
            token_limit_parameter="max_completion_tokens",
        )
