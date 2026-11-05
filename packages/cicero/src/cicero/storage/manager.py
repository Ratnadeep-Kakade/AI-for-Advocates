"""Google Cloud Storage operations for Cicero's private document objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, BinaryIO

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.cloud import storage

from cicero.auth.google_credentials import GoogleCredentialsProvider
from cicero.config import Settings


class StorageConfigurationError(RuntimeError):
    """Raised when storage configuration or authentication is unavailable."""


class StorageObjectNotFoundError(FileNotFoundError):
    """Raised when a requested object does not exist in the configured bucket."""


class StorageObjectAlreadyExistsError(FileExistsError):
    """Raised when an upload would overwrite an existing object."""


@dataclass(frozen=True, slots=True)
class StoredObjectMetadata:
    """Selected metadata returned by Cloud Storage after an object operation."""

    bucket_name: str
    object_name: str
    size_bytes: int
    content_type: str | None
    crc32c: str | None
    md5_hash: str | None
    generation: int | None
    etag: str | None
    updated: datetime | None


@dataclass(frozen=True, slots=True)
class SignedUploadUrl:
    """A short-lived capability to upload one object using HTTP PUT."""

    url: str
    bucket_name: str
    object_name: str
    method: str
    required_headers: dict[str, str]
    expires_in_seconds: int
    max_file_size_bytes: int


@dataclass(frozen=True, slots=True)
class SignedDownloadUrl:
    """A short-lived capability to download one object using HTTP GET."""

    url: str
    bucket_name: str
    object_name: str
    method: str
    expires_in_seconds: int


class StorageManager:
    """Thin synchronous GCS adapter.

    The Google Cloud Storage Python client is synchronous. Keep these methods
    out of async request handlers until they are run in a worker thread or
    replaced with an async orchestration boundary.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        credentials_provider: GoogleCredentialsProvider | None = None,
        client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._credentials_provider = credentials_provider or GoogleCredentialsProvider(settings)
        self._client: Any | None = client

    @property
    def is_initialized(self) -> bool:
        return self._client is not None

    def _get_client(self) -> Any:
        if self._client is None:
            credentials = self._credentials_provider.load()
            if credentials is None:
                raise StorageConfigurationError(
                    "Google Cloud credentials are unavailable. Configure Modal WIF or "
                    "run 'gcloud auth application-default login' for local development."
                )
            self._client = storage.Client(
                project=self._settings.gcs_project_id,
                credentials=credentials,
            )
        return self._client

    def _get_blob(self, object_name: str) -> Any:
        self._validate_object_name(object_name)
        return self._get_client().bucket(self._settings.gcs_bucket_name).blob(object_name)

    def _get_signing_credentials(self) -> Any:
        """Load credentials with signBlob support.

        The fallback keeps lightweight test doubles and older custom providers
        compatible; the production provider implements the dedicated method.
        """
        signing_loader = getattr(
            self._credentials_provider, "load_signing_credentials", None
        )
        if callable(signing_loader):
            credentials = signing_loader()
        else:
            credentials = self._credentials_provider.load()
        if credentials is None:
            raise StorageConfigurationError(
                "Google Cloud credentials are unavailable for signed URL generation."
            )
        return credentials

    @staticmethod
    def _validate_object_name(object_name: str) -> None:
        if not object_name or not object_name.strip():
            raise ValueError("GCS object name must not be empty.")
        if object_name.startswith("/") or "\\\\" in object_name:
            raise ValueError("GCS object name must be a relative POSIX path.")
        parts = object_name.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("GCS object name contains an invalid path segment.")

    def generate_upload_url(
        self,
        object_name: str,
        *,
        content_type: str,
    ) -> SignedUploadUrl:
        """Generate a V4 signed PUT URL bound to the exact content type.

        The ifGenerationMatch=0 precondition makes the upload create-only:
        the request fails if a live object already exists at this object name.

        The configured size limit is returned for client-side preflight and
        must be enforced again by the API after upload using object metadata.
        A signed PUT URL does not enforce a maximum request-body size.
        """
        if not content_type or not content_type.strip():
            raise ValueError("Content type must not be empty.")

        blob = self._get_blob(object_name)
        expiry = self._settings.gcs_upload_url_expiry_seconds
        signing_credentials = self._get_signing_credentials()
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiry),
            method="PUT",
            credentials=signing_credentials,
            content_type=content_type,
            query_parameters={"ifGenerationMatch": "0"},
        )
        return SignedUploadUrl(
            url=url,
            bucket_name=self._settings.gcs_bucket_name,
            object_name=object_name,
            method="PUT",
            required_headers={"Content-Type": content_type},
            expires_in_seconds=expiry,
            max_file_size_bytes=self._settings.gcs_max_file_size_bytes,
        )

    def generate_download_url(
        self,
        object_name: str,
        *,
        generation: int | None = None,
        response_disposition: str | None = None,
    ) -> SignedDownloadUrl:
        """Generate a V4 signed GET URL, optionally pinned to an object generation."""
        blob = self._get_blob(object_name)
        expiry = self._settings.gcs_download_url_expiry_seconds
        signing_credentials = self._get_signing_credentials()
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiry),
            method="GET",
            credentials=signing_credentials,
            generation=str(generation) if generation is not None else None,
            response_disposition=response_disposition,
        )
        return SignedDownloadUrl(
            url=url,
            bucket_name=self._settings.gcs_bucket_name,
            object_name=object_name,
            method="GET",
            expires_in_seconds=expiry,
        )

    def upload_object(
        self,
        object_name: str,
        file_obj: BinaryIO,
        *,
        content_type: str,
    ) -> StoredObjectMetadata:
        """Upload a file-like object without overwriting an existing object."""
        blob = self._get_blob(object_name)
        current_position = file_obj.tell()
        file_obj.seek(0, 2)
        size_bytes = file_obj.tell()
        file_obj.seek(current_position)
        if size_bytes <= 0:
            raise ValueError("Cannot upload an empty object.")
        if size_bytes > self._settings.gcs_max_file_size_bytes:
            raise ValueError(
                f"Object exceeds the configured maximum of "
                f"{self._settings.gcs_max_file_size_bytes} bytes."
            )
        try:
            blob.upload_from_file(
                file_obj,
                rewind=True,
                size=size_bytes,
                content_type=content_type,
                if_generation_match=0,
            )
            blob.reload()
        except PreconditionFailed as exc:
            raise StorageObjectAlreadyExistsError(
                f"GCS object already exists: {object_name}"
            ) from exc
        return self._to_metadata(blob)

    def get_object_metadata(self, object_name: str) -> StoredObjectMetadata:
        """Fetch metadata for an existing object."""
        blob = self._get_blob(object_name)
        try:
            blob.reload()
        except NotFound as exc:
            raise StorageObjectNotFoundError(object_name) from exc
        return self._to_metadata(blob)

    def object_exists(self, object_name: str) -> bool:
        """Return whether an object exists."""
        return bool(self._get_blob(object_name).exists())

    def delete_object(self, object_name: str) -> None:
        """Delete an object, surfacing missing-object errors explicitly."""
        blob = self._get_blob(object_name)
        try:
            blob.delete()
        except NotFound as exc:
            raise StorageObjectNotFoundError(object_name) from exc

    def check_bucket_access(self) -> dict[str, str | None]:
        """Read bucket metadata to verify the configured identity can access it."""
        bucket = self._get_client().get_bucket(self._settings.gcs_bucket_name)
        return {
            "bucket_name": bucket.name,
            "location": bucket.location,
            "storage_class": bucket.storage_class,
        }

    def close(self) -> None:
        """Close the underlying Google Cloud Storage client, if initialized."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _to_metadata(self, blob: Any) -> StoredObjectMetadata:
        return StoredObjectMetadata(
            bucket_name=self._settings.gcs_bucket_name,
            object_name=blob.name,
            size_bytes=int(blob.size or 0),
            content_type=blob.content_type,
            crc32c=blob.crc32c,
            md5_hash=blob.md5_hash,
            generation=int(blob.generation) if blob.generation is not None else None,
            etag=blob.etag,
            updated=blob.updated,
        )
