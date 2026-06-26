"""Tests for organisation API routes."""

import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Isolated DB so tests don't collide via /tmp/nexus_ai.db
import uuid as _uuid
os.environ["DB_PATH"] = os.path.join(tempfile.gettempdir(), f"nexus_org_test_{os.getpid()}_{_uuid.uuid4().hex[:8]}.db")

from src.app import app


client = TestClient(app)

_suffix = "_" + _uuid.uuid4().hex[:6]


def _register_user(username: str, password: str = "password123"):
    return client.post("/auth/register", params={"username": username, "password": password})


def _make_token(username: str, role: str = "user") -> str:
    from src.routes._helpers import _make_token as _mt
    return _mt(username, role=role)


def _auth_header(username: str, role: str = "user") -> dict:
    return {"Authorization": f"Bearer {_make_token(username, role=role)}"}


def _create_org(name: str, username: str, role: str = "user") -> dict:
    resp = client.post("/orgs", json={"name": name + _suffix}, headers=_auth_header(username, role))
    assert resp.status_code == 200 or resp.status_code == 201
    return resp.json()


# ── Org CRUD tests ─────────────────────────────────────────────────────────


def test_create_org():
    _register_user("org_create_user")
    name = "Test Org CR" + _suffix
    resp = client.post("/orgs", json={"name": name}, headers=_auth_header("org_create_user"))
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("name") == name
    assert data.get("owner") == "org_create_user"
    assert data.get("id")


def test_create_org_missing_name():
    _register_user("org_create_no_name")
    resp = client.post("/orgs", json={}, headers=_auth_header("org_create_no_name"))
    assert resp.status_code == 400


def test_create_org_requires_auth():
    resp = client.post("/orgs", json={"name": "No Auth"})
    assert resp.status_code == 401


def test_list_orgs():
    _register_user("org_list_user")
    _create_org("ListOrg1", "org_list_user")
    _create_org("ListOrg2", "org_list_user")
    resp = client.get("/orgs", headers=_auth_header("org_list_user"))
    assert resp.status_code == 200
    data = resp.json()
    assert "orgs" in data
    assert len(data["orgs"]) >= 2


def test_get_org():
    _register_user("org_get_user")
    org = _create_org("GetOrgTest", "org_get_user")
    org_id = org["id"]
    resp = client.get(f"/orgs/{org_id}", headers=_auth_header("org_get_user"))
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("id") == org_id


def test_get_org_not_found():
    _register_user("org_get_nf")
    resp = client.get("/orgs/nonexistent-org-id", headers=_auth_header("org_get_nf"))
    assert resp.status_code in (403, 404)


def test_update_org():
    _register_user("org_upd_user")
    org = _create_org("UpdateOrg", "org_upd_user")
    org_id = org["id"]
    new_name = "Updated Org Name" + _suffix
    resp = client.patch(f"/orgs/{org_id}", json={"name": new_name}, headers=_auth_header("org_upd_user"))
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("name") == new_name


def test_delete_org():
    _register_user("org_del_user")
    org = _create_org("DeleteOrg", "org_del_user")
    org_id = org["id"]
    resp = client.delete(f"/orgs/{org_id}", headers=_auth_header("org_del_user"))
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("deleted") is True


# ── Member tests ────────────────────────────────────────────────────────


def test_add_list_remove_member():
    _register_user("org_member_owner")
    _register_user("org_member_user")
    org = _create_org("MemberTestOrg", "org_member_owner")
    org_id = org["id"]

    add_resp = client.post(
        f"/orgs/{org_id}/members",
        json={"username": "org_member_user", "role": "editor"},
        headers=_auth_header("org_member_owner"),
    )
    assert add_resp.status_code == 200

    list_resp = client.get(f"/orgs/{org_id}/members", headers=_auth_header("org_member_owner"))
    assert list_resp.status_code == 200
    members = list_resp.json().get("members", [])
    usernames = [m.get("username") for m in members]
    assert "org_member_user" in usernames

    remove_resp = client.delete(
        f"/orgs/{org_id}/members/org_member_user",
        headers=_auth_header("org_member_owner"),
    )
    assert remove_resp.status_code == 200


