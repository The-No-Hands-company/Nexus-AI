"""Redis / Valkey shared state store.

Provides distributed rate limiting, session state, pub/sub, and distributed
locks for Nexus AI.  Falls back to a thread-safe in-memory store when no Redis
URL is configured so that single-process deployments work without Redis.

Environment variables:
    REDIS_URL        — Redis connection URL (redis://host:port/db)
                       Leave unset for in-memory fallback.
    REDIS_MAX_CONN   — Max connections in the pool (default 10)
    REDIS_TIMEOUT    — Socket / connect timeout in seconds (default 3)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger("nexus.redis")

_REDIS_URL = os.getenv("REDIS_URL", "")
_MAX_CONN = int(os.getenv("REDIS_MAX_CONN", "10"))
_TIMEOUT = float(os.getenv("REDIS_TIMEOUT", "3"))

_redis_client = None
_redis_init_lock = threading.Lock()

# ── In-memory fallback backend ────────────────────────────────────────────────

class _MemStore:
    """Thread-safe in-memory key-value store with TTL, pub/sub, and locks."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}  # key -> (value, expires_at)
        self._lock = threading.RLock()
        self._subscribers: dict[str, list] = defaultdict(list)

    def get(self, key: str) -> Any:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            value, exp = item
            if exp is not None and time.time() > exp:
                del self._data[key]
                return None
            return value

    def set(self, key: str, value: Any, ex: int | None = None) -> None:
        with self._lock:
            exp = time.time() + ex if ex else None
            self._data[key] = (value, exp)

    def delete(self, *keys: str) -> int:
        with self._lock:
            count = 0
            for key in keys:
                if key in self._data:
                    del self._data[key]
                    count += 1
            return count

    def exists(self, *keys: str) -> int:
        with self._lock:
            return sum(1 for k in keys if self.get(k) is not None)

    def incr(self, key: str, amount: int = 1) -> int:
        with self._lock:
            current = self.get(key) or 0
            new_val = int(current) + amount
            item = self._data.get(key)
            exp = item[1] if item else None
            self._data[key] = (new_val, exp)
            return new_val

    def expire(self, key: str, seconds: int) -> bool:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return False
            value, _ = item
            self._data[key] = (value, time.time() + seconds)
            return True

    def ttl(self, key: str) -> int:
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return -2
            _, exp = item
            if exp is None:
                return -1
            remaining = exp - time.time()
            return max(0, int(remaining))

    def keys(self, pattern: str = "*") -> list[str]:
        with self._lock:
            now = time.time()
            # Remove expired
            expired = [k for k, (_, exp) in self._data.items() if exp is not None and now > exp]
            for k in expired:
                del self._data[k]
            if pattern == "*":
                return list(self._data.keys())
            # Simple prefix match
            prefix = pattern.rstrip("*")
            return [k for k in self._data.keys() if k.startswith(prefix)]

    def publish(self, channel: str, message: str) -> int:
        with self._lock:
            subs = self._subscribers.get(channel, [])
            for cb in subs:
                try:
                    cb(channel, message)
                except Exception:
                    pass
            return len(subs)

    def subscribe(self, channel: str, callback) -> None:
        with self._lock:
            self._subscribers[channel].append(callback)

    def unsubscribe(self, channel: str, callback) -> None:
        with self._lock:
            subs = self._subscribers.get(channel, [])
            self._subscribers[channel] = [c for c in subs if c != callback]

    def flush(self) -> None:
        with self._lock:
            self._data.clear()

    @property
    def is_fallback(self) -> bool:
        return True


_mem_store = _MemStore()


# ── Redis initialisation ──────────────────────────────────────────────────────

