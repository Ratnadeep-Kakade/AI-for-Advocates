# Cicero Backend — Milestone 1

Minimal backend foundation for Cicero, following `CICERO.txt`.

## Included

- FastAPI application factory
- `GET /` root endpoint
- `GET /health` liveness endpoint
- Environment-backed settings with safe defaults
- Modal ASGI deployment entrypoint
- Pytest tests for the HTTP contract
- One ADR documenting the deployment choice

This milestone deliberately does **not** include model providers, agents, orchestration,
PostgreSQL, GCS, authentication, or RAG.

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- A Modal account for cloud deployment

## Local setup

From this directory:

```bash
uv sync
uv run pytest
uv run uvicorn cicero.api.app:app --reload --app-dir src
```

Then open:

- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

Copy `.env.example` to `.env` if you want to change the local settings.
No secrets are required for this milestone.

## Modal setup and development

Authenticate once:

```bash
uv run modal setup
```

Run a development deployment with hot reload:

```bash
uv run modal serve deploy/modal/api_app.py
```

Modal prints a temporary `https://...-dev.modal.run` URL. Test:

```bash
curl https://YOUR-DEV-URL/health
```

Deploy a persistent Modal app:

```bash
uv run modal deploy deploy/modal/api_app.py
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `CICERO_APP_NAME` | `Cicero API` | API title |
| `CICERO_ENVIRONMENT` | `development` | Runtime environment label |
| `CICERO_LOG_LEVEL` | `INFO` | Logging level |

Do not add API keys or database credentials to `.env.example`, commit them, or bake
them into the Modal image. Later milestones should use Modal Secrets and a proper
secret-management strategy.

## Notes

- `/health` is a liveness endpoint only. It does not claim that PostgreSQL, GCS,
  or model providers are healthy. Those dependencies do not exist in this milestone.
- The API intentionally has no authentication yet. Do not expose client documents
  or sensitive operations until authentication and authorisation are implemented.
- The Modal deployment uses `modal.asgi_app` to expose the full FastAPI application.
- The Modal image installs the backend project dependencies and explicitly adds the
  local `cicero` Python package to the image.
