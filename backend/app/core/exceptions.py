class ProviderError(RuntimeError):
    """Raised when an upstream provider fails."""


class NotConfiguredError(ProviderError):
    """Raised when a provider is missing required credentials."""


class ReconnectRequiredError(ProviderError):
    """Raised when the saved user Twitch token must be reconnected."""


class AuthError(RuntimeError):
    """Base class for expected authentication/registration failures."""

    status_code = 400


class InvalidAuthRequestError(AuthError):
    """The pasted token or Twitch validation response cannot be used."""

    status_code = 400


class RegistrationClosedError(AuthError):
    """A new account is not allowed by the registration settings."""

    status_code = 403


class AccountDisabledError(AuthError):
    """The local account exists but an admin disabled it."""

    status_code = 403


class AccountConflictError(AuthError):
    """A signed-in user tried to connect a different Twitch account."""

    status_code = 409


class LastAdminError(AuthError):
    """Disabling this account would leave no active administrator."""

    status_code = 400
