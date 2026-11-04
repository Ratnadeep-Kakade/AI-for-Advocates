from cicero.rag.argon.schemas import EvidenceItem, ValidationStatus
from cicero.rag.retrieval import EvidenceValidator, ParsedDocView

FULL_TEXT = "AAA BBB CCC"
VIEW = ParsedDocView(
    document_id="DOC_1",
    full_text=FULL_TEXT,
    pages={1: (0, len(FULL_TEXT))},
    nodes={"N1": {"document_id": "DOC_1", "page_start": 1, "page_end": 1}},
    tables={
        "T1": {
            "page": 1,
            "cells": [
                {
                    "row_index": 0,
                    "col_index": 0,
                    "raw_cell_value": "AAA",
                    "char_start": 0,
                    "char_end": 3,
                }
            ],
        }
    },
)


def _resolve(document_id: str):
    return VIEW if document_id == "DOC_1" else None


def _item(**kw) -> EvidenceItem:
    base = dict(
        evidence_id="EV_001",
        document_id="DOC_1",
        case_id="CASE_1",
        org_id="ORG_1",
        node_id="N1",
        page=1,
        char_start=0,
        char_end=3,
        original_source_text="AAA",
        extracted_text="AAA",
        why_included="matched",
        token_count=1,
    )
    base.update(kw)
    return EvidenceItem(**base)


def test_verified_span() -> None:
    v = EvidenceValidator(_resolve)
    status, _ = v.validate_single_item(_item(), "CASE_1", "ORG_1")
    assert status == ValidationStatus.VERIFIED


def test_span_mismatch() -> None:
    v = EvidenceValidator(_resolve)
    status, _ = v.validate_single_item(_item(original_source_text="XXX"), "CASE_1", "ORG_1")
    assert status == ValidationStatus.SPAN_MISMATCH


def test_cross_case_rejected() -> None:
    v = EvidenceValidator(_resolve)
    status, _ = v.validate_single_item(_item(case_id="CASE_2"), "CASE_1", "ORG_1")
    assert status == ValidationStatus.INVALID_SOURCE_REFERENCE


def test_cross_org_rejected() -> None:
    v = EvidenceValidator(_resolve)
    status, _ = v.validate_single_item(_item(org_id="ORG_2"), "CASE_1", "ORG_1")
    assert status == ValidationStatus.INVALID_SOURCE_REFERENCE


def test_summary_rejected_as_evidence() -> None:
    v = EvidenceValidator(_resolve)
    item = _item(
        original_source_text="[RETRIEVAL AID SUMMARY ONLY - NOT AUTHORITATIVE EVIDENCE] ...",
        char_start=0,
        char_end=3,
    )
    status, _ = v.validate_single_item(item, "CASE_1", "ORG_1")
    assert status == ValidationStatus.INSUFFICIENT_PROVENANCE


def test_unknown_document_rejected() -> None:
    v = EvidenceValidator(_resolve)
    status, _ = v.validate_single_item(_item(document_id="DOC_X"), "CASE_1", "ORG_1")
    assert status == ValidationStatus.INVALID_SOURCE_REFERENCE


def test_table_item_verified() -> None:
    v = EvidenceValidator(_resolve)
    item = _item(
        node_id="N_TBL_T1",
        table_id="T1",
        why_included="raw_table",
        extracted_text="AAA",
        table_cell_references=[{"row_index": 0, "col_index": 0, "raw_cell_value": "AAA"}],
    )
    status, _ = v.validate_single_item(item, "CASE_1", "ORG_1")
    assert status == ValidationStatus.VERIFIED


def test_table_cell_value_mismatch() -> None:
    v = EvidenceValidator(_resolve)
    item = _item(
        node_id="N_TBL_T1",
        table_id="T1",
        why_included="raw_table",
        table_cell_references=[{"row_index": 0, "col_index": 0, "raw_cell_value": "ZZZ"}],
    )
    status, _ = v.validate_single_item(item, "CASE_1", "ORG_1")
    assert status == ValidationStatus.INVALID_TABLE_REFERENCE


def test_budget_enforced_in_list_validation() -> None:
    v = EvidenceValidator(_resolve)
    item = _item(token_count=50)
    verified, rejected = v.validate_evidence_list([item], "CASE_1", "ORG_1", token_budget=10)
    assert verified == []
    assert rejected[0]["status"] == "TOKEN_BUDGET_EXCEEDED"
