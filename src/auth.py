from __future__ import annotations

import hashlib
import os
import secrets
import time
import uuid
from dataclasses import dataclass

import jwt as _jwt


JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
JWT_EXPIRE_H = int(os.getenv("JWT_EXPIRE_H", "24"))
MULTI_USER = os.getenv("MULTI_USER", "false").lower() in {"1", "true", "yes", "on"}


@dataclass
class AuthPrincipal:
    user_id: str = "anonymous"
    role: str = "owner"
    token_id: str | None = None


class AuthManager:
    @staticmethod
    def decode_token(token_str: str) -> dict | None:
        if not token_str:
            return None
        try:
            return _jwt.decode(token_str, JWT_SECRET, algorithms=[JWT_ALGO])
        except Exception:
            return None

    @staticmethod
    def _extract_bearer(request) -> str:
        headers = getattr(request, "headers", {})
        if isinstance(headers, dict):
            auth = headers.get("Authorization", "")
        else:
            auth = headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:]
        return ""

    @staticmethod
    def get_principal(request=None) -> AuthPrincipal:
        if request is None:
            return AuthPrincipal()
        token_str = AuthManager._extract_bearer(request)
        if not token_str:
            return AuthPrincipal()
        payload = AuthManager.decode_token(token_str)
        if payload is None:
            return AuthPrincipal()
        return AuthPrincipal(
            user_id=payload.get("sub", "anonymous"),
            role=payload.get("role", "owner"),
            token_id=payload.get("jti"),
        )

    @staticmethod
    def require_user(request=None) -> AuthPrincipal:
        principal = AuthManager.get_principal(request)
        if principal.user_id == "anonymous":
            raise PermissionError("Authentication required")
        return principal

    @staticmethod
    def require_admin(request=None) -> AuthPrincipal:
        principal = AuthManager.get_principal(request)
        if principal.user_id == "anonymous":
            raise PermissionError("Authentication required")
        if principal.role != "admin":
            raise PermissionError("Admin access required")
        return principal

    @staticmethod
    def issue_token(user_id: str, role: str = "user") -> str:
        now = int(time.time())
        payload = {
            "sub": user_id,
            "role": role,
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + JWT_EXPIRE_H * 3600,
        }
        return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.sha256((salt + password).encode()).hexdigest()
        return f"{salt}${h}"

    @staticmethod
    def verify_password(password: str, stored: str) -> bool:
        if "$" not in stored:
            return False
        parts = stored.split("$")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return False
        salt, expected = parts
        h = hashlib.sha256((salt + password).encode()).hexdigest()
        return h == expected


# ── Flat API (legacy convenience wrappers over AuthManager) ────────────

def decode_token(token: str) -> dict | None:
    return AuthManager.decode_token(token)


def get_principal(request=None) -> AuthPrincipal:
    return AuthManager.get_principal(request)


def issue_token(user_id: str, role: str = "user") -> str:
    return AuthManager.issue_token(user_id, role=role)


def hash_password(password: str) -> str:
    return AuthManager.hash_password(password)


def verify_password(password: str, stored: str) -> bool:
    return AuthManager.verify_password(password, stored)


def require_admin(request=None) -> AuthPrincipal:
    return AuthManager.require_admin(request)


def require_user(request=None) -> AuthPrincipal:
    return AuthManager.require_user(request)
