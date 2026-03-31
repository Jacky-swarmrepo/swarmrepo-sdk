"""High-level legal principal bootstrap helpers for the public SDK."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


RequestExecutor = Callable[..., Awaitable[dict[str, Any]]]


async def issue_principal_bootstrap_key_via_request(
    request: RequestExecutor,
    *,
    actor_type: str,
    bootstrap_secret: str | None = None,
    principal_access_key: str | None = None,
    actor_id: str | None = None,
    org_id: str | None = None,
    acting_user_id: str | None = None,
    label: str | None = None,
    ttl_sec: int | None = None,
) -> dict[str, Any]:
    """Issue a principal bootstrap key through the reviewed public/private bridge."""
    if principal_access_key:
        return await request(
            "POST",
            "/v1/legal/principal-bootstrap-keys/issue",
            json={
                "actor_type": actor_type,
                "org_id": org_id,
                "label": label,
                "ttl_sec": ttl_sec,
            },
            headers={"Authorization": f"Bearer {principal_access_key}"},
            auth=False,
        )
    if not bootstrap_secret or not actor_id or not acting_user_id:
        raise ValueError(
            "bootstrap_secret, actor_id, and acting_user_id are required when "
            "principal_access_key is not provided."
        )
    return await request(
        "POST",
        "/api/v1/internal/legal/principal-bootstrap-keys/issue",
        json={
            "actor_type": actor_type,
            "actor_id": actor_id,
            "org_id": org_id,
            "acting_user_id": acting_user_id,
            "label": label,
            "ttl_sec": ttl_sec,
        },
        headers={"X-Legal-Bootstrap-Secret": bootstrap_secret},
        auth=False,
    )


async def bootstrap_principal_session_via_request(
    request: RequestExecutor,
    *,
    bootstrap_key: str,
    ttl_sec: int | None = None,
) -> dict[str, Any]:
    """Exchange a bootstrap key for a reviewed principal session token."""
    return await request(
        "POST",
        "/api/v1/internal/legal/principal-sessions/bootstrap",
        json={"ttl_sec": ttl_sec} if ttl_sec is not None else {},
        headers={"Authorization": f"Bearer {bootstrap_key}"},
        auth=False,
    )


__all__ = [
    "bootstrap_principal_session_via_request",
    "issue_principal_bootstrap_key_via_request",
]
