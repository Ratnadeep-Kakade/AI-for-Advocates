from google.auth.exceptions import DefaultCredentialsError

from cicero.auth.google_credentials import (
    GoogleCredentialsConfigurationError,
    GoogleCredentialsProvider,
)
from cicero.config import Settings


def test_local_adc_is_returned(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    sentinel = object()
    captured = {}

    def fake_default(*, scopes):
        captured["scopes"] = scopes
        return sentinel, "project-id"

    monkeypatch.delenv("MODAL_IDENTITY_TOKEN", raising=False)
    monkeypatch.setattr("cicero.auth.google_credentials.google.auth.default", fake_default)

    credentials = GoogleCredentialsProvider(settings).load()

    assert credentials is sentinel
    assert captured["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]


def test_missing_local_adc_returns_none(monkeypatch) -> None:
    settings = Settings(_env_file=None)

    def fake_default(*, scopes):
        raise DefaultCredentialsError("ADC not found")

    monkeypatch.delenv("MODAL_IDENTITY_TOKEN", raising=False)
    monkeypatch.setattr("cicero.auth.google_credentials.google.auth.default", fake_default)

    assert GoogleCredentialsProvider(settings).load() is None


def test_modal_wif_configuration_is_reused_for_google_cloud_services(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        database_wif_project_number="116460390489",
        database_wif_pool_id="cicero-modal-pool",
        database_wif_provider_id="modal-oidc",
        database_wif_service_account_email=(
            "cicero-backend@project-d05a24bb-cf47-4351-b6e.iam.gserviceaccount.com"
        ),
    )
    sentinel = object()
    captured = {}

    def fake_load(info, *, scopes):
        captured["info"] = info
        captured["scopes"] = scopes
        return sentinel, None

    monkeypatch.setenv("MODAL_IDENTITY_TOKEN", "header.payload.signature")
    monkeypatch.setattr(
        "cicero.auth.google_credentials.google.auth.load_credentials_from_dict",
        fake_load,
    )

    assert GoogleCredentialsProvider(settings).load() is sentinel
    assert captured["info"]["audience"].endswith(
        "/workloadIdentityPools/cicero-modal-pool/providers/modal-oidc"
    )
    assert captured["info"]["service_account_impersonation_url"].endswith(
        ":generateAccessToken"
    )


def test_modal_wif_missing_configuration_fails_closed(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    monkeypatch.setenv("MODAL_IDENTITY_TOKEN", "header.payload.signature")

    try:
        GoogleCredentialsProvider(settings).load()
    except GoogleCredentialsConfigurationError as exc:
        assert "settings are incomplete" in str(exc)
    else:
        raise AssertionError("Expected incomplete WIF settings to fail closed")
