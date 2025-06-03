# a2a_server/security/auth.py
from __future__ import annotations

import os
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

__all__ = ["require_admin_token"]

_bearer = HTTPBearer(auto_error=False)


def require_admin_token(
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
):  # noqa: D401 - imperative helper
    """Guard that **rejects** unless `Authorization: Bearer <token>` matches
    `$A2A_ADMIN_TOKEN`.  If the env-var is **unset** we assume *dev mode* and
    allow all traffic (so `pytest` keeps working).
    """
    expected = os.getenv("A2A_ADMIN_TOKEN")
    if expected is None:  # dev‑mode shortcut
        return None

    if not creds or creds.credentials != expected:
        raise HTTPException(status_code=401, detail="unauthorised")

    return creds.credentials