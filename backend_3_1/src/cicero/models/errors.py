class ModelGatewayError(Exception):
    """Base class for errors safe to handle at the application boundary."""


class ModelConfigurationError(ModelGatewayError):
    """A provider, credential, or model-role configuration is missing or invalid."""


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
