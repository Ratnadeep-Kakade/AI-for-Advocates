# ADR 0002: Provider-independent model gateway

- Status: Accepted
- Date: 2026-11-02

## Context

Cicero needs Muse Spark for the Request Interpreter and Orchestrator, plus a shared specialist model. The specialist model is now assumed to be a quantized Llama 70B checkpoint served by vLLM on a Modal A100-80GB GPU. The model gateway must not couple agent code to a model vendor or deployment topology.

## Decision

- Keep a provider-neutral `ModelProvider` contract.
- Keep the CPU FastAPI backend separate from the GPU inference service.
- Serve the Llama checkpoint through vLLM's OpenAI-compatible Chat Completions API.
- Add a `vllm_modal` provider adapter.
- Keep the Meta adapter for Muse Spark.
- Add a generic OpenAI-compatible adapter for compatible future services.
- Resolve provider and model separately for each logical role: interpreter, orchestrator, document intelligence, legal researcher, argument, counterargument and evaluator.
- Default all five specialist roles to the same `vllm_modal` model ID, `llama-70b`.
- Do not automatically fail over to a different model.

## GPU constraint

One A100-80GB is not a safe target for an unquantized 70B BF16/FP16 checkpoint. The initial single-GPU configuration therefore requires a compatible 4-bit AWQ checkpoint and conservative context/concurrency settings. If this does not fit or provide adequate KV-cache headroom for the selected checkpoint, move to two GPUs or a smaller model/shorter context rather than hiding CPU offload or OOM behaviour behind the gateway.

## Consequences

- Switching among registered providers/models is configuration-only.
- A new non-OpenAI-compatible provider requires a new adapter, not changes to agents.
- GPU cold starts and vLLM model loading are separate from FastAPI startup.
- Model-specific features such as structured output and tool calling must later be represented as provider capabilities, not assumed universally.
