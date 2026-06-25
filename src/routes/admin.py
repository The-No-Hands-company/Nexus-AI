"""Admin & system management routes.

Extracted from src/api/routes.py for maintainability.
Covers: user management, quotas, feature flags, cache, backups,
audit logs, drift detection, team policies, compliance, deployment,
SIEM, IP filtering, human eval, cost monitoring, and more.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

from ._helpers import (  # noqa: E402
    _api_error,
    _read_json_body,
    require_auth,
    require_admin,
)
from ..db import (  # noqa: E402
    load_pref as db_load_pref,
    save_pref as db_save_pref,
    list_users as db_list_users,
    update_user_role as db_update_user_role,
    get_user as db_get_user,
    load_safety_audit_entries as db_load_safety_audit_entries,
    daily_strict_clone_bypass_totals as db_daily_bypass_totals,
)


# ═══════════════════════════════════════════════════════════════════════════════
#  bypass / turn-budget / reset-providers
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/bypass-history")
def admin_bypass_history(request: Request, days: int = 30):
    require_admin(request)
    """Daily bypass totals for the last `days` calendar days (max 365)."""
    days = max(1, min(int(days), 365))
    daily = db_daily_bypass_totals(days=days)
    return {
        "days": days,
        "total": sum(r["count"] for r in daily),
        "daily": daily,
    }


@router.get("/turn-budget-summary")
def admin_turn_budget_summary(request: Request, limit: int = 100, since_ts: float = 0.0):
    require_admin(request)
    """Recent summary of turn-budget pressure and downgrade decisions from activity_log."""
    from ..agent import get_turn_budget_summary
    return get_turn_budget_summary(limit=limit, since_ts=since_ts)


@router.post("/reset-providers")
def admin_reset_providers(request: Request):
    require_admin(request)
    """Clear all provider demotion flags, warmup strike counters, and rate-limit cooldowns.

    Call this when providers appear unavailable after a bad startup or a temporary
    network blip that triggered the warmup demotion penalty.  The circuit-breaker
    half-open transition is handled automatically; this only clears the *demotion*
    and *cooldown* state that is tracked separately.
    """
    from ..agent import (
        _provider_demotion_until,
        _provider_demotion_reasons,
        _provider_warmup_failure_strikes,
        _cooldowns,
    )
    demotions_cleared = list(_provider_demotion_until.keys())
    _provider_demotion_until.clear()
    _provider_demotion_reasons.clear()
    _provider_warmup_failure_strikes.clear()
    cooldowns_cleared = list(_cooldowns.keys())
    _cooldowns.clear()
    return {
        "ok": True,
        "demotions_cleared": demotions_cleared,
        "cooldowns_cleared": cooldowns_cleared,
    }


@router.get("/tool-audit")
def tool_audit_log(request: Request, limit: int = 100, kind: str = "", session_id: str = ""):
    require_admin(request)
    """Return the tool-call audit log. Supports filtering by kind and session_id."""
    from ..tools_builtin import get_tool_audit_log
    try:
        records = get_tool_audit_log(
            limit=max(1, min(int(limit), 1000)),
            kind=kind.strip() or None,
            session_id=session_id.strip() or None,
        )
        return {"records": records, "total": len(records)}
    except Exception as exc:
        return _api_error(str(exc), "server_error", 500)


# ═══════════════════════════════════════════════════════════════════════════════
#  Usage webhook (non-/admin paths)
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/usage/webhook")
def usage_webhook_get(request: Request):
    require_admin(request)
    return {
        "enabled": db_load_pref("usage_webhook_enabled", "false") == "true",
        "url": db_load_pref("usage_webhook_url", ""),
        "has_secret": bool(db_load_pref("usage_webhook_secret", "")),
    }


@router.post("/usage/webhook")
async def usage_webhook_set(request: Request):
    require_admin(request)
    data = await request.json()
    enabled = bool(data.get("enabled", True))
    url = str(data.get("url", "") or "").strip()
    secret = str(data.get("secret", "") or "").strip()
    if enabled and not url:
        return _api_error("url is required when webhook is enabled", "validation_error", 422)
    if url and not (url.startswith("http://") or url.startswith("https://")):
        return _api_error("url must start with http:// or https://", "validation_error", 422)

    db_save_pref("usage_webhook_enabled", "true" if enabled else "false")
    db_save_pref("usage_webhook_url", url)
    if secret:
        db_save_pref("usage_webhook_secret", secret)
    return {"ok": True, "enabled": enabled, "url": url}


@router.post("/usage/webhook/push")
def usage_webhook_push(request: Request, days: int = 1):
    require_admin(request)

    enabled = db_load_pref("usage_webhook_enabled", "false") == "true"
    url = db_load_pref("usage_webhook_url", "").strip()
    secret = db_load_pref("usage_webhook_secret", "")
    if not enabled:
        return _api_error("usage webhook is disabled", "invalid_request", 400)
    if not url:
        return _api_error("usage webhook URL is not configured", "invalid_request", 400)

    from ..usage_tracking import usage_stats
    payload = usage_stats(days=max(1, min(int(days), 365)), username="")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    import hashlib
    import hmac
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "nexus-ai-usage-webhook/1.0",
    }
    if secret:
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers["X-Nexus-Signature"] = f"sha256={signature}"

    try:
        from urllib import request as urllib_request

        req = urllib_request.Request(url=url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=10) as resp:
            status_code = int(getattr(resp, "status", 200) or 200)
        return {"ok": True, "status": status_code, "url": url}
    except Exception as exc:
        return _api_error(f"webhook push failed: {exc}", "upstream_error", 502)


# ═══════════════════════════════════════════════════════════════════════════════
#  User management
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/users")
def admin_list_users(request: Request):
    require_admin(request)
    users = db_list_users()
    safe = [{"username": u["username"], "display_name": u.get("display_name", ""),
              "role": u.get("role", "user"), "created_at": u.get("created_at", "")}
            for u in users]
    return {"users": safe, "total": len(safe)}


@router.patch("/users/{username}/role")
async def admin_update_role(username: str, request: Request):
    require_admin(request)
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    role = str(data.get("role", "")).strip().lower()
    if role not in ("admin", "user", "viewer"):
        return _api_error("role must be one of: admin, user, viewer", "validation_error", 422)
    target = db_get_user(username)
    if not target:
        return _api_error("user not found", "not_found", 404)
    ok = db_update_user_role(username, role)
    return {"username": username, "role": role, "updated": ok}


@router.post("/users/{username}/unlock-login")
async def admin_unlock_login(username: str, request: Request):
    """Admin endpoint to clear login lockout state for a user."""
    require_admin(request)
    from ..db import clear_login_attempts

    clear_login_attempts(username)
    return {"username": username, "unlocked": True}


# ═══════════════════════════════════════════════════════════════════════════════
#  Per-user quota dashboard
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/quota")
def admin_quota_dashboard(request: Request):
    require_admin(request)
    from ..profiles import get_quota_state
    users = db_list_users()
    result = []
    for u in users:
        uname = u["username"]
        state = get_quota_state(uname)
        result.append({"username": uname, "role": u.get("role", "user"), **state})
    return {"quotas": result, "total": len(result)}


@router.post("/quota/{username}")
async def admin_set_quota(username: str, request: Request):
    require_admin(request)
    try:
        data = await _read_json_body(request)
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)
    user = db_get_user(username)
    if not user:
        return _api_error("user not found", "not_found", 404)
    tokens_per_day = int(data.get("tokens_per_day", 0))
    requests_per_day = data.get("requests_per_day")
    if requests_per_day is not None:
        requests_per_day = int(requests_per_day)
    from ..profiles import set_quota
    state = set_quota(username, tokens_per_day, requests_per_day)
    return {"username": username, **state}


# ═══════════════════════════════════════════════════════════════════════════════
#  Database backup / restore
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/backup")
def db_backup(request: Request):
    require_admin(request)
    from datetime import datetime, timezone
    import io
    import sqlite3 as _sqlite3
    import hashlib
    from ..db import SQLiteBackend, _backend as _b

    def _verify_sql_dump(sql_dump: str) -> bool:
        try:
            conn = _sqlite3.connect(":memory:")
            for stmt in sql_dump.split(";\n"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def _replicate_offsite(sql_bytes: bytes, sha256_hex: str) -> str:
        target = os.getenv("OFFSITE_BACKUP_URL", "").strip()
        if not target:
            return "disabled"
        try:
            import urllib.request as _urlreq
            from datetime import datetime as _dt, timezone as _tz

            ts_label = _dt.now(_tz.utc).strftime("%Y%m%d_%H%M%S")
            if "?" not in target and not target.endswith(".sql"):
                upload_url = target.rstrip("/") + f"/nexus_backup_{ts_label}.sql"
            else:
                upload_url = target

            req = _urlreq.Request(
                upload_url,
                data=sql_bytes,
                method="PUT",
                headers={
                    "Content-Type": "application/sql",
                    "X-Backup-SHA256": sha256_hex,
                    "X-Backup-Timestamp": ts_label,
                },
            )
            with _urlreq.urlopen(req, timeout=15):
                pass

            retention_days = int(os.getenv("OFFSITE_BACKUP_RETENTION_DAYS", "0"))
            if retention_days > 0 and "?" not in target:
                try:
                    import json as _json
                    cutoff_ts = _dt.now(_tz.utc).timestamp() - retention_days * 86400
                    list_req = _urlreq.Request(
                        target.rstrip("/") + "/",
                        method="GET",
                        headers={"Accept": "application/json"},
                    )
                    with _urlreq.urlopen(list_req, timeout=10) as resp:
                        listing = _json.loads(resp.read())
                    for entry in listing if isinstance(listing, list) else []:
                        name = str(entry.get("name", ""))
                        created = float(entry.get("created_at", 0))
                        if name.endswith(".sql") and created < cutoff_ts:
                            del_url = target.rstrip("/") + f"/{name}"
                            del_req = _urlreq.Request(del_url, method="DELETE")
                            try:
                                with _urlreq.urlopen(del_req, timeout=10):
                                    pass
                            except Exception:
                                pass
                except Exception:
                    pass

            return "replicated"
        except Exception:
            return "failed"

    if not isinstance(_b, SQLiteBackend):
        return _api_error("Backup only supported for SQLite backend", "not_supported", 400)
    src = _sqlite3.connect(str(_b.db_path))
    dst = _sqlite3.connect(":memory:")
    src.backup(dst)
    dst_buf = io.BytesIO()
    for line in dst.iterdump():
        dst_buf.write((line + "\n").encode())
    sql_bytes = dst_buf.getvalue()
    sql_text = sql_bytes.decode("utf-8", errors="ignore")
    backup_sha256 = hashlib.sha256(sql_bytes).hexdigest()
    verify_ok = _verify_sql_dump(sql_text)
    replication_status = _replicate_offsite(sql_bytes, backup_sha256)
    dst_buf.seek(0)
    src.close()
    dst.close()
    from fastapi.responses import StreamingResponse
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        dst_buf,
        media_type="application/sql",
        headers={
            "Content-Disposition": f'attachment; filename="nexus_backup_{ts}.sql"',
            "X-Backup-SHA256": backup_sha256,
            "X-Backup-Verified": "true" if verify_ok else "false",
            "X-Offsite-Replication": replication_status,
        },
    )


@router.post("/api/restore")
async def db_restore(request: Request):
    require_admin(request)
    from ..db import SQLiteBackend, _backend as _b
    if not isinstance(_b, SQLiteBackend):
        return _api_error("Restore only supported for SQLite backend", "not_supported", 400)
    body = await request.body()
    if not body:
        return _api_error("SQL backup body is required", "validation_error", 422)
    import sqlite3 as _sqlite3
    import shutil
    import os as _os
    tmp_path = str(_b.db_path) + ".restore_tmp"
    try:
        conn = _sqlite3.connect(tmp_path)
        for stmt in body.decode("utf-8").split(";\n"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass
        conn.commit()
        conn.close()
        shutil.copy2(tmp_path, str(_b.db_path))
        _os.remove(tmp_path)
    except Exception as e:
        try:
            _os.remove(tmp_path)
        except Exception:
            pass
        return _api_error(f"Restore failed: {e}", "restore_error", 500)
    return {"ok": True, "message": "Database restored successfully"}


@router.post("/backup/gist/restore")
def gist_restore_endpoint(request: Request):
    """Force restore of SQLite DB from configured GitHub Gist backup."""
    require_admin(request)
    from ..gist_backup import restore_from_gist
    restored = restore_from_gist()
    if restored:
        return {"ok": True, "restored": True, "message": "Database restored from gist backup"}
    return {
        "ok": False,
        "restored": False,
        "message": "No gist backup restored (missing config, missing backup, or restore failed)",
    }


@router.post("/backup/gist/push")
def gist_push_endpoint(request: Request):
    """Force immediate push of SQLite DB to configured GitHub Gist backup."""
    require_admin(request)
    from ..gist_backup import push_now as gist_push_now
    gist_push_now()
    return {"ok": True, "message": "Gist backup push triggered"}


@router.post("/quota/reset/{username}")
async def admin_reset_quota(username: str, request: Request):
    require_admin(request)
    user = db_get_user(username)
    if not user:
        return _api_error("user not found", "not_found", 404)
    from ..profiles import reset_quota_usage

    reset_quota_usage(username)
    from datetime import datetime, timezone
    return {"ok": True, "username": username, "reset_at": datetime.now(timezone.utc).isoformat()}


# ═══════════════════════════════════════════════════════════════════════════════
#  Feature flags
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/flags")
async def list_feature_flags(request: Request):
    require_admin(request)
    from ..feature_flags import list_flags
    return {"flags": list_flags()}


@router.get("/flags/{flag_name}")
async def get_feature_flag(flag_name: str, request: Request):
    require_admin(request)
    from ..db import load_feature_flag
    flag = load_feature_flag(flag_name)
    if not flag:
        return JSONResponse({"error": "flag not found"}, status_code=404)
    return flag


@router.post("/flags/{flag_name}")
async def set_feature_flag(flag_name: str, request: Request):
    require_admin(request)
    from ..feature_flags import set_flag
    body = await request.json()
    flag = set_flag(
        flag_name,
        enabled=bool(body.get("enabled", False)),
        description=body.get("description", ""),
        rollout_percentage=int(body.get("rollout_percentage", 0)),
        user_overrides=body.get("user_overrides"),
        org_overrides=body.get("org_overrides"),
        value=body.get("value"),
    )
    return flag


@router.delete("/flags/{flag_name}")
async def delete_feature_flag(flag_name: str, request: Request):
    require_admin(request)
    from ..feature_flags import delete_flag
    deleted = delete_flag(flag_name)
    return {"deleted": deleted}


# ═══════════════════════════════════════════════════════════════════════════════
#  Audit log
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/audit-log")
async def admin_audit_log(request: Request):
    require_admin(request)
    from ..db import list_audit_log
    params = dict(request.query_params)
    limit = int(params.get("limit", 100))
    actor = params.get("actor", "")
    action = params.get("action", "")
    return {"entries": list_audit_log(limit=limit, actor=actor, action=action)}


# ═══════════════════════════════════════════════════════════════════════════════
#  Circuit breakers
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/circuit-breakers")
async def list_circuit_breakers(request: Request):
    require_admin(request)
    try:
        from ..circuit_breaker import all_circuit_status
        return {"circuit_breakers": all_circuit_status()}
    except ImportError:
        return {"circuit_breakers": []}


@router.post("/circuit-breakers/{name}/reset")
async def reset_circuit_breaker(name: str, request: Request):
    require_admin(request)
    try:
        from ..circuit_breaker import reset_circuit
        reset = reset_circuit(name)
        return {"name": name, "reset": reset}
    except ImportError:
        return JSONResponse({"error": "circuit_breaker module not available"}, status_code=503)


# ═══════════════════════════════════════════════════════════════════════════════
#  Cache
# ═══════════════════════════════════════════════════════════════════════════════


@router.delete("/cache/{cache_key}")
async def invalidate_cache_key(cache_key: str, request: Request):
    require_admin(request)
    try:
        from ..redis_state import cache_invalidate
        cache_invalidate(cache_key)
        return {"invalidated": cache_key}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


@router.post("/cache/flush")
async def flush_cache(request: Request):
    require_admin(request)
    body = await request.json()
    prefix = body.get("prefix", "")
    try:
        from ..redis_state import flush_prefix, flush_all
        if prefix:
            n = flush_prefix(prefix)
            return {"flushed": n, "prefix": prefix}
        else:
            flush_all()
            return {"flushed": "all"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)


# ═══════════════════════════════════════════════════════════════════════════════
#  GDPR / data deletion
# ═══════════════════════════════════════════════════════════════════════════════


@router.delete("/users/{username}/data")
async def delete_user_data(username: str, request: Request):
    """
    GDPR right-to-erasure endpoint (admin only).
    Cascades across: DB tables, ChromaDB memory, memory JSON store, RAG corpus,
    and all Redis session / token / refresh keys for the user.
    """
    require_admin(request)
    from ..db import delete_user_data as _delete_user_data
    result = _delete_user_data(username)

    try:
        from ..redis_state import get_redis
        _r = get_redis()
        if _r is not None:
            pattern_sessions = f"nexus:sessions:{username}"
            pattern_refresh = f"nexus:refresh:{username}:*"
            _r.delete(pattern_sessions)
            refresh_keys = _r.keys(pattern_refresh)
            if refresh_keys:
                _r.delete(*refresh_keys)
            result["redis_sessions"] = 1
    except Exception:
        pass

    try:
        from ..observability import write_audit_log
        actor = require_auth(request)
        write_audit_log(
            actor=actor if isinstance(actor, str) else str(actor.get("username", "admin")),
            action="gdpr_delete",
            resource=f"user:{username}",
            metadata=result,
        )
    except Exception:
        pass
    return {"username": username, "deleted": result}


# ═══════════════════════════════════════════════════════════════════════════════
#  Federated learning
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/federated/fallback-hooks")
async def api_admin_federated_fallback_hooks(request: Request, limit: int = 200, since_ts: float = 0.0):
    require_admin(request)
    from ..federated import get_fallback_hook_summary, list_fallback_hooks

    hooks = list_fallback_hooks(limit=limit, since_ts=since_ts)
    summary = get_fallback_hook_summary(limit=limit, since_ts=since_ts)
    return {
        "summary": summary,
        "hooks": hooks,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Retention / eval-creative
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/retention/eval-creative")
async def api_admin_retention_eval_creative(request: Request):
    require_admin(request)
    from ..db import run_eval_creative_retention_cleanup

    body = await _read_json_body(request, "invalid JSON body")
    result = run_eval_creative_retention_cleanup(
        eval_retention_days=int(body.get("eval_retention_days") or 0) or None,
        creative_retention_days=int(body.get("creative_retention_days") or 0) or None,
        max_rows=int(body.get("max_rows") or 5000),
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Drift detection
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/drift")
async def api_drift_summary(request: Request):
    require_admin(request)
    from ..drift_detector import get_drift_summary
    return get_drift_summary()


@router.get("/drift/events")
async def api_drift_events(request: Request, plane: str = "all", severity: str = "all", limit: int = 50):
    require_admin(request)
    from ..drift_detector import list_drift_events
    return {"events": list_drift_events(plane=plane, severity=severity, limit=limit)}


@router.post("/drift/baseline/quality")
async def api_drift_baseline_quality(request: Request):
    require_admin(request)
    from ..drift_detector import set_quality_baseline
    body = await request.json()
    set_quality_baseline(body)
    return {"ok": True, "message": "Quality baseline updated"}


@router.post("/drift/baseline/safety")
async def api_drift_baseline_safety(request: Request):
    require_admin(request)
    from ..drift_detector import update_safety_baseline
    body = await request.json()
    update_safety_baseline(body)
    return {"ok": True, "message": "Safety baseline updated"}


@router.post("/drift/check/architecture")
async def api_drift_check_arch(request: Request):
    require_admin(request)
    from ..drift_detector import check_architecture_drift
    result = check_architecture_drift()
    return result


@router.get("/drift/weekly")
async def api_drift_weekly_results(request: Request):
    require_admin(request)
    from ..drift_detector import get_weekly_results
    return {"results": get_weekly_results()}


@router.post("/drift/weekly/run")
async def api_drift_weekly_run(request: Request):
    require_admin(request)
    from ..drift_detector import run_weekly_quality_benchmark
    result = run_weekly_quality_benchmark()
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Team policies
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/team-policies")
async def api_create_policy(request: Request):
    require_admin(request)
    from ..team_policies import create_policy
    body    = await request.json()
    team_id = str(body.pop("team_id", "default"))
    name    = str(body.pop("name", "Unnamed Policy"))
    result  = create_policy(team_id, name, **body)
    return result


@router.get("/team-policies")
async def api_list_policies(request: Request, team_id: str = "default"):
    require_admin(request)
    from ..team_policies import list_policies
    return {"policies": list_policies(team_id=team_id)}


@router.get("/team-policies/{policy_id}")
async def api_get_policy(request: Request, policy_id: str):
    require_admin(request)
    from ..team_policies import get_policy
    p = get_policy(policy_id)
    if not p:
        return _api_error("Policy not found", status_code=404)
    return p


@router.put("/team-policies/{policy_id}")
async def api_update_policy(policy_id: str, request: Request):
    require_admin(request)
    from ..team_policies import update_policy
    body   = await request.json()
    result = update_policy(policy_id, updates=body)
    if not result:
        return _api_error("Policy not found", status_code=404)
    return result


@router.delete("/team-policies/{policy_id}")
async def api_delete_policy(request: Request, policy_id: str):
    require_admin(request)
    from ..team_policies import delete_policy
    ok = delete_policy(policy_id)
    return {"ok": ok}


@router.post("/team-policies/evaluate")
async def api_evaluate_policy(request: Request):
    require_admin(request)
    from ..team_policies import evaluate_policy
    body = await request.json()
    team_id = str(body.get("team_id", "default"))
    tool_action = str(body.get("tool_action", ""))
    username = str(body.get("user") or body.get("username") or "")
    role = str(body.get("role", "user"))
    context = body.get("context", {}) or {}
    model = str(body.get("model") or context.get("model") or "").strip() or None
    region = str(body.get("region") or context.get("region") or "").strip() or None
    return evaluate_policy(
        team_id=team_id,
        tool_action=tool_action,
        model=model,
        region=region,
        username=username,
        role=role,
        context=context,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Roles
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/roles")
async def api_list_roles(request: Request):
    require_admin(request)
    from ..team_policies import ROLE_HIERARCHY
    return {"roles": list(ROLE_HIERARCHY.keys())}


@router.post("/roles/check")
async def api_check_role(request: Request):
    require_admin(request)
    from ..team_policies import role_can
    body          = await request.json()
    actor_role    = str(body.get("actor_role", "user"))
    required_role = str(body.get("required_role", "admin"))
    return {"can": role_can(actor_role, required_role)}


# ═══════════════════════════════════════════════════════════════════════════════
#  Compliance
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/compliance")
async def api_get_compliance(request: Request):
    require_admin(request)
    from ..team_policies import get_compliance_config
    return get_compliance_config()


@router.put("/compliance")
async def api_update_compliance(request: Request):
    require_admin(request)
    from ..team_policies import update_compliance_config
    body = await request.json()
    try:
        return update_compliance_config(body)
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/compliance/connectors/{connector}")
async def api_get_compliance_connector(request: Request, connector: str):
    require_admin(request)
    from ..team_policies import get_managed_connector_config
    try:
        return get_managed_connector_config(connector)
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.put("/compliance/connectors/{connector}")
async def api_update_compliance_connector(connector: str, request: Request):
    require_admin(request)
    from ..team_policies import update_managed_connector_config
    body = await request.json()
    try:
        return update_managed_connector_config(
            connector=connector,
            enabled=body.get("enabled") if "enabled" in body else None,
            providers=body.get("providers") if isinstance(body.get("providers"), list) else None,
        )
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/compliance/connectors/{connector}/test")
async def api_test_compliance_connector(connector: str, request: Request):
    require_admin(request)
    from ..team_policies import test_managed_connector
    body = await request.json()
    return test_managed_connector(
        connector=connector,
        provider=str(body.get("provider", "")),
        region=str(body.get("region", "")),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  Deployment profiles
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/deployment-profile")
async def api_get_deployment_profile(request: Request):
    """Return the active deployment profile and its key settings."""
    require_admin(request)
    from ..deployment_profiles import get_profile_summary
    return get_profile_summary()


@router.get("/deployment-profiles")
async def api_list_deployment_profiles(request: Request):
    """List all built-in deployment profiles."""
    require_admin(request)
    from ..deployment_profiles import list_profiles
    return {"profiles": list_profiles()}


# ═══════════════════════════════════════════════════════════════════════════════
#  Department quota
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/quota/departments")
async def api_set_dept_quota(request: Request):
    require_admin(request)
    from ..team_policies import set_department_quota
    body = await request.json()
    dept = str(body.get("department", ""))
    return set_department_quota(
        department=dept,
        daily_tokens=int(body.get("daily_tokens", 100000)),
        monthly_cost_usd=float(body.get("monthly_cost_usd", 500.0)),
        max_users=int(body.get("max_users", 50)),
    )


@router.get("/quota/departments")
async def api_list_dept_quotas(request: Request):
    require_admin(request)
    from ..team_policies import list_department_quotas
    return {"quotas": list_department_quotas()}


@router.get("/quota/departments/{department}")
async def api_get_dept_quota(request: Request, department: str):
    require_admin(request)
    from ..team_policies import get_department_quota
    q = get_department_quota(department)
    if not q:
        return _api_error("Department not found", status_code=404)
    return q


# ═══════════════════════════════════════════════════════════════════════════════
#  Policy violations
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/policy-violations")
async def api_list_violations(request: Request, team_id: str | None = None, limit: int = 100):
    require_admin(request)
    from ..team_policies import list_violations, list_policy_alerts
    return {
        "violations": list_violations(team_id=team_id, limit=limit),
        "alerts": list_policy_alerts(team_id=team_id, status="open", limit=limit),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Approval workflows
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/approval-workflows")
async def api_create_workflow(request: Request):
    require_admin(request)
    from ..team_policies import create_approval_workflow
    body      = await request.json()
    action    = str(body.get("action", ""))
    requestor = str(body.get("requestor", ""))
    tiers     = body.get("custom_tiers")
    return create_approval_workflow(action, requestor, custom_tiers=tiers)


@router.get("/approval-workflows")
async def api_list_workflows(request: Request, status: str | None = None, limit: int = 50):
    require_admin(request)
    from ..team_policies import list_workflows
    return {"workflows": list_workflows(status=status, limit=limit)}


@router.post("/approval-workflows/{workflow_id}/advance")
async def api_advance_workflow(workflow_id: str, request: Request):
    require_admin(request)
    from ..team_policies import advance_workflow
    body = await request.json()
    approver = str(body.get("approver", ""))
    approver_role = str(body.get("approver_role", "admin"))
    decision = str(body.get("decision", "approve"))
    comment = str(body.get("comment", ""))
    result = advance_workflow(workflow_id, approver, approver_role, decision, reason=comment)
    if result.get("error") == "workflow not found":
        return _api_error("Workflow not found", status_code=404)
    if not result.get("ok"):
        return _api_error(result.get("error", "Workflow advance failed"), status_code=400)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Audit log export
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/audit-log/export")
async def api_audit_export(request: Request, fmt: str = "json", limit: int = 500):
    require_admin(request)
    from ..db import verify_safety_audit_entries
    from ..team_policies import build_audit_export
    entries = db_load_safety_audit_entries(limit=limit)
    content_bytes, content_type = build_audit_export(entries, fmt=fmt)
    integrity = verify_safety_audit_entries(limit=limit)
    if fmt == "csv":
        from fastapi.responses import Response
        return Response(
            content=content_bytes,
            media_type=content_type,
            headers={
                "Content-Disposition": "attachment; filename=audit.csv",
                "X-Audit-Integrity": "ok" if integrity.get("ok") else "failed",
            },
        )
    return {
        "entries": entries,
        "export": content_bytes.decode("utf-8"),
        "format": fmt,
        "content_type": content_type,
        "integrity": integrity,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SIEM integration config
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/siem/config")
async def api_siem_get(request: Request):
    require_admin(request)
    from ..db import load_pref as _lp
    config = _lp("siem_config") or {}
    return {"config": config}


@router.post("/siem/config")
async def api_siem_set(request: Request):
    require_admin(request)
    from ..db import save_pref as _sp
    body = await request.json()
    endpoint = str(body.get("endpoint", "")).strip()
    if not endpoint:
        return _api_error("endpoint required", status_code=422)
    config = {
        "endpoint":   endpoint,
        "format":     str(body.get("format", "json")),
        "auth_token": str(body.get("auth_token", "")),
        "enabled":    bool(body.get("enabled", True)),
        "events":     list(body.get("events", ["safety_violation", "auth_failure"])),
    }
    _sp("siem_config", config)
    return {"ok": True, "config": config}


@router.post("/siem/test")
async def api_siem_test(request: Request):
    require_admin(request)
    from ..db import load_pref as _lp
    import httpx
    config = _lp("siem_config") or {}
    endpoint = config.get("endpoint", "")
    if not endpoint:
        return _api_error("No SIEM endpoint configured", status_code=400)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                endpoint,
                json={"type": "test", "source": "nexus-ai", "message": "SIEM integration test"},
                headers={"Authorization": f"Bearer {config.get('auth_token', '')}"},
            )
            return {"ok": True, "status_code": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
#  Security: IP filter
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/security/ip-filter")
async def api_ip_filter_status(request: Request):
    require_admin(request)
    try:
        from ..security.ip_filter import get_filter_status
        return get_filter_status()
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/security/ip-filter/allowlist")
async def api_ip_allowlist_add(request: Request):
    require_admin(request)
    body = await request.json()
    cidr = str(body.get("cidr", "")).strip()
    if not cidr:
        return _api_error("cidr is required", status_code=400)
    try:
        from ..security.ip_filter import add_to_allowlist
        ok = add_to_allowlist(cidr)
        return {"added": ok, "cidr": cidr}
    except Exception as exc:
        return _api_error(str(exc))


@router.delete("/security/ip-filter/allowlist/{cidr:path}")
async def api_ip_allowlist_remove(request: Request, cidr: str):
    require_admin(request)
    try:
        from ..security.ip_filter import remove_from_allowlist
        ok = remove_from_allowlist(cidr)
        return {"removed": ok, "cidr": cidr}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/security/ip-filter/blocklist")
async def api_ip_blocklist_add(request: Request):
    require_admin(request)
    body = await request.json()
    cidr = str(body.get("cidr", "")).strip()
    if not cidr:
        return _api_error("cidr is required", status_code=400)
    try:
        from ..security.ip_filter import add_to_blocklist
        ok = add_to_blocklist(cidr)
        return {"added": ok, "cidr": cidr}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/security/check-ip")
async def api_check_ip(request: Request):
    require_admin(request)
    body = await request.json()
    ip = str(body.get("ip", "")).strip()
    if not ip:
        return _api_error("ip is required", status_code=400)
    try:
        from ..security.ip_filter import is_ip_allowed
        allowed, reason = is_ip_allowed(ip)
        return {"ip": ip, "allowed": allowed, "reason": reason}
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Human evaluation
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/human-eval/tasks")
async def api_human_eval_tasks(request: Request, limit: int = 20):
    require_admin(request)
    try:
        from ..evals.human_eval_pipeline import get_pending_tasks
        return {"tasks": get_pending_tasks(limit=min(int(limit), 100))}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/human-eval/tasks/{task_id}/rate")
async def api_human_eval_rate(request: Request, task_id: str):
    require_admin(request)
    body = await request.json()
    rating = body.get("rating")
    rater_id = str(body.get("rater_id", "admin"))
    notes = str(body.get("notes", ""))
    if rating is None:
        return _api_error("rating is required", status_code=400)
    try:
        from ..evals.human_eval_pipeline import submit_rating
        ok = submit_rating(task_id, rating, rater_id, notes)
        return {"submitted": ok, "task_id": task_id}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/human-eval/stats")
async def api_human_eval_stats(request: Request):
    require_admin(request)
    try:
        from ..evals.human_eval_pipeline import get_eval_stats
        return get_eval_stats()
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Retention policies
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/retention/policies")
async def api_retention_policies(request: Request):
    require_admin(request)
    try:
        from ..retention import list_policies
        return {"policies": list_policies()}
    except Exception as exc:
        return _api_error(str(exc))


@router.put("/retention/policies/{data_type}")
async def api_retention_set_policy(request: Request, data_type: str):
    require_admin(request)
    body = await request.json()
    days = int(body.get("retention_days", 0))
    if days <= 0:
        return _api_error("retention_days must be > 0", status_code=400)
    try:
        from ..retention import set_policy
        set_policy(data_type, days)
        return {"set": True, "data_type": data_type, "retention_days": days}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/retention/purge")
async def api_retention_purge(request: Request):
    require_admin(request)
    try:
        from ..retention import run_purge_cycle
        results = run_purge_cycle()
        return {"purged": results}
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/retention/history")
async def api_retention_history(request: Request, limit: int = 10):
    require_admin(request)
    try:
        from ..retention import get_purge_history
        return {"history": get_purge_history(limit=min(int(limit), 100))}
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Cost anomaly
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/cost-anomaly/history")
async def api_cost_anomaly_history(request: Request, team: str = "", limit: int = 50):
    require_admin(request)
    try:
        from ..cost_anomaly import get_anomaly_history
        return {"anomalies": get_anomaly_history(team=team or None, limit=min(int(limit), 500))}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/cost-anomaly/check")
async def api_cost_anomaly_check(request: Request):
    require_admin(request)
    try:
        from ..cost_anomaly import check_all_teams
        return {"anomalies": check_all_teams()}
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Capacity planning
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/capacity/planning")
async def api_capacity_planning_report(request: Request, days: int = 30, horizon_days: int = 14):
    require_admin(request)
    from ..usage_tracking import get_usage_daily
    safe_days = max(7, min(int(days), 365))
    safe_horizon = max(1, min(int(horizon_days), 90))
    try:
        series = get_usage_daily(days=safe_days)
        if not series:
            return {
                "days": safe_days,
                "horizon_days": safe_horizon,
                "history_points": 0,
                "daily_avg_calls": 0,
                "daily_avg_tokens": 0,
                "projected_calls": 0,
                "projected_tokens": 0,
                "recommendation": "insufficient_data",
            }

        total_calls = sum(int(row.get("calls") or 0) for row in series)
        total_tokens = sum(int(row.get("in_tok") or 0) + int(row.get("out_tok") or 0) for row in series)
        day_count = max(1, len(series))
        avg_calls = total_calls / day_count
        avg_tokens = total_tokens / day_count

        projected_calls = int(round(avg_calls * safe_horizon))
        projected_tokens = int(round(avg_tokens * safe_horizon))

        peak_calls = max(int(row.get("calls") or 0) for row in series)
        peak_tokens = max(int(row.get("in_tok") or 0) + int(row.get("out_tok") or 0) for row in series)
        recommended_daily_capacity = int(round(max(avg_calls * 1.3, peak_calls * 1.1)))

        return {
            "days": safe_days,
            "horizon_days": safe_horizon,
            "history_points": day_count,
            "daily_avg_calls": round(avg_calls, 2),
            "daily_avg_tokens": round(avg_tokens, 2),
            "daily_peak_calls": peak_calls,
            "daily_peak_tokens": peak_tokens,
            "projected_calls": projected_calls,
            "projected_tokens": projected_tokens,
            "recommended_daily_capacity": recommended_daily_capacity,
            "recommendation": "scale_up" if peak_calls > avg_calls * 1.2 else "steady",
            "series": series,
        }
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Webhook delivery
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/webhooks/delivery/stats")
async def api_webhook_delivery_stats(request: Request):
    require_admin(request)
    try:
        from ..webhooks_delivery import get_webhook_stats
        return get_webhook_stats()
    except Exception as exc:
        return _api_error(str(exc))


@router.get("/webhooks/delivery/dlq")
async def api_webhook_dlq(request: Request):
    require_admin(request)
    try:
        from ..webhooks_delivery import list_dlq
        return {"dlq": list_dlq()}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/webhooks/delivery/{delivery_id}/retry")
async def api_webhook_retry(request: Request, delivery_id: str):
    require_admin(request)
    try:
        from ..webhooks_delivery import retry_dlq_delivery
        ok = retry_dlq_delivery(delivery_id)
        return {"retried": ok, "delivery_id": delivery_id}
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Tool policies
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/tool-policies")
async def api_list_tool_policies(request: Request):
    require_admin(request)
    try:
        from ..agent_tool_policy import list_policies
        return {"policies": list_policies()}
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/tool-policies")
async def api_set_tool_policy(request: Request):
    require_admin(request)
    body = await request.json()
    persona_id = str(body.get("persona_id", "")).strip()
    if not persona_id:
        return _api_error("persona_id is required", status_code=400)
    try:
        from ..agent_tool_policy import ToolPolicy, set_policy
        policy = ToolPolicy(
            persona_id=persona_id,
            mode=str(body.get("mode", "unrestricted")),
            allowed_tools=body.get("allowed_tools", []),
            denied_tools=body.get("denied_tools", []),
            max_calls_per_session=int(body.get("max_calls_per_session", 0)),
            require_approval_for=body.get("require_approval_for", []),
            description=str(body.get("description", "")),
        )
        set_policy(policy)
        return {"set": True, "persona_id": persona_id}
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  RAG index
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/rag/index/{collection}/invalidate/{doc_id}")
async def api_rag_invalidate_doc(request: Request, collection: str, doc_id: str):
    require_admin(request)
    try:
        from ..rag.incremental_index import invalidate_document
        ok = invalidate_document(doc_id, collection)
        return {"invalidated": ok, "doc_id": doc_id, "collection": collection}
    except Exception as exc:
        return _api_error(str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
#  Memory
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/memory/health")
async def api_memory_health(request: Request):
    require_admin(request)
    try:
        from ..memory.forgetting import get_memory_health_report
        return get_memory_health_report()
    except Exception as exc:
        return _api_error(str(exc))


@router.post("/memory/consolidate")
async def api_memory_consolidate(request: Request):
    require_admin(request)
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    dry_run = bool(body.get("dry_run", False))
    try:
        from ..memory.forgetting import run_consolidation
        return run_consolidation(dry_run=dry_run)
    except Exception as exc:
        return _api_error(str(exc))
