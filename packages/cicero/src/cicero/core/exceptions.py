class CiceroError(Exception):
    """Base exception for all Cicero core errors."""
    pass


class ModelGatewayError(CiceroError):
    """Base class for model gateway errors safe to handle at the application boundary."""
    pass


class ModelConfigurationError(ModelGatewayError):
    """A provider, credential, or model-role configuration is missing or invalid."""
    pass


class ModelProviderError(ModelGatewayError):
    """A normalised provider failure."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        code: str,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


class CiceroValidationError(CiceroError):
    """Raised when deterministic validation fails."""
    pass
