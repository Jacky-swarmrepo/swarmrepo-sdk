"""Principal session identity normalization for the public SDK."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PrincipalSessionIdentity:
    principal_type: str
    principal_id: str
    actor_type: str
    actor_id: str
    org_id: str | None
    acting_user_id: str | None


def resolve_principal_session_identity(
    payload: Mapping[str, Any],
) -> PrincipalSessionIdentity:
    """Normalize a bootstrap-session payload into canonical principal fields."""
    principal_type = str(payload.get("principal_type") or payload.get("actor_type") or "").strip()
    if principal_type not in {"individual_account", "organization_account"}:
        raise ValueError("principal session payload is missing a valid principal_type")

    actor_id = str(payload.get("actor_id") or payload.get("principal_id") or "").strip()
    if not actor_id:
        raise ValueError("principal session payload is missing actor_id")

    org_id = str(payload["org_id"]).strip() if payload.get("org_id") else None
    principal_id = str(
        payload.get("principal_id")
        or (org_id if principal_type == "organization_account" and org_id else actor_id)
    ).strip()
    if not principal_id:
        raise ValueError("principal session payload is missing principal_id")

    request_actor_context = payload.get("request_actor_context")
    if request_actor_context is not None and not isinstance(request_actor_context, Mapping):
        raise ValueError("principal session request_actor_context must be an object")

    request_actor_type = (
        str(request_actor_context.get("actor_type")).strip()
        if isinstance(request_actor_context, Mapping) and request_actor_context.get("actor_type")
        else None
    )
    if request_actor_type and request_actor_type != "human":
        raise ValueError("principal session request_actor_context must resolve to a human actor")

    acting_user_id = None
    if isinstance(request_actor_context, Mapping) and request_actor_context.get("actor_user_id"):
        acting_user_id = str(request_actor_context["actor_user_id"]).strip()
    elif payload.get("acting_user_id"):
        acting_user_id = str(payload["acting_user_id"]).strip()

    return PrincipalSessionIdentity(
        principal_type=principal_type,
        principal_id=principal_id,
        actor_type=str(payload.get("actor_type") or principal_type).strip(),
        actor_id=actor_id,
        org_id=org_id if principal_type == "organization_account" else None,
        acting_user_id=acting_user_id or None,
    )


__all__ = [
    "PrincipalSessionIdentity",
    "resolve_principal_session_identity",
]
