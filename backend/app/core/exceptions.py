class ProviderError(RuntimeError):
    """Raised when an upstream provider fails."""


class NotConfiguredError(ProviderError):
    """Raised when a provider is missing required credentials."""


class ReconnectRequiredError(ProviderError):
    """Raised when the saved user Twitch token must be reconnected."""


class DeviceFlowPendingError(ProviderError):
    """Twitch says the user has not approved the device code yet."""


class DeviceFlowSlowDownError(ProviderError):
    """Twitch asked the caller to poll less frequently."""


class DeviceFlowExpiredTokenError(ProviderError):
    """The Twitch device code expired before the user approved it."""


class DeviceFlowAccessDeniedError(ProviderError):
    """The user declined the Twitch device authorization."""


class DeviceFlowTerminalError(ProviderError):
    """The device grant failed and polling must stop."""


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


class DeviceFlowNotFoundError(AuthError):
    """The device flow is unknown, cancelled, already used, or expired."""

    status_code = 410


class DeviceFlowExpiredError(AuthError):
    """The device flow exceeded its lifetime before approval."""

    status_code = 400


class DeviceFlowDeniedError(AuthError):
    """The user declined the authorization at Twitch."""

    status_code = 400


# Scan failures are shared with every signed-in user. Store only the exception
# type plus a fixed phrase: provider exceptions can embed request URLs (the old
# Twitch token request put the client secret in the query string), response
# bodies, and tokens. Existing rows may still contain such text, so the same
# sanitizer runs when a scan row is serialized.
SCAN_ERROR_MESSAGE = "scan failed"
SAFE_SCAN_ERROR_PREFIX = "Scan failed (details redacted)"


def describe_exception(exc: BaseException) -> str:
    """Return a short, non-sensitive provider exception description."""
    return type(exc).__name__


def safe_scan_error(exc: BaseException) -> str:
    return f"{describe_exception(exc)}: {SCAN_ERROR_MESSAGE}"


def sanitize_scan_error(value: str | None) -> str | None:
    if not value:
        return None

    # Only the exact shape written by ``safe_scan_error`` is safe to expose.
    name, separator, message = value.partition(": ")
    if (
        separator
        and message == SCAN_ERROR_MESSAGE
        and name
        and len(name) <= 80
        and all(char.isalnum() or char in "_." for char in name)
    ):
        return value
    return SAFE_SCAN_ERROR_PREFIX
