from cicero.rag.argon.schemas import extract_legal_identifiers


def test_nested_clause_identifier_is_preserved() -> None:
    identifiers = extract_legal_identifiers("The exception in Section 4.2(b)(ii) applies.")
    assert "4.2(b)(ii)" in identifiers
    assert "section 4.2(b)(ii)" in identifiers


def test_roman_article_has_arabic_alias() -> None:
    identifiers = extract_legal_identifiers("See Article IV for definitions.")
    assert "article iv" in identifiers
    assert "article 4" in identifiers
