import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import save_validation_baselines
from src.validation_program import get_validation_overview, run_validation_program


async def _browser_cases_good():
    return [
        {"case_id": "browser-a", "passed": True, "latency_ms": 10.0, "recovery_expected": True, "recovered": True},
        {"case_id": "browser-b", "passed": True, "latency_ms": 12.0},
    ]


async def _browser_cases_bad():
    return [
        {"case_id": "browser-a", "passed": False, "latency_ms": 50.0, "recovery_expected": True, "recovered": False},
        {"case_id": "browser-b", "passed": False, "latency_ms": 60.0},
    ]


def _simple_cases(domain: str):
    return [
        {"case_id": f"{domain}-a", "passed": True, "latency_ms": 5.0},
        {"case_id": f"{domain}-b", "passed": True, "latency_ms": 7.0},
    ]


def test_validation_program_persists_reports_and_baselines(monkeypatch):
    monkeypatch.setattr("src.validation_program._run_browser_cases", _browser_cases_good)
    monkeypatch.setattr("src.validation_program._run_multimodal_cases", lambda: _simple_cases("multimodal"))
    monkeypatch.setattr("src.validation_program._run_multi_agent_cases", lambda: _simple_cases("multi_agent"))
    monkeypatch.setattr("src.validation_program.alert_slo_breach", lambda *args, **kwargs: {"sent": False})
    monkeypatch.setattr("src.validation_program.alert_error_rate", lambda *args, **kwargs: {"sent": False})

    report = run_validation_program(update_baseline=True, alert_on_regression=True)
    assert report["program"] == "core_quality"
    assert report["summary"]["success_rate"] == 1.0
    assert report["baselines"]["browser"]["success_rate"] == 1.0

    overview = get_validation_overview(limit=5)
    assert overview["count"] >= 1
    assert overview["reports"][0]["program"] == "core_quality"


def test_validation_program_alerts_on_regression(monkeypatch):
    save_validation_baselines(
        {
            "browser": {
                "success_rate": 1.0,
                "tool_error_rate": 0.0,
                "recovery_rate": 1.0,
                "latency_p95": 10.0,
            }
        }
    )
    monkeypatch.setattr("src.validation_program._run_browser_cases", _browser_cases_bad)
    monkeypatch.setattr("src.validation_program._run_multimodal_cases", lambda: _simple_cases("multimodal"))
    monkeypatch.setattr("src.validation_program._run_multi_agent_cases", lambda: _simple_cases("multi_agent"))

    alerts = []
    monkeypatch.setattr("src.validation_program.alert_slo_breach", lambda *args, **kwargs: alerts.append(("slo", args, kwargs)) or {"sent": True})
    monkeypatch.setattr("src.validation_program.alert_error_rate", lambda *args, **kwargs: alerts.append(("error_rate", args, kwargs)) or {"sent": True})

    report = run_validation_program(domains=["browser"], update_baseline=False, alert_on_regression=True)
    assert report["has_regression"] is True
    assert len(alerts) == 2