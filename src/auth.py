from __future__ import annotations

import os
import time
from dataclasses import dataclass


JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
JWT_EXPIRE_H = int(os.getenv("JWT_EXPIRE_H", "24"))
MULTI_USER = os.getenv("MULTI_USER", "false").lower() in {"1", "true", "yes", "on"}


@dataclass
class AuthPrincipal:
    user_id: str = "anonymous"
    role: str = "owner"


class AuthManager:
    @staticmethod
    def get_principal(request=None) -> AuthPrincipal:
        return AuthPrincipal()

    @staticmethod
    def require_user(request=None) -> AuthPrincipal:
        return AuthPrincipal()

    @staticmethod
    def require_admin(request=None) -> AuthPrincipal:
        return AuthPrincipal(role="admin")

    @staticmethod
    def issue_token(user_id: str) -> dict:
        now = int(time.time())
        return {"sub": user_id, "iat": now, "exp": now + JWT_EXPIRE_H * 3600}