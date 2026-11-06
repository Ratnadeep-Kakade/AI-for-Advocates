"""Reusable Google Cloud credential loading for Cicero services.

Modal workloads authenticate through the existing Workload Identity Federation
configuration and impersonate the Cicero service account. Local development
uses Application Default Credentials (ADC).
"""

from __future__ import annotations

import os
from typing import Any

import google.auth
from google.auth import impersonated_credentials
from google.auth.exceptions import DefaultCredentialsError

from cicero.core.config import Settings


class GoogleCredentialsConfigurationError(RuntimeError):
    """Raised when Google Cloud credentials cannot be configured safely."""


class GoogleCredentialsProvider:
    """Load shared Google Cloud credentials for database, storage, and other APIs."""

    _SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _modal_wif_config(self, *, impersonate_service_account: bool) -> dict[str, Any]:
        """Build the trusted Modal executable-source WIF configuration."""
        required = (
            self._settings.database_wif_project_number,
            self._settings.database_wif_pool_id,
            self._settings.database_wif_provider_id,
            self._settings.database_wif_service_account_email,
        )
        if not all(required):
            raise GoogleCredentialsConfigurationError(
                "Modal OIDC is available, but Workload Identity Federation settings are "
                "incomplete. Configure the WIF project number, pool ID, provider ID, "
                "and service-account email."
            )

        # The executable command is fixed in application code and emits
        # only Modal's injected OIDC token.
        os.environ["GOOGLE_EXTERNAL_ACCOUNT_ALLOW_EXECUTABLES"] = "1"
        project_number = self._settings.database_wif_project_number
        pool_id = self._settings.database_wif_pool_id
        provider_id = self._settings.database_wif_provider_id
        service_account_email = self._settings.database_wif_service_account_email
        config: dict[str, Any] = {
            "type": "external_account",
            "audience": (
                "//iam.googleapis.com/projects/"
                f"{project_number}/locations/global/workloadIdentityPools/"
                f"{pool_id}/providers/{provider_id}"
            ),
            "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
            "token_url": "https://sts.googleapis.com/v1/token",
            "credential_source": {
                "executable": {
                    "command": "python -m cicero.auth.modal_oidc_token",
                    "timeout_millis": 10000,
                }
            },
        }
        if impersonate_service_account:
            config["service_account_impersonation_url"] = (
                "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/"
                f"{service_account_email}:generateAccessToken"
            )
        return config

    def load(self) -> Any | None:
        """Return the standard API credentials or local ADC.

        Modal credentials impersonate the Cicero service account for normal
        Google API access. Local development uses Application Default
        Credentials. Returns ``None`` when local ADC is unavailable.
        """
        if os.environ.get("MODAL_IDENTITY_TOKEN"):
            try:
                credentials, _ = google.auth.load_credentials_from_dict(
                    self._modal_wif_config(impersonate_service_account=True),
                    scopes=self._SCOPES,
                )
            except GoogleCredentialsConfigurationError:
                raise
            except Exception as exc:
                raise GoogleCredentialsConfigurationError(
                    "Unable to initialise Google Workload Identity Federation credentials."
                ) from exc
            return credentials

        # Local development: gcloud auth application-default login.
        try:
            credentials, _ = google.auth.default(scopes=self._SCOPES)
            return credentials
        except DefaultCredentialsError:
            # Preserve the Cloud SQL Connector's own default credential discovery.
            return None

    def load_signing_credentials(self) -> Any:
        """Return credentials capable of IAM signBlob for V4 signed URLs.

        The Modal executable-source credentials are deliberately loaded without
        service-account impersonation, then explicitly wrapped in
        ``impersonated_credentials.Credentials``. This wrapper implements
        ``sign_bytes`` through IAM Credentials API, unlike the pluggable
        executable credential object used for ordinary API access.
        """
        if os.environ.get("MODAL_IDENTITY_TOKEN"):
            config = self._modal_wif_config(impersonate_service_account=False)
            try:
                source_credentials, _ = google.auth.load_credentials_from_dict(
                    config, scopes=self._SCOPES
                )
            except GoogleCredentialsConfigurationError:
                raise
            except Exception as exc:
                raise GoogleCredentialsConfigurationError(
                    "Unable to initialise source credentials for signed URL generation."
                ) from exc
        else:
            try:
                source_credentials, _ = google.auth.default(scopes=self._SCOPES)
            except DefaultCredentialsError as exc:
                raise GoogleCredentialsConfigurationError(
                    "Google Application Default Credentials are unavailable "
                    "for signed URL generation."
                ) from exc

            # Service-account key credentials and already-impersonated credentials
            # can sign directly. User ADC generally needs service-account impersonation.
            if callable(getattr(source_credentials, "sign_bytes", None)):
                return source_credentials

        target_principal = self._settings.database_wif_service_account_email
        if not target_principal:
            raise GoogleCredentialsConfigurationError(
                "A target service-account email is required for signed URL generation."
            )

        try:
            return impersonated_credentials.Credentials(
                source_credentials=source_credentials,
                target_principal=target_principal,
                target_scopes=self._SCOPES,
                lifetime=900,
            )
        except Exception as exc:
            raise GoogleCredentialsConfigurationError(
                "Unable to configure service-account impersonation for signed URL generation."
            ) from exc
