"""Team policies, RBAC, and compliance controls for Nexus AI enterprise.

Features:
- Team-level tool and data access policies
- Role hierarchy beyond admin/user/viewer
- Regional compliance settings
- Department / cost-center quota allocation
- Audit trail export
- Multi-tier approval workflows
- Policy violation alerts
"""
from __future__ import annotations

import copy
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "user": 10,
    "developer": 20,
    "analyst": 25,
    "manager": 30,
    "director": 40,
    "admin": 50,
    "superadmin": 60,
}

HIGH_RISK_TIER_MAP: dict[str, list[str]] = {
    "delete_database": ["manager", "director", "admin"],
    "run_command": ["manager"],
    "delete_file": ["developer"],
    "write_file": [],
    "bulk_delete": ["manager", "director"],
    "schema_migration": ["developer", "manager"],
}

_REMEDIATION_BY_REASON = {
    "tool_denied": "Remove the blocked action or update the team policy deny-list if the action is legitimately required.",
    "tool_not_in_allowlist": "Add the action to the team allow-list or use an approved alternative tool.",
    "model_not_allowed": "Select a model that is explicitly allowed for this team or update the model policy.",
    "region_not_allowed": "Run the action in an allowed region or expand the policy's allowed_regions after review.",
    "hitl_required": "Advance the generated approval workflow to an approved state, then retry with policy_workflow_id.",
}

_DEFAULT_REGION_PROFILES: dict[str, dict[str, Any]] = {
    "global": {
        "display_name": "Global",
        "data_residency": "flexible",
        "cross_region_inference": True,
        "allowed_idps": ["oidc", "saml", "google_oidc", "github_oauth"],
        "compliance_apis": [],
    },
    "eu": {
        "display_name": "European Union",
        "data_residency": "eu",
        "cross_region_inference": False,
        "allowed_idps": ["oidc", "saml"],
        "compliance_apis": ["gdpr_export", "gdpr_delete"],
    },
    "us": {
        "display_name": "United States",
        "data_residency": "us",
        "cross_region_inference": True,
        "allowed_idps": ["oidc", "saml", "google_oidc", "github_oauth"],
        "compliance_apis": ["ccpa_delete"],
    },
}

_MANAGED_CONNECTOR_ALLOWED_PROVIDERS: dict[str, set[str]] = {
    "sso":             {"oidc", "saml", "google_oidc", "github_oauth", "azure_ad", "okta", "ping_identity", "auth0"},
    "compliance_apis": {"gdpr_export", "gdpr_delete", "ccpa_delete", "dsar", "audit_export", "soc2_report", "hipaa_export"},
    "scim":            {"okta_scim", "azure_ad_scim", "onelogin_scim", "google_scim"},
    "audit_log":       {"splunk", "datadog", "elastic", "siem_syslog"},
    "secrets":         {"aws_secrets_manager", "azure_key_vault", "hashicorp_vault", "gcp_secret_manager"},
    "storage":         {"aws_s3", "azure_blob", "gcs", "minio"},
    "ticketing":       {"jira", "linear", "github_issues", "servicenow"},
    "hr":              {"workday", "bamboohr", "rippling"},
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def role_level(role: str) -> int:
    return ROLE_HIERARCHY.get(role, 0)


def role_can(actor_role: str, required_role: str) -> bool:
    return role_level(actor_role) >= role_level(required_role)


@dataclass
class TeamPolicy:
    policy_id: str
    team_id: str
    name: str
    description: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    allowed_models: list[str] = field(default_factory=list)
    max_tokens_per_request: int = 0
    max_requests_per_day: int = 0
    require_hitl_for: list[str] = field(default_factory=list)
    data_classification: str = "internal"
    allowed_regions: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    created_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "team_id": self.team_id,
            "name": self.name,
            "description": self.description,
            "allowed_tools": list(self.allowed_tools),
            "denied_tools": list(self.denied_tools),
            "allowed_models": list(self.allowed_models),
            "max_tokens_per_request": self.max_tokens_per_request,
            "max_requests_per_day": self.max_requests_per_day,
            "require_hitl_for": list(self.require_hitl_for),
            "data_classification": self.data_classification,
            "allowed_regions": list(self.allowed_regions),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
        }


