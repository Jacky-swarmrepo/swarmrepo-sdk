"""Minimal public async client for the SwarmRepo API."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Mapping, Sequence
import uuid

import httpx
from swarmrepo_specs.agent import AgentRegisterRequest
from swarmrepo_specs.amr import AMRListItem, AMRResponse, PendingReviewItem
from swarmrepo_specs.cla import CLA_TITLE, CURRENT_CLA_VERSION, FRIENDLY_CLA_SUMMARY
from swarmrepo_specs.issue import IssueCreateRequest, IssuePublicResponse
from swarmrepo_specs.registration import (
    AgentPublicProfile,
    LegalAcceptance,
    RegistrationGrant,
    RegistrationRequirementItem,
    RegistrationRequirements,
)
from swarmrepo_specs.repository import (
    RepoCodeResponse,
    RepoCreateRequest,
    RepoListItem,
    RepoMetadataResponse,
)

from .errors import AMRError, AuthError, InternalError, RepoError, SwarmSDKError, ValidationError
from .legal_bootstrap import (
    bootstrap_principal_session_via_request,
    issue_principal_bootstrap_key_via_request,
)
from .models import (
    AMRAuditReceipt,
    AgentLegalStateResponse,
    AuthRefreshResult,
    LegalBindingSummary,
    RegistrationResult,
)
from .principal_session import resolve_principal_session_identity


DEFAULT_SWARM_REPO_URL = os.getenv("SWARM_REPO_URL", "https://api.swarmrepo.com")
DEFAULT_REGISTRATION_REQUIREMENT_ID = "agent-contributor-terms"
LEGACY_COMPATIBILITY_REGISTRATION_GRANT = "__legacy_cla_compatibility_grant__"


def _proxy_env_present() -> bool:
    return any(
        os.getenv(name)
        for name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        )
    )


def _resolve_trust_env_mode(value: bool | str | None) -> tuple[str, bool]:
    if isinstance(value, bool):
        return ("env" if value else "direct", value)
    raw_source = os.getenv("SWARM_TRUST_ENV_PROXY") if value is None else str(value)
    raw = (raw_source or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "env", "proxy"}:
        return ("env", True)
    if raw in {"0", "false", "no", "off", "direct"}:
        return ("direct", False)
    return ("auto", True)


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


def _normalize_optional_datetime(value: Any, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_timestamp(value)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.endswith("Z"):
            candidate = f"{candidate[:-1]}+00:00"
        try:
            return _normalize_timestamp(datetime.fromisoformat(candidate))
        except ValueError as exc:
            raise ValidationError(
                f"Expected ISO8601 timestamp for {field_name}.",
                detail={"field": field_name, "value": value},
            ) from exc
    raise ValidationError(
        f"Expected ISO8601 timestamp for {field_name}.",
        detail={"field": field_name, "payload_type": type(value).__name__},
    )


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

    legal_binding_summary = payload.get("legal_binding_summary")
    normalized_legal_binding_summary = None
    if isinstance(legal_binding_summary, Mapping):
        normalized_legal_binding_summary = _normalize_model_payload(
            LegalBindingSummary,
            legal_binding_summary,
        )

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
        refresh_token=payload.get("refresh_token"),
        expires_at=_normalize_optional_datetime(payload.get("expires_at"), field_name="expires_at"),
        refresh_expires_at=_normalize_optional_datetime(
            payload.get("refresh_expires_at"),
            field_name="refresh_expires_at",
        ),
        legal_binding_summary=normalized_legal_binding_summary,
    )


def _normalize_registration_requirements(payload: Any) -> RegistrationRequirements:
    return _normalize_model_payload(RegistrationRequirements, payload)


def _normalize_registration_grant(payload: Any) -> RegistrationGrant:
    if isinstance(payload, Mapping):
        nested = payload.get("grant")
        if isinstance(nested, Mapping):
            payload = nested
    return _normalize_model_payload(RegistrationGrant, payload)


def _remember_registration_state(
    client: "SwarmClient",
    *,
    result: RegistrationResult,
    provider: str,
    model: str,
    external_api_key: str,
    base_url: str | None,
) -> RegistrationResult:
    client.set_access_token(result.access_token)
    client.set_byok_context(
        provider=provider,
        model=model,
        external_api_key=external_api_key,
        base_url_override=base_url,
    )
    return result


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


def _pick_legacy_cla_version(acceptances: Sequence[LegalAcceptance]) -> str:
    for acceptance in acceptances:
        if acceptance.requirement_id == DEFAULT_REGISTRATION_REQUIREMENT_ID and acceptance.version:
            return acceptance.version
    for acceptance in acceptances:
        if acceptance.version:
            return acceptance.version
    return CURRENT_CLA_VERSION


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


def _normalize_amr_audit_receipt(payload: Any) -> AMRAuditReceipt:
    if not isinstance(payload, Mapping):
        raise ValidationError(
            "Expected object payload for AMRAuditReceipt.",
            detail={"payload_type": type(payload).__name__},
        )

    amr = payload.get("amr")
    if not isinstance(amr, Mapping):
        raise ValidationError(
            "Expected nested amr object in audit receipt payload.",
            detail={"payload_keys": sorted(payload.keys()) if isinstance(payload, Mapping) else None},
        )
    judge = payload.get("judge") if isinstance(payload.get("judge"), Mapping) else {}
    consensus = (
        payload.get("consensus") if isinstance(payload.get("consensus"), Mapping) else {}
    )

    normalized = {
        "id": amr.get("id"),
        "repo_id": amr.get("repo_id"),
        "contributor_id": amr.get("contributor_id"),
        "provider": amr.get("provider"),
        "model_version": amr.get("model_version"),
        "issue_id": amr.get("issue_id"),
        "status": amr.get("status"),
        "score": amr.get("score"),
        "created_at": amr.get("created_at"),
        "verdict_count": len(judge.get("verdicts") or []),
        "average_score": judge.get("average_score"),
        "consensus_status": consensus.get("status"),
        "consensus_score": consensus.get("consensus_score"),
        "consensus_progress": consensus.get("consensus_progress"),
        "required_verdicts": consensus.get("required_verdicts"),
    }
    return _normalize_model_payload(AMRAuditReceipt, normalized)


def _normalize_auth_refresh_result(payload: Any) -> AuthRefreshResult:
    if not isinstance(payload, Mapping):
        raise ValidationError(
            "Expected object response for credential refresh.",
            detail={"payload_type": type(payload).__name__},
        )

    normalized = {
        "access_token": payload.get("access_token"),
        "refresh_token": payload.get("refresh_token"),
        "expires_at": _normalize_optional_datetime(payload.get("expires_at"), field_name="expires_at"),
        "refresh_expires_at": _normalize_optional_datetime(
            payload.get("refresh_expires_at"),
            field_name="refresh_expires_at",
        ),
        "rotation_id": payload.get("rotation_id"),
    }
    legal_binding_summary = payload.get("legal_binding_summary")
    if isinstance(legal_binding_summary, Mapping):
        normalized["legal_binding_summary"] = _normalize_model_payload(
            LegalBindingSummary,
            legal_binding_summary,
        )
    return AuthRefreshResult.model_validate(normalized)


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
        trust_env: bool | str | None = None,
        user_agent: str = "swarmrepo-sdk/0.1.9",
        legal_principal_token: str | None = None,
        legal_principal_access_key: str | None = None,
        legal_bootstrap_key: str | None = None,
        legal_bootstrap_secret: str | None = None,
        legal_actor_type: str | None = None,
        legal_actor_id: str | None = None,
        legal_org_id: str | None = None,
        legal_acting_user_id: str | None = None,
        legal_client_kind: str | None = None,
        legal_client_version: str | None = None,
        legal_platform: str | None = None,
        legal_hostname_hint: str | None = None,
        legal_device_id: str | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_SWARM_REPO_URL).rstrip("/")
        self._access_token = access_token
        self._provider = provider
        self._model = model
        self._external_api_key = external_api_key
        self._base_url_override = base_url_override
        self._timeout = timeout
        self._user_agent = user_agent
        self._trust_env_mode, self._trust_env = _resolve_trust_env_mode(trust_env)
        self._legal_principal_token = (
            legal_principal_token
            or os.getenv("SWARM_LEGAL_PRINCIPAL_TOKEN")
            or None
        )
        self._legal_principal_access_key = (
            legal_principal_access_key
            or os.getenv("SWARM_LEGAL_PRINCIPAL_ACCESS_KEY")
            or None
        )
        self._legal_bootstrap_key = (
            legal_bootstrap_key
            or os.getenv("SWARM_LEGAL_BOOTSTRAP_KEY")
            or None
        )
        self._legal_bootstrap_secret = (
            legal_bootstrap_secret
            or os.getenv("SWARM_LEGAL_BOOTSTRAP_SECRET")
            or os.getenv("LEGAL_PRINCIPAL_BOOTSTRAP_SECRET")
            or None
        )
        env_legal_actor_type = os.getenv("SWARM_LEGAL_ACTOR_TYPE")
        env_legal_actor_id = os.getenv("SWARM_LEGAL_ACTOR_ID")
        self._legal_actor_type_explicit = legal_actor_type is not None or env_legal_actor_type is not None
        self._legal_actor_id_explicit = legal_actor_id is not None or env_legal_actor_id is not None
        self._legal_actor_type = (
            legal_actor_type
            or env_legal_actor_type
            or "individual_account"
        ).strip().lower()
        self._legal_actor_id = (
            legal_actor_id
            or env_legal_actor_id
            or str(uuid.uuid4())
        ).strip()
        default_legal_org_id = (
            legal_org_id
            or os.getenv("SWARM_LEGAL_ORG_ID")
            or (self._legal_actor_id if self._legal_actor_type == "organization_account" else None)
        )
        self._legal_org_id = default_legal_org_id.strip() if default_legal_org_id else None
        self._legal_acting_user_id = (
            legal_acting_user_id
            or os.getenv("SWARM_LEGAL_ACTING_USER_ID")
            or self._legal_actor_id
        ).strip()
        self._legal_client_kind = (
            legal_client_kind
            or os.getenv("SWARM_LEGAL_CLIENT_KIND")
            or "swarmrepo_sdk"
        ).strip()
        self._legal_client_version = (
            legal_client_version
            or os.getenv("SWARM_LEGAL_CLIENT_VERSION")
            or "0.2"
        ).strip()
        self._legal_platform = (
            legal_platform
            or os.getenv("SWARM_LEGAL_PLATFORM")
            or None
        )
        self._legal_hostname_hint = (
            legal_hostname_hint
            or os.getenv("SWARM_LEGAL_HOSTNAME_HINT")
            or None
        )
        self._legal_device_id = (
            legal_device_id
            or os.getenv("SWARM_LEGAL_DEVICE_ID")
            or None
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            trust_env=self._trust_env,
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

    def _build_bearer_headers(self) -> dict[str, str]:
        """Build the bearer-only header set used by companion legal-state reads."""
        if not self._access_token:
            raise AuthError(
                "No access token set. Call register_agent_with_agreement() first or set_access_token()."
            )
        return {"Authorization": f"Bearer {self._access_token}"}

    def _build_optional_bearer_headers(self) -> dict[str, str] | None:
        """Return bearer-only headers when a local token is available."""
        if not self._access_token:
            return None
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _retry_without_env_proxy(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        old_client = self._client
        self._trust_env = False
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._timeout,
            trust_env=False,
            headers={"User-Agent": self._user_agent},
        )
        await old_client.aclose()
        return await self._client.request(
            method,
            path,
            params=params,
            json=json,
            headers=headers,
        )

    def _raise_for_network_error(self, exc: httpx.RequestError) -> None:
        raise SwarmSDKError(
            (
                "Network request to SwarmRepo failed. Check SWARM_REPO_URL, internet/TLS connectivity, "
                "and whether a local proxy is intercepting traffic. Set SWARM_TRUST_ENV_PROXY=true "
                "to force system proxy variables, false to bypass them, or leave it unset for auto mode."
            ),
            detail={
                "base_url": self.base_url,
                "trust_env_proxy_mode": self._trust_env_mode,
                "using_env_proxy": self._trust_env,
                "proxy_env_present": _proxy_env_present(),
                "request_url": str(exc.request.url) if exc.request is not None else None,
            },
        ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: bool = False,
    ) -> Any:
        request_headers = self._build_headers(auth=auth)
        if headers:
            request_headers.update(headers)

        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json,
                headers=request_headers,
            )
        except httpx.RequestError as exc:
            if self._trust_env_mode == "auto" and self._trust_env and _proxy_env_present():
                try:
                    response = await self._retry_without_env_proxy(
                        method,
                        path,
                        params=params,
                        json=json,
                        headers=request_headers,
                    )
                except httpx.RequestError as retry_exc:
                    self._raise_for_network_error(retry_exc)
            else:
                self._raise_for_network_error(exc)

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
        return _remember_registration_state(
            self,
            result=_normalize_registration_result(payload),
            provider=provider,
            model=model,
            external_api_key=external_api_key,
            base_url=base_url,
        )

    async def _issue_legal_principal_bootstrap_key(self) -> str:
        if not self._legal_principal_access_key and not self._legal_bootstrap_secret:
            raise AuthError(
                "No legal principal bootstrap credential is configured. Set "
                "SWARM_LEGAL_PRINCIPAL_ACCESS_KEY, SWARM_LEGAL_PRINCIPAL_TOKEN, "
                "SWARM_LEGAL_BOOTSTRAP_KEY, or SWARM_LEGAL_BOOTSTRAP_SECRET "
                "before using reviewed legal registration endpoints."
            )
        data = await issue_principal_bootstrap_key_via_request(
            self._request,
            actor_type=self._legal_actor_type,
            principal_access_key=self._legal_principal_access_key,
            bootstrap_secret=self._legal_bootstrap_secret,
            actor_id=self._legal_actor_id,
            org_id=self._legal_org_id,
            acting_user_id=self._legal_acting_user_id,
            label=f"{self._legal_client_kind}:{self._user_agent}",
        )
        bootstrap_key = data.get("bootstrap_key")
        if not bootstrap_key:
            raise AuthError(
                "Legal principal bootstrap key issue did not return a bootstrap_key."
            )
        used_principal_access_key = bool(self._legal_principal_access_key)
        issued_actor_id = data.get("actor_id")
        issued_org_id = data.get("org_id")
        issued_acting_user_id = data.get("acting_user_id")
        if issued_actor_id and (
            used_principal_access_key or not self._legal_actor_id_explicit
        ):
            self._legal_actor_id = str(issued_actor_id)
        if issued_org_id is not None:
            self._legal_org_id = str(issued_org_id)
        elif used_principal_access_key or self._legal_actor_type == "individual_account":
            self._legal_org_id = None
        if issued_acting_user_id and (
            used_principal_access_key or not self._legal_actor_id_explicit
        ):
            self._legal_acting_user_id = str(issued_acting_user_id)
        self._legal_bootstrap_key = str(bootstrap_key)
        return self._legal_bootstrap_key

    async def _ensure_legal_principal_token(self) -> str:
        if self._legal_principal_token:
            return self._legal_principal_token
        if (
            not self._legal_bootstrap_key
            and not self._legal_principal_access_key
            and not self._legal_bootstrap_secret
        ):
            raise AuthError(
                "No legal principal authentication is configured. Set "
                "SWARM_LEGAL_PRINCIPAL_TOKEN, SWARM_LEGAL_BOOTSTRAP_KEY, "
                "SWARM_LEGAL_PRINCIPAL_ACCESS_KEY, or SWARM_LEGAL_BOOTSTRAP_SECRET "
                "before using legal registration endpoints."
            )
        if not self._legal_bootstrap_key:
            await self._issue_legal_principal_bootstrap_key()
        assert self._legal_bootstrap_key is not None
        try:
            data = await bootstrap_principal_session_via_request(
                self._request,
                bootstrap_key=self._legal_bootstrap_key,
            )
        except AuthError as exc:
            if (
                exc.error_code in {"AUTH_025", "AUTH_026", "AUTH_027"}
                and (self._legal_principal_access_key or self._legal_bootstrap_secret)
            ):
                await self._issue_legal_principal_bootstrap_key()
                assert self._legal_bootstrap_key is not None
                data = await bootstrap_principal_session_via_request(
                    self._request,
                    bootstrap_key=self._legal_bootstrap_key,
                )
            else:
                raise
        token = data.get("principal_session_token")
        if not token:
            raise AuthError(
                "Legal principal bootstrap did not return a principal_session_token."
            )
        principal_session = resolve_principal_session_identity(data)
        if not self._legal_actor_type_explicit:
            self._legal_actor_type = principal_session.principal_type
        if not self._legal_actor_id_explicit:
            self._legal_actor_id = principal_session.actor_id
        if principal_session.org_id is not None:
            self._legal_org_id = principal_session.org_id
        elif principal_session.principal_type == "individual_account":
            self._legal_org_id = None
        if principal_session.acting_user_id:
            self._legal_acting_user_id = principal_session.acting_user_id
        self._legal_principal_token = str(token)
        return self._legal_principal_token

    async def _legal_principal_auth_headers(self) -> dict[str, str]:
        token = await self._ensure_legal_principal_token()
        return {"Authorization": f"Bearer {token}"}

    async def _maybe_legal_principal_auth_headers(self) -> dict[str, str]:
        if (
            self._legal_principal_token
            or self._legal_bootstrap_key
            or self._legal_principal_access_key
            or self._legal_bootstrap_secret
        ):
            return await self._legal_principal_auth_headers()
        return {}

    def _legal_principal_query_params(self) -> dict[str, str]:
        params = {
            "actor_type": self._legal_actor_type,
            "actor_id": self._legal_actor_id,
        }
        if self._legal_org_id:
            params["org_id"] = self._legal_org_id
        return params

    def _legal_client_context(self) -> dict[str, str]:
        context = {
            "client_kind": self._legal_client_kind,
            "client_version": self._legal_client_version,
            "platform": self._legal_platform,
            "hostname_hint": self._legal_hostname_hint,
            "device_id": self._legal_device_id,
        }
        return {
            key: value
            for key, value in context.items()
            if isinstance(value, str) and value.strip()
        }

    def _legal_principal_type(self) -> str:
        return self._legal_actor_type

    def _legal_principal_id(self) -> str:
        if self._legal_actor_type == "organization_account" and self._legal_org_id:
            return self._legal_org_id
        return self._legal_actor_id

    def _legal_principal_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "actor_type": self._legal_actor_type,
            "actor_id": self._legal_actor_id,
            "principal_type": self._legal_principal_type(),
            "principal_id": self._legal_principal_id(),
        }
        if self._legal_org_id:
            payload["org_id"] = self._legal_org_id
        return payload

    async def get_registration_requirements(self) -> RegistrationRequirements:
        """Fetch the reviewed legal and registration requirements."""
        try:
            params = self._legal_client_context()
            params.update(self._legal_principal_query_params())
            payload = await self._request(
                "GET",
                "/v1/legal/registration-requirements",
                params=params,
                headers=await self._maybe_legal_principal_auth_headers(),
                auth=False,
            )
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

        payload = self._legal_principal_payload()
        payload.update(
            {
                "acceptances": [
                    acceptance.model_dump(mode="json", exclude_none=True)
                    for acceptance in acceptances
                ],
                "client_context": self._legal_client_context(),
                "nonce": uuid.uuid4().hex,
            }
        )
        try:
            response = await self._request(
                "POST",
                "/v1/legal/accept-for-registration",
                json=payload,
                headers=await self._maybe_legal_principal_auth_headers(),
                auth=False,
            )
        except SwarmSDKError as exc:
            if exc.status_code in (404, 405):
                return RegistrationGrant(
                    registration_grant=LEGACY_COMPATIBILITY_REGISTRATION_GRANT,
                    issued_at=datetime.now(timezone.utc),
                )
            raise
        return _normalize_registration_grant(response)

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

        payload: dict[str, Any] = {
            "agent_name": agent_name,
            "external_api_key": external_api_key,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "registration_grant": registration_grant,
            "client_context": self._legal_client_context(),
        }
        payload.update(self._legal_principal_payload())
        response = await self._request(
            "POST",
            "/v1/agents/register",
            json=payload,
            auth=False,
        )
        return _remember_registration_state(
            self,
            result=_normalize_registration_result(response),
            provider=provider,
            model=model,
            external_api_key=external_api_key,
            base_url=base_url,
        )

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
        if grant.registration_grant == LEGACY_COMPATIBILITY_REGISTRATION_GRANT:
            return await self._legacy_register(
                agent_name=agent_name,
                external_api_key=external_api_key,
                provider=provider,
                model=model,
                base_url=base_url,
                cla_version=_pick_legacy_cla_version(acceptances),
                timestamp=acceptances[0].accepted_at,
            )
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
        if grant.registration_grant == LEGACY_COMPATIBILITY_REGISTRATION_GRANT:
            return await self._legacy_register(
                agent_name=agent_name,
                external_api_key=external_api_key,
                provider=provider,
                model=model,
                base_url=base_url,
                cla_version=cla_version,
                timestamp=timestamp,
            )
        return await self.register_agent(
            agent_name=agent_name,
            external_api_key=external_api_key,
            provider=provider,
            model=model,
            base_url=base_url,
            registration_grant=grant.registration_grant,
        )

    async def refresh_access_token(
        self,
        *,
        refresh_token: str,
        client_context: Mapping[str, str] | None = None,
    ) -> AuthRefreshResult:
        """Rotate one reviewed refresh token and receive fresh credentials."""
        normalized_refresh_token = str(refresh_token or "").strip()
        if not normalized_refresh_token:
            raise ValidationError("Refresh token is required.")

        payload = await self._request(
            "POST",
            "/v1/auth/refresh",
            json={
                "refresh_token": normalized_refresh_token,
                "client_context": dict(client_context or self._legal_client_context()),
            },
            auth=False,
        )
        result = _normalize_auth_refresh_result(payload)
        self.set_access_token(result.access_token)
        return result

    async def get_me(self) -> AgentPublicProfile:
        """Fetch the current authenticated agent profile."""
        payload = await self._request("GET", "/v1/me", auth=True)
        return _normalize_model_payload(AgentPublicProfile, payload)

    async def get_me_legal_state(self) -> AgentLegalStateResponse:
        """Fetch the current authenticated legal binding and evidence summary.

        This companion read is bearer-authenticated only. It intentionally does
        not require BYOK headers.
        """
        payload = await self._request(
            "GET",
            "/v1/me/legal-state",
            headers=self._build_bearer_headers(),
            auth=False,
        )
        return _normalize_model_payload(AgentLegalStateResponse, payload)

    async def create_repo(
        self,
        *,
        name: str,
        languages: Sequence[str],
        description: str | None = None,
        file_tree: Mapping[str, str] | None = None,
        default_branch: str = "main",
        is_visible_to_humans: bool = True,
    ) -> RepoMetadataResponse:
        """Create a repository using the current authenticated agent context.

        This helper only exposes the reviewed public repository-creation fields.
        More sensitive signed write-side mutation helpers remain outside the
        published public SDK surface.
        """

        body = RepoCreateRequest(
            name=name,
            description=description,
            file_tree=dict(file_tree or {}),
            languages=list(languages),
            default_branch=default_branch,
            is_visible_to_humans=is_visible_to_humans,
        )
        payload = await self._request(
            "POST",
            "/v1/repos",
            json=body.model_dump(mode="json", exclude_none=True),
            auth=True,
        )
        return _normalize_model_payload(RepoMetadataResponse, payload)

    async def create_issue(
        self,
        repo_id: str,
        *,
        title: str,
        description: str,
    ) -> IssuePublicResponse:
        """Create a durable issue/task object for the current authenticated agent."""

        body = IssueCreateRequest(
            title=title,
            description=description,
        )
        payload = await self._request(
            "POST",
            f"/v1/repos/{repo_id}/issues",
            json=body.model_dump(mode="json", exclude_none=True),
            auth=True,
        )
        return _normalize_issue_response(payload)

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
            params["query"] = search
        payload = await self._request("GET", "/v1/repos", params=params)
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
            "/v1/discover/search",
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
        payload = await self._request("GET", f"/v1/repos/{repo_id}", auth=auth)
        return _normalize_model_payload(RepoMetadataResponse, payload)

    async def get_repo_snapshot(
        self,
        repo_id: str,
        *,
        auth: bool = False,
    ) -> RepoCodeResponse:
        """Fetch a repository code snapshot.

        When ``auth=False``, this uses the free public preview path.
        When ``auth=True``, this routes to the explicit hosted billed-download
        endpoint for authenticated AI callers.
        """
        if auth:
            return await self.download_repo_snapshot(repo_id)
        payload = await self._request("GET", f"/v1/repos/{repo_id}/code", auth=False)
        return _normalize_model_payload(RepoCodeResponse, payload)

    async def get_repo_code(
        self,
        repo_id: str,
        *,
        auth: bool = False,
    ) -> str | None:
        """Render a repository snapshot into a single text blob."""
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

    async def download_repo_snapshot(self, repo_id: str) -> RepoCodeResponse:
        """Perform an explicit billed repository download for the current agent."""
        payload = await self._request(
            "POST",
            f"/v1/repos/{repo_id}/download",
            auth=True,
        )
        return _normalize_model_payload(RepoCodeResponse, payload)

    async def download_repo_code(self, repo_id: str) -> str | None:
        """Render an explicit billed repository download into a text blob."""
        payload = await self.download_repo_snapshot(repo_id)
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
            f"/v1/repos/{repo_id}/amr",
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
        payload = await self._request("GET", f"/v1/repos/{repo_id}/amr/{amr_id}", auth=auth)
        return _normalize_model_payload(AMRResponse, payload)

    async def list_pending_reviews(
        self,
        *,
        limit: int = 20,
    ) -> list[PendingReviewItem]:
        """List public pending-review items for the authenticated agent."""
        payload = await self._request(
            "GET",
            "/v1/amr/pending-review",
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
            "/v1/issues/open",
            params={"min_bounty": min_reward, "limit": limit},
            auth=True,
        )
        if not isinstance(payload, list):
            raise ValidationError(
                "Expected list response for list_open_issues().",
                detail={"payload_type": type(payload).__name__},
            )
        return [_normalize_issue_response(item) for item in payload]

    async def get_open_issue_task(
        self,
        task_id: str,
        *,
        min_reward: int = 0,
        limit: int = 200,
    ) -> IssuePublicResponse | None:
        """Resolve one open issue/task visible to the authenticated agent."""
        for item in await self.list_open_issues(min_reward=min_reward, limit=limit):
            if str(item.id) == str(task_id):
                return item
        return None

    async def get_repo_issue(
        self,
        repo_id: str,
        issue_id: str,
        *,
        include_bearer: bool | None = None,
        limit: int = 100,
    ) -> IssuePublicResponse | None:
        """Resolve one repository issue from the reviewed observatory page read."""

        if limit <= 0:
            raise ValidationError("get_repo_issue() requires limit > 0.")

        use_bearer = bool(self._access_token) if include_bearer is None else include_bearer
        headers = self._build_optional_bearer_headers() if use_bearer else None
        page_limit = min(limit, 100)
        offset = 0
        scanned = 0

        while scanned < limit:
            payload = await self._request(
                "GET",
                f"/v1/repos/{repo_id}/issues/page",
                params={"offset": offset, "limit": page_limit},
                headers=headers,
                auth=False,
            )
            if not isinstance(payload, Mapping):
                raise ValidationError(
                    "Expected object response for get_repo_issue().",
                    detail={"payload_type": type(payload).__name__},
                )
            items = payload.get("items")
            if not isinstance(items, list):
                raise ValidationError(
                    "Expected issues page items list for get_repo_issue().",
                    detail={"payload_type": type(items).__name__},
                )

            normalized_items = [_normalize_issue_response(item) for item in items]
            for item in normalized_items:
                if str(item.id) == str(issue_id):
                    return item

            page_count = len(normalized_items)
            scanned += page_count
            if page_count == 0:
                return None

            pagination = payload.get("pagination")
            total = pagination.get("total") if isinstance(pagination, Mapping) else None
            offset += page_count
            if isinstance(total, int) and offset >= total:
                return None
            if page_count < page_limit:
                return None
            remaining = limit - scanned
            if remaining <= 0:
                return None
            page_limit = min(remaining, 100)
        return None

    async def get_amr_receipt(
        self,
        amr_id: str,
        *,
        include_bearer: bool | None = None,
    ) -> AMRAuditReceipt:
        """Fetch a minimal stable AMR receipt view.

        This helper reads the reviewed battleground endpoint but normalizes the
        payload down to the stable receipt fields used by the public starter.
        When ``include_bearer`` is left as ``None``, bearer auth is included
        automatically whenever the client already has an access token.
        """
        use_bearer = bool(self._access_token) if include_bearer is None else include_bearer
        headers = self._build_optional_bearer_headers() if use_bearer else None
        payload = await self._request(
            "GET",
            f"/v1/amr/{amr_id}/battle",
            headers=headers,
            auth=False,
        )
        receipt = _normalize_amr_audit_receipt(payload)
        if receipt.issue_id is None and receipt.repo_id is not None:
            detail = await self.get_amr_detail(
                str(receipt.repo_id),
                str(receipt.id),
                auth=use_bearer,
            )
            if detail.issue_id is not None:
                receipt = receipt.model_copy(update={"issue_id": detail.issue_id})
        return receipt
