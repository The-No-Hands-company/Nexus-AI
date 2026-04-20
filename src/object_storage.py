"""Object storage replication backend for S3 / R2 / GCS.

Supports push/restore of the SQLite DB and chat export bundles.
Configured via environment variables; no credentials are stored in code.
"""
from __future__ import annotations

import io
import os
import json
import hashlib
import logging
import gzip
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

S3_ENDPOINT      = os.getenv("S3_ENDPOINT", "")           # custom endpoint for R2/MinIO
S3_BUCKET        = os.getenv("S3_BUCKET", "nexus-ai-backups")
S3_ACCESS_KEY    = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY    = os.getenv("S3_SECRET_KEY", "")
S3_REGION        = os.getenv("S3_REGION", "auto")
S3_PREFIX        = os.getenv("S3_PREFIX", "nexus-ai/")
DB_PATH          = os.getenv("DB_PATH", "/tmp/nexus_ai.db")
NOTION_TOKEN     = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID     = os.getenv("NOTION_DATABASE_ID", "")
OBSIDIAN_VAULT   = os.getenv("OBSIDIAN_VAULT_PATH", "")


def _s3_client():
    """Return a boto3 S3 client or raise if boto3/credentials are missing."""
    try:
        import boto3  # type: ignore
        from botocore.config import Config  # type: ignore
    except ImportError as exc:
        raise RuntimeError("boto3 is not installed — run: pip install boto3") from exc

    kwargs: dict[str, Any] = {
        "aws_access_key_id":     S3_ACCESS_KEY or None,
        "aws_secret_access_key": S3_SECRET_KEY or None,
        "region_name":           S3_REGION,
        "config":                Config(signature_version="s3v4"),
    }
    if S3_ENDPOINT:
        kwargs["endpoint_url"] = S3_ENDPOINT
    return boto3.client("s3", **kwargs)


# ── DB backup helpers ─────────────────────────────────────────────────────────

