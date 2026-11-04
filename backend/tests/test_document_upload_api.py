from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cicero.api.app import create_app
from cicero.api.routes.documents import (
    UploadCompleteRequest,
    UploadUrlRequest,
    _object_name,
    _safe_filename,
)
from cicero.config import Settings


def test_document_routes_are_registered() -> None:
    app = create_app(settings=Settings(_env_file=None))
    paths = set(app.openapi()["paths"].keys())
    assert "/api/cases/{case_id}/documents/upload-url" in paths
    assert "/api/cases/{case_id}/documents/complete" in paths
    assert "/api/cases/{case_id}/documents" in paths


def test_document_routes_fail_closed_without_demo_identity() -> None:
    app = create_app(settings=Settings(_env_file=None))
    response = TestClient(app).get(f"/api/cases/{uuid4()}/documents")
    assert response.status_code == 503


def test_upload_request_rejects_empty_or_non_positive_file_size() -> None:
    with pytest.raises(ValidationError):
        UploadUrlRequest(filename="file.pdf", content_type="application/pdf", file_size=0)


def test_upload_request_accepts_pdf_metadata() -> None:
    payload = UploadUrlRequest(
        filename="Zepto UDRHP.pdf",
        content_type="application/pdf",
        file_size=1024,
    )
    assert payload.file_size == 1024


def test_safe_filename_removes_path_and_unsafe_characters() -> None:
    assert _safe_filename(r"C:\\temp\\Zepto UDRHP.pdf") == "Zepto_UDRHP.pdf"


def test_object_name_is_scoped_and_server_generated() -> None:
    org_id, case_id, document_id, version_id = (uuid4() for _ in range(4))
    name = _object_name(org_id, case_id, document_id, version_id, "filing.pdf")
    assert name.startswith(f"orgs/{org_id}/cases/{case_id}/documents/{document_id}/")
    assert f"/versions/{version_id}/filing.pdf" in name


def test_complete_request_requires_identifiers() -> None:
    with pytest.raises(ValidationError):
        UploadCompleteRequest(filename="filing.pdf", content_type="application/pdf")


def test_publish_failure_marks_run_failed(monkeypatch) -> None:
    """A failed Pub/Sub dispatch must not leave the run silently pending."""
    from cicero.api.routes import documents as documents_module

    class DeniedCredentials:
        def __init__(self, settings) -> None:
            pass

        def load(self):
            raise RuntimeError("pubsub.topics.publish denied")

    recorded: dict = {}

    def fake_mark_failed(settings, payload, error) -> None:
        recorded["payload"] = payload
        recorded["error"] = error

    monkeypatch.setattr(documents_module, "GoogleCredentialsProvider", DeniedCredentials)
    monkeypatch.setattr(documents_module, "_mark_dispatch_failed_sync", fake_mark_failed)

    payload = {
        "organization_id": str(uuid4()),
        "case_id": str(uuid4()),
        "document_id": str(uuid4()),
        "version_id": str(uuid4()),
        "processing_run_id": str(uuid4()),
    }
    documents_module._publish_document_job(
        "projects/demo/topics/cicero-document-processing",
        payload,
        Settings(_env_file=None),
    )

    assert recorded["payload"] == payload
    assert isinstance(recorded["error"], RuntimeError)
