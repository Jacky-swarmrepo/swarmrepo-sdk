"""Public Python SDK surface for SwarmRepo."""

from .client import DEFAULT_SWARM_REPO_URL, SwarmClient
from .errors import (
    AMRError,
    AuthError,
    InternalError,
    RepoError,
    SwarmSDKError,
    ValidationError,
)
from .models import RegistrationResult

__version__ = "0.1.0"

__all__ = [
    "AMRError",
    "AuthError",
    "DEFAULT_SWARM_REPO_URL",
    "InternalError",
    "RegistrationResult",
    "RepoError",
    "SwarmClient",
    "SwarmSDKError",
    "ValidationError",
    "__version__",
]
