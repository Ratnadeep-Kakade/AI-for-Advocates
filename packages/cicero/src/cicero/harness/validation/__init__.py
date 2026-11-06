from typing import Any, Dict, List, Optional
from cicero.domain.contracts import EvidenceRef
from cicero.domain.verification import ValidationFailure, VerificationReport
from .citation_exists import CitationValidator
from .evidence_resolver import EvidenceResolver
from .quote_matcher import QuoteMatcher


def run_deterministic_validation(
    agent_id: str,
    task_id: str,
    evidence: List[EvidenceRef],
    source_texts: Optional[Dict[str, str]] = None,
) -> VerificationReport:
    """Runs deterministic Tier 1 Python validation checks and produces a VerificationReport."""
    failures: List[ValidationFailure] = []
    quotes_checked = 0
    quotes_verified = 0
    citations_checked = 0
    citations_verified = 0

    sources = source_texts or {}

    for ref in evidence:
        if ref.citation:
            citations_checked += 1
            valid, msg = CitationValidator.validate_citation_format(ref.citation)
            if valid:
                citations_verified += 1
            else:
                failures.append(ValidationFailure(rule="citation_exists", target=ref.citation, message=msg))

        if ref.exact_quote:
            quotes_checked += 1
            src = sources.get(ref.document_id, "")
            if src:
                matched, ratio = QuoteMatcher.verify_quote(ref.exact_quote, src)
                if matched:
                    quotes_verified += 1
                else:
                    failures.append(ValidationFailure(rule="quote_match", target=ref.id, message=f"Quote mismatch (overlap {ratio:.2f})"))
            else:
                quotes_verified += 1

    valid_refs, ref_errors = EvidenceResolver.resolve_references(evidence)
    for err in ref_errors:
        failures.append(ValidationFailure(rule="evidence_resolver", target=task_id, message=err))

    all_passed = len(failures) == 0
    return VerificationReport(
        task_id=task_id,
        agent_id=agent_id,
        all_passed=all_passed,
        failures=failures,
        quotes_checked=quotes_checked,
        quotes_verified=quotes_verified,
        citations_checked=citations_checked,
        citations_verified=citations_verified,
        evidence_refs_resolved=len(evidence) if valid_refs else 0,
    )


__all__ = [
    "QuoteMatcher",
    "CitationValidator",
    "EvidenceResolver",
    "run_deterministic_validation",
]
