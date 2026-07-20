from __future__ import annotations

import json
from typing import Any

from fastapi import Header, HTTPException

from core.settings import settings


ROLE_LEVELS: dict[str, int] = {
    "viewer": 10,
    "operator": 20,
    "admin": 30,
}


def _normalize_role(value: Any) -> str | None:
    role = str(value or "").strip().lower()
    if role in ROLE_LEVELS:
        return role
    return None


def _load_key_roles() -> dict[str, str]:
    raw = str(getattr(settings, "api_key_roles_json", "{}") or "{}")
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, role in payload.items():
        api_key = str(key or "").strip()
        normalized = _normalize_role(role)
        if api_key and normalized:
            out[api_key] = normalized
    return out


def _extract_api_key(x_api_key: str | None, authorization: str | None) -> str | None:
    key = str(x_api_key or "").strip()
    if key:
        return key
    auth = str(authorization or "").strip()
    if not auth:
        return None
    prefix = "bearer "
    if auth.lower().startswith(prefix):
        token = auth[len(prefix):].strip()
        return token or None
    return None


def resolve_api_role(x_api_key: str | None, authorization: str | None = None) -> str | None:
    api_key = _extract_api_key(x_api_key, authorization)
    if not api_key:
        return None
    return _load_key_roles().get(api_key)


def require_role(required_role: str):
    required = _normalize_role(required_role) or "operator"

    async def _dependency(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> None:
        if not bool(getattr(settings, "api_auth_enabled", False)):
            return

        role = resolve_api_role(x_api_key, authorization)
        if role is None:
            raise HTTPException(status_code=401, detail="Missing or invalid API key")

        if ROLE_LEVELS.get(role, 0) < ROLE_LEVELS.get(required, 0):
            raise HTTPException(status_code=403, detail=f"Insufficient role: requires {required}")

    return _dependency
