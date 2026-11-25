"""Read access through the existing Centinela identity validation contract."""

import re

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer

bearer_dependency = Depends(HTTPBearer(auto_error=False))


def analytics_read_access(request: Request, _credentials=bearer_dependency) -> None:
    settings = request.app.state.settings
    if settings.environment == "local":
        return
    if settings.identity_validation_url is None:
        raise HTTPException(
            503,
            detail={
                "code": "integration_pending",
                "message": "Centinela identity is not configured",
            },
        )
    if not settings.identity_allowed_users:
        raise HTTPException(
            503,
            detail={
                "code": "access_policy_unconfigured",
                "message": "Analytical access policy is not configured",
            },
        )
    if request.method not in ("GET", "HEAD"):
        raise HTTPException(
            403,
            detail={
                "code": "analytics_read_only",
                "message": "Remote analytical processing is disabled",
            },
        )
    authorization = request.headers.get("authorization", "")
    if not re.fullmatch(r"Bearer [A-Za-z0-9_.~-]{20,8192}", authorization):
        raise HTTPException(
            401,
            detail={"code": "token_not_valid", "message": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        with httpx.Client(
            timeout=settings.identity_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(
                str(settings.identity_validation_url),
                headers={"Authorization": authorization},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            503,
            detail={
                "code": "identity_unavailable",
                "message": "Centinela identity is unavailable",
            },
        ) from exc
    if response.status_code in (401, 403):
        raise HTTPException(
            response.status_code,
            detail={
                "code": (
                    "token_not_valid"
                    if response.status_code == 401
                    else "identity_forbidden"
                ),
                "message": "Access denied",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = response.headers.get("x-authenticated-user-id", "")
    if (
        response.status_code != 204
        or not re.fullmatch(r"[A-Za-z0-9]{1,128}", principal)
        or response.headers.get("x-authenticated-token-type") != "access"
    ):
        raise HTTPException(
            503,
            detail={
                "code": "identity_contract_error",
                "message": "Invalid identity validation response",
            },
        )
    if principal not in settings.identity_allowed_users:
        raise HTTPException(
            403,
            detail={
                "code": "analytics_forbidden",
                "message": "Analytical access has not been granted",
            },
        )
    request.state.analytics_principal = principal
