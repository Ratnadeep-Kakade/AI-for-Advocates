# Cicero: Enterprise Multi-Agent Legal Intelligence Platform

Cicero is a modern, production-grade legal research and deliberation platform inspired by Anthropic's multi-agent architectures and Claude Skills.

## Repository Layout
- `apps/web`: Vite + React + Tailwind frontend.
- `apps/api`: Thin FastAPI layer and Modal CPU container.
- `apps/ml-worker`: Stateless Modal GPU worker (Docling, BGE-M3, BGE-Reranker).
- `packages/cicero`: Core pure Python engine (zero Torch, zero FastAPI).
- `config/`: Central declarative configurations (models, permissions, workflows).
- `evals/`: Synthetic legal benchmarks and retrieval evaluations.
