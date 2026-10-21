from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.services.supabase_gateway import AuthenticatedUser, SupabaseGateway


CurrentUser = AuthenticatedUser
bearer = HTTPBearer(auto_error=False)


def get_supabase_gateway(request: Request) -> SupabaseGateway:
    gateway = getattr(request.app.state, "supabase_gateway", None)
    if gateway is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "persistence_unavailable", "message": "The persistent workspace service is unavailable."},
        )
    return gateway


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    gateway: Annotated[SupabaseGateway, Depends(get_supabase_gateway)],
) -> CurrentUser:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required", "message": "Sign in to continue."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return gateway.verify_user(credentials.credentials)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_access_token", "message": "Your session has expired. Sign in again."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def get_current_user_if_configured(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> CurrentUser | None:
    """Require authentication whenever persistent workspaces are configured.

    The unconfigured branch preserves the repository's local scratch workflow
    and makes deterministic screening tests independent of Supabase. A deployed
    app with Supabase configured always takes the authenticated branch.
    """
    gateway = getattr(request.app.state, "supabase_gateway", None)
    if gateway is None:
        return None
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required", "message": "Sign in to continue."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return gateway.verify_user(credentials.credentials)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_access_token", "message": "Your session has expired. Sign in again."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

