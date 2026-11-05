from typing import Dict, Any
from cicero.rag.ports import Parser

class ModalParserAdapter(Parser):
    async def parse_document(self, file_bytes: bytes, filename: str) -> Dict[str, Any]:
        import modal
        cls = modal.Cls.from_name("cicero-rag-worker", "DoclingParserService")
        return await cls().parse.remote.aio(file_bytes, filename)
