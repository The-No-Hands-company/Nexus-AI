"""Validation program runners for browser, multimodal, and multi-agent quality."""

from __future__ import annotations

import asyncio
import statistics
import time
from datetime import datetime, timezone
from typing import Any

from .alerting import alert_error_rate, alert_slo_breach
from .db import (
    list_validation_reports,
    load_validation_baselines,
    save_validation_baselines,
    save_validation_report,
)

_DEFAULT_DOMAINS = ("browser", "multimodal", "multi_agent")
_VALIDATION_TASK = "__internal_validation_program__"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _p95(latencies: list[float]) -> float:
    if not latencies:
        return 0.0
    ordered = sorted(float(v) for v in latencies)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    return round(statistics.quantiles(ordered, n=100, method="inclusive")[94], 3)


def _finalize_domain(domain: str, cases: list[dict[str, Any]], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    attempted = [case for case in cases if not case.get("skipped")]
    passed = [case for case in attempted if case.get("passed")]
    failed = [case for case in attempted if not case.get("passed")]
    recovery_cases = [case for case in attempted if case.get("recovery_expected")]
    recovered = [case for case in recovery_cases if case.get("recovered")]
    latencies = [float(case.get("latency_ms") or 0.0) for case in attempted]

    attempted_count = len(attempted)
    success_rate = round(len(passed) / max(1, attempted_count), 4)
    tool_error_rate = round(len(failed) / max(1, attempted_count), 4)
    recovery_rate = round(len(recovered) / max(1, len(recovery_cases)), 4) if recovery_cases else 1.0
    latency_p95 = _p95(latencies)

    regression_flags: list[str] = []
    baseline = baseline or {}
    if baseline:
        if success_rate + 0.05 < float(baseline.get("success_rate") or 0.0):
            regression_flags.append("success_rate")
        if tool_error_rate - 0.05 > float(baseline.get("tool_error_rate") or 0.0):
            regression_flags.append("tool_error_rate")
        baseline_latency = float(baseline.get("latency_p95") or 0.0)
        if baseline_latency > 0 and latency_p95 > baseline_latency * 1.5:
            regression_flags.append("latency_p95")

    return {
        "domain": domain,
        "created_at": _now_iso(),
        "cases": cases,
        "summary": {
            "attempted": attempted_count,
            "passed": len(passed),
            "failed": len(failed),
            "skipped": len(cases) - attempted_count,
            "success_rate": success_rate,
            "tool_error_rate": tool_error_rate,
            "recovery_rate": recovery_rate,
            "latency_p95": latency_p95,
        },
        "baseline": baseline,
        "regression_flags": regression_flags,
        "has_regression": bool(regression_flags),
    }


async def _run_browser_cases() -> list[dict[str, Any]]:
    from .browser_agent import confirm_pending_step, create_session, execute_step

    cases: list[dict[str, Any]] = []

    t0 = time.perf_counter()
    session = create_session("https://validation.local", hitl_checkpoints=["click"])
    pending = await execute_step(session.session_id, "click", {"selector": "#danger"})
    latency = (time.perf_counter() - t0) * 1000
    cases.append(
        {
            "case_id": "browser_hitl_pause",
            "passed": bool(pending.get("pending_confirmation")),
            "latency_ms": round(latency, 3),
            "details": pending,
            "recovery_expected": True,
            "recovered": False,
        }
    )

    t0 = time.perf_counter()
    rejected = await confirm_pending_step(session.session_id, approve=False, actor="validation")
    latency = (time.perf_counter() - t0) * 1000
    cases.append(
        {
            "case_id": "browser_hitl_reject_recovery",
            "passed": bool(rejected.get("ok")),
            "latency_ms": round(latency, 3),
            "details": rejected,
            "recovery_expected": True,
            "recovered": bool(rejected.get("ok")),
        }
    )

    t0 = time.perf_counter()
    planner_session = create_session("https://validation.local")
    plan = await execute_step(
        planner_session.session_id,
        "queue_form_fill",
        {"fields": {"email": "qa@example.com", "name": "Nexus QA"}, "submit_selector": "button[type=submit]"},
    )
    latency = (time.perf_counter() - t0) * 1000
    cases.append(
        {
            "case_id": "browser_form_plan_generation",
            "passed": bool(plan.get("result", {}).get("ok")),
            "latency_ms": round(latency, 3),
            "details": plan,
        }
    )
    return cases


def _run_multimodal_cases() -> list[dict[str, Any]]:
    import io

    from .vision import diff_documents, understand_office_doc, understand_pdf

    cases: list[dict[str, Any]] = []

    t0 = time.perf_counter()
    diff = diff_documents("Quarterly revenue was 10.", "Quarterly revenue was 12.")
    latency = (time.perf_counter() - t0) * 1000
    cases.append(
        {
            "case_id": "multimodal_document_diff",
            "passed": bool(diff.get("ok")) and bool(diff.get("changed")) and float(diff.get("similarity") or 0.0) < 1.0,
            "latency_ms": round(latency, 3),
            "details": diff,
        }
    )

    try:
        import openpyxl  # type: ignore

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Metrics"
        sheet.append(["metric", "value"])
        sheet.append(["success_rate", "0.95"])
        payload = io.BytesIO()
        workbook.save(payload)
        t0 = time.perf_counter()
        office = understand_office_doc(payload.getvalue(), "validation.xlsx")
        latency = (time.perf_counter() - t0) * 1000
        first_sheet = (office.get("sheets") or [{}])[0]
        cases.append(
            {
                "case_id": "multimodal_xlsx_understanding",
                "passed": bool(office.get("ok")) and str(first_sheet.get("name") or "") == "Metrics",
                "latency_ms": round(latency, 3),
                "details": office,
            }
        )
    except Exception as exc:
        cases.append({
            "case_id": "multimodal_xlsx_understanding",
            "passed": False,
            "skipped": True,
            "latency_ms": 0.0,
            "details": {"reason": str(exc)},
        })

    try:
        import fitz  # type: ignore

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Nexus validation PDF")
        pdf_bytes = doc.tobytes()
        doc.close()
        t0 = time.perf_counter()
        pdf_result = understand_pdf(pdf_bytes)
        latency = (time.perf_counter() - t0) * 1000
        cases.append(
            {
                "case_id": "multimodal_pdf_understanding",
                "passed": bool(pdf_result.get("ok")) and "Nexus validation PDF" in str(pdf_result.get("full_text") or ""),
                "latency_ms": round(latency, 3),
                "details": pdf_result,
            }
        )
    except Exception as exc:
        cases.append({
            "case_id": "multimodal_pdf_understanding",
            "passed": False,
            "skipped": True,
            "latency_ms": 0.0,
            "details": {"reason": str(exc)},
        })

    return cases


def _run_multi_agent_cases() -> list[dict[str, Any]]:
    from .agent_bus import get_dlq, post_message, read_messages, send_to_dlq
    from .collab import broadcast_to_room, create_room, get_room_events, join_room, leave_room

    cases: list[dict[str, Any]] = []

    t0 = time.perf_counter()
    outbound = post_message("planner", "worker-validation", "validate rollout", topic="validation")
    inbound = read_messages("worker-validation", limit=5, unread_only=False, mark_read=True, topic="validation")
    latency = (time.perf_counter() - t0) * 1000
    cases.append(
        {
            "case_id": "multi_agent_bus_roundtrip",
            "passed": bool(inbound) and str(inbound[-1].content) == "validate rollout",
            "latency_ms": round(latency, 3),
            "details": {"message_id": outbound.msg_id, "received": [m.to_dict() for m in inbound]},
        }
    )

    t0 = time.perf_counter()
    dlq_entry = send_to_dlq(outbound, "validation_probe")
    dlq_rows = get_dlq(limit=10)
    latency = (time.perf_counter() - t0) * 1000
    cases.append(
        {
            "case_id": "multi_agent_dlq_capture",
            "passed": any(str(entry.msg.msg_id) == str(dlq_entry.msg.msg_id) for entry in dlq_rows),
            "latency_ms": round(latency, 3),
            "details": {"dlq_size": len(dlq_rows)},
        }
    )

    t0 = time.perf_counter()
    room = create_room(owner="alice", name="Validation Room")
    join_room(room.room_id, "bob")
    broadcast_to_room(room.room_id, {"type": "validation_sync", "payload": "ok"})
    leave_room(room.room_id, "bob")
    events = get_room_events(room.room_id, limit=20)
    latency = (time.perf_counter() - t0) * 1000
    cases.append(
        {
            "case_id": "multi_agent_collab_flow",
            "passed": any(str(event.get("type") or "") == "validation_sync" for event in events),
            "latency_ms": round(latency, 3),
            "details": {"room_id": room.room_id, "event_count": len(events)},
        }
    )

    return cases


def run_validation_program(
    domains: list[str] | None = None,
    update_baseline: bool = False,
    alert_on_regression: bool = True,
) -> dict[str, Any]:
    selected_domains = [str(domain).strip().lower() for domain in (domains or list(_DEFAULT_DOMAINS)) if str(domain).strip()]
    if not selected_domains:
        raise ValueError("at least one validation domain is required")

    baselines = load_validation_baselines()
    domain_reports: list[dict[str, Any]] = []
    for domain in selected_domains:
        if domain == "browser":
            cases = asyncio.run(_run_browser_cases())
        elif domain == "multimodal":
            cases = _run_multimodal_cases()
        elif domain in {"multi_agent", "multi-agent"}:
            domain = "multi_agent"
            cases = _run_multi_agent_cases()
        else:
            raise ValueError(f"unsupported validation domain: {domain}")

        report = _finalize_domain(domain, cases, baseline=baselines.get(domain) if isinstance(baselines, dict) else None)
        domain_reports.append(report)

    overall_attempted = sum(int(report["summary"].get("attempted") or 0) for report in domain_reports)
    overall_passed = sum(int(report["summary"].get("passed") or 0) for report in domain_reports)
    overall_failed = sum(int(report["summary"].get("failed") or 0) for report in domain_reports)
    overall_success_rate = round(overall_passed / max(1, overall_attempted), 4)
    overall_tool_error_rate = round(overall_failed / max(1, overall_attempted), 4)
    overall_recovery_rate = round(
        sum(float(report["summary"].get("recovery_rate") or 0.0) for report in domain_reports) / max(1, len(domain_reports)),
        4,
    )
    overall_latency_p95 = round(
        sum(float(report["summary"].get("latency_p95") or 0.0) for report in domain_reports) / max(1, len(domain_reports)),
        3,
    )

    payload = save_validation_report(
        {
            "program": "core_quality",
            "domains": selected_domains,
            "domain_reports": domain_reports,
            "summary": {
                "attempted": overall_attempted,
                "passed": overall_passed,
                "failed": overall_failed,
                "success_rate": overall_success_rate,
                "tool_error_rate": overall_tool_error_rate,
                "recovery_rate": overall_recovery_rate,
                "latency_p95": overall_latency_p95,
            },
            "has_regression": any(report.get("has_regression") for report in domain_reports),
        }
    )

    if update_baseline:
        baseline_payload = dict(baselines if isinstance(baselines, dict) else {})
        for report in domain_reports:
            baseline_payload[report["domain"]] = dict(report["summary"])
        save_validation_baselines(baseline_payload)
        payload["baselines"] = baseline_payload
    else:
        payload["baselines"] = baselines

    if alert_on_regression:
        for report in domain_reports:
            if not report.get("has_regression"):
                continue
            summary = report.get("summary") or {}
            alert_slo_breach(
                slo_name=f"validation-{report['domain']}",
                metric="success_rate",
                current=float(summary.get("success_rate") or 0.0),
                threshold=float((report.get("baseline") or {}).get("success_rate") or 0.9),
                severity="warning",
            )
            alert_error_rate(
                service=f"validation-{report['domain']}",
                error_rate=float(summary.get("tool_error_rate") or 0.0),
                threshold=0.1,
            )
    return payload


def get_validation_overview(program: str = "core_quality", limit: int = 20) -> dict[str, Any]:
    reports = list_validation_reports(program=program, limit=limit)
    return {
        "program": program,
        "reports": reports,
        "count": len(reports),
        "baselines": load_validation_baselines(),
    }


def register_validation_program_schedules(run_fn: Any) -> None:
    try:
        import src.scheduler as _sched  # type: ignore[import]
    except ImportError:
        try:
            from . import scheduler as _sched  # type: ignore[assignment]
        except ImportError:
            return

    _sched.set_run_function(run_fn)
    existing_names = {job.name for job in _sched.list_jobs()}
    if "Weekly validation program" not in existing_names:
        _sched.schedule_job(
            name="Weekly validation program",
            task=_VALIDATION_TASK,
            schedule="168h",
        )