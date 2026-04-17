"""
Nexus AI Authentication & RBAC Layer.
Handles password hashing, JWT lifecycle, and role-based access control.
"""
import os
import secrets
import hashlib
import binascii
import jwt as _jwt
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from fastapi import Request, HTTPException, Depends
from .db import get_user, user_exists, create_user, count_users

JWT_SECRET   = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = int(os.getenv("JWT_EXPIRE_HOURS", "168"))
MULTI_USER   = os.getenv("MULTI_USER", "true").lower() == "true"

class AuthManager:
    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), (salt + "nexus_ai_salt").encode(), 200000)
        return salt + "$" + binascii.hexlify(dk).decode()

    @staticmethod
    def verify_password(password: str, stored: str) -> bool:
        try:
            parts = stored.split("$")
            if len(parts) != 2: return False
            salt, h = parts
            dk = hashlib.pbkdf2_hmac("sha256", password.encode(), (salt + "nexus_ai_salt").encode(), 200000)
            return h == binascii.hexlify(dk).decode()
        except Exception: return False

    @staticmethod
    def create_token(username: str, role: str = "user") -> str:
        exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_H)
        payload = {
            "sub": username,
            "role": role,
            "exp": exp
        }
        return _jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        try:
            return _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        except Exception: return None

# ── RBAC & Dependencies ──────────────────────────────────────────────────────

def get_current_user(request: Request) -> str:
    if not MULTI_USER: return "nexus_admin"
    
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    
    token = header[7:]
    payload = AuthManager.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return payload["sub"]

def get_current_role(request: Request) -> str:
    if not MULTI_USER: return "admin"
    
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "): return "guest"
    
    token = header[7:]
    payload = AuthManager.decode_token(token)
    return payload.get("role", "user") if payload else "guest"

def require_role(allowed_roles: List[str]):
    def role_dependency(request: Request):
        role = get_current_role(request)
        if role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Permission denied. Required: {allowed_roles}")
        return role
    return role_dependency

# ── Higher Level Wrappers ─────────────────────────────────────────────────────

def login_user(username: str, password: str) -> Optional[str]:
    user = get_user(username)
    if user and AuthManager.verify_password(password, user["password"]):
        # Fetch role from DB if exists, else default
        role = user.get("role", "user")
        return AuthManager.create_token(username, role)
    return None

def register_user(username: str, password: str, display_name: str = "") -> bool:
    if user_exists(username): return False
    hashed = AuthManager.hash_password(password)
    role = "admin" if count_users() == 0 else "user"
    return create_user(username, hashed, display_name, role)
