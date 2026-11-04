from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = str


class Settings(BaseSettings):
    """Application configuration. Secret values are excluded from repr output."""

    model_config = SettingsConfigDict(
        env_prefix="CICERO_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_name: str = "Cicero API"
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Comma-separated exact browser origins allowed to call the API.
    cors_allowed_origins: str = ""

    # Provider credentials use provider-native environment variable names.
    meta_model_api_key: SecretStr | None = Field(
        default=None, validation_alias="MODEL_API_KEY", repr=False
    )
    vllm_api_key: SecretStr | None = Field(
        default=None, validation_alias="CICERO_VLLM_API_KEY", repr=False
    )
    generic_api_key: SecretStr | None = Field(
        default=None, validation_alias="CICERO_GENERIC_API_KEY", repr=False
    )

    meta_base_url: str = "https://api.meta.ai/v1"
    meta_model_id: str = "muse-spark-1.3"
    vllm_base_url: str | None = None
    generic_base_url: str | None = None

    interpreter_provider: ProviderName = "meta"
    interpreter_model: str = "muse-spark-1.3"
    orchestrator_provider: ProviderName = "meta"
    orchestrator_model: str = "muse-spark-1.3"

    document_intelligence_provider: ProviderName = "mock"
    document_intelligence_model: str = "deepseek-r1-distill-llama-70b"
    legal_researcher_provider: ProviderName = "mock"
    legal_researcher_model: str = "deepseek-r1-distill-llama-70b"
    argument_provider: ProviderName = "mock"
    argument_model: str = "deepseek-r1-distill-llama-70b"
    counterargument_provider: ProviderName = "mock"
    counterargument_model: str = "deepseek-r1-distill-llama-70b"
    evaluator_provider: ProviderName = "mock"
    evaluator_model: str = "deepseek-r1-distill-llama-70b"

    model_timeout_seconds: float = Field(default=300.0, gt=0, le=1800)
    model_max_retries: int = Field(default=2, ge=0, le=5)

    # Cloud SQL built-in database authentication. Connector IAM authorisation
    # (Cloud SQL Client role) is separate from this database username/password.
    database_instance_connection_name: str | None = None
    database_name: str | None = None
    database_user: str | None = None
    database_password: SecretStr | None = Field(default=None, repr=False)
    database_ip_type: Literal["public", "private", "psc"] = "public"
    database_refresh_strategy: Literal["lazy", "background"] = "lazy"
    database_pool_size: int = Field(default=3, ge=1, le=20)
    database_max_overflow: int = Field(default=2, ge=0, le=20)
    database_pool_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)

    # Google Cloud Storage. Objects remain private; the API issues short-lived
    # signed URLs after application-level organisation/case authorization.
    gcs_project_id: str = "project-d05a24bb-cf47-4351-b6e"
    gcs_bucket_name: str = "cicero-legal-documents-1575"
    gcs_upload_url_expiry_seconds: int = Field(default=900, ge=60, le=3600)
    gcs_download_url_expiry_seconds: int = Field(default=300, ge=60, le=3600)
    gcs_max_file_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1)

    # Workload Identity Federation settings. These values are identifiers, not secrets.
    database_wif_project_number: str | None = None
    database_wif_pool_id: str = "cicero-modal-pool"
    database_wif_provider_id: str = "modal-oidc"
    database_wif_service_account_email: str | None = None

    # Explicitly opt-in, single-tenant hackathon demo identity. This is not
    # authentication and must remain disabled for production deployments.
    demo_mode: bool = False
    demo_user_id: UUID | None = None
    demo_organization_id: UUID | None = None

    @property
    def database_configured(self) -> bool:
        """True only when all required Cloud SQL connection settings exist."""
        return all(
            (
                self.database_instance_connection_name,
                self.database_name,
                self.database_user,
                self.database_password and self.database_password.get_secret_value(),
            )
        )

    @property
    def database_partially_configured(self) -> bool:
        values = (
            self.database_instance_connection_name,
            self.database_name,
            self.database_user,
            self.database_password and self.database_password.get_secret_value(),
        )
        return any(values) and not all(values)

    @property
    def demo_identity_configured(self) -> bool:
        return (
            self.demo_mode
            and self.environment != "production"
            and self.demo_user_id is not None
            and self.demo_organization_id is not None
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
