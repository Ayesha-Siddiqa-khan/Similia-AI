"""Verify Supabase identities and trusted roles before privileged access.

Roles live in `app_metadata.similia_role` (server-controlled, never user_metadata).
Operators/admins manage the knowledge base; practitioners also take patient cases.
"""

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.supabase import get_supabase_admin_client

bearer = HTTPBearer(auto_error=False)

OPERATOR_ROLES = ("operator", "admin")
PRACTITIONER_ROLES = ("practitioner", *OPERATOR_ROLES)


def _verified_user_id(
    credentials: HTTPAuthorizationCredentials | None, roles: tuple[str, ...], denied: str
) -> str:
    if credentials is None:
        raise HTTPException(401, "Sign in to continue")
    try:
        user = get_supabase_admin_client().auth.get_user(credentials.credentials).user
    except Exception:
        raise HTTPException(401, "Session could not be verified") from None
    if user is None:
        raise HTTPException(401, "Session could not be verified")
    if user.app_metadata.get("similia_role") not in roles:
        raise HTTPException(403, denied)
    return str(user.id)


def require_operator(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    return _verified_user_id(credentials, OPERATOR_ROLES, "A Similia operator role is required")


def require_practitioner(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    """Return the verified user id of a practitioner (or operator/admin)."""
    return _verified_user_id(
        credentials, PRACTITIONER_ROLES, "A Similia practitioner role is required"
    )
