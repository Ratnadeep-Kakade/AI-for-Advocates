import asyncio
import logging
import random
from collections.abc import Sequence
from time import monotonic
from typing import Any

import httpx
from pydantic import SecretStr

from cicero.models.contracts import ChatMessage, TokenUsage
from cicero.models.errors import ModelConfigurationError, ModelProviderError

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """Small async adapter for providers exposing OpenAI-compatible Chat Completions."""

    name = "openai_compatible"

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str | None,
        api_key: SecretStr | None,
        timeout_seconds: float = 90.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        token_limit_parameter: str = "max_tokens",
    ) -> None:
        self.name = provider_name
        self.base_url = base_url.rstrip("/") if base_url else None
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.transport = transport
        if token_limit_parameter not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("Unsupported token limit parameter.")
        self.token_limit_parameter = token_limit_parameter

    async def generate(
        self,
        *,
        model: str,
        messages: Sequence[ChatMessage],
        max_output_tokens: int,
        temperature: float | None = None,
        routing_affinity_key: str | None = None,
    ) -> "ProviderResult":
        if not self.base_url:
            raise ModelConfigurationError(
                f"{self.name} base URL is not configured."
            )
        if not self.api_key:
            raise ModelConfigurationError(
                f"Credentials for provider '{self.name}' are not configured."
            )
        if not model.strip():
            raise ModelConfigurationError(
                f"Model identifier for provider '{self.name}' is empty."
            )

        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.model_dump() for message in messages],
            self.token_limit_parameter: max_output_tokens,
        }
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            "Content-Type": "application/json",
        }
        if routing_affinity_key:
            headers["Modal-Routing-Affinity-Key"] = routing_affinity_key

        endpoint = f"{self.base_url}/chat/completions"
        attempt = 0

        while True:
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = await client.post(endpoint, headers=headers, json=payload)
                if response.is_error:
                    raise self._normalise_http_error(response)
                return self._parse_response(response.json())
            except ModelProviderError as exc:
                if not exc.retryable or attempt >= self.max_retries:
                    raise
            except httpx.TimeoutException as exc:
                if attempt >= self.max_retries:
                    raise ModelProviderError(
                        "The model provider request timed out.",
                        provider=self.name,
                        code="timeout",
                        retryable=True,
                    ) from exc
            except httpx.RequestError as exc:
                if attempt >= self.max_retries:
                    raise ModelProviderError(
                        "Could not connect to the model provider.",
                        provider=self.name,
                        code="connection_error",
                        retryable=True,
                    ) from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise ModelProviderError(
                    "The model provider returned an invalid response.",
                    provider=self.name,
                    code="invalid_response",
                    retryable=False,
                ) from exc

            delay = min(0.5 * (2**attempt) + random.uniform(0, 0.25), 8.0)
            attempt += 1
            await asyncio.sleep(delay)

    def _normalise_http_error(self, response: httpx.Response) -> ModelProviderError:
        status = response.status_code
        if status == 401 or status == 403:
            code = "authentication_error"
            message = f"{self.name} rejected the configured credentials."
            retryable = False
        elif status == 429:
            code = "rate_limited"
            message = f"{self.name} rate limit reached."
            retryable = True
        elif status >= 500:
            code = "provider_server_error"
            message = f"{self.name} returned a server error."
            retryable = True
        elif status == 400:
            code = "invalid_request"
            message = f"{self.name} rejected the request. Check model ID and request parameters."
            retryable = False
        else:
            code = "provider_http_error"
            message = f"{self.name} returned HTTP {status}."
            retryable = False

        # Deliberately do not log or expose provider response bodies: they may echo
        # confidential request details.
        return ModelProviderError(
            message,
            provider=self.name,
            code=code,
            retryable=retryable,
            status_code=status,
        )

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> "ProviderResult":
        choices = payload["choices"]
        if not choices:
            raise ValueError("Provider returned no choices.")

        choice = choices[0]
        message = choice["message"]
        content = message.get("content")
        if isinstance(content, list):
            text_parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            ]
            content = "".join(text_parts)
        if not isinstance(content, str):
            raise ValueError("Provider response did not contain text content.")

        raw_usage = payload.get("usage") or {}
        completion_details = raw_usage.get("completion_tokens_details") or {}
        usage = TokenUsage(
            input_tokens=raw_usage.get("prompt_tokens"),
            output_tokens=raw_usage.get("completion_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            reasoning_tokens=completion_details.get("reasoning_tokens"),
        )
        return ProviderResult(
            text=content,
            usage=usage,
            finish_reason=choice.get("finish_reason"),
            request_id=payload.get("id"),
        )


class ProviderResult:
    def __init__(
        self,
        *,
        text: str,
        usage: TokenUsage,
        finish_reason: str | None,
        request_id: str | None,
    ) -> None:
        self.text = text
        self.usage = usage
        self.finish_reason = finish_reason
        self.request_id = request_id
