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
        default=SecretStr("cicero-vllm-internal-key-2026"),
        validation_alias="CICERO_VLLM_API_KEY",
        repr=False,
    )
    generic_api_key: SecretStr | None = Field(
        default=None, validation_alias="CICERO_GENERIC_API_KEY", repr=False
    )

    meta_base_url: str = "https://api.meta.ai/v1"
    meta_model_id: str = "muse-spark-1.3"
    vllm_base_url: str | None = (
        "https://computer-1575-vision--cicero-llama-inference-llamaserver.us-east.modal.direct/v1"
    )
    generic_base_url: str | None = None

    interpreter_provider: ProviderName = "meta"
    interpreter_model: str = "muse-spark-1.3"
    orchestrator_provider: ProviderName = "meta"
    orchestrator_model: str = "muse-spark-1.3"

    # Document Intelligence runs on DeepSeek-R1-Distill-Llama-70B on Modal's A100.
    document_intelligence_provider: ProviderName = "vllm_modal"
    document_intelligence_model: str = "deepseek-r1-distill-llama-70b"
    # Specialised reasoning agents run DeepSeek-R1-Distill-Llama-70B on Modal's A100-80GB
    # vLLM service. Graceful fallback to Meta Muse-Spark is handled at the gateway layer.
    legal_researcher_provider: ProviderName = "vllm_modal"
    legal_researcher_model: str = "deepseek-r1-distill-llama-70b"
    argument_provider: ProviderName = "vllm_modal"
    argument_model: str = "deepseek-r1-distill-llama-70b"
    counterargument_provider: ProviderName = "vllm_modal"
    counterargument_model: str = "deepseek-r1-distill-llama-70b"
    evaluator_provider: ProviderName = "vllm_modal"
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
    # 500-600 page legal PDFs (especially scans) routinely exceed 50 MiB.
    gcs_max_file_size_bytes: int = Field(default=200 * 1024 * 1024, ge=1)
    # Pub/Sub topic used to dispatch registered document versions to Cloud Run.
    pubsub_document_topic: str | None = None
    rag_worker_url: str | None = Field(
        default="https://computer-1575-vision--cicero-rag-worker-fastapi-app.us-east.modal.run",
        validation_alias="CICERO_RAG_WORKER_URL",
    )
    # Gemini is used only as the Google Search grounding intermediary for the
    # Legal Researcher (DeepSeek reasons over the collected sources).
    gemini_api_key: SecretStr | None = Field(
        default=None, validation_alias="CICERO_GEMINI_API_KEY", repr=False
    )
    gemini_model: str = "gemini-2.5-flash"
    # "auto" lets the embedding/reranking stack pick CUDA when available
    # (Modal T4 worker) and CPU otherwise (local/Cloud Run fallback).
    rag_device: str = "auto"
    # Ingestion parser: "pdfplumber" (default, lightweight line extraction —
    # completes in seconds on digital PDFs and cannot OOM the worker) or
    # "docling" (full layout/OCR pipeline; needs the large-memory worker).
    rag_parser_mode: str = "pdfplumber"
    # Cross-encoder rejection threshold. BGE reranker sigmoid scores on
    # legal text are low in absolute terms; 0.22 (the prototype default)
    # rejected every candidate in live testing. Evidence is still
    # quote-validated downstream, so a low floor is safe.
    rag_rerank_threshold: float = 0.005
    # Must stay below the 3600s Modal/Cloud Run ingestion ceiling.
    rag_lease_minutes: int = Field(default=50, ge=5, le=120)
    pubsub_push_audience: str | None = None
    pubsub_push_service_account: str | None = None
    rag_service_token: SecretStr | None = Field(
        default=None, validation_alias="CICERO_RAG_SERVICE_TOKEN", repr=False
    )

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
