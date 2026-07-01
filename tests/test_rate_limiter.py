"""Tests for src/rate_limiter.py — sliding-window enforcement and per-user quotas."""

from __future__ import annotations

import time


from src.rate_limiter import (
    RateLimitMiddleware,
    check_rate_limit,
    get_quota_status,
    get_settings,
    list_user_overrides,
    remove_user_override,
    set_user_quota,
    update_settings,
)


class TestRateLimiterBasics:
    """Unit tests for the rate limiter module."""

    def test_default_settings_loaded(self):
        s = get_settings()
        assert s["mode"] == "soft"
        assert s["per_minute"] == 60
        assert s["per_day"] == 2500

    def test_update_settings_persists(self):
        update_settings("hard", 30, 1000)
        s = get_settings()
        assert s["mode"] == "hard"
        assert s["per_minute"] == 30
        assert s["per_day"] == 1000
        # Reset to defaults for other tests
        update_settings("soft", 60, 2500)

    def test_check_rate_limit_allows_first_request(self):
        pid = f"test-{time.time()}"
        result = check_rate_limit(pid)
        assert result["allowed"] is True
        assert result["retry_after_seconds"] == 0

    def test_check_rate_limit_returns_principal(self):
        result = check_rate_limit("alice")
        assert result["principal"] == "alice"

    def test_get_quota_status_initial(self):
        status = get_quota_status("bob")
        assert status["principal"] == "bob"
        assert status["used_this_minute"] >= 0
        assert status["allowed"] is True

    def test_get_quota_status_respects_global_limits(self):
        status = get_quota_status("unknown_user")
        assert status["per_minute_limit"] == 60
        assert status["per_day_limit"] == 2500


class TestPerUserQuotaOverrides:
    """Tests for per-user quota override management."""

    def test_set_user_quota_creates_override(self):
        result = set_user_quota("power_user", per_minute=200, per_day=10000)
        assert result["username"] == "power_user"
        assert result["per_minute"] == 200
        assert result["per_day"] == 10000
        assert result["has_override"] is True

    def test_override_reflected_in_quota_status(self):
        set_user_quota("vip", per_minute=500, per_day=50000)
        status = get_quota_status("vip")
        assert status["per_minute_limit"] == 500
        assert status["per_day_limit"] == 50000

    def test_override_appears_in_list(self):
        set_user_quota("listed_user", per_minute=100, per_day=None)
        users = list_user_overrides()
        usernames = [u["username"] for u in users]
        assert "listed_user" in usernames

    def test_remove_override_restores_global(self):
        set_user_quota("temp_user", per_minute=50, per_day=500)
        assert remove_user_override("temp_user") is True
        status = get_quota_status("temp_user")
        assert status["per_minute_limit"] == 60  # global default

    def test_remove_nonexistent_override_returns_false(self):
        assert remove_user_override("no_such_user_xyz") is False


class TestRateLimitBurst:
    """Tests that rate limiting actually blocks after exceeding limits."""

    def test_burst_under_limit_all_allowed(self):
        update_settings("hard", 10, 100)  # Low limits for testing
        pid = f"burst-user-{time.time()}"
        for _ in range(10):
            r = check_rate_limit(pid)
            assert r["allowed"] is True, f"Expected allowed but got {r}"
        update_settings("soft", 60, 2500)  # Reset

    def test_burst_over_limit_blocked_in_hard_mode(self):
        update_settings("hard", 3, 100)  # Very low
        pid = f"hard-burst-{time.time()}"
        # First 3 should pass
        for _ in range(3):
            assert check_rate_limit(pid)["allowed"] is True
        # 4th should be blocked in hard mode
        r = check_rate_limit(pid)
        assert r["allowed"] is False
        assert r["retry_after_seconds"] > 0
        update_settings("soft", 60, 2500)

    def test_burst_over_limit_allowed_in_soft_mode(self):
        update_settings("soft", 3, 100)
        pid = f"soft-burst-{time.time()}"
        for _ in range(3):
            assert check_rate_limit(pid)["allowed"] is True
        # In soft mode, still allowed but with limit info
        r = check_rate_limit(pid)
        assert r["allowed"] is True
        assert r.get("limit_type") in ("per_minute", "")
        update_settings("soft", 60, 2500)


class TestRateLimitMiddlewareClass:
    """Minimal smoke tests for the ASGI middleware class."""

    def test_middleware_instantiable(self):
        class FakeApp:
            async def __call__(self, scope, receive, send):
                pass

        mw = RateLimitMiddleware(FakeApp())
        assert mw is not None

    def test_middleware_skips_health_paths(self):
        """Middleware should skip health/metrics paths."""
        mw = RateLimitMiddleware(None)
        # _SKIP_PREFIXES should contain health and metrics
        assert any(p == "/health" for p in mw._SKIP_PREFIXES)
        assert any(p == "/metrics" for p in mw._SKIP_PREFIXES)
        assert any(p == "/static" for p in mw._SKIP_PREFIXES)
        assert "OPTIONS" in mw._SKIP_METHODS
        assert "HEAD" in mw._SKIP_METHODS
