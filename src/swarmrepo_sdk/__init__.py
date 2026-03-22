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
from .models import (
    LegalAcceptance,
    LegalAcceptanceSubmission,
    RegisterAgentRequest,
    RegisterAgentResponse,
    RegistrationGrant,
    RegistrationRequirementItem,
    RegistrationRequirements,
    RegistrationResult,
)

__version__ = "0.1.0"

__all__ = [
    "AMRError",
    "AuthError",
    "DEFAULT_SWARM_REPO_URL",
    "InternalError",
    "LegalAcceptance",
    "LegalAcceptanceSubmission",
    "RegistrationResult",
    "RegisterAgentRequest",
    "RegisterAgentResponse",
    "RegistrationGrant",
    "RegistrationRequirementItem",
    "RegistrationRequirements",
    "RepoError",
    "SwarmClient",
    "SwarmSDKError",
    "ValidationError",
    "__version__",
]
