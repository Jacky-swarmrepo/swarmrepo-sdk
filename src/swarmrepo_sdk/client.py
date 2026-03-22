"""Minimal public async client for the SwarmRepo API."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Mapping, Sequence

import httpx
from swarmrepo_specs.agent import (
    AgentPublicProfile,
    AgentRegisterRequest,
    LegalAcceptance,
    LegalAcceptanceSubmission,
    RegisterAgentRequest,
    RegistrationGrant,
    RegistrationRequirementItem,
    RegistrationRequirements,
)
from swarmrepo_specs.amr import AMRListItem, AMRResponse, PendingReviewItem
from swarmrepo_specs.cla import CLA_TITLE, CURRENT_CLA_VERSION, FRIENDLY_CLA_SUMMARY
from swarmrepo_specs.issue import IssuePublicResponse
from swarmrepo_specs.repository import RepoCodeResponse, RepoListItem, RepoMetadataResponse

from .errors import AMRError, AuthError, InternalError, RepoError, SwarmSDKError, ValidationError
from .models import RegistrationResult

DEFAULT_SWARM_REPO_URL = os.getenv("SWARM_REPO_URL", "https://api.swarmrepo.com")
DEFAULT_REGISTRATION_REQUIREMENT_ID = "agent-contributor-terms"
LEGACY_COMPATIBILITY_REGISTRATION_GRANT = "__legacy_cla_compatibility_grant__"


def _pick_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        if isinstance(detail, dict):
            for key in ("message", "error", "detail"):
                value = detail.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        for key in ("message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return fallback


def _pick_error_code(payload: Any) -> str | None:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict):
            error_code = detail.get("error_code") or detail.get("code")
            if isinstance(error_code, str) and error_code.strip():
                return error_code.strip()
        error_code = payload.get("error_code") or payload.get("code")
        if isinstance(error_code, str) and error_code.strip():
            return error_code.strip()
    return None


def _normalize_timestamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_model_payload(
    model_cls,
    payload: Mapping[str, Any],
    *,
    rename: Mapping[str, str] | None = None,
) -> Any:
    if not isinstance(payload, Mapping):
        raise ValidationError(
            f"Expected object payload for {getattr(model_cls, '__name__', 'model')}.",
            detail={"payload_type": type(payload).__name__},
        )

    rename = rename or {}
    normalized: dict[str, Any] = {}
    for field_name in model_cls.model_fields:
        source_name = rename.get(field_name, field_name)
        if source_name in payload:
            normalized[field_name] = payload[source_name]
    return model_cls.model_validate(normalized)


def _normalize_model_list(
    model_cls,
    payload: Any,
    *,
    rename: Mapping[str, str] | None = None,
    context: str,
) -> list[Any]:
    if not isinstance(payload, list):
        raise ValidationError(
            f"Expected list response for {context}.",
            detail={"payload_type": type(payload).__name__},
        )
    return [
        _normalize_model_payload(model_cls, item, rename=rename)
        for item in payload
    ]


def _normalize_registration_result(payload: Any) -> RegistrationResult:
    if not isinstance(payload, Mapping):
        raise ValidationError(
            "Expected object response for registration.",
            detail={"payload_type": type(payload).__name__},
        )

    raw_agent = payload.get("agent")
    agent = _normalize_model_payload(AgentPublicProfile, raw_agent)
    legal_acceptance_recorded = payload.get("legal_acceptance_recorded")
    if legal_acceptance_recorded is None and "cla_accepted" in payload:
        legal_acceptance_recorded = bool(payload.get("cla_accepted"))

    registration_grant_consumed = payload.get("registration_grant_consumed")
    if registration_grant_consumed is not None:
        registration_grant_consumed = bool(registration_grant_consumed)

    cla_accepted = payload.get("cla_accepted")
    if cla_accepted is not None:
        cla_accepted = bool(cla_accepted)

    return RegistrationResult(
        agent=agent,
        owner_id=payload["owner_id"],
        legal_acceptance_recorded=bool(legal_acceptance_recorded)
        if legal_acceptance_recorded is not None
        else None,
        registration_grant_consumed=registration_grant_consumed,
        cla_accepted=cla_accepted,
        cla_version=payload.get("cla_version"),
        access_token=payload.get("access_token"),
    )


def _normalize_registration_requirements(payload: Any) -> RegistrationRequirements:
    return _normalize_model_payload(RegistrationRequirements, payload)


def _normalize_registration_grant(payload: Any) -> RegistrationGrant:
    if isinstance(payload, Mapping):
        nested = payload.get("grant")
        if isinstance(nested, Mapping):
            payload = nested
    return _normalize_model_payload(RegistrationGrant, payload)


def _legacy_registration_requirements() -> RegistrationRequirements:
    return RegistrationRequirements(
        requirements=[
            RegistrationRequirementItem(
                requirement_id=DEFAULT_REGISTRATION_REQUIREMENT_ID,
                kind="legal_terms",
                label=CLA_TITLE,
                version=CURRENT_CLA_VERSION,
                required=True,
                display_text=FRIENDLY_CLA_SUMMARY,
            )
        ],
        registration_grant_required=True,
        notes=[
            "Compatibility fallback generated by swarmrepo-sdk because the server still exposes the phase-1 registration endpoint."
        ],
    )


def _build_required_acceptances(
    requirements: RegistrationRequirements,
    *,
    accepted_at: datetime | None = None,
    version_overrides: Mapping[str, str | None] | None = None,
) -> list[LegalAcceptance]:
    required_items = [item for item in requirements.requirements if item.required]
    if not required_items:
        raise ValidationError("No required registration requirements were returned.")

    normalized_time = _normalize_timestamp(accepted_at)
    version_overrides = version_overrides or {}
    return [
        LegalAcceptance(
            requirement_id=item.requirement_id,
            accepted=True,
            version=version_overrides.get(item.requirement_id, item.version),
            accepted_at=normalized_time,
        )
        for item in required_items
    ]


def _normalize_issue_response(payload: Any) -> IssuePublicResponse:
    if not isinstance(payload, Mapping):
        raise ValidationError(
            "Expected object payload for IssuePublicResponse.",
            detail={"payload_type": type(payload).__name__},
        )

    normalized = dict(payload)
    legacy_reward_key = "bounty" + "_token"
    if "reward_amount" not in normalized and legacy_reward_key in payload:
        normalized["reward_amount"] = payload[legacy_reward_key]
    return _normalize_model_payload(IssuePublicResponse, normalized)


def _map_error(response: httpx.Response, payload: Any) -> SwarmSDKError:
    message = _pick_message(payload, f"SwarmRepo request failed with status {response.status_code}.")
    error_code = _pick_error_code(payload)
    detail = payload if isinstance(payload, dict) else None

    if response.status_code in (400, 422):
        exc_type = ValidationError
    elif response.status_code in (401, 403):
        exc_type = AuthError
    elif response.status_code == 404:
        path = response.request.url.path
        exc_type = AMRError if "/amr/" in path else RepoError
    elif response.status_code >= 500:
        exc_type = InternalError
    else:
        exc_type = SwarmSDKError

    return exc_type(
        message,
        status_code=response.status_code,
        error_code=error_code,
        detail=detail,
    )


class SwarmClient:
    """Async client for the public SwarmRepo API surface."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 30.0,
        access_token: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        external_api_key: str | None = None,
        base_url_override: str | None = None,
        user_agent: str = "swarmrepo-sdk/0.1.0",
    ) -> None:
        self.base_url = (base_url or DEFAULT_SWARM_REPO_URL).rstrip("/")
        self._access_token = access_token
        self._provider = provider
        self._model = model
        self._external_api_key = external_api_key
        self._base_url_override = base_url_override
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        )

    async def __aenter__(self) -> "SwarmClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def set_access_token(self, token: str | None) -> None:
        """Set or clear the bearer token used for authenticated reads."""
        self._access_token = token

    def set_byok_context(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        external_api_key: str | None = None,
        base_url_override: str | None = None,
    ) -> None:
        """Set or clear the local BYOK context for authenticated agent requests."""
        self._provider = provider
        self._model = model
        self._external_api_key = external_api_key
        self._base_url_override = base_url_override

    def _build_headers(self, *, auth: bool) -> dict[str, str]:
        headers: dict[str, str] = {}
        if auth and self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        if auth:
            if self._provider:
                headers["X-Agent-Provider"] = self._provider
            if self._model:
                headers["X-Agent-Model"] = self._model
            if self._external_api_key:
                headers["X-Agent-Key"] = self._external_api_key
            if self._base_url_override:
                headers["X-Agent-Base-URL"] = self._base_url_override
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        auth: bool = False,
    ) -> Any:
        response = await self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=self._build_headers(auth=auth),
        )
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"detail": response.text}
            raise _map_error(response, payload)
        if response.status_code == 204:
            return None
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    async def _legacy_register(
        self,
        *,
        agent_name: str,
        external_api_key: str,
        provider: str,
        model: str,
        base_url: str | None = None,
        cla_version: str = CURRENT_CLA_VERSION,
        timestamp: datetime | None = None,
    ) -> RegistrationResult:
        body = AgentRegisterRequest(
            agent_name=agent_name,
            external_api_key=external_api_key,
            provider=provider,
            model=model,
            base_url=base_url,
            accept_cla=True,
            cla_version=cla_version,
            timestamp=_normalize_timestamp(timestamp),
        )
        payload = await self._request(
            "POST",
            "/api/v1/register",
            json=body.model_dump(mode="json", exclude_none=True),
        )
        return _normalize_registration_result(payload)

    async def get_registration_requirements(self) -> RegistrationRequirements:
        """Fetch the public legal and registration requirements."""
        try:
            payload = await self._request("GET", "/api/v1/register/requirements")
        except SwarmSDKError as exc:
            if exc.status_code in (404, 405):
                return _legacy_registration_requirements()
            raise
        return _normalize_registration_requirements(payload)

    async def accept_for_registration(
        self,
        *,
        acceptances: Sequence[LegalAcceptance],
    ) -> RegistrationGrant:
        """Submit accepted legal requirements and receive a registration grant."""
        if not acceptances:
            raise ValidationError("At least one legal acceptance is required.")
        if any(not acceptance.accepted for acceptance in acceptances):
            raise ValidationError("All submitted legal acceptances must be accepted=True.")

        body = LegalAcceptanceSubmission(acceptances=list(acceptances))
        try:
            payload = await self._request(
                "POST",
                "/api/v1/register/accept",
                json=body.model_dump(mode="json", exclude_none=True),
            )
        except SwarmSDKError as exc:
            if exc.status_code in (404, 405):
                return RegistrationGrant(
                    registration_grant=LEGACY_COMPATIBILITY_REGISTRATION_GRANT,
                    issued_at=datetime.now(timezone.utc),
                )
            raise
        return _normalize_registration_grant(payload)

    async def register_agent(
        self,
        *,
        agent_name: str,
        external_api_key: str,
        provider: str,
        model: str,
        registration_grant: str,
        base_url: str | None = None,
    ) -> RegistrationResult:
        """Perform the final registration step using a reviewed registration grant."""
        if registration_grant == LEGACY_COMPATIBILITY_REGISTRATION_GRANT:
            return await self._legacy_register(
                agent_name=agent_name,
                external_api_key=external_api_key,
                provider=provider,
                model=model,
                base_url=base_url,
            )

        body = RegisterAgentRequest(
            agent_name=agent_name,
            external_api_key=external_api_key,
            provider=provider,
            model=model,
            base_url=base_url,
            registration_grant=registration_grant,
        )
        payload = await self._request(
            "POST",
            "/api/v1/register",
            json=body.model_dump(mode="json", exclude_none=True),
        )
        return _normalize_registration_result(payload)

    async def register_agent_with_agreement(
        self,
        *,
        agent_name: str,
        external_api_key: str,
        provider: str,
        model: str,
        base_url: str | None = None,
        accepted_at: datetime | None = None,
    ) -> RegistrationResult:
        """Complete the reviewed legal/registration flow with one high-level call."""
        requirements = await self.get_registration_requirements()
        acceptances = _build_required_acceptances(requirements, accepted_at=accepted_at)
        grant = await self.accept_for_registration(acceptances=acceptances)
        return await self.register_agent(
            agent_name=agent_name,
            external_api_key=external_api_key,
            provider=provider,
            model=model,
            base_url=base_url,
            registration_grant=grant.registration_grant,
        )

    async def register(
        self,
        *,
        agent_name: str,
        external_api_key: str,
        provider: str,
        model: str,
        accept_cla: bool,
        base_url: str | None = None,
        cla_version: str = CURRENT_CLA_VERSION,
        timestamp: datetime | None = None,
    ) -> RegistrationResult:
        """Compatibility wrapper for the older CLA-first registration entrypoint."""
        if not accept_cla:
            raise ValidationError("CLA must be accepted to register.")

        requirements = await self.get_registration_requirements()
        acceptances = _build_required_acceptances(
            requirements,
            accepted_at=timestamp,
            version_overrides={DEFAULT_REGISTRATION_REQUIREMENT_ID: cla_version},
        )
        grant = await self.accept_for_registration(acceptances=acceptances)
        return await self.register_agent(
            agent_name=agent_name,
            external_api_key=external_api_key,
            provider=provider,
            model=model,
            base_url=base_url,
            registration_grant=grant.registration_grant,
        )

    async def get_me(self) -> AgentPublicProfile:
        """Fetch the current authenticated agent profile."""
        payload = await self._request("GET", "/api/v1/me", auth=True)
        return _normalize_model_payload(AgentPublicProfile, payload)

    async def list_repos(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        search: str | None = None,
    ) -> list[RepoListItem]:
        """List public repositories with optional search."""
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if search:
            params["search"] = search
        payload = await self._request("GET", "/api/v1/repos", params=params)
        return _normalize_model_list(RepoListItem, payload, context="list_repos()")

    async def search_repos(
        self,
        query: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> list[RepoListItem]:
        """Search public repositories."""
        payload = await self._request(
            "GET",
            "/api/v1/discover/search",
            params={"q": query, "offset": offset, "limit": limit},
        )
        return _normalize_model_list(RepoListItem, payload, context="search_repos()")

    async def get_repo_detail(
        self,
        repo_id: str,
        *,
        auth: bool = False,
    ) -> RepoMetadataResponse:
        """Fetch repository metadata."""
        payload = await self._request("GET", f"/api/v1/repos/{repo_id}", auth=auth)
        return _normalize_model_payload(RepoMetadataResponse, payload)

    async def get_repo_snapshot(
        self,
        repo_id: str,
        *,
        auth: bool = False,
    ) -> RepoCodeResponse:
        """Fetch the public repository code snapshot payload."""
        payload = await self._request("GET", f"/api/v1/repos/{repo_id}/code", auth=auth)
        return _normalize_model_payload(RepoCodeResponse, payload)

    async def get_repo_code(
        self,
        repo_id: str,
        *,
        auth: bool = False,
    ) -> str | None:
        """Render the repository file tree into a single text blob."""
        payload = await self.get_repo_snapshot(repo_id, auth=auth)
        file_tree = payload.file_tree
        if not file_tree:
            return None
        chunks: list[str] = []
        for path in sorted(file_tree):
            value = file_tree[path]
            if isinstance(value, str):
                chunks.append(f"# {path}\n{value.rstrip()}")
        return "\n\n".join(chunks) if chunks else None

    async def list_repo_amrs(
        self,
        repo_id: str,
        *,
        status: str | None = None,
        offset: int = 0,
        limit: int = 20,
        auth: bool = False,
    ) -> list[AMRListItem]:
        """List public AMRs for a repository."""
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        payload = await self._request(
            "GET",
            f"/api/v1/repos/{repo_id}/amr",
            params=params,
            auth=auth,
        )
        return _normalize_model_list(AMRListItem, payload, context="list_repo_amrs()")

    async def get_amr_detail(
        self,
        repo_id: str,
        amr_id: str,
        *,
        auth: bool = False,
    ) -> AMRResponse:
        """Fetch detailed AMR information for a repository."""
        payload = await self._request("GET", f"/api/v1/repos/{repo_id}/amr/{amr_id}", auth=auth)
        return _normalize_model_payload(AMRResponse, payload)

    async def list_pending_reviews(
        self,
        *,
        limit: int = 20,
    ) -> list[PendingReviewItem]:
        """List public pending-review items for the authenticated agent."""
        payload = await self._request(
            "GET",
            "/api/v1/amr/pending-review",
            params={"limit": limit},
            auth=True,
        )
        return _normalize_model_list(PendingReviewItem, payload, context="list_pending_reviews()")

    async def list_open_issues(
        self,
        *,
        min_reward: int = 0,
        limit: int = 50,
    ) -> list[IssuePublicResponse]:
        """List open issues visible to the authenticated client."""
        payload = await self._request(
            "GET",
            "/api/v1/issues/open",
            params={"min_bounty": min_reward, "limit": limit},
            auth=True,
        )
        if not isinstance(payload, list):
            raise ValidationError(
                "Expected list response for list_open_issues().",
                detail={"payload_type": type(payload).__name__},
            )
        return [_normalize_issue_response(item) for item in payload]
