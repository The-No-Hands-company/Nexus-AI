"""
src/security/ip_filter.py — IP allowlisting, geo-blocking, and rate-limiting middleware

Features:
  - CIDR-based IP allowlist (whitelist mode): only listed networks can access the API
  - CIDR-based IP blocklist (blacklist mode): explicit deny for known-bad ranges
  - Country-code geo-blocking: block or allow specific ISO 3166-1 alpha-2 country codes
  - Trusted proxy header support: X-Forwarded-For, X-Real-IP
  - Bypass for health-check endpoints

Environment variables:
    IP_ALLOWLIST        — comma-separated CIDR ranges that are allowed (empty = allow all)
    IP_BLOCKLIST        — comma-separated CIDR ranges that are always blocked
    GEO_BLOCKED_COUNTRIES — comma-separated ISO codes to block (e.g. "CN,RU,KP")
    GEO_ALLOWED_COUNTRIES — comma-separated ISO codes to allow exclusively (overrides blocklist)
    TRUSTED_PROXIES     — comma-separated CIDR ranges of trusted reverse proxies
    IP_BYPASS_PATHS     — comma-separated path prefixes that bypass IP filtering (default: /health)
    MAXMIND_DB_PATH     — path to GeoLite2-Country.mmdb for geo-lookup (optional)
"""

from __future__ import annotations

import ipaddress
import logging
import os
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger("nexus.security.ip_filter")

# ── Config ─────────────────────────────────────────────────────────────────────

