import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from src.app import app
from src.db import add_safety_audit_entry, clear_safety_audit_entries
from src.tools_builtin import dispatch_builtin
import src.team_policies as team_policies


client = TestClient(app)


def _reset_team_policy_state():
    team_policies._policies.clear()
    team_policies._violation_log.clear()
    team_policies._policy_alerts.clear()
    team_policies._approval_workflows.clear()
    team_policies._workflows.clear()
    team_policies._department_quotas.clear()
    team_policies._department_usage.clear()
    team_policies._compliance_config.clear()
    team_policies._compliance_config.update(
        {
            "regions": team_policies.copy.deepcopy(team_policies._DEFAULT_REGION_PROFILES),
            "default_region": "global",
            "data_residency_enforced": False,
            "gdpr_mode": False,
            "hipaa_mode": False,
            "soc2_mode": False,
            "managed_connectors": {
                "sso": {
                    "enabled": True,
                    "providers": ["oidc", "saml", "google_oidc", "github_oauth"],
                },
                "compliance_apis": {
                    "enabled": False,
                    "providers": [],
                },
            },
            "updated_at": team_policies._utc_now(),
        }
    )


def test_policy_hitl_gate_and_workflow_approval(tmp_path):
    _reset_team_policy_state()

    created = client.post(
        "/admin/team-policies",
        json={
            "team_id": "team-hitl",
            "name": "Ops approval",
            "allowed_tools": ["run_command"],
            "require_hitl_for": ["run_command"],
        },
    )
    assert created.status_code == 200

    eval_resp = client.post(
        "/admin/team-policies/evaluate",
        json={
            "team_id": "team-hitl",
            "tool_action": "run_command",
            "user": "alice",
            "role": "developer",
            "context": {"command": "printf hi"},
        },
    )
    assert eval_resp.status_code == 200
    payload = eval_resp.json()
    assert payload["allowed"] is False
    assert payload["requires_hitl"] is True
    assert payload["workflow_id"]
    assert payload["next_approver_role"] == "manager"

    advanced = client.post(
        f"/admin/approval-workflows/{payload['workflow_id']}/advance",
        json={
            "approver": "manager_a",
            "approver_role": "manager",
            "decision": "approve",
            "comment": "approved for maintenance window",
        },
    )
    assert advanced.status_code == 200
    assert advanced.json()["workflow"]["status"] == "approved"

    dispatched = dispatch_builtin(
        {
            "action": "run_command",
            "command": "printf hi",
            "workdir": str(tmp_path),
            "team_id": "team-hitl",
            "username": "alice",
            "role": "developer",
            "policy_workflow_id": payload["workflow_id"],
        },
        session_id="sess-hitl",
    )
    assert dispatched is not None
    assert dispatched["status"] == "done"
    assert "hi" in dispatched["result"]


def test_policy_denial_creates_violation_and_alert(tmp_path):
    _reset_team_policy_state()

    created = client.post(
        "/admin/team-policies",
        json={
            "team_id": "team-deny",
            "name": "No deletes",
            "denied_tools": ["delete_file"],
        },
    )
    assert created.status_code == 200

    target = tmp_path / "blocked.txt"
    target.write_text("content")

    dispatched = dispatch_builtin(
        {
            "action": "delete_file",
            "path": "blocked.txt",
            "workdir": str(tmp_path),
            "team_id": "team-deny",
            "username": "bob",
        },
        session_id="sess-deny",
    )
    assert dispatched is not None
    assert dispatched["status"] == "error"
    assert dispatched["error"] == "policy_denied"
    assert target.exists()

    violations = client.get("/admin/policy-violations?team_id=team-deny&limit=10")
    assert violations.status_code == 200
    data = violations.json()
    assert len(data["violations"]) == 1
    assert len(data["alerts"]) == 1
    assert data["violations"][0]["reason"] == "tool_denied"
    assert "remediation" in data["violations"][0]
    assert data["alerts"][0]["status"] == "open"


def test_compliance_update_validates_regions():
    _reset_team_policy_state()

    invalid = client.put(
        "/admin/compliance",
        json={
            "default_region": "apac",
            "regions": {"global": {"display_name": "Global"}},
        },
    )
    assert invalid.status_code == 422

    valid = client.put(
        "/admin/compliance",
        json={
            "default_region": "eu",
            "data_residency_enforced": True,
            "regions": {
                "global": {
                    "display_name": "Global",
                    "data_residency": "global",
                    "cross_region_inference": True,
                    "allowed_idps": ["oidc"],
                    "compliance_apis": [],
                },
                "eu": {
                    "display_name": "European Union",
                    "data_residency": "eu",
                    "cross_region_inference": False,
                    "allowed_idps": ["saml"],
                    "compliance_apis": ["gdpr_delete"],
                },
            },
        },
    )
    assert valid.status_code == 200
    payload = valid.json()
    assert payload["default_region"] == "eu"
    assert payload["data_residency_enforced"] is True
    assert payload["regions"]["eu"]["data_residency"] == "eu"


def test_safety_audit_integrity_and_export():
    clear_safety_audit_entries()
    add_safety_audit_entry({"ts": 1.0, "type": "block", "session_id": "s1", "detail": "one"})
    add_safety_audit_entry({"ts": 2.0, "type": "pii_scrub", "session_id": "s1", "detail": "two"})

    audit = client.get("/safety/audit?limit=10")
    assert audit.status_code == 200
    audit_payload = audit.json()
    assert audit_payload["integrity"]["ok"] is True
    assert audit_payload["integrity"]["checked"] >= 2

    export = client.get("/admin/audit-log/export?fmt=json&limit=10")
    assert export.status_code == 200
    export_payload = export.json()
    assert export_payload["integrity"]["ok"] is True
    assert '"type": "block"' in export_payload["export"]
