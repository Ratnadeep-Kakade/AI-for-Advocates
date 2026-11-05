from cicero.rag.retrieval import QueryRouter

router = QueryRouter()


def test_exact_clause_route_strips_container_word() -> None:
    plan = router.route("Show Section 4.2(b)(ii)", case_id="CASE_1")
    assert plan.query_type == "exact_clause"
    assert plan.target_clause_label == "4.2(b)(ii)"


def test_exact_clause_route_keeps_article_roman() -> None:
    plan = router.route("What is in article IV regarding indemnity?", case_id="CASE_1")
    assert plan.query_type == "exact_clause"
    assert plan.target_clause_label == "ARTICLE IV"


def test_definition_route() -> None:
    plan = router.route("What does Termination Event mean?", case_id="CASE_1")
    assert plan.query_type == "defined_term"
    assert plan.target_defined_term == "Termination Event"


def test_cross_reference_route() -> None:
    plan = router.route("Which clauses are subject to Section 8.2?", case_id="CASE_1")
    assert plan.query_type == "cross_reference"
    assert plan.target_xref_label == "8.2"
    assert plan.target_xref_type == "subject_to"


def test_temporal_route() -> None:
    plan = router.route("What is the effective date of this agreement?", case_id="CASE_1")
    assert plan.query_type == "metadata_temporal"
    assert plan.date_role_filter == "effective"


def test_temporal_quarter_bounds() -> None:
    plan = router.route("Which obligations expire in Q3 2026?", case_id="CASE_1")
    assert plan.query_type == "metadata_temporal"
    assert plan.date_start_iso == "2026-07-01"
    assert plan.date_end_iso == "2026-09-30"


def test_table_route_parses_shareholder_filter() -> None:
    plan = router.route("How many shares does Founder A own?", case_id="CASE_1")
    assert plan.query_type == "table_lookup"
    assert plan.table_query_params is not None
    assert plan.table_query_params["row_filter_val"] == "Founder A"


def test_multi_doc_route() -> None:
    plan = router.route("Compare the termination clauses in both agreements", case_id="CASE_1")
    assert plan.query_type == "multi_doc_comparison"


def test_semantic_fallback() -> None:
    plan = router.route(
        "What are the indemnification obligations of the founders?", case_id="CASE_1"
    )
    assert plan.query_type == "semantic"
    assert plan.target_clause_label is None
    assert plan.target_defined_term is None
