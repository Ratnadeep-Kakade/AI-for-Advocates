import logging
from time import monotonic
from typing import Mapping

from cicero.config import Settings, get_settings
from cicero.models.contracts import GenerationRequest, GenerationResult, ModelRole
from cicero.models.errors import ModelConfigurationError
from cicero.models.providers import (
    MetaModelProvider,
    MockModelProvider,
    ProviderRegistry,
    VLLMModalProvider,
)
from cicero.models.providers.base import ModelProvider
from cicero.models.providers.openai_compatible import OpenAICompatibleProvider

logger = logging.getLogger(__name__)


class ModelGateway:
    """Resolve logical roles and dispatch requests through registered providers."""

    def __init__(
        self,
        *,
        providers: Mapping[str, ModelProvider] | ProviderRegistry,
        role_targets: Mapping[ModelRole, tuple[str, str | None]],
        environment: str = "development",
    ) -> None:
        self.providers = (
            providers if isinstance(providers, ProviderRegistry) else ProviderRegistry(providers)
        )
        self._role_targets = dict(role_targets)
        self._environment = environment
        if environment == "production":
            mock_roles = [
                role.value
                for role, (provider_name, _) in self._role_targets.items()
                if provider_name == "mock"
            ]
            if mock_roles:
                raise ModelConfigurationError(
                    "Mock provider cannot be assigned in production: " + ", ".join(mock_roles)
                )

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "ModelGateway":
        settings = settings or get_settings()
        providers: dict[str, ModelProvider] = {
            "meta": MetaModelProvider(
                api_key=settings.meta_model_api_key,
                base_url=settings.meta_base_url,
                timeout_seconds=settings.model_timeout_seconds,
                max_retries=settings.model_max_retries,
            ),
            "vllm_modal": VLLMModalProvider(
                api_key=settings.vllm_api_key,
                base_url=settings.vllm_base_url,
                timeout_seconds=settings.model_timeout_seconds,
                max_retries=settings.model_max_retries,
            ),
            "openai_compatible": OpenAICompatibleProvider(
                provider_name="openai_compatible",
                api_key=settings.generic_api_key,
                base_url=settings.generic_base_url,
                timeout_seconds=settings.model_timeout_seconds,
                max_retries=settings.model_max_retries,
            ),
            "mock": MockModelProvider(),
        }
        return cls(
            providers=providers,
            role_targets={
                ModelRole.INTERPRETER: (settings.interpreter_provider, settings.interpreter_model),
                ModelRole.ORCHESTRATOR: (settings.orchestrator_provider, settings.orchestrator_model),
                ModelRole.DOCUMENT_INTELLIGENCE: (
                    settings.document_intelligence_provider,
                    settings.document_intelligence_model,
                ),
                ModelRole.LEGAL_RESEARCHER: (
                    settings.legal_researcher_provider,
                    settings.legal_researcher_model,
                ),
                ModelRole.ARGUMENT: (settings.argument_provider, settings.argument_model),
                ModelRole.COUNTERARGUMENT: (
                    settings.counterargument_provider,
                    settings.counterargument_model,
                ),
                ModelRole.EVALUATOR: (settings.evaluator_provider, settings.evaluator_model),
            },
            environment=settings.environment,
        )

    def route_for(self, role: ModelRole) -> tuple[str, str]:
        target = self._role_targets.get(role)
        if target is None:
            raise ModelConfigurationError(f"No model is configured for role '{role.value}'.")
        provider_name, model_id = target
        if not model_id or not model_id.strip():
            raise ModelConfigurationError(f"No model ID is configured for role '{role.value}'.")
        self.providers.get(provider_name)  # Validate provider during route inspection.
        return provider_name, model_id

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        provider_name, model_id = self.route_for(request.role)
        provider = self.providers.get(provider_name)

        started = monotonic()
        response = await provider.generate(
            model=model_id,
            messages=request.messages,
            max_output_tokens=request.max_output_tokens,
            temperature=request.temperature,
            routing_affinity_key=request.routing_affinity_key,
        )
        duration_ms = round((monotonic() - started) * 1000)

        # Never log prompts, completions, or client document content.
        logger.info(
            "model_generation_completed",
            extra={
                "model_role": request.role.value,
                "model_provider": provider_name,
                "model_id": model_id,
                "duration_ms": duration_ms,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.total_tokens,
                "provider_request_id": response.request_id,
            },
        )
        return GenerationResult(
            text=response.text,
            role=request.role,
            provider=provider_name,
            model=model_id,
            usage=response.usage,
            finish_reason=response.finish_reason,
            provider_request_id=response.request_id,
            duration_ms=duration_ms,
        )
