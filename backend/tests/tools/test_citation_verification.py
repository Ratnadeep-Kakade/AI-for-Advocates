from cicero.tools.citation_verification import (
    check_reference_existence,
    normalize_text,
    quote_matches_source,
    verify_quote_references,
)


def test_normalize_text_canonicalises() -> None:
    assert normalize_text("  The  “Period” — Six\nYears ") == 'the "period" - six years'


def test_quote_matches_with_typographic_differences() -> None:
    source = "The court held that “the period is six years” for such claims."
    assert quote_matches_source("the period is six years", source)
    assert quote_matches_source("“the period is six years”", source)
    assert not quote_matches_source("the period is ten years", source)


def test_verify_quote_references_statuses() -> None:
    verdicts = verify_quote_references(
        [
            {"source_id": "A", "quote": "six years"},
            {"source_id": "A", "quote": "ten years"},
            {"source_id": "MISSING", "quote": "six years"},
        ],
        {"A": "The limitation period is six years."},
    )
    assert [v["status"] for v in verdicts] == [
        "verified",
        "quote_mismatch",
        "unknown_source",
    ]


def test_check_reference_existence() -> None:
    result = check_reference_existence(["E1", "E2", "E3"], {"E1", "E3"})
    assert result == {"existing": ["E1", "E3"], "unknown": ["E2"]}
