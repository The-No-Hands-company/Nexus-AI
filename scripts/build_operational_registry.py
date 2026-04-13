from __future__ import annotations

import csv
import json
from collections import OrderedDict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = ROOT / "docs" / "registry"
INPUT_V2_6 = REGISTRY_DIR / "feature_registry_v2_6.csv"


DOMAIN_CONFIG: dict[str, dict[str, Any]] = {
    "CORE": {
        "module_path": "src/agent.py;src/app.py",
        "endpoint": "/agent;/agent/stream",
        "ui_surface": "chat-shell;message-stream",
        "owner_team": "core-agent",
        "benchmark_prefix": "bench.core",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "ROUTER": {
        "module_path": "src/agent.py;src/model_router.py;src/ensemble.py",
        "endpoint": "/settings;/providers;/health",
        "ui_surface": "provider-drawer;settings-panel",
        "owner_team": "routing-platform",
        "benchmark_prefix": "bench.router",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "SAFETY": {
        "module_path": "src/safety.py;src/safety_pipeline.py;src/safety_middleware.py",
        "endpoint": "/safety/check;/safety/pii-scan;/approvals/*",
        "ui_surface": "safety-panel;approval-cards",
        "owner_team": "safety-runtime",
        "benchmark_prefix": "bench.safety",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "MEMORY": {
        "module_path": "src/memory.py;src/context_window.py;src/knowledge_graph.py",
        "endpoint": "/memory/*;/kg/*",
        "ui_surface": "memory-sidebar;knowledge-panel",
        "owner_team": "memory-systems",
        "benchmark_prefix": "bench.memory",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "TOOLS": {
        "module_path": "src/tools_builtin.py;src/agent.py",
        "endpoint": "/agent;/tasks/*",
        "ui_surface": "tool-cards;artifact-viewer",
        "owner_team": "tooling-runtime",
        "benchmark_prefix": "bench.tools",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "MULTIAGENT": {
        "module_path": "src/autonomy.py;src/agent_bus.py;src/agents",
        "endpoint": "/agents/*;/swarm/activity;/orchestrate/*",
        "ui_surface": "swarm-view;agents-console",
        "owner_team": "multiagent-runtime",
        "benchmark_prefix": "bench.multiagent",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "MULTIMODAL": {
        "module_path": "src/tools_builtin.py;src/rag/rag_system.py;static/index.html",
        "endpoint": "/v1/chat/completions;/agent/stream",
        "ui_surface": "attachments-panel;artifact-viewer",
        "owner_team": "multimodal-runtime",
        "benchmark_prefix": "bench.multimodal",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "UX": {
        "module_path": "static/index.html;src/app.py",
        "endpoint": "/;/static/*",
        "ui_surface": "chat-shell;sidebar;settings-panel",
        "owner_team": "ux-product",
        "benchmark_prefix": "bench.ux",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "API": {
        "module_path": "src/api/routes.py;src/api/schemas.py",
        "endpoint": "/v1/*;/settings;/health",
        "ui_surface": "api-clients;openai-compat-surface",
        "owner_team": "api-platform",
        "benchmark_prefix": "bench.api",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "AUTH": {
        "module_path": "src/api/routes.py;src/db.py",
        "endpoint": "/auth/*;/me",
        "ui_surface": "login-register;user-settings",
        "owner_team": "identity-access",
        "benchmark_prefix": "bench.auth",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "OBS": {
        "module_path": "src/api/routes.py;src/db.py",
        "endpoint": "/benchmark/*;/usage;/health",
        "ui_surface": "usage-dashboard;provider-status",
        "owner_team": "observability",
        "benchmark_prefix": "bench.obs",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "PERF": {
        "module_path": "src/agent.py;src/model_router.py;src/ensemble.py",
        "endpoint": "/benchmark/*;/providers;/settings/ensemble",
        "ui_surface": "benchmark-panel;provider-status",
        "owner_team": "performance-engineering",
        "benchmark_prefix": "bench.perf",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "DATA": {
        "module_path": "src/db.py;src/execution_trace.py;src/knowledge_graph.py",
        "endpoint": "/tasks/*;/kg/*;/memory/*",
        "ui_surface": "chat-history;projects-panel",
        "owner_team": "data-runtime",
        "benchmark_prefix": "bench.data",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "EVAL": {
        "module_path": "src/api/routes.py;src/db.py;tests/test_v1_contracts.py",
        "endpoint": "/benchmark/run;/benchmark/results",
        "ui_surface": "benchmark-panel;feedback-panel",
        "owner_team": "eval-quality",
        "benchmark_prefix": "bench.eval",
        "primary_test_module": "tests.test_v1_contracts",
    },
    "PLATFORM": {
        "module_path": "src/app.py;main.py;Dockerfile;railway.toml",
        "endpoint": "/health;/webhook/*",
        "ui_surface": "ops-admin;deploy-config",
        "owner_team": "platform-selfhost",
        "benchmark_prefix": "bench.platform",
        "primary_test_module": "tests.test_v1_contracts",
    },
}


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            item = dict(row)
            item["depends_on"] = [x for x in str(item.get("depends_on", "")).split(";") if x]
            item["dependency_graph"] = json.loads(str(item.get("dependency_graph", "{}")))
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def scale_counts(source_rows: list[dict[str, str]], target_total: int) -> OrderedDict[str, int]:
    counts: OrderedDict[str, int] = OrderedDict()
    for row in source_rows:
        counts[row["domain"]] = counts.get(row["domain"], 0) + 1
    total = sum(counts.values())
    raw = {key: counts[key] * target_total / total for key in counts}
    integers = {key: int(raw[key]) for key in raw}
    remaining = target_total - sum(integers.values())
    fractions = sorted(((raw[key] - integers[key], key) for key in raw), reverse=True)
    idx = 0
    while remaining > 0:
        integers[fractions[idx % len(fractions)][1]] += 1
        remaining -= 1
        idx += 1
    return OrderedDict((key, integers[key]) for key in counts)


def build_domain_order(source_rows: list[dict[str, str]]) -> OrderedDict[str, str]:
    mapping: OrderedDict[str, str] = OrderedDict()
    for row in source_rows:
        domain = row["domain"]
        if domain not in mapping:
            mapping[domain] = row["feature_class"]
    return mapping


def build_acceptance_stub(fid: str, title: str, domain: str, feature_class: str) -> str:
    domain_label = domain.lower().replace("_", " ")
    class_label = feature_class.lower().replace("_", " ")
    return (
        f"Given {fid} ({title}) is implemented for {domain_label} {class_label} behavior, "
        "when exercised via its linked runtime/API/UI path, then it meets expected output, error, "
        "policy, and regression coverage requirements."
    )


def build_rows(domain_classes: OrderedDict[str, str], counts: OrderedDict[str, int], source_rows: list[dict[str, str]], version: str) -> list[dict[str, Any]]:
    template_by_domain: dict[str, dict[str, str]] = {}
    for row in source_rows:
        template_by_domain.setdefault(row["domain"], row)

    out: list[dict[str, Any]] = []
    for domain, count in counts.items():
        cls = domain_classes[domain]
        cfg = DOMAIN_CONFIG[domain]
        template = template_by_domain[domain]
        for idx in range(1, count + 1):
            fid = f"NAI-{domain}-{cls}-{idx:05d}"
            depends_on = ""
            dep_graph = json.dumps({})
            if idx <= counts.get(domain, 0):
                if idx <= int(template["feature_id"].split("-")[-1]) or domain == template["domain"]:
                    pass
            if cls == "CONTRACT":
                deps = [f"NAI-{domain}-CONTRACT-{idx-1:05d}"] if idx > 1 else []
            else:
                deps = ["NAI-API-CONTRACT-00001"]
                if cls != "SECURITY":
                    deps.append("NAI-SAFETY-SECURITY-00001")
                if idx > 1:
                    deps.append(f"NAI-{domain}-{cls}-{idx-1:05d}")
                if cls == "UX" and domain != "API":
                    deps.append(f"NAI-{domain}-RUNTIME-00001")
            dedup: list[str] = []
            seen: set[str] = set()
            for dep in deps:
                if dep != fid and dep not in seen:
                    dedup.append(dep)
                    seen.add(dep)
            depends_on = ";".join(dedup)
            dep_graph = json.dumps(
                {
                    "strategy": "contract-first",
                    "requires": dedup,
                    "ready_when": ["all_dependencies_verified", "acceptance_criteria_tested"],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )

            row = {
                "feature_id": fid,
                "domain": domain,
                "feature_class": cls,
                "state": "specified",
                "priority": template.get("priority", "P2"),
                "title": template.get("title", "").rsplit(" ", 1)[0] + f" {idx:03d}",
                "source_doc": template.get("source_doc", "docs/ROADMAP_SCALE_SYSTEM.md"),
                "acceptance_criteria_ref": f"AC-{fid}",
                "acceptance_criteria_stub": build_acceptance_stub(
                    fid,
                    template.get("title", "").rsplit(" ", 1)[0] + f" {idx:03d}",
                    domain,
                    cls,
                ),
                "depends_on": depends_on,
                "dependency_graph": dep_graph,
                "slo_target_p95_ms": template.get("slo_target_p95_ms", ""),
                "slo_target_p99_ms": template.get("slo_target_p99_ms", ""),
                "compat_level": template.get("compat_level", ""),
                "safety_budget": template.get("safety_budget", ""),
                "coverage_min": template.get("coverage_min", ""),
                "reliability_error_budget": template.get("reliability_error_budget", ""),
                "availability_target": template.get("availability_target", ""),
                "module_path": cfg["module_path"],
                "endpoint": cfg["endpoint"],
                "ui_surface": cfg["ui_surface"],
                "test_id": f"{cfg['primary_test_module']}::{fid}",
                "benchmark_id": f"{cfg['benchmark_prefix']}::{fid}",
                "owner_team": cfg["owner_team"],
                "evidence_ref": f"planned:evidence::{fid}",
                "mapping_mode": "templated_operational_seed",
                "evidence_status": "planned",
                "owner": cfg["owner_team"],
                "notes": f"registry {version}: operational linkage + ownership + evidence seed",
            }
            out.append(row)
    return out


def build_rollup(rows: list[dict[str, Any]], version: str) -> dict[str, Any]:
    state_counts: dict[str, int] = {}
    mapping_mode_counts: dict[str, int] = {}
    evidence_status_counts: dict[str, int] = {}
    domain_summary: dict[str, dict[str, Any]] = {}
    linkage_fields = ["module_path", "endpoint", "ui_surface", "test_id", "benchmark_id", "owner_team", "evidence_ref"]
    for row in rows:
        state = str(row["state"])
        state_counts[state] = state_counts.get(state, 0) + 1
        mapping_mode = str(row.get("mapping_mode", "unknown"))
        evidence_status = str(row.get("evidence_status", "unknown"))
        mapping_mode_counts[mapping_mode] = mapping_mode_counts.get(mapping_mode, 0) + 1
        evidence_status_counts[evidence_status] = evidence_status_counts.get(evidence_status, 0) + 1
        domain = str(row["domain"])
        summary = domain_summary.setdefault(
            domain,
            {
                "count": 0,
                "state_counts": {},
                "mapping_mode_counts": {},
                "evidence_status_counts": {},
                "linkage_coverage": {field: 0 for field in linkage_fields},
                "owner_teams": set(),
            },
        )
        summary["count"] += 1
        summary["state_counts"][state] = summary["state_counts"].get(state, 0) + 1
        summary["mapping_mode_counts"][mapping_mode] = summary["mapping_mode_counts"].get(mapping_mode, 0) + 1
        summary["evidence_status_counts"][evidence_status] = summary["evidence_status_counts"].get(evidence_status, 0) + 1
        for field in linkage_fields:
            if str(row.get(field, "")).strip():
                summary["linkage_coverage"][field] += 1
        summary["owner_teams"].add(str(row.get("owner_team", "")))

    for summary in domain_summary.values():
        summary["owner_teams"] = sorted(x for x in summary["owner_teams"] if x)
        total = max(summary["count"], 1)
        summary["linkage_coverage_pct"] = {
            field: round((count / total) * 100, 2) for field, count in summary["linkage_coverage"].items()
        }

    return {
        "version": version,
        "total_features": len(rows),
        "state_counts": state_counts,
        "mapping_mode_counts": mapping_mode_counts,
        "evidence_status_counts": evidence_status_counts,
        "domain_summary": domain_summary,
    }


def write_rollup_and_dashboard(version: str, rollup: dict[str, Any]) -> tuple[Path, Path]:
    rollup_path = REGISTRY_DIR / f"feature_registry_{version}_rollup.json"
    dashboard_path = REGISTRY_DIR / f"feature_registry_{version}_dashboard.md"
    rollup_path.write_text(json.dumps(rollup, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Feature Registry {version} Dashboard",
        "",
        f"Total features: {rollup['total_features']}",
        "",
        "## State Rollup",
        "",
    ]
    for state, count in sorted(rollup["state_counts"].items()):
        lines.append(f"- {state}: {count}")
    lines.extend(["", "## Mapping Status", ""])
    for mapping_mode, count in sorted(rollup["mapping_mode_counts"].items()):
        lines.append(f"- {mapping_mode}: {count}")
    lines.extend(["", "## Evidence Status", ""])
    for evidence_status, count in sorted(rollup["evidence_status_counts"].items()):
        lines.append(f"- {evidence_status}: {count}")
    lines.extend(["", "## Domain Rollup", "", "| Domain | Count | State Summary | Mapping Summary | Evidence Summary | Linkage Coverage | Owner Teams |", "|---|---:|---|---|---|---|---|"])
    for domain, summary in rollup["domain_summary"].items():
        state_summary = ", ".join(f"{k}={v}" for k, v in sorted(summary["state_counts"].items()))
        mapping_summary = ", ".join(f"{k}={v}" for k, v in sorted(summary["mapping_mode_counts"].items()))
        evidence_summary = ", ".join(f"{k}={v}" for k, v in sorted(summary["evidence_status_counts"].items()))
        coverage = ", ".join(f"{k}={v}%" for k, v in summary["linkage_coverage_pct"].items())
        owners = ", ".join(summary["owner_teams"])
        lines.append(f"| {domain} | {summary['count']} | {state_summary} | {mapping_summary} | {evidence_summary} | {coverage} | {owners} |")
    dashboard_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rollup_path, dashboard_path


def write_meta(version: str, rows: list[dict[str, Any]], target_total: int, source_registry: str) -> Path:
    meta_path = REGISTRY_DIR / f"feature_registry_{version}.meta.json"
    meta = {
        "version": version,
        "generated_at": "2026-04-13",
        "total_features": len(rows),
        "target_total": target_total,
        "source_registry": source_registry,
        "operational_columns": [
            "module_path",
            "endpoint",
            "ui_surface",
            "test_id",
            "benchmark_id",
            "owner_team",
            "evidence_ref",
            "mapping_mode",
            "evidence_status",
        ],
        "state_model": "specified baseline with operational linkage seeds",
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta_path


def main() -> None:
    source_rows = load_rows(INPUT_V2_6)
    domain_classes = build_domain_order(source_rows)

    versions = [
        ("v3", OrderedDict((k, sum(1 for r in source_rows if r["domain"] == k)) for k in domain_classes), 20000, str(INPUT_V2_6)),
        ("v3_1", scale_counts(source_rows, 50000), 50000, str(INPUT_V2_6)),
    ]

    for version, counts, total, source_registry in versions:
        rows = build_rows(domain_classes, counts, source_rows, version)
        fieldnames = list(rows[0].keys())
        csv_path = REGISTRY_DIR / f"feature_registry_{version}.csv"
        jsonl_path = REGISTRY_DIR / f"feature_registry_{version}.jsonl"
        write_csv(csv_path, rows, fieldnames)
        write_jsonl(jsonl_path, rows)
        rollup = build_rollup(rows, version)
        rollup_path, dashboard_path = write_rollup_and_dashboard(version, rollup)
        meta_path = write_meta(version, rows, total, source_registry)
        print(json.dumps({
            "version": version,
            "csv": str(csv_path.relative_to(ROOT)),
            "jsonl": str(jsonl_path.relative_to(ROOT)),
            "rollup": str(rollup_path.relative_to(ROOT)),
            "dashboard": str(dashboard_path.relative_to(ROOT)),
            "meta": str(meta_path.relative_to(ROOT)),
            "total_features": len(rows),
        }))


if __name__ == "__main__":
    main()