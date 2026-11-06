from collections.abc import Mapping

from cicero.core.exceptions import ModelConfigurationError
from .base import ModelProvider


class ProviderRegistry:
    """Named provider adapters available to the Model Gateway."""

    def __init__(self, providers: Mapping[str, ModelProvider] | None = None) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for name, provider in (providers or {}).items():
            self.register(name, provider)

    def register(
        self,
        name: str,
        provider: ModelProvider,
        *,
        replace: bool = False,
    ) -> None:
        key = name.strip()
        if not key:
            raise ModelConfigurationError("Provider name cannot be empty.")
        if key in self._providers and not replace:
            raise ModelConfigurationError(f"Provider '{key}' is already registered.")
        if provider.name != key:
            raise ModelConfigurationError(
                f"Provider adapter name '{provider.name}' does not match registry key '{key}'."
            )
        self._providers[key] = provider

    def get(self, name: str) -> ModelProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ModelConfigurationError(
                f"Provider '{name}' is not registered."
            ) from exc

    def contains(self, name: str) -> bool:
        return name in self._providers

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
