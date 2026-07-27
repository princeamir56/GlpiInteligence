"""Custom exceptions raised by the GLPI connector."""
from __future__ import annotations


class GLPIAPIError(Exception):
    """Base exception for all GLPI API related errors."""

    def __init__(self, message: str, status_code: int | None = None, payload: object | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class GLPIAuthError(GLPIAPIError):
    """Raised when initSession fails (bad App-Token or User-Token)."""


class GLPISessionExpired(GLPIAPIError):
    """Raised when the Session-Token is no longer accepted by GLPI."""


class GLPIRateLimited(GLPIAPIError):
    """Raised when the GLPI API returns a 429 status."""


class GLPIUnavailable(GLPIAPIError):
    """Raised when the GLPI API is unreachable after the configured retries."""
