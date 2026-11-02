# ADR 0001: FastAPI backend deployed on Modal

- Status: Accepted
- Scope: Milestone 1 only

## Context

Cicero's agreed architecture uses Python + FastAPI for the backend and Modal for
hosting. The frontend will be deployed separately. This milestone only needs a
small public HTTP API and a repeatable deployment path.

## Decision

- Use FastAPI with an application factory.
- Expose the full ASGI application through Modal's `modal.asgi_app`.
- Keep the API package independent of Modal so it can run locally and in tests.
- Use a CPU-oriented Modal image; no GPU is required for the API foundation.
- Keep configuration environment-based and do not include credentials.

## Consequences

- Local tests do not require Modal credentials.
- Modal deployment requires a configured Modal account.
- The `/health` endpoint is liveness-only until external dependencies are added.
- Authentication, database connectivity, GCS, model providers, and orchestration
  are intentionally deferred to later milestones.

## References

- https://modal.com/docs/sdk/py/latest/asgi_app
- https://modal.com/docs/sdk/py/latest/Image
- https://modal.com/docs/examples/streaming
