"""
GitHub Gist backup/restore for the SQLite database.
On startup: pull DB from Gist if it exists.
On every write: push DB to Gist in a background thread.
"""
import os
import base64
import threading
import requests
from pathlib import Path

GIST_TOKEN = os.getenv("GIST_TOKEN", "")
GIST_ID    = os.getenv("GIST_ID", "")
GIST_FILE  = "claude_alt.db.b64"
DB_PATH    = os.getenv("DB_PATH", "/tmp/claude_alt.db")

_push_lock  = threading.Lock()
_push_timer = None


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {GIST_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def restore_from_gist() -> bool:
    """
    Pull DB from Gist on startup.
    Returns True if restored, False if nothing to restore.
    """
    if not GIST_TOKEN or not GIST_ID:
        print("⚠️  No GIST_TOKEN/GIST_ID set — persistence via Gist disabled.")
        return False
    try:
        resp = requests.get(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(), timeout=15
        )
        resp.raise_for_status()
        files = resp.json().get("files", {})
        if GIST_FILE not in files:
            print("ℹ️  No backup found in Gist — starting fresh.")
            return False
        raw_url = files[GIST_FILE]["raw_url"]
        raw     = requests.get(raw_url, timeout=15).text.strip()
        if raw == "empty" or not raw:
            print("ℹ️  Gist backup is empty — starting fresh.")
            return False
        db_bytes = base64.b64decode(raw)
        Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(DB_PATH).write_bytes(db_bytes)
        print(f"✅ DB restored from Gist ({len(db_bytes):,} bytes)")
        return True
    except Exception as e:
        print(f"⚠️  Gist restore failed: {e} — starting fresh.")
        return False


def _do_push() -> None:
    """Actually push DB to Gist. Called from background thread."""
    if not GIST_TOKEN or not GIST_ID:
        return
    try:
        db_path = Path(DB_PATH)
        if not db_path.exists():
            return
        encoded = base64.b64encode(db_path.read_bytes()).decode()
        resp = requests.patch(
            f"https://api.github.com/gists/{GIST_ID}",
            headers=_headers(),
            json={"files": {GIST_FILE: {"content": encoded}}},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"⚠️  Gist push failed: {e}")


def schedule_push() -> None:
    """
    Debounced push — waits 3s after the last write before pushing.
    This batches rapid consecutive writes (e.g. saving a chat + memory)
    into a single Gist API call.
    """
    global _push_timer
    with _push_lock:
        if _push_timer is not None:
            _push_timer.cancel()
        _push_timer = threading.Timer(3.0, _do_push)
        _push_timer.daemon = True
        _push_timer.start()


def push_now() -> None:
    """Immediate synchronous push (used on graceful shutdown if needed)."""
    _do_push()
