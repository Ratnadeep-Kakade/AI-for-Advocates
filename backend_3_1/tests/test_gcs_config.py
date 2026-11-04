import pytest
from pydantic import ValidationError

from cicero.config import Settings


def test_gcs_settings_have_expected_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.gcs_project_id == "project-d05a24bb-cf47-4351-b6e"
    assert settings.gcs_bucket_name == "cicero-legal-documents-1575"
    assert settings.gcs_upload_url_expiry_seconds == 900
    assert settings.gcs_download_url_expiry_seconds == 300
    assert settings.gcs_max_file_size_bytes == 50 * 1024 * 1024


def test_gcs_settings_can_be_overridden_by_environment(monkeypatch) -> None:
    monkeypatch.setenv("CICERO_GCS_PROJECT_ID", "test-project")
    monkeypatch.setenv("CICERO_GCS_BUCKET_NAME", "test-private-bucket")
    monkeypatch.setenv("CICERO_GCS_UPLOAD_URL_EXPIRY_SECONDS", "600")
    monkeypatch.setenv("CICERO_GCS_DOWNLOAD_URL_EXPIRY_SECONDS", "180")
    monkeypatch.setenv("CICERO_GCS_MAX_FILE_SIZE_BYTES", "10485760")

    settings = Settings(_env_file=None)

    assert settings.gcs_project_id == "test-project"
    assert settings.gcs_bucket_name == "test-private-bucket"
    assert settings.gcs_upload_url_expiry_seconds == 600
    assert settings.gcs_download_url_expiry_seconds == 180
    assert settings.gcs_max_file_size_bytes == 10 * 1024 * 1024


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("CICERO_GCS_UPLOAD_URL_EXPIRY_SECONDS", "30"),
        ("CICERO_GCS_UPLOAD_URL_EXPIRY_SECONDS", "3601"),
        ("CICERO_GCS_DOWNLOAD_URL_EXPIRY_SECONDS", "30"),
        ("CICERO_GCS_DOWNLOAD_URL_EXPIRY_SECONDS", "3601"),
        ("CICERO_GCS_MAX_FILE_SIZE_BYTES", "0"),
    ],
)
def test_invalid_gcs_limits_are_rejected(monkeypatch, field: str, value: str) -> None:
    monkeypatch.setenv(field, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
