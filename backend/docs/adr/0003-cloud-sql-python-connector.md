# ADR 0003: Cloud SQL connectivity through the Python Connector

- Status: Accepted
- Scope: Milestone 3.1

## Context

Cicero's PostgreSQL database already exists in Google Cloud SQL. The backend must connect to that database without recreating or altering its existing schemas. The API runs on Modal, while local development runs on the developer's machine.

## Decision

- Use the Cloud SQL Python Connector with its asynchronous `asyncpg` driver.
- Use SQLAlchemy 2.x `AsyncEngine` and `async_sessionmaker` for application pooling and sessions.
- Create the Connector inside FastAPI's running event loop using `create_async_connector()`.
- Use `async_creator` when constructing the SQLAlchemy async engine.
- Use lazy connector refresh for the serverless Modal API process.
- Use ADC for local development.
- Use Modal OIDC tokens with Google Workload Identity Federation to impersonate the dedicated `cicero-backend` service account. Do not create or store a long-lived service-account key.
- Keep Google IAM authorisation to the Cloud SQL instance separate from PostgreSQL username/password authentication.
- Keep database connectivity optional when no database settings are configured, so model-gateway-only local development continues to work.
- Provide a separate database readiness endpoint; `/health` remains a liveness check.
- Do not create, alter, or migrate existing tables in this milestone.

## Consequences

- The API image must install `cloud-sql-python-connector[asyncpg]`, `asyncpg`, `google-auth`, and SQLAlchemy.
- Local developers must authenticate ADC and have the Cloud SQL Client IAM role. Modal uses the federated service account, which also has the Cloud SQL Client role.
- Modal requires a separately managed database Secret containing PostgreSQL connection settings and non-secret WIF identifiers; the Modal OIDC token is injected at runtime.
- Every Modal container owns its own SQLAlchemy pool. Pool size and container concurrency must be tuned against Cloud SQL's connection limit.
- Workload Identity Federation is the selected keyless authentication mechanism for Modal; verify provider attribute conditions and service-account impersonation bindings before deployment.
- Existing schemas will be mapped explicitly in the next milestone; `Base.metadata.create_all()` is not used.
