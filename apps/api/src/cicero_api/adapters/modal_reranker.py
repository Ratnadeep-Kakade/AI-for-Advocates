from typing import List, Dict, Any
from cicero.rag.ports import Reranker

class ModalRerankerAdapter(Reranker):
    async def rerank(self, query: str, candidates: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        import modal
        cls = modal.Cls.from_name("cicero-rag-worker", "RerankerService")
        return await cls().rerank.remote.aio(query, candidates, top_k)
