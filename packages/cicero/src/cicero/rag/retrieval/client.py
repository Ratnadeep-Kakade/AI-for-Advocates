from __future__ import annotations

import httpx

from cicero.config import Settings


class RagServiceUnavailable(RuntimeError):
    """Raised when the Cloud Run RAG service cannot complete a request."""


class RagClient:
    """Authenticated Modal-to-Cloud-Run client for future Cicero agents."""

    def __init__(self, settings: Settings) -> None:
        if not settings.rag_worker_url or not settings.rag_service_token:
            raise RagServiceUnavailable("RAG worker URL/token are not configured")
        self.base_url = settings.rag_worker_url.rstrip("/")
        self.token = settings.rag_service_token.get_secret_value()

    async def retrieve(
        self,
        *,
        organization_id: str,
        case_id: str,
        query: str,
        top_k: int = 8,
        token_budget: int | None = None,
        document_ids: list[str] | None = None,
        ablation: dict | None = None,
    ) -> dict:
        body: dict = {
            "organization_id": organization_id,
            "case_id": case_id,
            "query": query,
            "top_k": top_k,
        }
        if token_budget is not None:
            body["token_budget"] = token_budget
        if document_ids:
            body["document_ids"] = document_ids
        if ablation:
            body["ablation"] = ablation
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                response = await client.post(
                    f"{self.base_url}/retrieve",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=body,
                )
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RagServiceUnavailable("Cloud Run RAG retrieval request failed") from exc
