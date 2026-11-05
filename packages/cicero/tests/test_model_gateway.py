import json

import httpx
import pytest
from pydantic import SecretStr

from cicero.config import Settings
from cicero.models.contracts import ChatMessage, GenerationRequest, ModelRole, TokenUsage
from cicero.models.errors import ModelConfigurationError, ModelProviderError
from cicero.models.gateway import ModelGateway
from cicero.models.providers.meta import MetaModelProvider
from cicero.models.providers.mock import MockModelProvider
from cicero.models.providers.registry import ProviderRegistry
from cicero.models.providers.vllm_modal import VLLMModalProvider


class FakeProvider:
    def __init__(self, name: str = "fake") -> None:
        self.name = name

    async def generate(self, **kwargs):
        class Result:
            text = "ready"
            usage = TokenUsage(input_tokens=3, output_tokens=2, total_tokens=5)
            finish_reason = "stop"
            request_id = "req_test"

        return Result()


@pytest.mark.asyncio
async def test_gateway_routes_interpreter_to_meta() -> None:
    gateway = ModelGateway(
        providers={"meta": FakeProvider("meta")},
        role_targets={ModelRole.INTERPRETER: ("meta", "muse-spark-1.3")},
    )
    result = await gateway.generate(
        GenerationRequest(
            role=ModelRole.INTERPRETER,
            messages=[ChatMessage(role="user", content="Reply ready.")],
        )
    )
    assert result.text == "ready"
    assert result.provider == "meta"
    assert result.model == "muse-spark-1.3"
    assert result.usage.total_tokens == 5


@pytest.mark.asyncio
async def test_mock_provider_allows_zero_cost_specialist_development() -> None:
    gateway = ModelGateway(
        providers={"mock": MockModelProvider()},
        role_targets={
            ModelRole.DOCUMENT_INTELLIGENCE: ("mock", "deepseek-r1-distill-llama-70b")
        },
    )
    result = await gateway.generate(
        GenerationRequest(
            role=ModelRole.DOCUMENT_INTELLIGENCE,
            messages=[ChatMessage(role="user", content="Analyse this sample clause.")],
        )
    )
    assert result.provider == "mock"
    assert "Gateway connectivity confirmed" in result.text
    assert result.usage.total_tokens == 0


@pytest.mark.asyncio
async def test_gateway_can_switch_one_agent_without_changing_other_routes() -> None:
    gateway = ModelGateway(
        providers={"mock": MockModelProvider(), "vllm_modal": FakeProvider("vllm_modal")},
        role_targets={
            ModelRole.ARGUMENT: ("vllm_modal", "deepseek-r1-distill-llama-70b"),
            ModelRole.EVALUATOR: ("mock", "deepseek-r1-distill-llama-70b"),
        },
    )
    argument = await gateway.generate(
        GenerationRequest(
            role=ModelRole.ARGUMENT,
            messages=[ChatMessage(role="user", content="Draft an argument.")],
        )
    )
    evaluator = await gateway.generate(
        GenerationRequest(
            role=ModelRole.EVALUATOR,
            messages=[ChatMessage(role="user", content="Evaluate this argument.")],
        )
    )
    assert argument.provider == "vllm_modal"
    assert evaluator.provider == "mock"


@pytest.mark.asyncio
async def test_gateway_fails_when_model_id_missing() -> None:
    gateway = ModelGateway(
        providers={"mock": MockModelProvider()},
        role_targets={ModelRole.DOCUMENT_INTELLIGENCE: ("mock", None)},
    )
    with pytest.raises(ModelConfigurationError, match="No model ID"):
        await gateway.generate(
            GenerationRequest(
                role=ModelRole.DOCUMENT_INTELLIGENCE,
                messages=[ChatMessage(role="user", content="Test")],
            )
        )


def test_provider_registry_rejects_duplicate_registration() -> None:
    registry = ProviderRegistry({"mock": MockModelProvider()})
    with pytest.raises(ModelConfigurationError, match="already registered"):
        registry.register("mock", MockModelProvider())


def test_mock_provider_is_rejected_in_production() -> None:
    with pytest.raises(ModelConfigurationError, match="cannot be assigned in production"):
        ModelGateway(
            providers={"mock": MockModelProvider()},
            role_targets={ModelRole.EVALUATOR: ("mock", "test-model")},
            environment="production",
        )


@pytest.mark.asyncio
async def test_meta_adapter_uses_documented_completion_token_parameter() -> None:
    payload = {
        "id": "chatcmpl_test",
        "choices": [
            {
                "message": {"role": "assistant", "content": "ready"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 4,
            "total_tokens": 14,
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "muse-spark-1.3"
        assert body["max_completion_tokens"] == 128
        assert "max_tokens" not in body
        return httpx.Response(200, json=payload)

    provider = MetaModelProvider(
        api_key=SecretStr("test-key"),
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    result = await provider.generate(
        model="muse-spark-1.3",
        messages=[ChatMessage(role="user", content="Ping")],
        max_output_tokens=128,
    )
    assert result.text == "ready"
    assert result.usage.reasoning_tokens == 2
    assert result.request_id == "chatcmpl_test"


@pytest.mark.asyncio
async def test_vllm_modal_adapter_uses_api_key_and_affinity_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer cicero-test-api-key"
        assert request.headers["Modal-Routing-Affinity-Key"] == "conversation-1"
        body = json.loads(request.content)
        assert body["max_tokens"] == 64
        return httpx.Response(
            200,
            json={
                "id": "modal_req",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ready"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    provider = VLLMModalProvider(
        api_key=SecretStr("cicero-test-api-key"),
        base_url="https://example.modal.direct/v1",
        transport=httpx.MockTransport(handler),
        max_retries=0,
    )
    result = await provider.generate(
        model="deepseek-r1-distill-llama-70b",
        messages=[ChatMessage(role="user", content="Ping")],
        max_output_tokens=64,
        routing_affinity_key="conversation-1",
    )
    assert result.text == "ready"


@pytest.mark.asyncio
async def test_provider_does_not_retry_bad_request() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"message": "bad request"}})

    provider = MetaModelProvider(
        api_key=SecretStr("test-key"),
        transport=httpx.MockTransport(handler),
        max_retries=2,
    )
    with pytest.raises(ModelProviderError) as error:
        await provider.generate(
            model="muse-spark-1.3",
            messages=[ChatMessage(role="user", content="Ping")],
            max_output_tokens=64,
        )
    assert error.value.code == "invalid_request"
    assert calls == 1


def test_settings_provider_allocation_matches_architecture() -> None:
    # Demo default: every role runs on Muse Spark so the full flow works
    # end-to-end. The four specialists move to DeepSeek/vLLM by env switch
    # (see the next test) once cicero-llama-inference is deployed.
    settings = Settings(_env_file=None)
    assert settings.interpreter_provider == "meta"
    assert settings.orchestrator_provider == "meta"
    assert settings.document_intelligence_provider == "meta"
    assert settings.legal_researcher_provider == "meta"
    assert settings.argument_provider == "meta"
    assert settings.counterargument_provider == "meta"
    assert settings.evaluator_provider == "meta"


def test_settings_allow_provider_switch_through_environment(monkeypatch) -> None:
    monkeypatch.setenv("CICERO_ARGUMENT_PROVIDER", "vllm_modal")
    monkeypatch.setenv("CICERO_ARGUMENT_MODEL", "deepseek-r1-distill-llama-70b")
    settings = Settings(_env_file=None)
    assert settings.argument_provider == "vllm_modal"
    assert settings.argument_model == "deepseek-r1-distill-llama-70b"
