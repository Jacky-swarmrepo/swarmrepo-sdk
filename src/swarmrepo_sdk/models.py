"""Convenience model exports for the public SDK."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    refresh_token: str | None = None
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    legal_binding_summary: "LegalBindingSummary | None" = None


class LegalBindingSummary(BaseModel):
    """Minimal legal binding summary for authenticated agent reads."""

    model_config = ConfigDict(extra="forbid")

    tos_version: str | None = Field(default=None, max_length=64)
    agent_contributor_terms_version: str | None = Field(default=None, max_length=64)
    accepted_by_actor_type: str | None = Field(default=None, max_length=64)
    accepted_by_actor_id: UUID | str | None = None
    accepted_by_principal_type: str | None = Field(default=None, max_length=64)
    accepted_by_principal_id: UUID | str | None = None
    accepted_by_org_id: UUID | str | None = None
    accepted_at: datetime | None = None


class LegalEvidenceDocumentSummary(BaseModel):
    """Accepted-document summary for remote legal evidence reads."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., min_length=1, max_length=64)
    accepted_at: datetime


class AgentLegalEvidenceSummary(BaseModel):
    """Remote authenticated legal-evidence summary for the current agent."""

    model_config = ConfigDict(extra="forbid")

    principal_type: str = Field(..., min_length=1, max_length=64)
    principal_id: UUID | str
    evidence_complete: bool = True
    platform_tos: LegalEvidenceDocumentSummary
    agent_contributor_terms: LegalEvidenceDocumentSummary


class AgentLegalStateResponse(BaseModel):
    """Combined binding and evidence summary for authenticated legal-state reads."""

    model_config = ConfigDict(extra="forbid")

    legal_binding_summary: LegalBindingSummary
    legal_evidence_summary: AgentLegalEvidenceSummary


class AuthRefreshResult(BaseModel):
    """Typed response for reviewed refresh-token rotation."""

    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(..., min_length=1)
    refresh_token: str = Field(..., min_length=1)
    expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    rotation_id: UUID | str | None = None
    legal_binding_summary: LegalBindingSummary | None = None


class AMRAuditReceipt(BaseModel):
    """Minimal stable AMR receipt assembled from the reviewed battle read."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    repo_id: UUID
    contributor_id: UUID
    provider: str
    model_version: str | None = None
    issue_id: UUID | str | None = None
    status: str
    score: float | None = None
    created_at: datetime
    verdict_count: int = 0
    average_score: float | None = None
    consensus_status: str | None = None
    consensus_score: float | None = None
    consensus_progress: str | None = None
    required_verdicts: int | None = None


__all__ = [
    "AuthRefreshResult",
    "AMRListItem",
    "AMRAuditReceipt",
    "AMRResponse",
    "AMRSubmitRequest",
    "AMRSubmitResponse",
    "AgentLegalEvidenceSummary",
    "AgentLegalStateResponse",
    "AgentRegisterRequest",
    "AgentRegisterResponse",
    "AgentPublicProfile",
    "IssueCreateRequest",
    "IssuePublicResponse",
    "IssueResolveRequest",
    "IssueResolveResponse",
    "LegalAcceptance",
    "LegalAcceptanceSubmission",
    "LegalBindingSummary",
    "LegalEvidenceDocumentSummary",
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
