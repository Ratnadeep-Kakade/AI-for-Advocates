from typing import Tuple

class CitationValidator:
    @staticmethod
    def validate_citation_format(citation: str) -> Tuple[bool, str]:
        if not citation or len(citation.strip()) < 4:
            return False, "Citation is empty or too short."
        return True, "Valid"
