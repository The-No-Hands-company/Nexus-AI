"""Integration tests for auth.py JWT flows and safety/copyright.py registry."""

import json
import time
import unittest
from unittest.mock import patch

from src.auth import (
    AuthPrincipal,
    decode_token,
    get_principal,
    hash_password,
    issue_token,
    require_admin,
    require_user,
    verify_password,
)
from src.safety.copyright import CopyrightRegistry, load_registry_from_db


class TestAuthJWTFlow(unittest.TestCase):
    """Tests for the PyJWT-based auth module."""

    def _make_request(self, token: str = ""):
        class _MockRequest:
            headers = {"Authorization": f"Bearer {token}"} if token else {}

        return _MockRequest()

    def test_issue_and_decode_token(self):
        token = issue_token("alice", role="admin")
        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)
        payload = decode_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "alice")
        self.assertEqual(payload["role"], "admin")
        self.assertEqual(payload["type"], "access")
        self.assertIn("jti", payload)
        self.assertIn("exp", payload)
        self.assertIn("iat", payload)

    def test_decode_tampered_token_returns_none(self):
        token = issue_token("bob")
        tampered = token[:-5] + "xxxxx"
        self.assertIsNone(decode_token(tampered))

    def test_decode_expired_token_returns_none(self):
        with patch("src.auth.JWT_EXPIRE_H", -1):
            token = issue_token("charlie")
        self.assertIsNone(decode_token(token))

    def test_decode_garbage_returns_none(self):
        self.assertIsNone(decode_token("not-a-jwt-at-all"))

    def test_decode_empty_returns_none(self):
        self.assertIsNone(decode_token(""))

    def test_get_principal_unauthenticated(self):
        req = self._make_request("")
        principal = get_principal(req)
        self.assertIsInstance(principal, AuthPrincipal)
        self.assertEqual(principal.user_id, "anonymous")
        self.assertEqual(principal.role, "owner")

    def test_get_principal_with_valid_token(self):
        token = issue_token("dave", role="user")
        req = self._make_request(token)
        principal = get_principal(req)
        self.assertEqual(principal.user_id, "dave")
        self.assertEqual(principal.role, "user")
        self.assertTrue(principal.token_id)

    def test_get_principal_with_expired_token(self):
        with patch("src.auth.JWT_EXPIRE_H", -1):
            token = issue_token("eve")
        req = self._make_request(token)
        principal = get_principal(req)
        self.assertEqual(principal.user_id, "anonymous")

    def test_require_user_authenticated(self):
        token = issue_token("frank", role="admin")
        req = self._make_request(token)
        principal = require_user(req)
        self.assertEqual(principal.user_id, "frank")

    def test_require_user_unauthenticated_raises(self):
        req = self._make_request("")
        with self.assertRaises(Exception) as ctx:
            require_user(req)
        self.assertIn("Authentication required", str(ctx.exception))

    def test_require_admin_with_admin_role(self):
        token = issue_token("grace", role="admin")
        req = self._make_request(token)
        principal = require_admin(req)
        self.assertEqual(principal.user_id, "grace")

    def test_require_admin_with_user_role_raises(self):
        token = issue_token("heidi", role="user")
        req = self._make_request(token)
        with self.assertRaises(Exception) as ctx:
            require_admin(req)
        self.assertIn("Admin access required", str(ctx.exception))

    def test_require_admin_unauthenticated_raises(self):
        req = self._make_request("")
        with self.assertRaises(Exception) as ctx:
            require_admin(req)
        self.assertIn("Authentication required", str(ctx.exception))

    def test_token_has_jti_unique(self):
        t1 = decode_token(issue_token("ivan"))
        t2 = decode_token(issue_token("ivan"))
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        self.assertNotEqual(t1["jti"], t2["jti"])


