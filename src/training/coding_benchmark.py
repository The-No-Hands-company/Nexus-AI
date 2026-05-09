from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class BenchmarkCase:
    case_id: str
    language: str
    prompt: str
    test_code: str


DEFAULT_CASES: list[BenchmarkCase] = [
    BenchmarkCase(
        case_id="py_fib",
        language="python",
        prompt="Write function fib(n) that returns nth Fibonacci number (fib(0)=0, fib(1)=1).",
        test_code=(
            "from candidate import fib\n"
            "assert fib(0) == 0\n"
            "assert fib(1) == 1\n"
            "assert fib(10) == 55\n"
        ),
    ),
    BenchmarkCase(
        case_id="py_palindrome",
        language="python",
        prompt="Write function is_palindrome(s) that ignores case and non-alnum chars.",
        test_code=(
            "from candidate import is_palindrome\n"
            "assert is_palindrome('A man, a plan, a canal: Panama') is True\n"
            "assert is_palindrome('race a car') is False\n"
        ),
    ),
]


def _run_python_case(candidate_code: str, case: BenchmarkCase, timeout_sec: int = 8) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="apex_code_bench_") as tmp:
        work = Path(tmp)
        (work / "candidate.py").write_text(candidate_code, encoding="utf-8")
        (work / "test_case.py").write_text(case.test_code, encoding="utf-8")
        proc = subprocess.run(
            ["python3", "test_case.py"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:],
            "returncode": proc.returncode,
        }


def run_coding_benchmark(
    generator,
    suites: list[str] | None = None,
    n_samples: int = 10,
) -> dict[str, Any]:
    suites = suites or ["python_unit"]
    active_cases = DEFAULT_CASES if "python_unit" in suites else []
    if n_samples > 0:
        active_cases = active_cases[: max(1, min(len(active_cases), n_samples))]

    results: list[dict[str, Any]] = []
    passed = 0
    for case in active_cases:
        candidate = str(generator(case.prompt) or "")
        run = _run_python_case(candidate, case)
        passed += 1 if run["ok"] else 0
        results.append(
            {
                "case_id": case.case_id,
                "language": case.language,
                "ok": bool(run["ok"]),
                "stderr": run["stderr"],
            }
        )

    total = len(results)
    score = (passed / total) if total else 0.0
    return {
        "suite": "coding_benchmark",
        "suites": suites,
        "n_cases": total,
        "pass_count": passed,
        "pass_rate": round(score, 4),
        "results": results,
    }


def save_benchmark_report(report: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
