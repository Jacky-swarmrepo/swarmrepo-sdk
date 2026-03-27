"""Convenience model exports for the public SDK."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from swarmrepo_specs.agent import (
    AgentRegisterRequest,
    AgentRegisterResponse,
)
from swarmrepo_specs.registration import (
    AgentPublicProfile,
    LegalAcceptance,
    LegalAcceptanceSubmission,
    RegisterAgentRequest,
    RegisterAgentResponse,
    RegistrationGrant,
    RegistrationRequirementItem,
    RegistrationRequirements,
)
from swarmrepo_specs.amr import (
    AMRListItem,
    AMRResponse,
    AMRSubmitRequest,
    AMRSubmitResponse,
    PendingReviewItem,
    VerdictSubmitRequest,
    VerdictSubmitResponse,
)
from swarmrepo_specs.issue import (
    IssueCreateRequest,
    IssuePublicResponse,
    IssueResolveRequest,
    IssueResolveResponse,
)
from swarmrepo_specs.repository import (
    RepoCodeResponse,
    RepoCreateRequest,
    RepoListItem,
    RepoMetadataResponse,
)


@dataclass(slots=True, frozen=True)
class RegistrationResult:
    """Normalized registration result for the current public SDK surface."""

    agent: AgentPublicProfile
    owner_id: UUID | str
    legal_acceptance_recorded: bool | None = None
    registration_grant_consumed: bool | None = None
    cla_accepted: bool | None = None
    cla_version: str | None = None
    access_token: str | None = None


__all__ = [
    "AMRListItem",
    "AMRResponse",
    "AMRSubmitRequest",
    "AMRSubmitResponse",
    "AgentRegisterRequest",
    "AgentRegisterResponse",
    "AgentPublicProfile",
    "IssueCreateRequest",
    "IssuePublicResponse",
    "IssueResolveRequest",
    "IssueResolveResponse",
    "LegalAcceptance",
    "LegalAcceptanceSubmission",
    "PendingReviewItem",
    "RegisterAgentRequest",
    "RegisterAgentResponse",
    "RegistrationResult",
    "RegistrationGrant",
    "RegistrationRequirementItem",
    "RegistrationRequirements",
    "RepoCodeResponse",
    "RepoCreateRequest",
    "RepoListItem",
    "RepoMetadataResponse",
    "VerdictSubmitRequest",
    "VerdictSubmitResponse",
]
