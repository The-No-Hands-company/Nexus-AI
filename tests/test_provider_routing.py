"""Test provider routing, health checks, and capability matrix."""
import os
import sys
import pytest
import json
from datetime import datetime, timezone

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.agent import (
    PROVIDERS,
    PROVIDER_CAPABILITIES,
    PROVIDER_TIERS,
    get_provider_health,
    get_provider_capabilities,
    get_providers_list,
    set_provider_persona_override,
    get_provider_persona_override,
    _smart_order,
    _score_complexity,
    _is_rate_limited,
    _mark_rate_limited,
    _config,
)


class TestProviderRegistry:
    """Test provider registry and configuration."""
    
    def test_providers_defined(self):
        """Test that all expected providers are defined."""
        expected_providers = [
            "ollama", "llm7", "groq", "cerebras", "gemini", "mistral",
            "openrouter", "nvidia", "cohere", "github_models", "grok", "claude"
        ]
        for provider in expected_providers:
            assert provider in PROVIDERS, f"Provider {provider} not found in PROVIDERS"
            assert "label" in PROVIDERS[provider], f"Provider {provider} missing 'label'"
            assert "default_model" in PROVIDERS[provider], f"Provider {provider} missing 'default_model'"
    
    def test_provider_tiers_valid(self):
        """Test that provider tiers contain valid provider IDs."""
        all_provider_ids = set(PROVIDERS.keys())
        for tier, providers in PROVIDER_TIERS.items():
            for provider_id in providers:
                assert provider_id in all_provider_ids, \
                    f"Invalid provider '{provider_id}' in tier '{tier}'"
    
    def test_capability_matrix_complete(self):
        """Test that capability matrix covers all providers."""
        for provider_id in PROVIDERS.keys():
            assert provider_id in PROVIDER_CAPABILITIES, \
                f"Provider {provider_id} missing from capability matrix"
            caps = PROVIDER_CAPABILITIES[provider_id]
            assert isinstance(caps, dict), f"Capabilities for {provider_id} is not a dict"
            # Check for expected capability flags
            expected_flags = ["vision", "json_mode", "tools", "reasoning", "streaming"]
            for flag in expected_flags:
                assert flag in caps, \
                    f"Provider {provider_id} missing capability flag '{flag}'"
                assert isinstance(caps[flag], bool), \
                    f"Capability '{flag}' for {provider_id} is not a boolean"


class TestProviderHealth:
    """Test provider health status checks."""
    
    def test_get_provider_health_returns_all_providers(self):
        """Test that get_provider_health returns health info for all providers."""
        health = get_provider_health()
        assert "providers" in health, "Health response missing 'providers' key"
        assert "timestamp" in health, "Health response missing 'timestamp' key"
        
        provider_ids = set(p["id"] for p in health["providers"])
        expected_ids = set(PROVIDERS.keys())
        assert provider_ids == expected_ids, \
            f"Health status missing providers: {expected_ids - provider_ids}"
    
    def test_health_status_fields(self):
        """Test that each provider health includes all required fields."""
        health = get_provider_health()
        
        for provider in health["providers"]:
            # Required fields
            assert "id" in provider, f"Provider health missing 'id'"
            assert "label" in provider, f"Provider health missing 'label'"
            assert "status" in provider, f"Provider health missing 'status'"
            assert "available" in provider, f"Provider health missing 'available'"
            assert "has_api_key" in provider, f"Provider health missing 'has_api_key'"
            assert "rate_limited" in provider, f"Provider health missing 'rate_limited'"
            assert "cooldown_remaining_seconds" in provider, \
                f"Provider health missing 'cooldown_remaining_seconds'"
            assert "capabilities" in provider, f"Provider health missing 'capabilities'"
            assert "benchmarks" in provider, f"Provider health missing 'benchmarks'"
            
            # Validate status
            assert provider["status"] in ("ready", "rate_limited", "unconfigured"), \
                f"Invalid status: {provider['status']}"
            
            # Validate benchmarks
            benchmarks = provider["benchmarks"]
            assert "estimated_latency_ms" in benchmarks
            assert "quality_score" in benchmarks
            assert "tier" in benchmarks
            assert "cost_tier" in benchmarks
    
    def test_rate_limit_state_consistency(self):
        """Test that rate_limited and cooldown_remaining are consistent."""
        health = get_provider_health()
        
        for provider in health["providers"]:
            if provider["rate_limited"]:
                # If rate limited, should have cooldown remaining
                assert provider["cooldown_remaining_seconds"] >= 0, \
                    f"Rate limited provider {provider['id']} has negative cooldown"
            else:
                # If not rate limited, cooldown should be 0
                assert provider["cooldown_remaining_seconds"] == 0, \
                    f"Non-rate-limited provider {provider['id']} has cooldown > 0"