@dataclass
class ApprovalWorkflow:
    workflow_id: str
    action: str
    requestor: str
    context: dict[str, Any]
    tiers: list[str]
    current_tier: int = 0
    status: str = "pending"
    approvals: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    expires_at: str = ""
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "action": self.action,
            "requestor": self.requestor,
            "context": dict(self.context),
            "tiers": list(self.tiers),
            "current_tier": self.current_tier,
            "status": self.status,
            "approvals": list(self.approvals),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "rejection_reason": self.rejection_reason,
            "next_approver_role": self.tiers[self.current_tier] if self.current_tier < len(self.tiers) else None,
        }


_policies: dict[str, TeamPolicy] = {}
_violation_log: list[dict[str, Any]] = []
_policy_alerts: list[dict[str, Any]] = []
_approval_workflows: list[dict[str, Any]] = []
_workflows: dict[str, ApprovalWorkflow] = {}
_department_quotas: dict[str, dict[str, Any]] = {}
_department_usage: dict[str, dict[str, Any]] = {}
_compliance_config: dict[str, Any] = {
    "regions": copy.deepcopy(_DEFAULT_REGION_PROFILES),
    "default_region": os.getenv("DEPLOYMENT_REGION", "global"),
    "data_residency_enforced": False,
    "gdpr_mode": os.getenv("GDPR_MODE", "false").lower() == "true",
    "hipaa_mode": os.getenv("HIPAA_MODE", "false").lower() == "true",
    "soc2_mode": os.getenv("SOC2_MODE", "false").lower() == "true",
    "managed_connectors": {
        "sso": {
            "enabled": True,
            "providers": ["oidc", "saml", "google_oidc", "github_oauth"],
        },
        "compliance_apis": {
            "enabled": False,
            "providers": [],
        },
        "scim": {
            "enabled": False,
            "providers": [],
        },
        "audit_log": {
            "enabled": False,
            "providers": [],
        },
        "secrets": {
            "enabled": False,
            "providers": [],
        },
        "storage": {
            "enabled": False,
            "providers": [],
        },
        "ticketing": {
            "enabled": False,
            "providers": [],
        },
        "hr": {
            "enabled": False,
            "providers": [],
        },
    },
    "deployment_controls": {
        "enforce_region_pinning": False,
        "allowed_deployment_targets": ["self_hosted", "enterprise"],
        "blocked_cloud_regions": [],
    },
    "updated_at": _utc_now(),
}


def create_policy(team_id: str, name: str, **kwargs) -> TeamPolicy:
    pid = str(uuid.uuid4())[:12]
    policy = TeamPolicy(policy_id=pid, team_id=team_id, name=name, **kwargs)
    _policies[pid] = policy
    logger.info("Created team policy %s for team %s", pid, team_id)
    return policy


def get_policy(policy_id: str) -> TeamPolicy | None:
    return _policies.get(policy_id)


def list_policies(team_id: str | None = None) -> list[dict[str, Any]]:
    items = [p.to_dict() for p in _policies.values()]
    if team_id:
        items = [p for p in items if p["team_id"] == team_id]
    return items


def update_policy(policy_id: str, updates: dict[str, Any]) -> TeamPolicy | None:
    policy = _policies.get(policy_id)
    if not policy:
        return None
    allowed_fields = {
        "name", "description", "allowed_tools", "denied_tools",
        "allowed_models", "max_tokens_per_request", "max_requests_per_day",
        "require_hitl_for", "data_classification", "allowed_regions",
    }
    for key, value in updates.items():
        if key in allowed_fields:
            setattr(policy, key, value)
    policy.updated_at = _utc_now()
    return policy


def delete_policy(policy_id: str) -> bool:
    if policy_id not in _policies:
        return False
    del _policies[policy_id]
    return True