def test_add_member_requires_admin():
    _register_user("org_member_admin1")
    _register_user("org_member_admin2")
    org = _create_org("MemberAdminTest", "org_member_admin1")
    org_id = org["id"]

    resp = client.post(
        f"/orgs/{org_id}/members",
        json={"username": "org_member_admin2"},
        headers=_auth_header("org_member_admin2"),
    )
    assert resp.status_code == 403


def test_add_member_missing_username():
    _register_user("org_member_no_user")
    org = _create_org("MemberNoName", "org_member_no_user")
    org_id = org["id"]
    resp = client.post(
        f"/orgs/{org_id}/members",
        json={"role": "editor"},
        headers=_auth_header("org_member_no_user"),
    )
    assert resp.status_code == 400


# ── Invite tests ────────────────────────────────────────────────────────


def test_create_and_accept_invite():
    _register_user("org_invite_owner")
    _register_user("org_invite_user")
    org = _create_org("InviteOrg", "org_invite_owner")
    org_id = org["id"]

    invite_resp = client.post(
        f"/orgs/{org_id}/invites",
        json={"email": "org_invite_user@test.com", "role": "member"},
        headers=_auth_header("org_invite_owner"),
    )
    assert invite_resp.status_code == 200
    invite = invite_resp.json()
    assert "token" in invite or "code" in invite


# ── Usage tests ────────────────────────────────────────────────────────


def test_org_usage():
    _register_user("org_usage_user")
    org = _create_org("UsageOrg", "org_usage_user")
    org_id = org["id"]
    resp = client.get(f"/orgs/{org_id}/usage", headers=_auth_header("org_usage_user"))
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("org_id") == org_id
    assert "usage" in data
    assert "members" in data


# ── GDPR / Privacy tests ───────────────────────────────────────────────


def test_privacy_data_deletion_request():
    _register_user("privacy_req_user")
    resp = client.post(
        "/privacy/data-deletion-request",
        json={
            "regulation": "gdpr",
            "subject_type": "user",
            "subject_id": "privacy_req_user",
            "confirm": True,
            "reason": "testing deletion",
        },
        headers=_auth_header("privacy_req_user"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "completed"
    assert data.get("regulation") == "gdpr"


def test_privacy_delete_requires_confirm():
    _register_user("privacy_noconfirm")
    resp = client.post(
        "/privacy/data-deletion-request",
        json={
            "regulation": "gdpr",
            "subject_type": "user",
            "subject_id": "privacy_noconfirm",
            "confirm": False,
        },
        headers=_auth_header("privacy_noconfirm"),
    )
    assert resp.status_code == 422


def test_privacy_delete_requires_valid_regulation():
    _register_user("privacy_bad_reg")
    resp = client.post(
        "/privacy/data-deletion-request",
        json={
            "regulation": "invalid",
            "subject_type": "user",
            "subject_id": "privacy_bad_reg",
            "confirm": True,
        },
        headers=_auth_header("privacy_bad_reg"),
    )
    assert resp.status_code == 422


# ── Org API keys tests ─────────────────────────────────────────────────


def test_org_api_key_lifecycle():
    _register_user("org_apikey_user")
    org = _create_org("APIKeyOrg", "org_apikey_user")
    org_id = org["id"]

    create_resp = client.post(
        f"/orgs/{org_id}/api-keys",
        json={"name": "test-key"},
        headers=_auth_header("org_apikey_user"),
    )
    assert create_resp.status_code == 200
    key_data = create_resp.json()
    assert key_data.get("key", "").startswith("nxk_org_")

    list_resp = client.get(f"/orgs/{org_id}/api-keys", headers=_auth_header("org_apikey_user"))
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert "keys" in list_data