def push_db_to_s3() -> dict:
    """Compress and upload the SQLite DB to S3/R2."""
    db_path = Path(DB_PATH)
    if not db_path.exists():
        return {"ok": False, "error": "DB file not found", "path": DB_PATH}

    raw = db_path.read_bytes()
    compressed = gzip.compress(raw, compresslevel=6)
    checksum = hashlib.sha256(compressed).hexdigest()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    key = f"{S3_PREFIX}db/{timestamp}_nexus_ai.db.gz"
    latest_key = f"{S3_PREFIX}db/latest_nexus_ai.db.gz"

    try:
        client = _s3_client()
        meta = {"sha256": checksum, "original_bytes": str(len(raw)), "timestamp": timestamp}
        client.put_object(Bucket=S3_BUCKET, Key=key, Body=compressed, Metadata=meta)
        client.put_object(Bucket=S3_BUCKET, Key=latest_key, Body=compressed, Metadata=meta)
        logger.info("DB pushed to S3: %s (%d bytes compressed)", key, len(compressed))
        return {"ok": True, "key": key, "bytes_compressed": len(compressed), "sha256": checksum}
    except Exception as exc:
        logger.error("S3 push failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def restore_db_from_s3(key: str | None = None) -> dict:
    """Download and restore the SQLite DB from S3/R2.

    If *key* is None, restores from the 'latest' pointer object.
    """
    try:
        client = _s3_client()
        actual_key = key or f"{S3_PREFIX}db/latest_nexus_ai.db.gz"
        obj = client.get_object(Bucket=S3_BUCKET, Key=actual_key)
        compressed = obj["Body"].read()
        raw = gzip.decompress(compressed)
        db_path = Path(DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(raw)
        checksum = hashlib.sha256(raw).hexdigest()
        logger.info("DB restored from S3: %s (%d bytes)", actual_key, len(raw))
        return {"ok": True, "key": actual_key, "bytes_restored": len(raw), "sha256": checksum}
    except Exception as exc:
        logger.error("S3 restore failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def list_s3_backups(limit: int = 20) -> dict:
    """List available DB backups in S3/R2."""
    try:
        client = _s3_client()
        prefix = f"{S3_PREFIX}db/"
        resp = client.list_objects_v2(Bucket=S3_BUCKET, Prefix=prefix, MaxKeys=limit)
        items = []
        for obj in resp.get("Contents", []):
            if obj["Key"].endswith(".db.gz") and "latest" not in obj["Key"]:
                items.append({
                    "key":           obj["Key"],
                    "size_bytes":    obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                })
        items.sort(key=lambda x: x["last_modified"], reverse=True)
        return {"ok": True, "backups": items}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backups": []}


def configure_s3(config: dict) -> dict:
    """Validate S3/R2 connectivity with the given config (does not persist to env)."""
    global S3_ENDPOINT, S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION, S3_PREFIX
    S3_ENDPOINT   = config.get("endpoint", S3_ENDPOINT)
    S3_BUCKET     = config.get("bucket", S3_BUCKET)
    S3_ACCESS_KEY = config.get("access_key", S3_ACCESS_KEY)
    S3_SECRET_KEY = config.get("secret_key", S3_SECRET_KEY)
    S3_REGION     = config.get("region", S3_REGION)
    S3_PREFIX     = config.get("prefix", S3_PREFIX)
    try:
        client = _s3_client()
        client.head_bucket(Bucket=S3_BUCKET)
        return {"ok": True, "bucket": S3_BUCKET, "endpoint": S3_ENDPOINT or "aws"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Notion export ─────────────────────────────────────────────────────────────

def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def export_chat_to_notion(chat: dict) -> dict:
    """Export a Nexus chat to a Notion database page."""
    if not NOTION_TOKEN:
        return {"ok": False, "error": "NOTION_TOKEN not configured"}
    if not NOTION_DB_ID:
        return {"ok": False, "error": "NOTION_DATABASE_ID not configured"}

    try:
        import requests  # type: ignore
    except ImportError:
        return {"ok": False, "error": "requests not installed"}

    title   = chat.get("title", "Untitled Chat")
    msgs    = chat.get("messages", [])
    created = chat.get("created_at", datetime.now(timezone.utc).isoformat())

    # Build children blocks from messages
    children = []
    for msg in msgs[:50]:  # Notion API has block limits
        role    = msg.get("role", "user")
        content = str(msg.get("content", ""))[:2000]
        children.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": f"[{role}] {content}"}}],
                "icon": {"emoji": "🤖" if role == "assistant" else "👤"},
                "color": "blue_background" if role == "assistant" else "gray_background",
            },
        })

    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": {
            "Name": {"title": [{"text": {"content": title}}]},
            "Created": {"date": {"start": created}},
            "Messages": {"number": len(msgs)},
        },
        "children": children,
    }

    try:
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=_notion_headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        page = resp.json()
        return {"ok": True, "page_id": page.get("id"), "url": page.get("url")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def export_chat_to_obsidian(chat: dict) -> dict:
    """Write a Nexus chat as a Markdown file to the Obsidian vault path."""
    vault = OBSIDIAN_VAULT
    if not vault:
        return {"ok": False, "error": "OBSIDIAN_VAULT_PATH not configured"}

    vault_path = Path(vault)
    if not vault_path.exists():
        return {"ok": False, "error": f"Vault path does not exist: {vault}"}

    nexus_folder = vault_path / "Nexus AI Chats"
    nexus_folder.mkdir(exist_ok=True)

    title   = chat.get("title", "Untitled Chat")
    msgs    = chat.get("messages", [])
    created = chat.get("created_at", datetime.now(timezone.utc).isoformat())
    cid     = chat.get("id", "unknown")

    # Build Markdown
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)[:80]
    md_lines = [
        f"---",
        f"title: \"{title}\"",
        f"created: {created}",
        f"chat_id: {cid}",
        f"tags: [nexus-ai, chat]",
        f"---",
        f"",
        f"# {title}",
        f"",
    ]
    for msg in msgs:
        role    = msg.get("role", "user")
        content = str(msg.get("content", ""))
        icon    = "🤖" if role == "assistant" else "👤"
        md_lines.append(f"### {icon} {role.capitalize()}")
        md_lines.append(content)
        md_lines.append("")

    md_content = "\n".join(md_lines)
    filename   = f"{safe_title}_{cid[:8]}.md"
    file_path  = nexus_folder / filename

    try:
        file_path.write_text(md_content, encoding="utf-8")
        return {"ok": True, "path": str(file_path), "filename": filename}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def export_workspace_to_obsidian(chats: list[dict]) -> dict:
    """Bulk export all chats to Obsidian vault."""
    results = []
    ok_count = 0
    for chat in chats:
        r = export_chat_to_obsidian(chat)
        results.append({"chat_id": chat.get("id"), **r})
        if r.get("ok"):
            ok_count += 1
    return {"ok": True, "exported": ok_count, "total": len(chats), "results": results}
