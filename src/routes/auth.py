"""Authentication & authorisation routes.

Extracted from src/api/routes.py for maintainability.
Covers: register, login, logout, token refresh, password reset, API keys,
email verification, OAuth SSO, MFA, WebAuthn / passkeys, SAML.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import secrets
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# ── Shared helpers ───────────────────────────────────────────────────────
from ._helpers import (  # noqa: E402
    _api_error,
    _client_ip,
    _device_hash,
    _detect_suspicious_login,
    _get_token_role,
    _hash_pw,
    _make_refresh_token,
    _make_token,
    _read_token,
    _redis_delete_refresh,
    _redis_get_refresh,
    _redis_revoke_token,
    _register_user_session,
    _verify_pw,
    require_auth,
)
from ..auth import JWT_ALGO, JWT_SECRET


# ── SMTP configuration (moved from api/routes.py) ─────────────────────────
_SMTP_HOST = os.getenv("SMTP_HOST", "")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")
_EMAIL_FROM = os.getenv("EMAIL_FROM", _SMTP_USER or "nexus@localhost")
_APP_URL = os.getenv("APP_URL", "http://localhost:8000")

# ── OAuth provider registry ───────────────────────────────────────────────
_OAUTH_PROVIDERS: dict[str, dict] = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "scope": "openid email profile",
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "client_id_env": "GITHUB_CLIENT_ID",
        "client_secret_env": "GITHUB_CLIENT_SECRET",
        "scope": "read:user user:email",
    },
}

# ── API key support ───────────────────────────────────────────────────────
_VALID_SCOPES = {"chat", "read", "admin", "embeddings", "tools"}


def _generate_api_key() -> tuple[str, str, str]:
    raw = "nxk_" + secrets.token_urlsafe(40)
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    prefix = raw[:12]
    return raw, key_hash, prefix


def _send_verification_email(email: str, token: str, username: str) -> bool:
    link = f"{_APP_URL}/auth/verify-email?token={token}&username={username}"
    body = f"Hello {username},\n\nVerify your email:\n{link}\n\nThis link expires in 24 hours."
    if not _SMTP_HOST:
        print(f"[email-verify] Token for {username}: {token} (SMTP not configured)")
        return True
    try:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(body)
        msg["Subject"] = "Verify your Nexus AI account"
        msg["From"] = _EMAIL_FROM
        msg["To"] = email
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as s:
            s.starttls()
            if _SMTP_USER:
                s.login(_SMTP_USER, _SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"[email-verify] SMTP error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════
#  Core auth
# ══════════════════════════════════════════════════════════════════════════


@router.post("/register")
def auth_register(username: str = "", password: str = ""):
    from ..db import create_user, user_exists

    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)
    if len(username) < 3 or len(password) < 8:
        return JSONResponse({"error": "username min 3 chars, password min 8 chars"}, status_code=400)
    if user_exists(username):
        return JSONResponse({"error": "username already taken"}, status_code=409)
    hashed = _hash_pw(password)
    ok = create_user(username, hashed, username)
    if ok:
        token = _make_token(username)
        refresh_token = _make_refresh_token(username)
        return {"token": token, "refresh_token": refresh_token, "username": username}
    return JSONResponse({"error": "registration failed"}, status_code=500)


@router.post("/login")
def auth_login(
    request: Request,
    username: str = "",
    password: str = "",
    mfa_code: str = "",
    recovery_code: str = "",
    remember_device: bool = False,
):
    from ..db import (
        clear_login_attempts,
        count_recent_failures,
        get_mfa_secret,
        get_user,
        is_trusted_device,
        record_login_attempt,
        save_trusted_device,
        use_mfa_recovery_code,
    )
    from ..observability import write_audit_log


    if not username or not password:
        return JSONResponse({"error": "username and password required"}, status_code=400)

    threshold = int(os.getenv("LOGIN_LOCKOUT_THRESHOLD", "5"))
    base_backoff = int(os.getenv("LOGIN_LOCKOUT_BASE_SECONDS", "30"))
    failures = count_recent_failures(username, window_seconds=86400)
    if failures >= threshold:
        penalty_exp = max(0, failures - threshold)
        retry_after = min(3600, base_backoff * (2**penalty_exp))
        return JSONResponse(
            {"error": "too many failed login attempts", "type": "login_lockout", "retry_after_seconds": retry_after},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    user = get_user(username)
    if not user or not _verify_pw(password, user["password"]):
        record_login_attempt(username, _client_ip(request), success=False)
        return JSONResponse({"error": "invalid credentials"}, status_code=401)

    mfa_record = get_mfa_secret(username)
    dev_hash = _device_hash(request)
    trusted_device = is_trusted_device(username, dev_hash)
    if mfa_record and int(mfa_record.get("enabled") or 0) == 1 and not trusted_device:
        mfa_ok = False
        if mfa_code:
            try:
                import pyotp  # type: ignore
                mfa_ok = bool(pyotp.TOTP(mfa_record["secret"]).verify(str(mfa_code).strip(), valid_window=1))
            except Exception:
                mfa_ok = False
        elif recovery_code:
            code_hash = hashlib.sha256(str(recovery_code).strip().encode()).hexdigest()
            mfa_ok = bool(use_mfa_recovery_code(username, code_hash))

        if not mfa_ok:
            record_login_attempt(username, _client_ip(request), success=False)
            return JSONResponse(
                {"error": "mfa required", "type": "mfa_required", "trusted_device": False},
                status_code=401,
            )

        if remember_device:
            save_trusted_device(username, dev_hash, label=request.headers.get("User-Agent", "")[:120])

    record_login_attempt(username, _client_ip(request), success=True)
    clear_login_attempts(username)

    if mfa_record and int(mfa_record.get("enabled") or 0) == 1 and not trusted_device:
        if _detect_suspicious_login(username, dev_hash, _client_ip(request)):
            write_audit_log(
                actor=username,
                action="suspicious_login",
                resource="auth/login",
                metadata={"ip": _client_ip(request), "device_hash": dev_hash[:16]},
            )

    token = _make_token(username)
    refresh_token = _make_refresh_token(username)
    _register_user_session(username, token, refresh_token, request)
    return {"token": token, "refresh_token": refresh_token, "username": username}


@router.get("/me")
def auth_me(request: Request):
    username = _read_token(request)
    if not username:
        return JSONResponse({"username": None}, status_code=401)
    return {"username": username}


@router.post("/logout")
async def auth_logout(request: Request):

    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    header = request.headers.get("Authorization", "")
    has_access = header.startswith("Bearer ")
    if has_access:
        token = header[7:]
        if token:
            _redis_revoke_token(token)

    refresh_token = str(body.get("refresh_token") or "").strip()
    if refresh_token:
        _redis_delete_refresh(refresh_token)

    return {"ok": True, "revoked_access": has_access, "revoked_refresh": bool(refresh_token)}


@router.post("/refresh")
async def auth_refresh(request: Request):

    import jwt as _jwt


    body = {}
    try:
        body = await request.json()
    except HTTPException:
        return _api_error("invalid JSON body", "validation_error", 400)

    refresh_token = str(body.get("refresh_token") or "").strip()
    if not refresh_token:
        return _api_error("refresh_token is required", "validation_error", 422)

    record = _redis_get_refresh(refresh_token)
    if not record:
        return _api_error("invalid refresh token", "unauthorized", 401)

    try:
        payload = _jwt.decode(refresh_token, JWT_SECRET, algorithms=[JWT_ALGO])
    except Exception:
        _redis_delete_refresh(refresh_token)
        return _api_error("invalid refresh token", "unauthorized", 401)

    if payload.get("type") != "refresh":
        return _api_error("invalid refresh token", "unauthorized", 401)

    username = str(payload.get("sub") or "").strip()
    if not username or record.get("username") != username:
        return _api_error("invalid refresh token", "unauthorized", 401)

    _redis_delete_refresh(refresh_token)
    new_access = _make_token(username)
    new_refresh = _make_refresh_token(username)
    return {"token": new_access, "refresh_token": new_refresh, "username": username}


@router.post("/password-reset")
async def auth_password_reset(request: Request):
    from ..db import SQLiteBackend, _backend as _b, _sql_execute, get_user as db_get_user


    try:
        body = await request.json()
    except HTTPException:
        return _api_error("invalid JSON body", "validation_error", 400)

    username = str(body.get("username", "")).strip()
    new_password = str(body.get("new_password", "")).strip()
    current_password = str(body.get("current_password", "")).strip()

    if not username or not new_password:
        return _api_error("username and new_password are required", "validation_error", 422)
    if len(new_password) < 8:
        return _api_error("new_password must be at least 8 characters", "validation_error", 422)

    user = db_get_user(username)
    if not user:
        return _api_error("user not found", "not_found", 404)

    caller = _read_token(request)
    caller_role = _get_token_role(request)
    is_self = caller == username
    is_admin = caller_role == "admin"

    if not is_self and not is_admin:
        return _api_error("Cannot reset another user's password", "forbidden", 403)

    if is_self and not is_admin:
        if not current_password or not _verify_pw(current_password, user["password"]):
            return _api_error("current_password is incorrect", "unauthorized", 401)

    new_hash = _hash_pw(new_password)
    if isinstance(_b, SQLiteBackend):
        _sql_execute("UPDATE users SET password=? WHERE username=?", (new_hash, username))
    else:
        _sql_execute("UPDATE users SET password=%s WHERE username=%s", (new_hash, username))
    return {"ok": True, "username": username}


# ══════════════════════════════════════════════════════════════════════════
#  API key management
# ══════════════════════════════════════════════════════════════════════════


@router.post("/api-keys")
async def create_api_key(request: Request):
    from ..db import create_api_key as db_create_api_key


    username = require_auth(request)
    try:
        data = await request.json()
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    name = str(data.get("name", "")).strip()
    if not name:
        return _api_error("name is required", "validation_error", 422)

    raw_scopes = data.get("scopes", ["chat", "read"])
    if not isinstance(raw_scopes, list):
        raw_scopes = [str(raw_scopes)]
    scopes = [s for s in raw_scopes if s in _VALID_SCOPES]
    if not scopes:
        scopes = ["chat", "read"]

    role = _get_token_role(request)
    if "admin" in scopes and role != "admin":
        return _api_error("admin scope requires admin role", "forbidden", 403)

    raw_key, key_hash, prefix = _generate_api_key()
    key_id = str(uuid.uuid4())
    ts = time.time()

    ok = db_create_api_key(key_id, username, key_hash, prefix, name, scopes, ts)
    if not ok:
        return _api_error("Failed to create API key", "server_error", 500)

    return {
        "id": key_id,
        "key": raw_key,
        "key_prefix": prefix,
        "name": name,
        "scopes": scopes,
        "created_at": ts,
        "note": "Store this key securely — it will not be shown again.",
    }


@router.get("/api-keys")
def list_api_keys(request: Request):
    from ..db import list_api_keys as db_list_api_keys


    username = require_auth(request)
    keys = db_list_api_keys(username)
    safe = []
    for k in keys:
        safe.append({
            "id": k["id"],
            "key_prefix": k["key_prefix"],
            "name": k["name"],
            "scopes": k["scopes"],
            "created_at": k["created_at"],
            "last_used_at": k.get("last_used_at"),
            "revoked_at": k.get("revoked_at"),
            "active": k.get("revoked_at") is None,
        })
    return {"keys": safe, "total": len(safe)}


@router.delete("/api-keys/{key_id}")
def delete_api_key(key_id: str, request: Request):
    from ..db import revoke_api_key as db_revoke_api_key


    username = require_auth(request)
    ok = db_revoke_api_key(key_id, username)
    if not ok:
        return _api_error("key not found or not owned by you", "not_found", 404)
    return {"ok": True, "revoked": key_id}


# ══════════════════════════════════════════════════════════════════════════
#  Email verification
# ══════════════════════════════════════════════════════════════════════════


@router.post("/send-verification")
async def send_verification_email(request: Request):
    from ..db import save_pref as db_save_pref, update_user_email as db_update_user_email


    username = require_auth(request)
    try:
        data = await request.json()
    except HTTPException:
        data = {}
    email = str(data.get("email", "")).strip().lower()
    if not email or "@" not in email:
        return _api_error("valid email required", "validation_error", 422)

    token = secrets.token_urlsafe(32)
    db_save_pref(f"email_verify_token.{username}", f"{token}:{email}")
    db_update_user_email(username, email, verified=False)
    sent = _send_verification_email(email, token, username)
    return {"ok": True, "email": email, "email_sent": sent}


@router.get("/verify-email")
def verify_email(token: str = "", username: str = ""):
    from ..db import save_pref as db_save_pref, load_pref as db_load_pref, update_user_email as db_update_user_email

    import secrets as _sec

    if not token or not username:
        return _api_error("token and username required", "validation_error", 422)
    stored = db_load_pref(f"email_verify_token.{username}", "")
    if not stored:
        return _api_error("no pending verification for this user", "not_found", 404)
    stored_token, email = (stored.split(":", 1) + [""])[:2]
    if not _sec.compare_digest(stored_token, token):
        return _api_error("invalid or expired token", "unauthorized", 401)
    db_update_user_email(username, email, verified=True)
    db_save_pref(f"email_verify_token.{username}", "")
    return {"ok": True, "username": username, "email": email, "verified": True}


# ══════════════════════════════════════════════════════════════════════════
#  OAuth2 / OIDC SSO
# ══════════════════════════════════════════════════════════════════════════


@router.get("/oauth/{provider}")
def oauth_redirect(provider: str, request: Request):
    from ..db import save_pref as db_save_pref
    import urllib.parse


    cfg = _OAUTH_PROVIDERS.get(provider)
    if not cfg:
        return _api_error(f"Unknown provider: {provider}. Valid: {list(_OAUTH_PROVIDERS)}", "not_found", 404)
    client_id = os.getenv(cfg["client_id_env"], "")
    if not client_id:
        return _api_error(f"{provider} OAuth not configured (missing {cfg['client_id_env']})", "not_configured", 503)
    state = secrets.token_urlsafe(16)
    db_save_pref(f"oauth_state.{state}", provider)
    callback = f"{_APP_URL}/auth/oauth/{provider}/callback"
    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": callback,
        "scope": cfg["scope"],
        "response_type": "code",
        "state": state,
    })
    return RedirectResponse(f"{cfg['auth_url']}?{params}")


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str = "", state: str = "", error: str = ""):
    from ..db import (
        load_pref as db_load_pref,
        save_pref as db_save_pref,
        get_or_create_oauth_user as db_get_or_create_oauth_user,
    )
    import httpx as _httpx


    if error:
        return _api_error(f"OAuth error: {error}", "oauth_error", 400)
    if not code:
        return _api_error("Missing authorization code", "oauth_error", 400)

    cfg = _OAUTH_PROVIDERS.get(provider)
    if not cfg:
        return _api_error(f"Unknown provider: {provider}", "not_found", 404)

    stored_provider = db_load_pref(f"oauth_state.{state}", "")
    if stored_provider != provider:
        return _api_error("Invalid OAuth state — possible CSRF", "unauthorized", 401)
    db_save_pref(f"oauth_state.{state}", "")

    client_id = os.getenv(cfg["client_id_env"], "")
    client_secret = os.getenv(cfg["client_secret_env"], "")
    callback = f"{_APP_URL}/auth/oauth/{provider}/callback"

    try:
        headers = {"Accept": "application/json"}
        token_resp = _httpx.post(cfg["token_url"], data={
            "client_id": client_id, "client_secret": client_secret,
            "code": code, "redirect_uri": callback,
            "grant_type": "authorization_code",
        }, headers=headers, timeout=10)
        token_data = token_resp.json()
        access_token = token_data.get("access_token", "")
        if not access_token:
            return _api_error("Failed to obtain access token", "oauth_error", 502)

        user_resp = _httpx.get(cfg["userinfo_url"],
                               headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                               timeout=10)
        user_data = user_resp.json()
    except Exception as e:
        return _api_error(f"OAuth exchange failed: {e}", "oauth_error", 502)

    if provider == "google":
        provider_id = str(user_data.get("sub", ""))
        email = str(user_data.get("email", ""))
        display_name = str(user_data.get("name", ""))
    elif provider == "github":
        provider_id = str(user_data.get("id", ""))
        email = str(user_data.get("email", "") or "")
        display_name = str(user_data.get("name", "") or user_data.get("login", ""))
    else:
        return _api_error("Unsupported provider", "not_found", 404)

    if not provider_id:
        return _api_error("Could not retrieve provider user ID", "oauth_error", 502)

    user = db_get_or_create_oauth_user(provider, provider_id, email, display_name)
    if not user:
        return _api_error("Failed to create or retrieve user", "server_error", 500)

    username = user["username"]
    jwt_token = _make_token(username)
    refresh = _make_refresh_token(username)
    return {
        "token": jwt_token, "refresh_token": refresh, "username": username,
        "provider": provider, "email": email,
    }


@router.get("/oauth/providers")
def list_oauth_providers():
    result = {}
    for name, cfg in _OAUTH_PROVIDERS.items():
        client_id = os.getenv(cfg["client_id_env"], "")
        result[name] = {"configured": bool(client_id), "auth_url": f"/auth/oauth/{name}"}
    return {"providers": result}


# ══════════════════════════════════════════════════════════════════════════
#  MFA (TOTP)
# ══════════════════════════════════════════════════════════════════════════


@router.post("/mfa/setup")
async def mfa_setup(request: Request):

    username = require_auth(request)
    try:
        import pyotp  # type: ignore
        import qrcode  # type: ignore
    except ImportError:
        return JSONResponse({"error": "MFA dependencies not installed"}, status_code=501)

    from ..db import save_mfa_secret

    secret = pyotp.random_base32()
    save_mfa_secret(username, secret)
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name="Nexus AI")

    qr_b64 = ""
    try:
        qr = qrcode.make(uri)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        pass

    return {"secret": secret, "uri": uri, "qr_png_base64": qr_b64}


@router.post("/mfa/enroll")
async def mfa_enroll_alias(request: Request):
    """Alias for MFA enrollment endpoint (compat with feature contract)."""
    return await mfa_setup(request)


@router.post("/mfa/verify")
async def mfa_verify(request: Request):

    username = require_auth(request)
    try:
        import pyotp  # type: ignore
    except ImportError:
        return JSONResponse({"error": "MFA dependencies not installed"}, status_code=501)

    body = await request.json()
    code = str(body.get("code", "")).strip()
    if not code:
        return _api_error("'code' is required", "invalid_request_error", 400)

    from ..db import get_mfa_secret, enable_mfa, save_mfa_recovery_codes
    import secrets as _sec

    record = get_mfa_secret(username)
    if not record:
        return _api_error("MFA not set up", "invalid_request_error", 400)

    totp = pyotp.TOTP(record["secret"])
    if not totp.verify(code, valid_window=1):
        return _api_error("Invalid code", "invalid_mfa_code", 400)

    enable_mfa(username)

    codes = [_sec.token_hex(8).upper() for _ in range(8)]
    hashes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
    save_mfa_recovery_codes(username, hashes)

    return {"mfa_enabled": True, "recovery_codes": codes}


@router.delete("/mfa")
async def mfa_disable(request: Request):
    from ..db import disable_mfa


    username = require_auth(request)
    disable_mfa(username)
    return {"mfa_enabled": False}


@router.post("/mfa/disable")
async def mfa_disable_alias(request: Request):
    """Alias for MFA disable endpoint (compat with feature contract)."""
    return await mfa_disable(request)


@router.get("/mfa/status")
async def mfa_status(request: Request):
    from ..db import get_mfa_secret


    username = require_auth(request)
    record = get_mfa_secret(username)
    return {"username": username, "mfa_enabled": bool(record and record.get("enabled"))}


@router.get("/trusted-devices")
async def trusted_devices_list(request: Request):
    from ..db import list_trusted_devices


    username = require_auth(request)
    return {"devices": list_trusted_devices(username)}


@router.post("/trusted-devices")
async def trusted_devices_add(request: Request):
    from ..db import save_trusted_device


    username = require_auth(request)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    label = str((body or {}).get("label") or request.headers.get("User-Agent", ""))[:120]
    save_trusted_device(username, _device_hash(request), label=label)
    return {"trusted": True, "device_hash": _device_hash(request)}


@router.delete("/trusted-devices/{device_hash}")
async def trusted_devices_remove(device_hash: str, request: Request):
    from ..db import remove_trusted_device


    username = require_auth(request)
    remove_trusted_device(username, device_hash)
    return {"removed": True, "device_hash": device_hash}


@router.post("/mfa/recovery-codes")
async def mfa_recovery_codes(request: Request):
    from ..db import get_mfa_secret, save_mfa_recovery_codes
    import secrets as _sec


    username = require_auth(request)
    record = get_mfa_secret(username)
    if not record or not record.get("enabled"):
        return _api_error("MFA must be enabled first", "invalid_request_error", 400)

    codes = [_sec.token_hex(8).upper() for _ in range(8)]
    hashes = [hashlib.sha256(c.encode()).hexdigest() for c in codes]
    save_mfa_recovery_codes(username, hashes)
    return {"recovery_codes": codes}


# ══════════════════════════════════════════════════════════════════════════
#  WebAuthn / Passkeys
# ══════════════════════════════════════════════════════════════════════════


@router.post("/webauthn/register")
async def webauthn_register_begin(request: Request):


    username = require_auth(request)
    try:
        from webauthn import generate_registration_options
        from webauthn.helpers.cose import COSEAlgorithmIdentifier
        from webauthn.helpers.structs import AuthenticatorSelectionCriteria, UserVerificationRequirement

        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        rp_name = os.getenv("WEBAUTHN_RP_NAME", "Nexus AI")
        options = generate_registration_options(
            rp_id=rp_id,
            rp_name=rp_name,
            user_name=username,
            user_display_name=username,
            authenticator_selection=AuthenticatorSelectionCriteria(
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
        )
        challenge_b64 = base64.urlsafe_b64encode(options.challenge).rstrip(b"=").decode()
        try:
            from ..redis_state import get_redis
            get_redis().set(f"nexus:webauthn_challenge:{username}", challenge_b64, ex=300)
        except Exception:
            pass

        return JSONResponse({
            "rp": {"id": rp_id, "name": rp_name},
            "user": {"name": username, "displayName": username, "id": username},
            "challenge": challenge_b64,
            "timeout": 60000,
            "attestation": "none",
        })
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)


@router.post("/webauthn/register/complete")
async def webauthn_register_complete(request: Request):
    from ..observability import write_audit_log


    username = require_auth(request)
    try:
        from webauthn import verify_registration_response
        from webauthn.helpers.structs import RegistrationCredential

        body = await request.json()
        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        expected_origin = os.getenv("WEBAUTHN_ORIGIN", "https://localhost")

        expected_challenge = b""
        try:
            from ..redis_state import get_redis
            raw = get_redis().get(f"nexus:webauthn_challenge:{username}")
            if raw:
                expected_challenge = base64.urlsafe_b64decode(raw + "==")
        except Exception:
            pass

        if not expected_challenge:
            return _api_error("registration challenge expired or not found", "invalid_request_error", 400)

        credential = RegistrationCredential.parse_raw(json.dumps(body))
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origin,
            require_user_verification=False,
        )
        device_name = str(body.get("deviceName") or request.headers.get("User-Agent", "")[:80])

        from ..db import save_webauthn_credential
        save_webauthn_credential(
            credential_id=verification.credential_id.hex(),
            username=username,
            public_key=base64.b64encode(verification.credential_public_key).decode(),
            sign_count=int(verification.sign_count),
            device_name=device_name,
        )
        write_audit_log(actor=username, action="webauthn_credential_registered", resource="auth/webauthn",
                        metadata={"device": device_name[:40]})
        return {"registered": True}
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)
    except Exception as exc:
        return _api_error(f"WebAuthn verification failed: {exc}", "invalid_request_error", 400)


@router.post("/webauthn/authenticate")
async def webauthn_authenticate_begin(request: Request):

    try:
        from webauthn import generate_authentication_options
        from webauthn.helpers.structs import UserVerificationRequirement

        body = await request.json()
        username = str(body.get("username") or "").strip()
        if not username:
            return _api_error("'username' is required", "invalid_request_error", 400)

        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        from ..db import list_webauthn_credentials

        stored_creds = list_webauthn_credentials(username)
        if not stored_creds:
            return _api_error("no passkeys registered for this user", "invalid_request_error", 404)

        options = generate_authentication_options(
            rp_id=rp_id,
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        challenge_b64 = base64.urlsafe_b64encode(options.challenge).rstrip(b"=").decode()
        try:
            from ..redis_state import get_redis
            get_redis().set(f"nexus:webauthn_auth_challenge:{username}", challenge_b64, ex=300)
        except Exception:
            pass

        return JSONResponse({
            "challenge": challenge_b64,
            "timeout": 60000,
            "rpId": rp_id,
            "allowCredentials": [{"id": c["credential_id"], "type": "public-key"} for c in stored_creds],
            "userVerification": "preferred",
        })
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)


@router.post("/webauthn/authenticate/complete")
async def webauthn_authenticate_complete(request: Request):
    from ..observability import write_audit_log


    try:
        from webauthn import verify_authentication_response
        from webauthn.helpers.structs import AuthenticationCredential

        body = await request.json()
        username = str(body.get("username") or "").strip()
        if not username:
            return _api_error("'username' is required", "invalid_request_error", 400)

        rp_id = os.getenv("WEBAUTHN_RP_ID", "localhost")
        expected_origin = os.getenv("WEBAUTHN_ORIGIN", "https://localhost")

        expected_challenge = b""
        try:
            from ..redis_state import get_redis
            raw = get_redis().get(f"nexus:webauthn_auth_challenge:{username}")
            if raw:
                expected_challenge = base64.urlsafe_b64decode(raw + "==")
        except Exception:
            pass

        if not expected_challenge:
            return _api_error("authentication challenge expired or not found", "invalid_request_error", 400)

        from ..db import get_webauthn_credential, update_webauthn_sign_count

        credential_id = str(body.get("id") or "").replace("-", "").lower()
        stored_cred = get_webauthn_credential(credential_id)
        if not stored_cred or stored_cred.get("username") != username:
            return _api_error("credential not found", "unauthorized", 401)

        credential = AuthenticationCredential.parse_raw(json.dumps(body))
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_rp_id=rp_id,
            expected_origin=expected_origin,
            credential_public_key=base64.b64decode(stored_cred["public_key"]),
            credential_current_sign_count=int(stored_cred.get("sign_count", 0)),
            require_user_verification=False,
        )
        update_webauthn_sign_count(credential_id, int(verification.new_sign_count))
        token = _make_token(username)
        refresh_token = _make_refresh_token(username)
        _register_user_session(username, token, refresh_token, request)
        write_audit_log(actor=username, action="webauthn_login", resource="auth/webauthn",
                        metadata={"credential_id": credential_id[:16]})
        return {"token": token, "refresh_token": refresh_token, "username": username}
    except ImportError:
        return JSONResponse({"error": "WebAuthn support not installed (webauthn)"}, status_code=503)
    except Exception as exc:
        return _api_error(f"WebAuthn authentication failed: {exc}", "unauthorized", 401)


# ══════════════════════════════════════════════════════════════════════════
#  SAML 2.0 enterprise SSO
# ══════════════════════════════════════════════════════════════════════════


def _get_saml_client(provider: str):
    """Build a pysaml2 Saml2Client for the given provider slug."""
    from saml2 import BINDING_HTTP_POST
    from saml2.client import Saml2Client
    from saml2.config import Config as Saml2Config

    idp_metadata_url = os.getenv(f"SAML_{provider.upper()}_IDP_METADATA_URL", "")
    sp_entity_id = os.getenv(f"SAML_{provider.upper()}_SP_ENTITY_ID", f"nexus-ai-{provider}")
    acs_url = os.getenv(f"SAML_{provider.upper()}_ACS_URL", f"https://localhost/auth/saml/{provider}/acs")

    if not idp_metadata_url:
        raise ValueError(f"SAML provider '{provider}' not configured (missing IDP_METADATA_URL)")

    settings = {
        "entityid": sp_entity_id,
        "service": {
            "sp": {
                "endpoints": {
                    "assertion_consumer_service": [(acs_url, BINDING_HTTP_POST)],
                },
                "allow_unsolicited": True,
                "authn_requests_signed": False,
                "want_assertions_signed": True,
            }
        },
        "metadata": {"remote": [{"url": idp_metadata_url}]},
    }
    cfg = Saml2Config()
    cfg.load(settings)
    return Saml2Client(config=cfg)


@router.get("/saml/{provider}/login")
async def saml_login(provider: str, request: Request):
    """Initiate SAML 2.0 authentication — redirects to IdP."""
    try:
        from saml2 import BINDING_HTTP_REDIRECT
        from ..db import save_saml_session_v2

        client = _get_saml_client(provider)
        relay_state = secrets.token_hex(16)
        session_id, info = client.prepare_for_authenticate(relay_state=relay_state)
        save_saml_session_v2(
            session_id=session_id,
            provider=provider,
            relay_state=relay_state,
            expires_at=time.time() + 600,
        )
        redirect_url = dict(info["headers"]).get("Location", "")
        if not redirect_url:
            return JSONResponse({"error": "failed to generate SAML redirect"}, status_code=500)
        return RedirectResponse(url=redirect_url, status_code=302)
    except ImportError:
        return JSONResponse({"error": "SAML support not installed (pysaml2)"}, status_code=503)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": f"SAML init failed: {exc}"}, status_code=500)


@router.post("/saml/{provider}/acs")
async def saml_acs(provider: str, request: Request):
    """SAML Assertion Consumer Service — processes SAMLResponse, issues JWT."""
    from ..observability import write_audit_log


    try:
        from saml2 import BINDING_HTTP_POST
        from ..db import (
            complete_saml_session,
            get_user as db_get_user,
            save_user as db_save_user,
        )

        client = _get_saml_client(provider)
        form = await request.form()
        saml_response_raw = str(form.get("SAMLResponse", ""))
        relay_state = str(form.get("RelayState", ""))
        if not saml_response_raw:
            return JSONResponse({"error": "missing SAMLResponse"}, status_code=400)

        authn_response = client.parse_authn_request_response(saml_response_raw, BINDING_HTTP_POST)
        if not authn_response:
            return JSONResponse({"error": "invalid SAML response"}, status_code=401)

        nameid = str(authn_response.get_subject() or "")
        ava = authn_response.ava or {}
        email = str(ava.get("email", [nameid])[0] if ava.get("email") else nameid)
        username = email.split("@")[0] if "@" in email else email
        if not username:
            return JSONResponse({"error": "could not determine username from SAML response"}, status_code=401)

        if not db_get_user(username):
            auto_pw_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            db_save_user(username, auto_pw_hash, role="user", source="saml")

        session_id = str(authn_response.in_response_to or relay_state)
        complete_saml_session(session_id=session_id, username=username, nameid=nameid)

        token = _make_token(username)
        refresh_token = _make_refresh_token(username)
        write_audit_log(actor=username, action="saml_login", resource=f"auth/saml/{provider}",
                        metadata={"nameid": nameid[:40]})
        return {"token": token, "refresh_token": refresh_token, "username": username}
    except ImportError:
        return JSONResponse({"error": "SAML support not installed (pysaml2)"}, status_code=503)
    except Exception as exc:
        return JSONResponse({"error": f"SAML ACS failed: {exc}"}, status_code=500)
