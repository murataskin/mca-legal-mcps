class JurixError(Exception):
    """Base exception for Jurix MCP."""


class RegistrationError(JurixError):
    """Raised when registration fails."""


class ActivationError(JurixError):
    """Raised when account activation fails."""


class AuthenticationError(JurixError):
    """Raised when login/session validation fails."""


class AccountPoolError(JurixError):
    """Raised when no usable account is available."""


class DownloadError(JurixError):
    """Raised when article download cannot complete."""