def _init_redis():
    """Attempt to connect to Redis; return client or None."""
    global _redis_client
    if not _REDIS_URL:
        logger.info("REDIS_URL not set — using in-memory state store")
        return None
    try:
        import redis  # type: ignore
        pool = redis.ConnectionPool.from_url(
            _REDIS_URL,
            max_connections=_MAX_CONN,
            socket_connect_timeout=_TIMEOUT,
            socket_timeout=_TIMEOUT,
            decode_responses=True,
        )
        client = redis.Redis(connection_pool=pool)
        client.ping()
        logger.info("Redis connected: %s", _REDIS_URL.split("@")[-1])
        return client
    except Exception as exc:
        logger.warning("Redis unavailable (%s) — using in-memory fallback", exc)
        return None


def get_redis():
    """Return the Redis client, or the in-memory fallback if Redis is unavailable."""
    global _redis_client
    if _redis_client is None:
        with _redis_init_lock:
            if _redis_client is None:
                _redis_client = _init_redis()
    return _redis_client or _mem_store


def is_redis_available() -> bool:
    """Return True if a live Redis connection exists."""
    client = get_redis()
    if isinstance(client, _MemStore):
        return False
    try:
        client.ping()
        return True
    except Exception:
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def redis_get(key: str) -> Any:
    client = get_redis()
    value = client.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value


def redis_set(key: str, value: Any, ex: int | None = None) -> None:
    client = get_redis()
    serialized = json.dumps(value) if not isinstance(value, (str, bytes, int, float)) else value
    if isinstance(client, _MemStore):
        client.set(key, value, ex=ex)
    else:
        if ex:
            client.set(key, serialized, ex=ex)
        else:
            client.set(key, serialized)


def redis_delete(*keys: str) -> int:
    return get_redis().delete(*keys)


def redis_exists(*keys: str) -> int:
    return get_redis().exists(*keys)


def redis_incr(key: str, amount: int = 1) -> int:
    client = get_redis()
    if isinstance(client, _MemStore):
        return client.incr(key, amount)
    return client.incr(key) if amount == 1 else client.incrby(key, amount)


def redis_expire(key: str, seconds: int) -> bool:
    return bool(get_redis().expire(key, seconds))


def redis_ttl(key: str) -> int:
    return get_redis().ttl(key)


def redis_keys(pattern: str = "*") -> list[str]:
    return list(get_redis().keys(pattern))


def redis_flush_all() -> None:
    """Flush all keys from the store (use with caution)."""
    client = get_redis()
    if isinstance(client, _MemStore):
        client.flush()
    else:
        client.flushdb()


# ── Rate limit helpers (distributed) ─────────────────────────────────────────

def incr_rate_counter(principal: str, window: str, window_seconds: int) -> int:
    """Increment and return the request count for a principal within a time window.

    Uses atomic incr + expire for distributed safety.
    Key format: ratelimit:{principal}:{window}
    """
    key = f"ratelimit:{principal}:{window}"
    client = get_redis()
    if isinstance(client, _MemStore):
        count = client.incr(key)
        client.expire(key, window_seconds)
        return count
    pipe = client.pipeline()
    pipe.incr(key)
    pipe.expire(key, window_seconds)
    results = pipe.execute()
    return int(results[0])


def get_rate_counter(principal: str, window: str) -> int:
    """Return the current counter for a principal/window without incrementing."""
    key = f"ratelimit:{principal}:{window}"
    val = get_redis().get(key)
    return int(val) if val else 0


# ── Session state ─────────────────────────────────────────────────────────────

def session_set(sid: str, data: dict, ttl: int = 3600) -> None:
    redis_set(f"session:{sid}", data, ex=ttl)


def session_get(sid: str) -> dict | None:
    val = redis_get(f"session:{sid}")
    return val if isinstance(val, dict) else None


def session_delete(sid: str) -> None:
    redis_delete(f"session:{sid}")


def session_touch(sid: str, ttl: int = 3600) -> None:
    redis_expire(f"session:{sid}", ttl)


# ── Pub/sub (SSE stream cancellation) ────────────────────────────────────────

def publish_stop_signal(stream_id: str) -> int:
    """Publish a stop signal for an active SSE stream."""
    return get_redis().publish(f"stream:stop:{stream_id}", "stop")


