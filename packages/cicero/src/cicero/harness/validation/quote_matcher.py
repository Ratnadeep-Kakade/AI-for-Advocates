import re
from typing import Tuple

class QuoteMatcher:
    @staticmethod
    def verify_quote(quote: str, source_text: str, tolerance: float = 0.95) -> Tuple[bool, float]:
        clean_quote = re.sub(r'\s+', ' ', quote.strip().lower())
        clean_source = re.sub(r'\s+', ' ', source_text.strip().lower())
        
        if clean_quote in clean_source:
            return True, 1.0
            
        # Basic character overlap ratio
        matches = sum(1 for c in clean_quote if c in clean_source)
        ratio = matches / max(len(clean_quote), 1)
        return ratio >= tolerance, ratio
