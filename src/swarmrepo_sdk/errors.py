"""Public exception surface for swarmrepo-sdk."""

from __future__ import annotations

from typing import Any


class SwarmSDKError(Exception):
    """Base exception for all public SDK failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.detail = detail or {}


class AuthError(SwarmSDKError):
    """Authentication or authorization failure."""


class RepoError(SwarmSDKError):
    """Repository-related failure."""


class AMRError(SwarmSDKError):
    """AMR-related read failure."""


class ValidationError(SwarmSDKError):
    """Client input or request validation failure."""


class InternalError(SwarmSDKError):
    """Unexpected server-side failure."""
