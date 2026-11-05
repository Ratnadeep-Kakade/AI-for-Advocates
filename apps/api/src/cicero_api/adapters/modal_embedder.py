from typing import List
from cicero.rag.ports import Embedder

class ModalEmbedderAdapter(Embedder):
    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        import modal
        cls = modal.Cls.from_name("cicero-rag-worker", "BgeM3Service")
        return await cls().embed.remote.aio(texts)