def _create_policy_alert(
    team_id: str,
    username: str,
    action: str,
    reason: str,
    policy_id: str,
    remediation: str,
    severity: str = "high",
    required_role: str | None = None,
    workflow_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    alert = {
        "id": str(uuid.uuid4())[:10],
        "created_at": _utc_now(),
        "team_id": team_id,
        "username": username,
        "action": action,
        "reason": reason,
        "severity": severity,
        "policy_id": policy_id,
        "workflow_id": workflow_id,
        "required_role": required_role,
        "remediation": remediation,
        "status": "open",
        "context": dict(context or {}),
        "delivery": {
            "channel": "in_app",
            "webhook_configured": bool(os.getenv("POLICY_ALERT_WEBHOOK_URL", "").strip()),
            "webhook_delivered": False,
        },
    }
    _policy_alerts.append(alert)
    if len(_policy_alerts) > 1000:
        del _policy_alerts[:-1000]
    return alert


def _log_violation(
    team_id: str,
    username: str,
    action: str,
    reason: str,
    policy_id: str,
    *,
    severity: str = "high",
    remediation: str = "",
    context: dict[str, Any] | None = None,
    required_role: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    alert = _create_policy_alert(
        team_id=team_id,
        username=username,
        action=action,
        reason=reason,
        policy_id=policy_id,
        remediation=remediation,
        severity=severity,
        required_role=required_role,
        workflow_id=workflow_id,
        context=context,
    )
    event = {
        "id": str(uuid.uuid4())[:8],
        "ts": _utc_now(),
        "team_id": team_id,
        "username": username,
        "action": action,
        "reason": reason,
        "severity": severity,
        "policy_id": policy_id,
        "workflow_id": workflow_id,
        "required_role": required_role,
        "remediation": remediation,
        "context": dict(context or {}),
        "alert": alert,
    }
    _violation_log.append(event)
    if len(_violation_log) > 1000:
        del _violation_log[:-1000]
    logger.warning("Policy violation: team=%s user=%s action=%s reason=%s", team_id, username, action, reason)
    return event


def list_violations(team_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    items = _violation_log
    if team_id:
        items = [entry for entry in items if entry["team_id"] == team_id]
    return list(reversed(items[-limit:]))


def list_policy_alerts(team_id: str | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    items = _policy_alerts
    if team_id:
        items = [entry for entry in items if entry["team_id"] == team_id]
    if status:
        items = [entry for entry in items if entry["status"] == status]
    return list(reversed(items[-limit:]))


def set_department_quota(department: str, daily_tokens: int = 0,
                         monthly_cost_usd: float = 0.0, max_users: int = 0) -> dict[str, Any]:
    _department_quotas[department] = {
        "department": department,
        "daily_tokens": daily_tokens,
        "monthly_cost_usd": monthly_cost_usd,
        "max_users": max_users,
        "updated_at": _utc_now(),
    }
    if department not in _department_usage:
        _department_usage[department] = {"tokens_today": 0, "cost_this_month": 0.0, "users": 0}
    return _department_quotas[department]


def get_department_quota(department: str) -> dict[str, Any] | None:
    quota = _department_quotas.get(department)
    usage = _department_usage.get(department, {})
    if quota is None:
        return None
    return {**quota, "usage": usage}


def list_department_quotas() -> list[dict[str, Any]]:
    return [{**quota, "usage": _department_usage.get(quota["department"], {})} for quota in _department_quotas.values()]


def record_department_usage(department: str, tokens: int, cost_usd: float = 0.0) -> dict[str, Any]:
    if department not in _department_usage:
        _department_usage[department] = {"tokens_today": 0, "cost_this_month": 0.0, "users": 0}
    usage = _department_usage[department]
    usage["tokens_today"] = usage.get("tokens_today", 0) + tokens
    usage["cost_this_month"] = usage.get("cost_this_month", 0.0) + cost_usd

    quota = _department_quotas.get(department)
    alerts = []
    if quota:
        if quota["daily_tokens"] > 0 and usage["tokens_today"] > quota["daily_tokens"]:
            alerts.append({"type": "daily_tokens_exceeded", "department": department, "used": usage["tokens_today"], "limit": quota["daily_tokens"]})
        if quota["monthly_cost_usd"] > 0 and usage["cost_this_month"] > quota["monthly_cost_usd"]:
            alerts.append({"type": "monthly_cost_exceeded", "department": department, "used": usage["cost_this_month"], "limit": quota["monthly_cost_usd"]})
    return {"usage": usage, "alerts": alerts}


def create_approval_workflow(action: str, requestor: str,
                             context: dict[str, Any] | None = None,
                             custom_tiers: list[str] | None = None) -> ApprovalWorkflow:
    workflow_id = str(uuid.uuid4())[:12]
    tiers = custom_tiers or HIGH_RISK_TIER_MAP.get(action, ["manager"])
    workflow = ApprovalWorkflow(
        workflow_id=workflow_id,
        action=action,
        requestor=requestor,
        context=context or {},
        tiers=tiers,
    )
    _workflows[workflow_id] = workflow
    _approval_workflows.append(workflow.to_dict())
    logger.info("Created approval workflow %s for action=%s requestor=%s tiers=%s", workflow_id, action, requestor, tiers)
    return workflow


def get_workflow(workflow_id: str) -> ApprovalWorkflow | None:
    return _workflows.get(workflow_id)


def advance_workflow(workflow_id: str, approver: str, approver_role: str,
                     decision: str, reason: str = "") -> dict[str, Any]:
    workflow = _workflows.get(workflow_id)
    if not workflow:
        return {"ok": False, "error": "workflow not found"}
    if workflow.status != "pending":
        return {"ok": False, "error": f"workflow is {workflow.status}"}

    required_role = workflow.tiers[workflow.current_tier] if workflow.current_tier < len(workflow.tiers) else None
    if required_role and not role_can(approver_role, required_role):
        return {"ok": False, "error": f"requires role >= {required_role}, got {approver_role}"}

    entry = {
        "tier": workflow.current_tier,
        "required_role": required_role,
        "approver": approver,
        "decision": decision,
        "reason": reason,
        "ts": _utc_now(),
    }
    workflow.approvals.append(entry)

    if decision == "reject":
        workflow.status = "rejected"
        workflow.rejection_reason = reason
    else:
        workflow.current_tier += 1
        if workflow.current_tier >= len(workflow.tiers):
            workflow.status = "approved"

    for alert in _policy_alerts:
        if alert.get("workflow_id") == workflow_id and alert.get("status") == "open":
            alert["status"] = "resolved" if workflow.status == "approved" else workflow.status
            alert["resolved_at"] = _utc_now()

    return {"ok": True, "workflow": workflow.to_dict()}


def list_workflows(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    items = list(_workflows.values())
    if status:
        items = [workflow for workflow in items if workflow.status == status]
    return [workflow.to_dict() for workflow in reversed(items[-limit:])]


def _workflow_matches_action(workflow: ApprovalWorkflow, tool_action: str, username: str) -> bool:
    return workflow.action == tool_action and (not username or workflow.requestor == username)


def _validate_region_profiles(regions: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for region_code, profile in regions.items():
        region = str(region_code or "").strip().lower()
        if not region:
            raise ValueError("region keys must be non-empty strings")
        profile_dict = dict(profile or {})
        normalized[region] = {
            "display_name": str(profile_dict.get("display_name") or region.upper()),
            "data_residency": str(profile_dict.get("data_residency") or region),
            "cross_region_inference": bool(profile_dict.get("cross_region_inference", region == "global")),
            "allowed_idps": [str(item).strip() for item in profile_dict.get("allowed_idps", []) if str(item).strip()],
            "compliance_apis": [str(item).strip() for item in profile_dict.get("compliance_apis", []) if str(item).strip()],
        }
    return normalized


def get_compliance_config() -> dict[str, Any]:
    return copy.deepcopy(_compliance_config)


def get_managed_connector_config(connector: str) -> dict[str, Any]:
    name = str(connector or "").strip().lower()
    if not name:
        raise ValueError("connector is required")
    current = dict(_compliance_config.get("managed_connectors", {}))
    cfg = dict(current.get(name, {}))
    return {
        "connector": name,
        "enabled": bool(cfg.get("enabled", False)),
        "providers": [str(item).strip() for item in cfg.get("providers", []) if str(item).strip()],
        "allowed_providers": sorted(_MANAGED_CONNECTOR_ALLOWED_PROVIDERS.get(name, set())),
        "updated_at": _compliance_config.get("updated_at"),
    }


def update_managed_connector_config(connector: str, enabled: bool | None = None,
                                    providers: list[str] | None = None) -> dict[str, Any]:
    name = str(connector or "").strip().lower()
    if not name:
        raise ValueError("connector is required")

    current = dict(_compliance_config.get("managed_connectors", {}))
    prev = dict(current.get(name, {}))

    provider_values = [str(item).strip() for item in list(providers or prev.get("providers", [])) if str(item).strip()]
    allowed = _MANAGED_CONNECTOR_ALLOWED_PROVIDERS.get(name)
    if allowed:
        invalid = sorted({provider for provider in provider_values if provider not in allowed})
        if invalid:
            raise ValueError(f"unsupported providers for {name}: {', '.join(invalid)}")

    current[name] = {
        "enabled": bool(prev.get("enabled", False) if enabled is None else enabled),
        "providers": provider_values,
    }
    _compliance_config["managed_connectors"] = current
    _compliance_config["updated_at"] = _utc_now()
    return get_managed_connector_config(name)


def test_managed_connector(connector: str, provider: str = "", region: str = "") -> dict[str, Any]:
    cfg = get_managed_connector_config(connector)
    selected_provider = str(provider or (cfg.get("providers") or [""])[0]).strip().lower()
    region_name = str(region or _compliance_config.get("default_region") or "global").strip().lower()
    regions = dict(_compliance_config.get("regions", {}))
    profile = dict(regions.get(region_name, regions.get("global", {})))
    allowed_region_providers = [str(item).strip().lower() for item in profile.get("allowed_idps", [])]
    allowed_compliance_apis = [str(item).strip().lower() for item in profile.get("compliance_apis", [])]

    if not cfg.get("enabled"):
        return {
            "ok": False,
            "connector": cfg["connector"],
            "reason": "connector_disabled",
            "region": region_name,
            "provider": selected_provider,
        }

    if selected_provider and selected_provider not in [p.lower() for p in cfg.get("providers", [])]:
        return {
            "ok": False,
            "connector": cfg["connector"],
            "reason": "provider_not_configured",
            "region": region_name,
            "provider": selected_provider,
            "configured_providers": cfg.get("providers", []),
        }

    if cfg["connector"] == "sso" and selected_provider and allowed_region_providers and selected_provider not in allowed_region_providers:
        return {
            "ok": False,
            "connector": cfg["connector"],
            "reason": "provider_blocked_by_region_profile",
            "region": region_name,
            "provider": selected_provider,
            "allowed_region_providers": allowed_region_providers,
        }

    if cfg["connector"] == "compliance_apis" and selected_provider and allowed_compliance_apis and selected_provider not in allowed_compliance_apis:
        return {
            "ok": False,
            "connector": cfg["connector"],
            "reason": "api_not_allowed_by_region_profile",
            "region": region_name,
            "provider": selected_provider,
            "allowed_region_apis": allowed_compliance_apis,
        }

    return {
        "ok": True,
        "connector": cfg["connector"],
        "region": region_name,
        "provider": selected_provider,
        "data_residency": profile.get("data_residency", "flexible"),
        "cross_region_inference": bool(profile.get("cross_region_inference", True)),
    }


def update_compliance_config(updates: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "regions",
        "default_region",
        "data_residency_enforced",
        "gdpr_mode",
        "hipaa_mode",
        "soc2_mode",
        "managed_connectors",
        "deployment_controls",
    }
    for key, value in updates.items():
        if key not in allowed:
            continue
        if key == "regions":
            if not isinstance(value, dict):
                raise ValueError("regions must be an object keyed by region code")
            _compliance_config["regions"] = _validate_region_profiles(value)
        elif key == "managed_connectors":
            if not isinstance(value, dict):
                raise ValueError("managed_connectors must be an object")
            current = dict(_compliance_config.get("managed_connectors", {}))
            for connector_name, connector_config in value.items():
                cfg = dict(connector_config or {})
                current[str(connector_name)] = {
                    "enabled": bool(cfg.get("enabled", current.get(str(connector_name), {}).get("enabled", False))),
                    "providers": [str(item).strip() for item in cfg.get("providers", current.get(str(connector_name), {}).get("providers", [])) if str(item).strip()],
                }
            _compliance_config["managed_connectors"] = current
        elif key in {"data_residency_enforced", "gdpr_mode", "hipaa_mode", "soc2_mode"}:
            _compliance_config[key] = bool(value)
        elif key == "deployment_controls":
            if not isinstance(value, dict):
                raise ValueError("deployment_controls must be an object")
            current = dict(_compliance_config.get("deployment_controls", {}))
            allowed_targets = [
                str(item).strip().lower()
                for item in value.get("allowed_deployment_targets", current.get("allowed_deployment_targets", []))
                if str(item).strip()
            ]
            blocked_regions = [
                str(item).strip().lower()
                for item in value.get("blocked_cloud_regions", current.get("blocked_cloud_regions", []))
                if str(item).strip()
            ]
            _compliance_config["deployment_controls"] = {
                "enforce_region_pinning": bool(value.get("enforce_region_pinning", current.get("enforce_region_pinning", False))),
                "allowed_deployment_targets": allowed_targets or ["self_hosted", "enterprise"],
                "blocked_cloud_regions": blocked_regions,
            }
        elif key == "default_region":
            _compliance_config[key] = str(value or "global").strip().lower() or "global"

    default_region = _compliance_config.get("default_region", "global")
    regions = _compliance_config.get("regions", {})
    if default_region not in regions:
        raise ValueError(f"default_region must exist in regions: {default_region}")

    if _compliance_config.get("data_residency_enforced"):
        for region_name, profile in regions.items():
            if region_name != "global" and str(profile.get("data_residency") or "").lower() == "flexible":
                raise ValueError("data residency enforced regions must declare a concrete data_residency value")

    _compliance_config["updated_at"] = _utc_now()
    return get_compliance_config()


def validate_deployment_compliance(
    region: str,
    deployment_target: str,
    cross_region_inference: bool | None = None,
    data_export_region: str = "",
) -> dict[str, Any]:
    region_name = str(region or _compliance_config.get("default_region") or "global").strip().lower()
    target_name = str(deployment_target or "self_hosted").strip().lower()
    export_region = str(data_export_region or "").strip().lower()

    regions = dict(_compliance_config.get("regions", {}))
    if region_name not in regions:
        return {
            "ok": False,
            "reason": "unknown_region",
            "region": region_name,
            "known_regions": sorted(regions.keys()),
        }

    profile = dict(regions.get(region_name, {}))
    deployment_controls = dict(_compliance_config.get("deployment_controls", {}))
    allowed_targets = [str(item).strip().lower() for item in deployment_controls.get("allowed_deployment_targets", [])]
    blocked_cloud_regions = [str(item).strip().lower() for item in deployment_controls.get("blocked_cloud_regions", [])]

    if allowed_targets and target_name not in allowed_targets:
        return {
            "ok": False,
            "reason": "deployment_target_not_allowed",
            "deployment_target": target_name,
            "allowed_deployment_targets": allowed_targets,
        }

    if target_name == "enterprise" and region_name in blocked_cloud_regions:
        return {
            "ok": False,
            "reason": "cloud_region_blocked",
            "region": region_name,
            "blocked_cloud_regions": blocked_cloud_regions,
        }

    effective_cross_region = bool(
        profile.get("cross_region_inference")
        if cross_region_inference is None
        else cross_region_inference
    )
    if _compliance_config.get("data_residency_enforced") and effective_cross_region:
        return {
            "ok": False,
            "reason": "cross_region_inference_blocked",
            "region": region_name,
            "data_residency_enforced": True,
        }

    if export_region and export_region != region_name and not bool(profile.get("cross_region_inference", False)):
        return {
            "ok": False,
            "reason": "cross_region_export_blocked",
            "region": region_name,
            "export_region": export_region,
        }

    return {
        "ok": True,
        "region": region_name,
        "deployment_target": target_name,
        "data_residency": str(profile.get("data_residency") or region_name),
        "cross_region_inference": effective_cross_region,
        "data_residency_enforced": bool(_compliance_config.get("data_residency_enforced", False)),
        "gdpr_mode": bool(_compliance_config.get("gdpr_mode", False)),
        "hipaa_mode": bool(_compliance_config.get("hipaa_mode", False)),
        "soc2_mode": bool(_compliance_config.get("soc2_mode", False)),
    }


def evaluate_policy(
    team_id: str,
    tool_action: str,
    model: str | None = None,
    region: str | None = None,
    username: str = "",
    role: str = "user",
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    team_policies = [policy for policy in _policies.values() if policy.team_id == team_id]
    if not team_policies:
        return {"allowed": True, "reason": "no_policy", "team_id": team_id}

    context = dict(context or {})
    effective_region = str(region or context.get("region") or _compliance_config.get("default_region") or "global").strip().lower()
    workflow_id = str(context.get("policy_workflow_id") or "").strip()
    workflow = _workflows.get(workflow_id) if workflow_id else None

    if workflow and workflow.status == "approved" and _workflow_matches_action(workflow, tool_action, username):
        return {
            "allowed": True,
            "reason": "policy_workflow_approved",
            "team_id": team_id,
            "workflow_id": workflow.workflow_id,
            "approved_by_policy": True,
        }

    for policy in team_policies:
        if tool_action in policy.denied_tools:
            reason = "tool_denied"
            remediation = _REMEDIATION_BY_REASON[reason]
            event = _log_violation(team_id, username, tool_action, reason, policy.policy_id, severity="high", remediation=remediation, context=context)
            return {"allowed": False, "reason": reason, "policy_id": policy.policy_id, "violation_id": event["id"], "remediation": remediation, "alert": event["alert"]}

        if policy.allowed_tools and tool_action not in policy.allowed_tools:
            reason = "tool_not_in_allowlist"
            remediation = _REMEDIATION_BY_REASON[reason]
            event = _log_violation(team_id, username, tool_action, reason, policy.policy_id, severity="medium", remediation=remediation, context=context)
            return {"allowed": False, "reason": reason, "policy_id": policy.policy_id, "violation_id": event["id"], "remediation": remediation, "alert": event["alert"]}

        if model and policy.allowed_models and model not in policy.allowed_models:
            reason = "model_not_allowed"
            remediation = _REMEDIATION_BY_REASON[reason]
            event = _log_violation(team_id, username, tool_action, reason, policy.policy_id, severity="medium", remediation=remediation, context={**context, "model": model})
            return {"allowed": False, "reason": reason, "policy_id": policy.policy_id, "violation_id": event["id"], "remediation": remediation, "alert": event["alert"]}

        if effective_region and policy.allowed_regions and effective_region not in {item.lower() for item in policy.allowed_regions}:
            reason = "region_not_allowed"
            remediation = _REMEDIATION_BY_REASON[reason]
            event = _log_violation(team_id, username, tool_action, reason, policy.policy_id, severity="high", remediation=remediation, context={**context, "region": effective_region})
            return {"allowed": False, "reason": reason, "policy_id": policy.policy_id, "violation_id": event["id"], "remediation": remediation, "alert": event["alert"]}

        if tool_action in policy.require_hitl_for:
            reason = "hitl_required"
            remediation = _REMEDIATION_BY_REASON[reason]
            approval_workflow = create_approval_workflow(
                action=tool_action,
                requestor=username or "system",
                context={**context, "team_id": team_id, "policy_id": policy.policy_id, "region": effective_region, "role": role},
                custom_tiers=HIGH_RISK_TIER_MAP.get(tool_action) or ["manager"],
            )
            event = _log_violation(
                team_id,
                username,
                tool_action,
                reason,
                policy.policy_id,
                severity="high",
                remediation=remediation,
                context=context,
                required_role=approval_workflow.to_dict().get("next_approver_role"),
                workflow_id=approval_workflow.workflow_id,
            )
            return {
                "allowed": False,
                "requires_hitl": True,
                "reason": reason,
                "policy_id": policy.policy_id,
                "workflow_id": approval_workflow.workflow_id,
                "next_approver_role": approval_workflow.to_dict().get("next_approver_role"),
                "violation_id": event["id"],
                "remediation": remediation,
                "alert": event["alert"],
            }

    return {"allowed": True, "reason": "policy_pass", "team_id": team_id, "region": effective_region}


def build_audit_export(entries: list[dict[str, Any]], fmt: str = "json") -> tuple[bytes, str]:
    if fmt == "csv":
        import csv
        import io

        buf = io.StringIO()
        if entries:
            writer = csv.DictWriter(buf, fieldnames=list(entries[0].keys()))
            writer.writeheader()
            writer.writerows(entries)
        return buf.getvalue().encode("utf-8"), "text/csv"
    return json.dumps(entries, indent=2).encode("utf-8"), "application/json"
