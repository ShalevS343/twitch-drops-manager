class ProviderError(RuntimeError):
    """Raised when an upstream provider fails."""


class NotConfiguredError(ProviderError):
    """Raised when a provider is missing required credentials."""
