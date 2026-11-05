from typing import List, Tuple
from cicero.domain.contracts import EvidenceRef

class EvidenceResolver:
    @staticmethod
    def resolve_references(refs: List[EvidenceRef]) -> Tuple[bool, List[str]]:
        missing = []
        for ref in refs:
            if not ref.document_id:
                missing.append(f"EvidenceRef '{ref.id}' is missing document_id")
        return len(missing) == 0, missing
