"""Deterministic citation and quotation verification (no LLM involved).

Used by the harness/Evaluator: given the claims an agent made and the source
texts available, decide mechanically whether each cited quote actually appears
in the cited source and whether each evidence reference exists.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    """Canonicalise text for exact-ish quote comparison."""
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("“", '"').replace("”", '"')
    normalized = normalized.replace("‘", "'").replace("’", "'")
    normalized = normalized.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", normalized).strip().lower()


def quote_matches_source(quote: str, source_text: str) -> bool:
    """True when the (normalised) quote appears verbatim in the source text."""
    if not quote:
        return False
    return normalize_text(quote) in normalize_text(source_text)


def verify_quote_references(
    references: list[dict],
    sources_by_id: dict[str, str],
) -> list[dict]:
    """Verify [{source_id, quote}] references against source texts.

    Returns per-reference verdicts: verified / quote_mismatch / unknown_source.
    """
    verdicts: list[dict] = []
    for ref in references:
        source_id = ref.get("source_id", "")
        quote = ref.get("quote", "")
        source_text = sources_by_id.get(source_id)
        if source_text is None:
            verdicts.append(
                {"source_id": source_id, "status": "unknown_source", "quote": quote}
            )
        elif quote_matches_source(quote, source_text):
            verdicts.append(
                {"source_id": source_id, "status": "verified", "quote": quote}
            )
        else:
            verdicts.append(
                {"source_id": source_id, "status": "quote_mismatch", "quote": quote}
            )
    return verdicts


def check_reference_existence(
    referenced_ids: list[str], available_ids: set[str]
) -> dict[str, list[str]]:
    """Split evidence references into existing and unknown (hallucinated)."""
    existing = [ref for ref in referenced_ids if ref in available_ids]
    unknown = [ref for ref in referenced_ids if ref not in available_ids]
    return {"existing": existing, "unknown": unknown}