class TestAuthPasswordHashing(unittest.TestCase):
    """Tests for PBKDF2 password hashing."""

    def test_hash_and_verify_correct(self):
        pw = "my-secret-password-123!"
        hashed = hash_password(pw)
        self.assertIn("$", hashed)
        self.assertTrue(verify_password(pw, hashed))

    def test_verify_wrong_password(self):
        pw = "correct-password"
        hashed = hash_password(pw)
        self.assertFalse(verify_password("wrong-password", hashed))

    def test_verify_empty_password(self):
        hashed = hash_password("real-password")
        self.assertFalse(verify_password("", hashed))

    def test_verify_malformed_stored(self):
        self.assertFalse(verify_password("any", "not-a-valid-format"))

    def test_verify_short_stored(self):
        self.assertFalse(verify_password("any", "nodelimiter"))

    def test_different_salts_produce_different_hashes(self):
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        self.assertNotEqual(h1, h2)


class TestCopyrightRegistry(unittest.TestCase):
    """Tests for the CopyrightRegistry with Jaccard similarity."""

    def setUp(self):
        self.registry = CopyrightRegistry()

    def test_empty_registry_returns_no_matches(self):
        results = self.registry.check("Any text at all")
        self.assertEqual(results, [])

    def test_register_and_check_exact_match(self):
        self.registry.register("The quick brown fox jumps over the lazy dog.")
        results = self.registry.check("The quick brown fox jumps over the lazy dog.")
        self.assertTrue(any(r["score"] >= 0.8 for r in results))

    def test_register_and_check_partial_match_below_threshold(self):
        self.registry.register("The quick brown fox jumps over the lazy dog.")
        results = self.registry.check("Totally unrelated text about something else entirely.")
        self.assertEqual(results, [])

    def test_custom_threshold(self):
        self.registry.register("One two three four five.")
        results = self.registry.check("One two three four five six seven.", threshold=0.5)
        self.assertTrue(any(r["score"] >= 0.5 for r in results))

    def test_register_multiple_sentences(self):
        self.registry.register("First sentence. Second sentence. Third sentence here.")
        entries = self.registry.list_entries()
        self.assertEqual(len(entries), 3)

    def test_list_entries(self):
        self.registry.register("Hello world.", source="test.txt")
        entries = self.registry.list_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].source, "test.txt")

    def test_clear(self):
        self.registry.register("Some text.")
        self.assertEqual(len(self.registry.list_entries()), 1)
        self.registry.clear()
        self.assertEqual(len(self.registry.list_entries()), 0)

    def test_register_with_metadata(self):
        self.registry.register("Copyrighted content.", metadata={"author": "John"})
        entries = self.registry.list_entries()
        self.assertEqual(entries[0].metadata, {"author": "John"})

    def test_check_returns_match_details(self):
        self.registry.register("Unique phrase in registry.", source="book.txt")
        results = self.registry.check("Unique phrase in registry.")
        self.assertGreater(len(results), 0)
        r = results[0]
        self.assertIn("score", r)
        self.assertIn("matched_text", r)
        self.assertIn("source", r)
        self.assertEqual(r["source"], "book.txt")

    def test_empty_text_register_adds_nothing(self):
        self.registry.register("")
        self.assertEqual(len(self.registry.list_entries()), 0)

    def test_whitespace_only_text_register_adds_nothing(self):
        self.registry.register("   \n\n  ")
        self.assertEqual(len(self.registry.list_entries()), 0)


class TestCopyrightRegistrySingleton(unittest.TestCase):
    """Tests for the module-level registry singleton."""

    def setUp(self):
        from src.safety import copyright as _cpy

        _cpy._registry = None

    def test_load_registry_returns_singleton(self):
        r1 = load_registry_from_db()
        r2 = load_registry_from_db()
        self.assertIs(r1, r2)

    def test_registry_persists_across_loads(self):
        reg = load_registry_from_db()
        reg.register("Persistent text here.")
        reg2 = load_registry_from_db()
        self.assertEqual(len(reg2.list_entries()), 1)


if __name__ == "__main__":
    unittest.main()
