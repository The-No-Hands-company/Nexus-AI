"""Organisation routes.

Extracted from src/api/routes.py for maintainability.
Covers: org CRUD, members, invites, GDPR, API keys,
per-org data isolation (chats, usage, memory, RAG).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ._helpers import (
    _api_error,
    _get_token_role,
    _read_json_body,
    require_auth,
    require_admin,
)

router = APIRouter(prefix="", tags=["orgs"])


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Organisation routes
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/orgs")
async def create_org(request: Request):
    """Create a new organisation."""
    username = require_auth(request)
    body = await request.json()
    name = str(body.get("name", "")).strip()
    if not name:
        return _api_error("'name' is required", "invalid_request_error", 400)
    from ..orgs import create_org as _create_org
    try:
        org = _create_org(name, username, plan=body.get("plan", "free"))
        return org
    except ValueError as exc:
        return _api_error(str(exc), "invalid_request_error", 400)


@router.get("/orgs")
async def list_orgs(request: Request):
    """List organisations the current user belongs to."""
    username = require_auth(request)
    from ..orgs import get_user_orgs
    return {"orgs": get_user_orgs(username)}


@router.get("/orgs/{org_id}")
async def get_org(org_id: str, request: Request):
    """Get a single organisation."""
    username = require_auth(request)
    from ..orgs import get_org as _get_org, require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    org = _get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    return org


@router.patch("/orgs/{org_id}")
async def update_org(org_id: str, request: Request):
    """Update an organisation."""
    username = require_auth(request)
    from ..orgs import update_org as _update_org, require_org_membership
    try:
        require_org_membership(org_id, username, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await request.json()
    org = _update_org(org_id, **body)
    return org or JSONResponse({"error": "org not found"}, status_code=404)


@router.delete("/orgs/{org_id}")
async def delete_org(org_id: str, request: Request):
    """Delete an organisation (admin only)."""
    username = require_auth(request)
    from ..orgs import delete_org as _delete_org, get_org
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username and _get_token_role(request) != "admin":
        return JSONResponse({"error": "forbidden"}, status_code=403)
    _delete_org(org_id)
    return {"deleted": True}


@router.get("/orgs/{org_id}/members")
async def list_org_members(org_id: str, request: Request):
    username = require_auth(request)
    from ..orgs import require_org_membership, list_members
    try:
        require_org_membership(org_id, username)
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    return {"members": list_members(org_id)}


@router.post("/orgs/{org_id}/members")
async def add_org_member(org_id: str, request: Request):
    username = require_auth(request)
    from ..orgs import require_org_membership, add_member
    try:
        require_org_membership(org_id, username, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await request.json()
    username = str(body.get("username", "")).strip()
    role = str(body.get("role", "member"))
    if not username:
        return _api_error("'username' is required", "invalid_request_error", 400)
    try:
        member = add_member(org_id, username, role=role)
        return member
    except ValueError as exc:
        return _api_error(str(exc), "invalid_request_error", 400)


@router.delete("/orgs/{org_id}/members/{username}")
async def remove_org_member(org_id: str, username: str, request: Request):
    requester = require_auth(request)
    from ..orgs import require_org_membership, remove_member
    try:
        require_org_membership(org_id, requester, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    remove_member(org_id, username)
    return {"removed": True}


@router.get("/orgs/{org_id}/usage")
async def org_usage_dashboard(org_id: str, request: Request):
    """Org-level usage with member quota breakdown and aggregate rollups."""
    username = require_auth(request)
    from ..orgs import require_org_membership, list_members, get_org_quota
    from ..profiles import get_quota_state

    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)

    members = list_members(org_id)
    member_usage = []
    total_tokens_used = 0
    total_requests_used = 0
    total_token_limit = 0
    total_request_limit = 0
    for m in members:
        member_username = str(m.get("username", ""))
        quota = get_quota_state(member_username)
        total_tokens_used += int(quota.get("tokens_used_today", 0) or 0)
        total_requests_used += int(quota.get("requests_used_today", 0) or 0)
        total_token_limit += int(quota.get("tokens_limit_day", 0) or 0)
        total_request_limit += int(quota.get("requests_limit_day", 0) or 0)
        member_usage.append(
            {
                "username": member_username,
                "role": m.get("role", "member"),
                "tokens_used_today": int(quota.get("tokens_used_today", 0) or 0),
                "tokens_limit_day": int(quota.get("tokens_limit_day", 0) or 0),
                "requests_used_today": int(quota.get("requests_used_today", 0) or 0),
                "requests_limit_day": int(quota.get("requests_limit_day", 0) or 0),
                "reset_at": quota.get("reset_at"),
            }
        )

    return {
        "org_id": org_id,
        "org_quota": get_org_quota(org_id),
        "usage": {
            "tokens_used_today": total_tokens_used,
            "tokens_limit_day": total_token_limit,
            "requests_used_today": total_requests_used,
            "requests_limit_day": total_request_limit,
        },
        "members": member_usage,
        "member_count": len(member_usage),
    }


@router.post("/orgs/{org_id}/invites")
async def create_org_invite(org_id: str, request: Request):
    username = require_auth(request)
    from ..orgs import require_org_membership, create_invite
    try:
        require_org_membership(org_id, username, min_role="admin")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await request.json()
    invite = create_invite(
        org_id,
        invited_by=username,
        email=body.get("email", ""),
        role=body.get("role", "member"),
    )
    return invite


@router.post("/orgs/invites/accept")
async def accept_org_invite(request: Request):
    username = require_auth(request)
    from ..orgs import accept_invite
    body = await request.json()
    token = str(body.get("token", "")).strip()
    if not token:
        return _api_error("'token' is required", "invalid_request_error", 400)
    try:
        result = accept_invite(token, username)
        return result
    except ValueError as exc:
        return _api_error(str(exc), "invalid_request_error", 400)



# ─────────────────────────────────────────────────────────────────────────────
# GDPR / data deletion
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/privacy/data-deletion-request")
async def privacy_data_deletion_request(request: Request):
    """Handle GDPR/CCPA right-to-erasure requests.

    Supports immediate execution against existing cascade delete primitives.
    Body:
      {
        "regulation": "gdpr|ccpa|both",
        "subject_type": "user|org",
        "subject_id": "<username|org_id>",
        "confirm": true,
        "reason": "optional"
      }
    """
    actor = require_auth(request)
    body = await _read_json_body(request)

    regulation = str(body.get("regulation", "gdpr")).strip().lower()
    if regulation not in {"gdpr", "ccpa", "both"}:
        return _api_error("regulation must be one of: gdpr, ccpa, both", "validation_error", 422)

    subject_type = str(body.get("subject_type", "user")).strip().lower()
    if subject_type not in {"user", "org"}:
        return _api_error("subject_type must be one of: user, org", "validation_error", 422)

    subject_id = str(body.get("subject_id") or actor).strip()
    if not subject_id:
        return _api_error("subject_id is required", "validation_error", 422)

    if not bool(body.get("confirm", False)):
        return _api_error("confirm=true is required to execute data deletion", "validation_error", 422)

    reason = str(body.get("reason", "")).strip()[:500]
    request_id = f"delreq_{uuid.uuid4().hex[:12]}"

    try:
        deleted: dict
        if subject_type == "user":
            if subject_id != actor:
                require_admin(request)
            from ..db import delete_user_data as _delete_user_data
            deleted = _delete_user_data(subject_id)
            resource = f"user:{subject_id}"
        else:
            from ..orgs import get_org
            from ..db import db_get_org_by_name, delete_org_data as _delete_org_data
            org = get_org(subject_id)
            if not org:
                # Support subject_id passed as org name for compatibility with
                # clients/tests that only keep the requested org slug.
                org = db_get_org_by_name(subject_id)
            if not org:
                return _api_error("org not found", "not_found", 404)
            if org.get("owner") != actor:
                require_admin(request)
            org_id = str(org.get("id") or subject_id)
            deleted = _delete_org_data(org_id)
            resource = f"org:{org_id}"

        try:
            from ..observability import write_audit_log
            write_audit_log(
                actor=actor,
                action="privacy_data_deletion_request",
                resource=resource,
                metadata={
                    "request_id": request_id,
                    "regulation": regulation,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "reason": reason,
                    "deleted": deleted,
                },
            )
        except Exception:
            pass

        return {
            "request_id": request_id,
            "status": "completed",
            "regulation": regulation,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "requested_by": actor,
            "deleted": deleted,
        }
    except HTTPException:
        raise
    except Exception as exc:
        return _api_error(f"failed to process data deletion request: {exc}", "server_error", 500)


def _get_current_user(request: Request) -> str:
    """Extract username from request auth, returns '' on failure."""
    try:
        user = require_auth(request)
        return user.get("username", "")
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# Org GDPR export + cascading delete
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/orgs/{org_id}/export")
async def export_org_data(org_id: str, request: Request):
    """
    Export all org data as a portable JSON bundle (GDPR data portability).
    Only org owners or admins may call this.
    """
    username = require_auth(request)
    from ..orgs import get_org
    from ..db import export_org_data as _export_org_data
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)  # raises if not admin
    bundle = _export_org_data(org_id)
    from ..observability import write_audit_log
    write_audit_log(
        actor=username,
        action="org_data_export",
        resource=f"org:{org_id}",
        metadata={"record_count": sum(len(v) if isinstance(v, list) else 1 for v in bundle.values())},
    )
    return JSONResponse(bundle)


@router.delete("/orgs/{org_id}/data")
async def delete_org_data(org_id: str, request: Request):
    """
    Cascading GDPR erasure of all org data.
    Only org owners or admins may call this.
    """
    username = require_auth(request)
    from ..orgs import get_org
    from ..db import delete_org_data as _delete_org_data
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)
    result = _delete_org_data(org_id)
    from ..observability import write_audit_log
    write_audit_log(
        actor=username,
        action="org_data_delete",
        resource=f"org:{org_id}",
        metadata=result,
    )
    return {"org_id": org_id, "deleted": result}


# ─────────────────────────────────────────────────────────────────────────────
# Org-scoped API keys
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/orgs/{org_id}/api-keys")
async def create_org_api_key_route(org_id: str, request: Request):
    """Create a new org-scoped API key. Caller must be org owner or admin."""
    username = require_auth(request)
    from ..orgs import get_org
    from ..db import create_org_api_key
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)

    body = await _read_json_body(request)
    name = str(body.get("name") or "").strip()
    scopes = body.get("scopes") or []
    if not name:
        return _api_error("'name' is required", "invalid_request_error", 400)
    if not isinstance(scopes, list):
        return _api_error("'scopes' must be an array", "invalid_request_error", 400)

    raw_key = "nxk_org_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]
    key_id = secrets.token_hex(16)
    now = time.time()

    create_org_api_key(
        key_id=key_id,
        org_id=org_id,
        created_by=username,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        scopes=json.dumps(scopes),
        created_at=now,
    )
    from ..observability import write_audit_log
    write_audit_log(actor=username, action="org_api_key_create", resource=f"org:{org_id}/key:{key_id}", metadata={"name": name})
    return {"id": key_id, "key": raw_key, "prefix": key_prefix, "name": name, "scopes": scopes, "created_at": now}


@router.get("/orgs/{org_id}/api-keys")
async def list_org_api_keys_route(org_id: str, request: Request):
    """List org API keys (never returns hashes)."""
    username = require_auth(request)
    from ..orgs import get_org
    from ..db import list_org_api_keys
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)
    keys = list_org_api_keys(org_id)
    return {"keys": keys}


@router.delete("/orgs/{org_id}/api-keys/{key_id}")
async def revoke_org_api_key_route(org_id: str, key_id: str, request: Request):
    """Revoke an org API key."""
    username = require_auth(request)
    from ..orgs import get_org
    from ..db import revoke_org_api_key
    org = get_org(org_id)
    if not org:
        return JSONResponse({"error": "org not found"}, status_code=404)
    if org.get("owner") != username:
        require_admin(request)
    revoke_org_api_key(key_id=key_id, org_id=org_id)
    from ..observability import write_audit_log
    write_audit_log(actor=username, action="org_api_key_revoke", resource=f"org:{org_id}/key:{key_id}", metadata={})
    return {"id": key_id, "revoked": True}


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Per-org data isolation endpoints
# Provide org-scoped views over chats, usage, memory, and RAG corpus.
# Callers must be an org member with at least viewer role.
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/orgs/{org_id}/chats")
async def org_chats(org_id: str, limit: int = 200, request: Request = None):
    """Return all chats belonging to members of this org (scoped to org_id)."""
    username = require_auth(request)
    from ..db import get_org_chats as _get_org_chats
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    chats = _get_org_chats(org_id, limit=max(1, min(int(limit), 1000)))
    return {"org_id": org_id, "chats": chats, "count": len(chats)}


@router.get("/orgs/{org_id}/chats/history")
async def org_chats_history(org_id: str, days: int = 30, request: Request = None):
    """Return org-scoped usage timeline (alias for usage, chat-focused view)."""
    username = require_auth(request)
    from ..db import get_org_usage as _get_org_usage
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    rows = _get_org_usage(org_id, days=max(1, min(int(days), 90)))
    return {"org_id": org_id, "days": days, "rows": rows, "count": len(rows)}


@router.get("/orgs/{org_id}/memory")
async def org_memory(org_id: str, limit: int = 100, request: Request = None):
    """Return memory entries tagged to this org (per-org isolation)."""
    username = require_auth(request)
    from ..db import get_org_memory_entries as _get_org_memory
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    entries = _get_org_memory(org_id, limit=max(1, min(int(limit), 500)))
    return {"org_id": org_id, "entries": entries, "count": len(entries)}


@router.get("/orgs/{org_id}/rag/documents")
async def org_rag_documents(org_id: str, request: Request = None):
    """Return all RAG corpus documents tagged with this org_id."""
    username = require_auth(request)
    from ..db import get_org_rag_documents as _get_org_rag
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="viewer")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    docs = _get_org_rag(org_id)
    return {"org_id": org_id, "documents": docs, "count": len(docs)}


@router.post("/orgs/{org_id}/rag/ingest")
async def org_rag_ingest(org_id: str, request: Request):
    """Ingest a document into the RAG corpus tagged with this org_id."""
    username = require_auth(request)
    from ..db import ingest_rag_for_org as _ingest_org_rag
    from ..orgs import require_org_membership
    try:
        require_org_membership(org_id, username, min_role="editor")
    except PermissionError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    body = await _read_json_body(request)
    text = str(body.get("text") or "").strip()
    source = str(body.get("source") or "")
    metadata = body.get("metadata") or {}
    if not text:
        return _api_error("'text' is required", "invalid_request_error", 400)
    if not isinstance(metadata, dict):
        return _api_error("'metadata' must be an object", "invalid_request_error", 400)
    ok = _ingest_org_rag(text, org_id=org_id, source=source, metadata=metadata)
    if not ok:
        return JSONResponse({"error": "RAG ingest failed or RAG not configured"}, status_code=503)
    from ..observability import write_audit_log
    write_audit_log(actor=username, action="org_rag_ingest", resource=f"org:{org_id}")
    return {"status": "ingested", "org_id": org_id, "source": source}
