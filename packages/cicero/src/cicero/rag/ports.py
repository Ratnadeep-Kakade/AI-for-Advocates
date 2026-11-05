from typing import List, Dict, Any, Protocol, runtime_checkable

@runtime_checkable
class Embedder(Protocol):
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        ...

@runtime_checkable
class Reranker(Protocol):
    async def rerank(self, query: str, candidates: List[str], top_k: int = 5) -> List[Dict[str, Any]]:
        ...

@runtime_checkable
class Parser(Protocol):
    async def parse_document(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        ...
