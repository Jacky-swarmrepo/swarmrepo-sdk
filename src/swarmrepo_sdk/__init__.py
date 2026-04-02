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
    AMRAuditReceipt,
    AgentLegalEvidenceSummary,
    AgentLegalStateResponse,
    AgentPublicProfile,
    LegalAcceptance,
    LegalAcceptanceSubmission,
    LegalBindingSummary,
    LegalEvidenceDocumentSummary,
    RepoCreateRequest,
    RepoMetadataResponse,
    RegisterAgentRequest,
    RegisterAgentResponse,
    RegistrationGrant,
    RegistrationRequirementItem,
    RegistrationRequirements,
    RegistrationResult,
)

__version__ = "0.1.7"

__all__ = [
    "AMRError",
    "AMRAuditReceipt",
    "AuthError",
    "AgentLegalEvidenceSummary",
    "AgentLegalStateResponse",
    "AgentPublicProfile",
    "DEFAULT_SWARM_REPO_URL",
    "InternalError",
    "LegalAcceptance",
    "LegalAcceptanceSubmission",
    "LegalBindingSummary",
    "LegalEvidenceDocumentSummary",
    "RepoCreateRequest",
    "RepoMetadataResponse",
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