def _parse_cidrs(env_var: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return []
    networks = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("IP filter: invalid CIDR '%s' in %s — skipping", part, env_var)
    return networks


_ALLOWLIST: list = []
_BLOCKLIST: list = []
_TRUSTED_PROXIES: list = []
_GEO_BLOCKED: set[str] = set()
_GEO_ALLOWED: set[str] = set()
_BYPASS_PATHS: list[str] = []
_MAXMIND_DB: str = ""
_mmdb_reader = None
_config_loaded = False


def _load_config() -> None:
    global _ALLOWLIST, _BLOCKLIST, _TRUSTED_PROXIES, _GEO_BLOCKED, _GEO_ALLOWED
    global _BYPASS_PATHS, _MAXMIND_DB, _config_loaded
    _ALLOWLIST = _parse_cidrs("IP_ALLOWLIST")
    _BLOCKLIST = _parse_cidrs("IP_BLOCKLIST")
    _TRUSTED_PROXIES = _parse_cidrs("TRUSTED_PROXIES")
    _GEO_BLOCKED = {c.strip().upper() for c in os.getenv("GEO_BLOCKED_COUNTRIES", "").split(",") if c.strip()}
    _GEO_ALLOWED = {c.strip().upper() for c in os.getenv("GEO_ALLOWED_COUNTRIES", "").split(",") if c.strip()}
    bypass_raw = os.getenv("IP_BYPASS_PATHS", "/health,/health/live,/health/deep")
    _BYPASS_PATHS = [p.strip() for p in bypass_raw.split(",") if p.strip()]
    _MAXMIND_DB = os.getenv("MAXMIND_DB_PATH", "").strip()
    _config_loaded = True


def _get_mmdb():
    global _mmdb_reader
    if _mmdb_reader is not None:
        return _mmdb_reader
    if not _MAXMIND_DB:
        return None
    try:
        import maxminddb  # type: ignore
        _mmdb_reader = maxminddb.open_database(_MAXMIND_DB)
        logger.info("MaxMind GeoLite2-Country loaded from %s", _MAXMIND_DB)
    except ImportError:
        logger.debug("maxminddb not installed — geo-blocking by country disabled")
    except Exception as exc:
        logger.warning("Could not open MaxMind DB: %s", exc)
    return _mmdb_reader


def _extract_client_ip(request: Request) -> str:
    """Extract the real client IP from request, respecting trusted proxy headers."""
    if not _config_loaded:
        _load_config()
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    real_ip = request.headers.get("x-real-ip", "").strip()
    remote_addr = request.client.host if request.client else "127.0.0.1"

    if forwarded_for and _TRUSTED_PROXIES:
        # Validate that the connecting IP is a trusted proxy before trusting X-Forwarded-For
        try:
            remote_ip = ipaddress.ip_address(remote_addr)
            if any(remote_ip in net for net in _TRUSTED_PROXIES):
                # Use the leftmost (original client) IP from X-Forwarded-For
                first_ip = forwarded_for.split(",")[0].strip()
                return first_ip
        except ValueError:
            pass

    if real_ip and _TRUSTED_PROXIES:
        try:
            remote_ip = ipaddress.ip_address(remote_addr)
            if any(remote_ip in net for net in _TRUSTED_PROXIES):
                return real_ip
        except ValueError:
            pass

    return remote_addr


def _check_ip(ip_str: str) -> tuple[bool, str]:
    """Returns (allowed, reason). allowed=True means the request may proceed."""
    if not _config_loaded:
        _load_config()
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False, f"unparseable IP: {ip_str}"

    # Explicit blocklist always wins
    for net in _BLOCKLIST:
        if ip in net:
            return False, f"IP {ip_str} is in blocklist ({net})"

    # Allowlist: if configured, IP must be in it
    if _ALLOWLIST:
        in_allow = any(ip in net for net in _ALLOWLIST)
        if not in_allow:
            return False, f"IP {ip_str} not in allowlist"

    return True, "ok"


def _check_geo(ip_str: str) -> tuple[bool, str]:
    """Returns (allowed, reason). allowed=True means the request may proceed."""
    if not (_GEO_BLOCKED or _GEO_ALLOWED):
        return True, "no geo rules"
    reader = _get_mmdb()
    if reader is None:
        return True, "geo-lookup unavailable"
    try:
        record = reader.get(ip_str)
        if record is None:
            return True, "no geo record"
        country_code = (record.get("country") or {}).get("iso_code", "").upper()
        if not country_code:
            return True, "no country code"
        if _GEO_ALLOWED and country_code not in _GEO_ALLOWED:
            return False, f"country {country_code} not in allowed list"
        if _GEO_BLOCKED and country_code in _GEO_BLOCKED:
            return False, f"country {country_code} is geo-blocked"
    except Exception as exc:
        logger.debug("Geo lookup error for %s: %s", ip_str, exc)
    return True, "ok"


# ── Starlette middleware ───────────────────────────────────────────────────────

class IPFilterMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces IP allowlist and geo-blocking rules."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        _load_config()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip filter for bypass paths
        path = request.url.path
        for bypass in _BYPASS_PATHS:
            if path.startswith(bypass):
                return await call_next(request)

        client_ip = _extract_client_ip(request)
        allowed, reason = _check_ip(client_ip)
        if not allowed:
            logger.warning("IP filter blocked %s — %s", client_ip, reason)
            return JSONResponse({"error": "Access denied", "reason": reason}, status_code=403)

        geo_allowed, geo_reason = _check_geo(client_ip)
        if not geo_allowed:
            logger.warning("Geo filter blocked %s — %s", client_ip, geo_reason)
            return JSONResponse({"error": "Access denied from your region", "reason": geo_reason},
                                status_code=403)

        return await call_next(request)


# ── Programmatic helpers (for tests and admin API) ────────────────────────────

def add_to_allowlist(cidr: str) -> bool:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        if net not in _ALLOWLIST:
            _ALLOWLIST.append(net)
        return True
    except ValueError:
        return False


def remove_from_allowlist(cidr: str) -> bool:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        if net in _ALLOWLIST:
            _ALLOWLIST.remove(net)
            return True
    except ValueError:
        pass
    return False


def add_to_blocklist(cidr: str) -> bool:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
        if net not in _BLOCKLIST:
            _BLOCKLIST.append(net)
        return True
    except ValueError:
        return False


def get_filter_status() -> dict:
    if not _config_loaded:
        _load_config()
    return {
        "allowlist_cidrs": [str(n) for n in _ALLOWLIST],
        "blocklist_cidrs": [str(n) for n in _BLOCKLIST],
        "geo_blocked_countries": sorted(_GEO_BLOCKED),
        "geo_allowed_countries": sorted(_GEO_ALLOWED),
        "trusted_proxies": [str(n) for n in _TRUSTED_PROXIES],
        "bypass_paths": _BYPASS_PATHS,
        "maxmind_db": _MAXMIND_DB or None,
    }


def is_ip_allowed(ip_str: str) -> tuple[bool, str]:
    """Public helper — check if an IP would be allowed by current rules."""
    ip_ok, ip_reason = _check_ip(ip_str)
    if not ip_ok:
        return False, ip_reason
    geo_ok, geo_reason = _check_geo(ip_str)
    return geo_ok, geo_reason
