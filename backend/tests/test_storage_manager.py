from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from google.api_core.exceptions import NotFound, PreconditionFailed

from cicero.config import Settings
from cicero.storage.manager import (
    SignedDownloadUrl,
    SignedUploadUrl,
    StorageConfigurationError,
    StorageManager,
    StorageObjectAlreadyExistsError,
    StorageObjectNotFoundError,
)


class FakeCredentialsProvider:
    def __init__(self, credentials=None) -> None:
        self.credentials = credentials if credentials is not None else object()
        self.calls = 0

    def load(self):
        self.calls += 1
        return self.credentials


class MissingCredentialsProvider:
    def load(self):
        return None


class FakeBlob:
    def __init__(self, name: str) -> None:
        self.name = name
        self.size = 12
        self.content_type = "application/pdf"
        self.crc32c = "crc"
        self.md5_hash = "md5"
        self.generation = 7
        self.etag = "etag"
        self.updated = datetime(2026, 11, 4, tzinfo=UTC)
        self.upload_args = None
        self.delete_args = None
        self.exists_result = True
        self.reload_error = None
        self.delete_error = None
        self.upload_error = None
        self.signed_url_args = None
        self.signed_url = "https://storage.googleapis.com/signed-object"

    def upload_from_file(self, file_obj, **kwargs):
        self.upload_args = kwargs
        if self.upload_error:
            raise self.upload_error

    def reload(self):
        if self.reload_error:
            raise self.reload_error

    def exists(self):
        return self.exists_result

    def delete(self, **kwargs):
        self.delete_args = kwargs
        if self.delete_error:
            raise self.delete_error

    def generate_signed_url(self, **kwargs):
        self.signed_url_args = kwargs
        return self.signed_url


class FakeBucket:
    def __init__(self) -> None:
        self.blobs = {}
        self.name = "cicero-legal-documents-1575"
        self.location = "ASIA-SOUTH1"
        self.storage_class = "STANDARD"

    def blob(self, name):
        return self.blobs.setdefault(name, FakeBlob(name))


class FakeClient:
    def __init__(self) -> None:
        self.fake_bucket = FakeBucket()
        self.closed = False
        self.bucket_name = None

    def bucket(self, name):
        self.bucket_name = name
        return self.fake_bucket

    def get_bucket(self, name):
        self.bucket_name = name
        return self.fake_bucket

    def close(self):
        self.closed = True


def make_manager(*, max_size=1024, provider=None, client=None):
    settings = Settings(_env_file=None, gcs_max_file_size_bytes=max_size)
    provider = provider or FakeCredentialsProvider()
    client = client or FakeClient()
    return (
        StorageManager(
            settings,
            credentials_provider=provider,
            client=client,
        ),
        provider,
        client,
    )


def test_upload_uses_create_only_precondition_and_returns_metadata():
    manager, _, client = make_manager()
    file_obj = BytesIO(b"legal document")

    metadata = manager.upload_object(
        "orgs/org-1/documents/doc-1/version-1/file.pdf",
        file_obj,
        content_type="application/pdf",
    )

    blob = client.fake_bucket.blobs["orgs/org-1/documents/doc-1/version-1/file.pdf"]
    assert blob.upload_args["if_generation_match"] == 0
    assert metadata.bucket_name == "cicero-legal-documents-1575"
    assert metadata.size_bytes == 12
    assert metadata.content_type == "application/pdf"
    assert metadata.generation == 7


def test_upload_rejects_empty_object():
    manager, _, _ = make_manager()
    with pytest.raises(ValueError, match="empty"):
        manager.upload_object("orgs/org-1/file.pdf", BytesIO(b""), content_type="application/pdf")


def test_upload_rejects_oversized_object():
    manager, _, _ = make_manager(max_size=4)
    with pytest.raises(ValueError, match="maximum"):
        manager.upload_object(
            "orgs/org-1/file.pdf", BytesIO(b"12345"), content_type="application/pdf"
        )


