from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from core.auth import require_role, resolve_api_role
from core.settings import settings


def test_resolve_api_role_supports_header_and_bearer_token() -> None:
    old_enabled = settings.api_auth_enabled
    old_roles = settings.api_key_roles_json
    try:
        settings.api_auth_enabled = True
        settings.api_key_roles_json = '{"adminkey":"admin","opkey":"operator"}'
        assert resolve_api_role("adminkey", None) == "admin"
        assert resolve_api_role(None, "Bearer opkey") == "operator"
    finally:
        settings.api_auth_enabled = old_enabled
        settings.api_key_roles_json = old_roles

def test_require_role_enforces_permissions_when_auth_enabled() -> None:
    old_enabled = settings.api_auth_enabled
    old_roles = settings.api_key_roles_json
    try:
        settings.api_auth_enabled = True
        settings.api_key_roles_json = '{"adminkey":"admin","opkey":"operator"}'
        dep_operator = require_role("operator")
        dep_admin = require_role("admin")

        asyncio.run(dep_operator(x_api_key="opkey", authorization=None))
        asyncio.run(dep_admin(x_api_key="adminkey", authorization=None))

        with pytest.raises(HTTPException) as missing:
            asyncio.run(dep_operator(x_api_key=None, authorization=None))
        assert missing.value.status_code == 401

        with pytest.raises(HTTPException) as denied:
            asyncio.run(dep_admin(x_api_key="opkey", authorization=None))
        assert denied.value.status_code == 403
    finally:
        settings.api_auth_enabled = old_enabled
        settings.api_key_roles_json = old_roles


def test_require_role_is_noop_when_auth_disabled() -> None:
    old_enabled = settings.api_auth_enabled
    old_roles = settings.api_key_roles_json
    try:
        settings.api_auth_enabled = False
        settings.api_key_roles_json = "{}"
        dep_admin = require_role("admin")
        asyncio.run(dep_admin(x_api_key=None, authorization=None))
    finally:
        settings.api_auth_enabled = old_enabled
        settings.api_key_roles_json = old_roles
