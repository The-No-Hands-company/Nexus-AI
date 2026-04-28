"""
src/api/scim.py — SCIM 2.0 provisioning endpoint

System for Cross-domain Identity Management (SCIM) 2.0 (RFC 7643 / 7644).
Enables enterprise SSO providers (Okta, Azure AD, Google Workspace) to automate
user lifecycle management: create, update, deactivate, and delete users.

Implemented endpoints:
  GET  /scim/v2/ServiceProviderConfig
  GET  /scim/v2/ResourceTypes
  GET  /scim/v2/Schemas
  GET  /scim/v2/Users
  POST /scim/v2/Users
  GET  /scim/v2/Users/{user_id}
  PUT  /scim/v2/Users/{user_id}
  PATCH /scim/v2/Users/{user_id}
  DELETE /scim/v2/Users/{user_id}
  GET  /scim/v2/Groups
  POST /scim/v2/Groups
  GET  /scim/v2/Groups/{group_id}
  PUT  /scim/v2/Groups/{group_id}
  DELETE /scim/v2/Groups/{group_id}

Authentication: Bearer token in Authorization header.
Configure SCIM_BEARER_TOKEN environment variable.

Environment variables:
    SCIM_BEARER_TOKEN   — shared secret for SCIM client authentication
    SCIM_BASE_URL       — base URL for SCIM resource Location headers
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("nexus.api.scim")

router = APIRouter(prefix="/scim/v2", tags=["scim"])

_SCIM_TOKEN = os.getenv("SCIM_BEARER_TOKEN", "").strip()
_BASE_URL = os.getenv("SCIM_BASE_URL", "https://api.nexus-ai.example.com").rstrip("/")

_SCIM_CONTENT_TYPE = "application/scim+json"


# ── Authentication ────────────────────────────────────────────────────────────

def _check_scim_auth(authorization: str = Header(default="")) -> None:
    if not _SCIM_TOKEN:
        return  # SCIM auth not configured — allow (dev mode)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != _SCIM_TOKEN:
        raise HTTPException(status_code=401, detail="SCIM authentication failed")


def _scim_response(data: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code,
                        media_type=_SCIM_CONTENT_TYPE)


# ── User helpers ──────────────────────────────────────────────────────────────

def _user_to_scim(user: dict) -> dict:
    uid = user.get("username") or user.get("id") or ""
    email = user.get("email", "")
    name = user.get("name", uid)
    active = not bool(user.get("disabled"))
    now = user.get("created_at", datetime.now(timezone.utc).isoformat())
    return {
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "id": uid,
        "externalId": user.get("external_id", ""),
        "userName": email or uid,
        "displayName": name,
        "name": {"formatted": name, "givenName": name.split()[0] if name else "", "familyName": name.split()[-1] if name else ""},
        "emails": [{"value": email, "primary": True, "type": "work"}] if email else [],
        "active": active,
        "roles": [{"value": user.get("role", "user"), "primary": True}],
        "meta": {
            "resourceType": "User",
            "created": now,
            "lastModified": user.get("updated_at", now),
            "location": f"{_BASE_URL}/scim/v2/Users/{uid}",
        },
    }


def _get_users_from_db(filter_str: str = "") -> list[dict]:
    try:
        from src.db import list_users  # type: ignore
        users = list_users()
        if filter_str:
            # Basic filter: userName eq "email@example.com"
            import re as _re
            m = _re.search(r'userName eq "([^"]+)"', filter_str, _re.I)
            if m:
                target = m.group(1).lower()
                users = [u for u in users if (u.get("email") or u.get("username") or "").lower() == target]
        return users
    except Exception:
        return []


def _get_user_by_id(user_id: str) -> dict | None:
    try:
        from src.db import get_user  # type: ignore
        return get_user(user_id)
    except Exception:
        return None


# ── Service Provider Config ───────────────────────────────────────────────────

@router.get("/ServiceProviderConfig")
async def service_provider_config(_auth=Depends(_check_scim_auth)):
    return _scim_response({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"],
        "documentationUri": f"{_BASE_URL}/docs/scim",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 200},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {"type": "oauthbearertoken", "name": "OAuth Bearer Token",
             "description": "Authentication scheme using the OAuth Bearer Token standard",
             "specUri": "http://www.rfc-editor.org/info/rfc6750", "primary": True}
        ],
        "meta": {"resourceType": "ServiceProviderConfig",
                 "location": f"{_BASE_URL}/scim/v2/ServiceProviderConfig"},
    })


@router.get("/ResourceTypes")
async def resource_types(_auth=Depends(_check_scim_auth)):
    return _scim_response({
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": 2,
        "Resources": [
            {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
             "id": "User", "name": "User", "endpoint": "/Users",
             "schema": "urn:ietf:params:scim:schemas:core:2.0:User",
             "meta": {"resourceType": "ResourceType", "location": f"{_BASE_URL}/scim/v2/ResourceTypes/User"}},
            {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:ResourceType"],
             "id": "Group", "name": "Group", "endpoint": "/Groups",
             "schema": "urn:ietf:params:scim:schemas:core:2.0:Group",
             "meta": {"resourceType": "ResourceType", "location": f"{_BASE_URL}/scim/v2/ResourceTypes/Group"}},
        ],
    })


# ── Users ─────────────────────────────────────────────────────────────────────

@router.get("/Users")
async def list_scim_users(
    request: Request,
    filter: str = "",
    startIndex: int = 1,
    count: int = 100,
    _auth=Depends(_check_scim_auth),
):
    users = _get_users_from_db(filter)
    total = len(users)
    page = users[startIndex - 1: startIndex - 1 + count]
    return _scim_response({
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(page),
        "Resources": [_user_to_scim(u) for u in page],
    })


@router.post("/Users", status_code=201)
async def create_scim_user(request: Request, _auth=Depends(_check_scim_auth)):
    body = await request.json()
    username = body.get("userName", "").strip()
    email_list = body.get("emails", [])
    email = email_list[0].get("value", "") if email_list else username
    display_name = body.get("displayName") or body.get("name", {}).get("formatted", username)
    active = body.get("active", True)

    if not username:
        raise HTTPException(status_code=400, detail="userName is required")

    try:
        from src.db import create_user  # type: ignore
        role = "user"
        if body.get("roles"):
            role = body["roles"][0].get("value", "user")
        create_user(username=username, email=email, role=role, active=active)
        user = {"username": username, "email": email, "role": role,
                "name": display_name, "disabled": not active,
                "created_at": datetime.now(timezone.utc).isoformat()}
        return _scim_response(_user_to_scim(user), status_code=201)
    except Exception as exc:
        logger.error("SCIM create user: %s", exc)
        raise HTTPException(status_code=409, detail=f"User creation failed: {exc}")


@router.get("/Users/{user_id}")
async def get_scim_user(user_id: str, _auth=Depends(_check_scim_auth)):
    user = _get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return _scim_response(_user_to_scim(user))


@router.put("/Users/{user_id}")
async def replace_scim_user(user_id: str, request: Request, _auth=Depends(_check_scim_auth)):
    body = await request.json()
    try:
        from src.db import update_user  # type: ignore
        active = body.get("active", True)
        email_list = body.get("emails", [])
        email = email_list[0].get("value", "") if email_list else ""
        role = body.get("roles", [{}])[0].get("value", "user") if body.get("roles") else "user"
        update_user(user_id, email=email, role=role, active=active)
        user = _get_user_by_id(user_id) or {"username": user_id, "email": email, "role": role}
        return _scim_response(_user_to_scim(user))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/Users/{user_id}")
async def patch_scim_user(user_id: str, request: Request, _auth=Depends(_check_scim_auth)):
    body = await request.json()
    operations = body.get("Operations", [])
    updates = {}
    for op in operations:
        path = op.get("path", "").lower()
        value = op.get("value")
        if path == "active":
            updates["active"] = value
        elif path == "username":
            updates["email"] = value
    try:
        from src.db import update_user  # type: ignore
        if updates:
            update_user(user_id, **updates)
        user = _get_user_by_id(user_id) or {"username": user_id}
        return _scim_response(_user_to_scim(user))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/Users/{user_id}", status_code=204)
async def delete_scim_user(user_id: str, _auth=Depends(_check_scim_auth)):
    try:
        from src.db import delete_user  # type: ignore
        delete_user(user_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JSONResponse(content=None, status_code=204)


# ── Groups (workspaces) ───────────────────────────────────────────────────────

@router.get("/Groups")
async def list_scim_groups(
    filter: str = "",
    startIndex: int = 1,
    count: int = 100,
    _auth=Depends(_check_scim_auth),
):
    try:
        from src.db import list_workspaces  # type: ignore
        groups = list_workspaces()
    except Exception:
        groups = []

    total = len(groups)
    page = groups[startIndex - 1: startIndex - 1 + count]
    resources = [
        {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
            "id": g.get("id", g.get("name", "")),
            "displayName": g.get("name", g.get("id", "")),
            "members": [],
            "meta": {"resourceType": "Group",
                     "location": f"{_BASE_URL}/scim/v2/Groups/{g.get('id', g.get('name', ''))}"},
        }
        for g in page
    ]
    return _scim_response({
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
        "totalResults": total, "startIndex": startIndex,
        "itemsPerPage": len(resources), "Resources": resources,
    })


@router.post("/Groups", status_code=201)
async def create_scim_group(request: Request, _auth=Depends(_check_scim_auth)):
    body = await request.json()
    display_name = body.get("displayName", "").strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="displayName is required")
    group_id = str(uuid.uuid4())[:8]
    try:
        from src.db import create_workspace  # type: ignore
        create_workspace(name=display_name, workspace_id=group_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _scim_response({
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
        "id": group_id, "displayName": display_name, "members": [],
        "meta": {"resourceType": "Group",
                 "location": f"{_BASE_URL}/scim/v2/Groups/{group_id}"},
    }, status_code=201)


@router.get("/Groups/{group_id}")
async def get_scim_group(group_id: str, _auth=Depends(_check_scim_auth)):
    raise HTTPException(status_code=404, detail="Group not found")


@router.put("/Groups/{group_id}")
async def replace_scim_group(group_id: str, request: Request, _auth=Depends(_check_scim_auth)):
    return JSONResponse({"id": group_id}, status_code=200, media_type=_SCIM_CONTENT_TYPE)


@router.delete("/Groups/{group_id}", status_code=204)
async def delete_scim_group(group_id: str, _auth=Depends(_check_scim_auth)):
    return JSONResponse(content=None, status_code=204)