def test_upload_rejects_existing_object():
    manager, _, client = make_manager()
    blob = client.fake_bucket.blob("orgs/org-1/file.pdf")
    blob.upload_error = PreconditionFailed("already exists")
    with pytest.raises(StorageObjectAlreadyExistsError):
        manager.upload_object(
            "orgs/org-1/file.pdf", BytesIO(b"data"), content_type="application/pdf"
        )


def test_metadata_maps_missing_object():
    manager, _, client = make_manager()
    blob = client.fake_bucket.blob("orgs/org-1/missing.pdf")
    blob.reload_error = NotFound("missing")
    with pytest.raises(StorageObjectNotFoundError):
        manager.get_object_metadata("orgs/org-1/missing.pdf")


def test_delete_maps_missing_object():
    manager, _, client = make_manager()
    blob = client.fake_bucket.blob("orgs/org-1/missing.pdf")
    blob.delete_error = NotFound("missing")
    with pytest.raises(StorageObjectNotFoundError):
        manager.delete_object("orgs/org-1/missing.pdf")


def test_object_name_rejects_path_traversal():
    manager, _, _ = make_manager()
    with pytest.raises(ValueError):
        manager.object_exists("../outside.pdf")


def test_bucket_access_returns_bucket_metadata():
    manager, _, _ = make_manager()
    assert manager.check_bucket_access() == {
        "bucket_name": "cicero-legal-documents-1575",
        "location": "ASIA-SOUTH1",
        "storage_class": "STANDARD",
    }


def test_close_closes_client():
    manager, _, client = make_manager()
    manager.close()
    assert client.closed is True


def test_missing_credentials_fail_closed():
    settings = Settings(_env_file=None)
    manager = StorageManager(
        settings,
        credentials_provider=MissingCredentialsProvider(),
    )
    with pytest.raises(StorageConfigurationError):
        manager._get_client()


def test_generate_upload_url_is_v4_put_create_only_and_content_type_bound():
    manager, _, client = make_manager()
    result = manager.generate_upload_url(
        "orgs/org-1/documents/doc-1/versions/ver-1/file.pdf",
        content_type="application/pdf",
    )
    blob = client.fake_bucket.blobs[
        "orgs/org-1/documents/doc-1/versions/ver-1/file.pdf"
    ]

    assert isinstance(result, SignedUploadUrl)
    assert result.url == blob.signed_url
    assert result.method == "PUT"
    assert result.required_headers == {"Content-Type": "application/pdf"}
    assert result.expires_in_seconds == 900
    assert result.max_file_size_bytes == 1024
    assert blob.signed_url_args["version"] == "v4"
    assert blob.signed_url_args["method"] == "PUT"
    assert blob.signed_url_args["content_type"] == "application/pdf"
    assert blob.signed_url_args["query_parameters"] == {"ifGenerationMatch": "0"}
    assert blob.signed_url_args["expiration"] == timedelta(seconds=900)


def test_generate_upload_url_rejects_empty_content_type():
    manager, _, _ = make_manager()
    with pytest.raises(ValueError, match="Content type"):
        manager.generate_upload_url("orgs/org-1/file.pdf", content_type=" ")


def test_generate_download_url_is_v4_get_and_can_pin_generation():
    manager, _, client = make_manager()
    result = manager.generate_download_url(
        "orgs/org-1/documents/doc-1/versions/ver-1/file.pdf",
        generation=12345,
        response_disposition='attachment; filename="contract.pdf"',
    )
    blob = client.fake_bucket.blobs[
        "orgs/org-1/documents/doc-1/versions/ver-1/file.pdf"
    ]

    assert isinstance(result, SignedDownloadUrl)
    assert result.url == blob.signed_url
    assert result.method == "GET"
    assert result.expires_in_seconds == 300
    assert blob.signed_url_args["version"] == "v4"
    assert blob.signed_url_args["method"] == "GET"
    assert blob.signed_url_args["generation"] == "12345"
    assert (
        blob.signed_url_args["response_disposition"]
        == 'attachment; filename="contract.pdf"'
    )


def test_generate_download_url_rejects_path_traversal():
    manager, _, _ = make_manager()
    with pytest.raises(ValueError):
        manager.generate_download_url("../outside.pdf")