class TestCapabilityMatrix:
    """Test provider capability matrix."""
    
    def test_get_provider_capabilities_structure(self):
        """Test that capability matrix has correct structure."""
        caps = get_provider_capabilities()
        assert "capabilities" in caps, "Missing 'capabilities' key"
        assert "providers" in caps, "Missing 'providers' key"
        
        # Check capabilities definition
        expected_capabilities = [
            "vision", "json_mode", "tools", "reasoning", "streaming"
        ]
        for cap in expected_capabilities:
            assert cap in caps["capabilities"], \
                f"Missing capability definition: {cap}"
            assert isinstance(caps["capabilities"][cap], str), \
                f"Capability '{cap}' definition is not a string"
    
    def test_providers_have_all_capabilities(self):
        """Test that all providers have all capability flags defined."""
        caps = get_provider_capabilities()
        providers_caps = caps["providers"]
        
        expected_flags = ["vision", "json_mode", "tools", "reasoning", "streaming"]
        for provider_id, provider_caps in providers_caps.items():
            for flag in expected_flags:
                assert flag in provider_caps, \
                    f"Provider {provider_id} missing capability '{flag}'"
                assert isinstance(provider_caps[flag], bool), \
                    f"Capability '{flag}' in {provider_id} is not boolean"


class TestProviderRouting:
    """Test provider routing logic."""
    
    def test_smart_order_low_complexity(self):
        """Test provider order for low complexity tasks."""
        order = _smart_order("what is 2+2?")
        assert len(order) > 0, "Smart order returned empty list"
        assert all(p in PROVIDERS for p in order), \
            "Smart order contains invalid provider IDs"
    
    def test_smart_order_high_complexity(self):
        """Test provider order for high complexity tasks."""
        task = (
            "Develop a full-stack REST API with user authentication, database, "
            "deployment pipeline, testing, and documentation. "
            "Architecture should support horizontal scaling. "
            "Include complete implementation with error handling."
        )
        order = _smart_order(task)
        assert len(order) > 0, "Smart order returned empty list"
        # High complexity should prioritize high-tier providers
        if "ollama" in PROVIDERS and os.getenv("OLLAMA_BASE_URL"):
            # ollama should be considered in routing
            assert "ollama" in order or order[0] in PROVIDER_TIERS["high"]
    
    def test_complexity_scoring(self):
        """Test task complexity scoring."""
        simple = "hello"
        medium = "Explain machine learning"
        complex_task = (
            "Build a production microservices architecture with "
            "deployment, monitoring, and disaster recovery"
        )
        
        score_simple = _score_complexity(simple)
        score_medium = _score_complexity(medium)
        score_complex = _score_complexity(complex_task)
        
        assert score_simple == "low"
        assert score_medium == "low" or score_medium == "medium"
        assert score_complex == "high" or score_complex == "medium"


class TestPersonaProviderOverride:
    """Test per-persona provider priority overrides."""
    
    def test_set_and_get_persona_override(self):
        """Test setting and retrieving persona-specific provider order."""
        persona = "general"
        custom_order = ["claude", "ollama", "gemini"]
        
        # Set override
        success = set_provider_persona_override(persona, custom_order)
        assert success, f"Failed to set provider override for {persona}"
        
        # Get override
        retrieved = get_provider_persona_override(persona)
        assert retrieved == custom_order, \
            f"Retrieved override {retrieved} doesn't match set {custom_order}"
    
    def test_invalid_provider_in_override(self):
        """Test that invalid providers are rejected."""
        persona = "general"
        invalid_order = ["claude", "invalid_provider"]
        
        success = set_provider_persona_override(persona, invalid_order)
        assert not success, "Should reject override with invalid provider"
    
    def test_invalid_persona(self):
        """Test that invalid personas are handled."""
        persona = "nonexistent_persona"
        order = ["claude", "ollama"]
        
        success = set_provider_persona_override(persona, order)
        assert not success, "Should reject override for nonexistent persona"


class TestProviderRateLimiting:
    """Test provider rate limiting logic."""
    
    def test_rate_limit_state_transitions(self):
        """Test rate limit state tracking."""
        from src.agent import _cooldowns
        
        provider_id = "test_provider"
        # Should not be rate limited initially
        assert not _is_rate_limited(provider_id), \
            "Provider should not be rate limited initially"
        
        # Mark as rate limited
        original_cooldowns = dict(_cooldowns)
        _mark_rate_limited(provider_id)
        assert _is_rate_limited(provider_id), \
            "Provider should be rate limited after marking"
        
        # Restore original state
        _cooldowns.clear()
        _cooldowns.update(original_cooldowns)


class TestProviderOrdering:
    """Test provider ordering and selection logic."""
    
    def test_provider_order_respects_tiers(self):
        """Test that provider order respects complexity tiers."""
        # For a simple task, should prefer low-tier providers
        simple_task = "say hello"
        order = _smart_order(simple_task)
        
        # At least some providers should be in the order
        assert len(order) > 0
        
        # All providers in order should be valid
        for provider in order:
            assert provider in PROVIDERS, f"Invalid provider in order: {provider}"
    
    def test_fallback_chain_completeness(self):
        """Test that fallback chain includes all available providers eventually."""
        from src.agent import _has_key
        
        order = _smart_order("test task")
        available_providers = {
            pid for pid, cfg in PROVIDERS.items() if _has_key(cfg)
        }
        
        # Order should eventually include all available providers
        providers_in_order = set(order)
        # At least some available providers should be in the order
        # (all if none are rate limited)
        assert len(providers_in_order & available_providers) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
