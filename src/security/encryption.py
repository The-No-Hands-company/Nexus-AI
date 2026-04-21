"""
src/security/encryption.py — KMS envelope encryption + field-level data encryption

Envelope encryption: each plaintext is encrypted with a randomly-generated
data-encryption key (DEK) using Fernet (AES-128-CBC + HMAC-SHA256). The DEK
is then wrapped (encrypted) by a key-encryption key (KEK) managed by the
configured KMS provider, producing a serialised ciphertext envelope that can
be stored alongside the encrypted data column.

Supported KMS providers (tried in order):
  1. AWS KMS     — FIELD_ENCRYPTION_KMS=aws + AWS_KMS_KEY_ARN
  2. GCP KMS     — FIELD_ENCRYPTION_KMS=gcp + GCP_KMS_KEY_PATH
  3. Vault Transit — FIELD_ENCRYPTION_KMS=vault + VAULT_ADDR + VAULT_TRANSIT_KEY
  4. Local Fernet key — FIELD_ENCRYPTION_KEY env var (dev fallback)
  5. Auto-generated ephemeral key — last resort, logged as WARNING

Environment variables:
    FIELD_ENCRYPTION_KEY    — 32-byte Fernet key for local/dev mode.
                              Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    FIELD_ENCRYPTION_KMS    — "aws" | "gcp" | "vault" | "local" (default: local)
    AWS_KMS_KEY_ARN         — ARN of the AWS KMS symmetric key
    GCP_KMS_KEY_PATH        — GCP Cloud KMS resource path (projects/.../cryptoKeyVersions/...)
    VAULT_TRANSIT_KEY       — Vault Transit Engine key name (default: nexus-ai)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import threading

logger = logging.getLogger("nexus.security.encryption")

_PROVIDER = os.getenv("FIELD_ENCRYPTION_KMS", "local").strip().lower()
_LOCAL_KEY_B64 = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
_AWS_KEY_ARN = os.getenv("AWS_KMS_KEY_ARN", "").strip()
_GCP_KEY_PATH = os.getenv("GCP_KMS_KEY_PATH", "").strip()
_VAULT_TRANSIT_KEY = os.getenv("VAULT_TRANSIT_KEY", "nexus-ai").strip()

_fernet_instance = None
_fernet_lock = threading.Lock()


# ── Local Fernet key initialisation ──────────────────────────────────────────

def _get_fernet():
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance
    with _fernet_lock:
        if _fernet_instance is not None:
            return _fernet_instance
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logger.error("cryptography package not installed — field encryption disabled")
            _fernet_instance = False
            return False

        key_b64 = _LOCAL_KEY_B64
        if not key_b64:
            key_b64 = _derive_from_env()
        if not key_b64:
            key_b64 = Fernet.generate_key().decode()
            logger.warning(
                "FIELD_ENCRYPTION_KEY not set — generated ephemeral key. "
                "Data encrypted with this key will be unrecoverable after restart. "
                "Set FIELD_ENCRYPTION_KEY in production."
            )
        try:
            _fernet_instance = Fernet(key_b64.encode() if isinstance(key_b64, str) else key_b64)
        except Exception as exc:
            logger.error("Invalid FIELD_ENCRYPTION_KEY: %s", exc)
            _fernet_instance = False
        return _fernet_instance


def _derive_from_env() -> str | None:
    """Derive a stable Fernet key from SECRET_KEY if FIELD_ENCRYPTION_KEY is unset."""
    secret_key = os.getenv("SECRET_KEY", "").strip()
    if not secret_key:
        return None
    import hashlib
    raw = hashlib.sha256(f"field-encryption:{secret_key}".encode()).digest()
    return base64.urlsafe_b64encode(raw).decode()


# ── AWS KMS DEK wrapping ──────────────────────────────────────────────────────

def _aws_wrap_dek(dek_plaintext: bytes) -> bytes | None:
    if not _AWS_KEY_ARN:
        return None
    try:
        import boto3  # type: ignore
        client = boto3.client("kms")
        resp = client.encrypt(KeyId=_AWS_KEY_ARN, Plaintext=dek_plaintext)
        return resp["CiphertextBlob"]
    except Exception as exc:
        logger.warning("AWS KMS wrap failed: %s", exc)
        return None


def _aws_unwrap_dek(dek_ciphertext: bytes) -> bytes | None:
    try:
        import boto3  # type: ignore
        client = boto3.client("kms")
        resp = client.decrypt(CiphertextBlob=dek_ciphertext)
        return resp["Plaintext"]
    except Exception as exc:
        logger.warning("AWS KMS unwrap failed: %s", exc)
        return None


# ── GCP KMS DEK wrapping ──────────────────────────────────────────────────────

def _gcp_wrap_dek(dek_plaintext: bytes) -> bytes | None:
    if not _GCP_KEY_PATH:
        return None
    try:
        from google.cloud import kms  # type: ignore
        client = kms.KeyManagementServiceClient()
        resp = client.encrypt(name=_GCP_KEY_PATH, plaintext=dek_plaintext)
        return resp.ciphertext
    except Exception as exc:
        logger.warning("GCP KMS wrap failed: %s", exc)
        return None


def _gcp_unwrap_dek(dek_ciphertext: bytes) -> bytes | None:
    try:
        from google.cloud import kms  # type: ignore
        client = kms.KeyManagementServiceClient()
        resp = client.decrypt(name=_GCP_KEY_PATH, ciphertext=dek_ciphertext)
        return resp.plaintext
    except Exception as exc:
        logger.warning("GCP KMS unwrap failed: %s", exc)
        return None


# ── Vault Transit DEK wrapping ────────────────────────────────────────────────

def _vault_wrap_dek(dek_plaintext: bytes) -> bytes | None:
    vault_addr = os.getenv("VAULT_ADDR", "").strip()
    vault_token = os.getenv("VAULT_TOKEN", "").strip()
    if not vault_addr or not vault_token:
        return None
    try:
        import urllib.request as _req
        b64_plain = base64.b64encode(dek_plaintext).decode()
        payload = json.dumps({"plaintext": b64_plain}).encode()
        url = f"{vault_addr}/v1/transit/encrypt/{_VAULT_TRANSIT_KEY}"
        req = _req.Request(url, data=payload,
                           headers={"X-Vault-Token": vault_token, "Content-Type": "application/json"},
                           method="POST")
        with _req.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        return data["data"]["ciphertext"].encode()
    except Exception as exc:
        logger.warning("Vault Transit wrap failed: %s", exc)
        return None


def _vault_unwrap_dek(dek_ciphertext: bytes) -> bytes | None:
    vault_addr = os.getenv("VAULT_ADDR", "").strip()
    vault_token = os.getenv("VAULT_TOKEN", "").strip()
    if not vault_addr or not vault_token:
        return None
    try:
        import urllib.request as _req
        payload = json.dumps({"ciphertext": dek_ciphertext.decode()}).encode()
        url = f"{vault_addr}/v1/transit/decrypt/{_VAULT_TRANSIT_KEY}"
        req = _req.Request(url, data=payload,
                           headers={"X-Vault-Token": vault_token, "Content-Type": "application/json"},
                           method="POST")
        with _req.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        return base64.b64decode(data["data"]["plaintext"])
    except Exception as exc:
        logger.warning("Vault Transit unwrap failed: %s", exc)
        return None


# ── Envelope encrypt/decrypt ──────────────────────────────────────────────────

def encrypt_field(plaintext: str) -> str:
    """Encrypt a plaintext string and return a base64-encoded ciphertext envelope.

    The envelope format is a JSON blob:
      {"v": 1, "provider": "<kms>", "dek": "<b64-wrapped-dek>", "data": "<b64-ciphertext>"}

    For the local Fernet provider, dek is omitted (the KEK IS the DEK).
    Returns plaintext unchanged (with a warning) if encryption fails.
    """
    if not plaintext:
        return plaintext
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return plaintext

    if _PROVIDER == "aws" and _AWS_KEY_ARN:
        dek = Fernet.generate_key()
        f = Fernet(dek)
        ciphertext = f.encrypt(plaintext.encode("utf-8"))
        wrapped_dek = _aws_wrap_dek(dek)
        if wrapped_dek:
            envelope = {"v": 1, "provider": "aws",
                        "dek": base64.b64encode(wrapped_dek).decode(),
                        "data": base64.b64encode(ciphertext).decode()}
            return base64.b64encode(json.dumps(envelope).encode()).decode()

    if _PROVIDER == "gcp" and _GCP_KEY_PATH:
        dek = Fernet.generate_key()
        f = Fernet(dek)
        ciphertext = f.encrypt(plaintext.encode("utf-8"))
        wrapped_dek = _gcp_wrap_dek(dek)
        if wrapped_dek:
            envelope = {"v": 1, "provider": "gcp",
                        "dek": base64.b64encode(wrapped_dek).decode(),
                        "data": base64.b64encode(ciphertext).decode()}
            return base64.b64encode(json.dumps(envelope).encode()).decode()

    if _PROVIDER == "vault":
        dek = Fernet.generate_key()
        f = Fernet(dek)
        ciphertext = f.encrypt(plaintext.encode("utf-8"))
        wrapped_dek = _vault_wrap_dek(dek)
        if wrapped_dek:
            envelope = {"v": 1, "provider": "vault",
                        "dek": base64.b64encode(wrapped_dek).decode(),
                        "data": base64.b64encode(ciphertext).decode()}
            return base64.b64encode(json.dumps(envelope).encode()).decode()

    # Local Fernet fallback
    fernet = _get_fernet()
    if not fernet:
        logger.warning("encrypt_field: no encryption available — returning plaintext")
        return plaintext
    ciphertext = fernet.encrypt(plaintext.encode("utf-8"))
    envelope = {"v": 1, "provider": "local", "data": base64.b64encode(ciphertext).decode()}
    return base64.b64encode(json.dumps(envelope).encode()).decode()


def decrypt_field(ciphertext_b64: str) -> str:
    """Decrypt a ciphertext envelope produced by encrypt_field.

    Returns the original plaintext. If decryption fails (wrong key, corrupted
    data, or missing provider), returns the input unchanged and logs an error.
    """
    if not ciphertext_b64:
        return ciphertext_b64
    try:
        envelope = json.loads(base64.b64decode(ciphertext_b64.encode()).decode())
    except Exception:
        return ciphertext_b64  # not an envelope — return as-is (unencrypted column)

    provider = envelope.get("provider", "local")
    data_b64 = envelope.get("data", "")
    if not data_b64:
        return ciphertext_b64

    try:
        from cryptography.fernet import Fernet
        ciphertext_bytes = base64.b64decode(data_b64.encode())

        if provider == "aws":
            wrapped_dek = base64.b64decode(envelope["dek"].encode())
            dek = _aws_unwrap_dek(wrapped_dek)
            if dek:
                return Fernet(dek).decrypt(ciphertext_bytes).decode("utf-8")

        if provider == "gcp":
            wrapped_dek = base64.b64decode(envelope["dek"].encode())
            dek = _gcp_unwrap_dek(wrapped_dek)
            if dek:
                return Fernet(dek).decrypt(ciphertext_bytes).decode("utf-8")

        if provider == "vault":
            wrapped_dek = base64.b64decode(envelope["dek"].encode())
            dek = _vault_unwrap_dek(wrapped_dek)
            if dek:
                return Fernet(dek).decrypt(ciphertext_bytes).decode("utf-8")

        # local
        fernet = _get_fernet()
        if fernet:
            return fernet.decrypt(ciphertext_bytes).decode("utf-8")
    except Exception as exc:
        logger.error("decrypt_field failed: %s", exc)
    return ciphertext_b64


# ── Convenience helpers for common PII fields ─────────────────────────────────

def encrypt_email(email: str) -> str:
    return encrypt_field(email)

def decrypt_email(ciphertext: str) -> str:
    return decrypt_field(ciphertext)

def encrypt_chat_message(message: str) -> str:
    return encrypt_field(message)

def decrypt_chat_message(ciphertext: str) -> str:
    return decrypt_field(ciphertext)


# ── Key rotation helper ───────────────────────────────────────────────────────

def rotate_local_key(old_key_b64: str, new_key_b64: str, ciphertext_b64: str) -> str:
    """Re-encrypt a ciphertext envelope under a new local Fernet key.

    Used for key rotation: decrypt with old key, re-encrypt with new key.
    Only works for local-provider envelopes. Returns original on any error.
    """
    try:
        from cryptography.fernet import Fernet
        envelope = json.loads(base64.b64decode(ciphertext_b64.encode()).decode())
        if envelope.get("provider") != "local":
            return ciphertext_b64
        ciphertext_bytes = base64.b64decode(envelope["data"].encode())
        plaintext = Fernet(old_key_b64.encode()).decrypt(ciphertext_bytes).decode("utf-8")
        new_ciphertext = Fernet(new_key_b64.encode()).encrypt(plaintext.encode("utf-8"))
        new_envelope = {"v": 1, "provider": "local",
                        "data": base64.b64encode(new_ciphertext).decode()}
        return base64.b64encode(json.dumps(new_envelope).encode()).decode()
    except Exception as exc:
        logger.error("rotate_local_key failed: %s", exc)
        return ciphertext_b64
