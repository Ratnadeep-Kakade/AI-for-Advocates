# ADR 0001: FastAPI backend hosted on Modal

- Status: Accepted
- Decision: Use Python + FastAPI for the backend and deploy it on Modal.
- Context: Cicero requires a modular API backend that coordinates model providers,
  retrieval, tools, and persisted workflows.
- Consequences: The frontend is deployed separately. Modal hosts the API and execution
  harness. External model APIs are called through a provider-independent gateway.