def subscribe_stop_signal(stream_id: str, callback) -> None:
    """Subscribe to stop signals for a stream (in-memory fallback only)."""
    client = get_redis()
    if isinstance(client, _MemStore):
        client.subscribe(f"stream:stop:{stream_id}", callback)


# ── Distributed lock ──────────────────────────────────────────────────────────

class _Lock:
    def __init__(self, key: str, ttl: int, token: str) -> None:
        self._key = key
        self._ttl = ttl
        self._token = token

    def release(self) -> None:
        client = get_redis()
        if isinstance(client, _MemStore):
            stored = client.get(self._key)
            if stored == self._token:
                client.delete(self._key)
        else:
            # Lua script for atomic check-and-delete
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            client.eval(script, 1, self._key, self._token)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


@contextmanager
def distributed_lock(
    name: str,
    ttl: int = 30,
    retry_delay: float = 0.1,
    retry_count: int = 50,
) -> Generator[bool, None, None]:
    """Acquire a distributed lock with automatic TTL-based expiry.

    Usage::
        with distributed_lock("my_resource") as acquired:
            if acquired:
                # critical section
                ...

    Falls back to a threading.Lock when using the in-memory store.
    """
    import secrets as _secrets
    key = f"dlock:{name}"
    token = _secrets.token_hex(16)
    client = get_redis()
    acquired = False

    if isinstance(client, _MemStore):
        # Simple in-process lock using the mem store's atomic incr
        for _ in range(retry_count):
            if not client.exists(key):
                client.set(key, token, ex=ttl)
                acquired = True
                break
            time.sleep(retry_delay)
        lock = _Lock(key, ttl, token)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
        return

    # Redis SET NX PX implementation
    for _ in range(retry_count):
        result = client.set(key, token, nx=True, ex=ttl)
        if result:
            acquired = True
            break
        time.sleep(retry_delay)

    lock = _Lock(key, ttl, token)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


# ── Response cache ────────────────────────────────────────────────────────────

_CACHE_DEFAULT_TTL = int(os.getenv("CACHE_TTL_SECONDS", "300"))


def cache_get(cache_key: str) -> Any:
    """Return cached value or None."""
    return redis_get(f"cache:{cache_key}")


def cache_set(cache_key: str, value: Any, ttl: int = _CACHE_DEFAULT_TTL) -> None:
    """Store a value in the response cache."""
    redis_set(f"cache:{cache_key}", value, ex=ttl)


def cache_invalidate(cache_key: str) -> int:
    """Delete a specific cache entry."""
    return redis_delete(f"cache:{cache_key}")


def cache_flush_prefix(prefix: str) -> int:
    """Delete all cache keys matching a prefix."""
    keys = redis_keys(f"cache:{prefix}*")
    return redis_delete(*keys) if keys else 0


def flush_prefix(prefix: str) -> int:
    """Backward-compatible alias for prefix cache flush."""
    return cache_flush_prefix(prefix)


def flush_all() -> None:
    """Flush all cache keys (admin operation)."""
    cache_flush_prefix("")


def cache_stats() -> dict:
    """Return stats about the current cache."""
    keys = redis_keys("cache:*")
    return {
        "total_cached_keys": len(keys),
        "backend": "redis" if is_redis_available() else "memory",
    }


# ── Health check ──────────────────────────────────────────────────────────────

def redis_health() -> dict:
    """Return Redis health information."""
    client = get_redis()
    if isinstance(client, _MemStore):
        return {
            "status": "degraded",
            "backend": "memory",
            "message": "Redis not configured — using in-memory fallback",
        }
    try:
        start = time.time()
        client.ping()
        latency_ms = round((time.time() - start) * 1000, 2)
        return {
            "status": "healthy",
            "backend": "redis",
            "url": _REDIS_URL.split("@")[-1] if "@" in _REDIS_URL else _REDIS_URL,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "backend": "redis",
            "error": str(exc),
        }
