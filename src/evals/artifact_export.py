"""src/evals/artifact_export.py — Exportable benchmark artifact generation.

Produces publication-ready benchmark artifacts:
  - JSONL (one record per sample, streaming-friendly)
  - CSV   (spreadsheet-compatible, suitable for Kaggle/Papers With Code upload)
  - HTML  (self-contained report with inline charts via ASCII sparklines)
  - Leaderboard JSON (Papers With Code / OpenLLM-compatible format)
  - Signed manifest (SHA-256 checksums for reproducibility attestation)

All exports include full reproducibility metadata: dataset name, version,
content hash, model, provider, timestamp, and Nexus AI version.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime, timezone
from typing import Any


_NEXUS_VERSION = os.getenv("NEXUS_VERSION", "1.0.0")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(content: bytes | str) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sparkline(values: list[float], width: int = 20) -> str:
    """ASCII sparkline for a sequence of 0–1 values."""
    blocks = " ▁▂▃▄▅▆▇█"
    if not values:
        return "─" * width
    step = max(len(values) // width, 1)
    buckets = [values[i * step:(i + 1) * step] for i in range(width)]
    chars = []
    for bucket in buckets:
        if not bucket:
            chars.append(" ")
        else:
            avg = sum(bucket) / len(bucket)
            idx = min(int(avg * 8), 8)
            chars.append(blocks[idx])
    return "".join(chars)


# ── JSONL export ──────────────────────────────────────────────────────────────

def export_jsonl(run_data: dict[str, Any]) -> str:
    """Return JSONL string — one JSON object per sample result."""
    lines: list[str] = []
    meta = {k: v for k, v in run_data.items() if k != "sample_results"}
    for sample in run_data.get("sample_results", []):
        record = {**meta, "sample": sample}
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines)


def export_suite_jsonl(suite_data: dict[str, Any], full_results: list[dict[str, Any]]) -> str:
    """Export a full suite (multiple datasets) as JSONL."""
    lines: list[str] = []
    suite_meta = {k: v for k, v in suite_data.items() if k != "results"}
    for run in full_results:
        meta = {**suite_meta, "dataset_summary": {k: v for k, v in run.items() if k != "sample_results"}}
        for sample in run.get("sample_results", []):
            record = {**meta, "sample": sample}
            lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines)


# ── CSV export ────────────────────────────────────────────────────────────────

def export_csv(run_data: dict[str, Any]) -> str:
    """Return CSV string suitable for spreadsheet analysis."""
    buf = io.StringIO()
    fieldnames = [
        "run_id", "dataset", "dataset_version", "split", "model", "provider",
        "created_at", "sample_id", "score", "passed", "latency_ms",
        "prompt_preview", "response_preview", "error",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()

    meta = {k: v for k, v in run_data.items() if k not in ("sample_results",)}
    for sample in run_data.get("sample_results", []):
        row = {
            "run_id": meta.get("run_id", ""),
            "dataset": meta.get("dataset", ""),
            "dataset_version": meta.get("dataset_version", ""),
            "split": meta.get("split", ""),
            "model": meta.get("model", ""),
            "provider": meta.get("provider", ""),
            "created_at": meta.get("created_at", ""),
            "sample_id": sample.get("sample_id", ""),
            "score": sample.get("score", ""),
            "passed": sample.get("passed", ""),
            "latency_ms": sample.get("latency_ms", ""),
            "prompt_preview": str(sample.get("prompt", ""))[:120].replace("\n", " "),
            "response_preview": str(sample.get("response", ""))[:120].replace("\n", " "),
            "error": sample.get("error", ""),
        }
        writer.writerow(row)

    return buf.getvalue()


def export_suite_csv(full_results: list[dict[str, Any]]) -> str:
    """Export all runs from a suite as a single CSV."""
    all_rows = []
    for run in full_results:
        meta = {k: v for k, v in run.items() if k != "sample_results"}
        for sample in run.get("sample_results", []):
            all_rows.append({**meta, **sample})

    if not all_rows:
        return ""

    buf = io.StringIO()
    fieldnames = sorted({k for row in all_rows for k in row.keys()})
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(all_rows)
    return buf.getvalue()


# ── HTML report ───────────────────────────────────────────────────────────────

def export_html_report(run_data: dict[str, Any] | None = None, suite_data: dict[str, Any] | None = None, full_results: list[dict[str, Any]] | None = None) -> str:
    """Generate a self-contained HTML benchmark report with inline CSS."""
    now = _now_iso()
    datasets_section = ""

    if suite_data and full_results:
        title = f"Nexus AI Benchmark Suite — {suite_data.get('model', 'unknown')} @ {suite_data.get('provider', 'unknown')}"
        summary_html = f"""
        <div class="summary">
          <div class="metric"><span class="label">Suite ID</span><span class="value">{suite_data.get('suite_id', '')}</span></div>
          <div class="metric"><span class="label">Provider</span><span class="value">{suite_data.get('provider', '')}</span></div>
          <div class="metric"><span class="label">Model</span><span class="value">{suite_data.get('model', '')}</span></div>
          <div class="metric"><span class="label">Overall Accuracy</span><span class="value accent">{suite_data.get('overall_accuracy', 0):.1%}</span></div>
          <div class="metric"><span class="label">Datasets Run</span><span class="value">{len(suite_data.get('datasets_run', []))}</span></div>
          <div class="metric"><span class="label">Generated</span><span class="value">{now}</span></div>
        </div>"""
        for run in full_results:
            scores = [s.get("score", 0) for s in run.get("sample_results", [])]
            spark = _sparkline(scores)
            datasets_section += f"""
            <div class="dataset-block">
              <h3>{run.get('dataset', '')} <small>({run.get('dataset_version', '')})</small></h3>
              <div class="metrics-row">
                <span>Accuracy: <strong>{run.get('accuracy', 0):.1%}</strong></span>
                <span>Samples: <strong>{run.get('num_samples', 0)}</strong></span>
                <span>Avg Latency: <strong>{run.get('avg_latency_ms', 0):.0f}ms</strong></span>
                <span>P95: <strong>{run.get('p95_latency_ms', 0):.0f}ms</strong></span>
              </div>
              <pre class="spark">{spark}</pre>
              <p class="hash">Content hash: {run.get('dataset_hash', '')}</p>
            </div>"""
    elif run_data:
        scores = [s.get("score", 0) for s in run_data.get("sample_results", [])]
        spark = _sparkline(scores)
        title = f"Nexus AI Benchmark — {run_data.get('dataset', 'unknown')}"
        summary_html = f"""
        <div class="summary">
          <div class="metric"><span class="label">Run ID</span><span class="value">{run_data.get('run_id', '')}</span></div>
          <div class="metric"><span class="label">Dataset</span><span class="value">{run_data.get('dataset', '')}</span></div>
          <div class="metric"><span class="label">Version</span><span class="value">{run_data.get('dataset_version', '')}</span></div>
          <div class="metric"><span class="label">Model</span><span class="value">{run_data.get('model', '')}</span></div>
          <div class="metric"><span class="label">Accuracy</span><span class="value accent">{run_data.get('accuracy', 0):.1%}</span></div>
          <div class="metric"><span class="label">Avg Latency</span><span class="value">{run_data.get('avg_latency_ms', 0):.0f}ms</span></div>
          <div class="metric"><span class="label">P95 Latency</span><span class="value">{run_data.get('p95_latency_ms', 0):.0f}ms</span></div>
          <div class="metric"><span class="label">Content Hash</span><span class="value">{run_data.get('dataset_hash', '')}</span></div>
        </div>
        <pre class="spark">{spark}</pre>"""
        datasets_section = _html_samples_table(run_data.get("sample_results", []))
    else:
        title = "Nexus AI Benchmark Report"
        summary_html = "<p>No data.</p>"

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; background: #0f1117; color: #e0e0e0; }
    .container { max-width: 1100px; margin: 0 auto; padding: 24px; }
    h1 { color: #7c83ff; border-bottom: 1px solid #2a2d3e; padding-bottom: 12px; }
    h3 { color: #a0a8ff; margin-top: 24px; }
    small { color: #666; font-size: 0.8em; }
    .summary { display: flex; flex-wrap: wrap; gap: 16px; margin: 20px 0; }
    .metric { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 8px; padding: 12px 16px; min-width: 140px; }
    .label { display: block; font-size: 0.75em; color: #888; text-transform: uppercase; letter-spacing: 0.05em; }
    .value { display: block; font-size: 1.1em; font-weight: 600; margin-top: 4px; }
    .accent { color: #7c83ff; }
    .metrics-row { display: flex; gap: 24px; flex-wrap: wrap; margin: 8px 0; }
    .dataset-block { background: #1a1d2e; border: 1px solid #2a2d3e; border-radius: 8px; padding: 16px; margin: 16px 0; }
    .spark { font-family: monospace; background: #0d0f1a; padding: 8px 12px; border-radius: 4px; color: #7c83ff; font-size: 1.3em; letter-spacing: 2px; }
    .hash { font-size: 0.75em; color: #555; font-family: monospace; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; }
    th { background: #1a1d2e; text-align: left; padding: 8px 12px; font-size: 0.8em; color: #888; text-transform: uppercase; }
    td { padding: 8px 12px; border-bottom: 1px solid #1a1d2e; font-size: 0.85em; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .pass { color: #4caf7d; } .fail { color: #f44336; }
    .footer { margin-top: 40px; padding-top: 16px; border-top: 1px solid #2a2d3e; font-size: 0.75em; color: #555; }
    """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>{css}</style>
</head>
<body>
  <div class="container">
    <h1>{title}</h1>
    {summary_html}
    {datasets_section}
    <div class="footer">
      Generated by Nexus AI v{_NEXUS_VERSION} &nbsp;|&nbsp; {now} &nbsp;|&nbsp;
      Nexus AI Benchmark — <a href="https://github.com/the-no-hands-company/nexus-ai" style="color:#7c83ff">github.com/the-no-hands-company/nexus-ai</a>
    </div>
  </div>
</body>
</html>"""


def _html_samples_table(samples: list[dict[str, Any]]) -> str:
    if not samples:
        return ""
    rows = ""
    for s in samples[:100]:
        passed = s.get("passed", False)
        cls = "pass" if passed else "fail"
        mark = "✓" if passed else "✗"
        rows += f"""<tr>
          <td>{s.get('sample_id', '')}</td>
          <td class="{cls}">{mark} {s.get('score', 0):.2f}</td>
          <td>{s.get('latency_ms', '')}ms</td>
          <td title="{s.get('prompt', '')}">{str(s.get('prompt', ''))[:80]}…</td>
          <td title="{s.get('response', '')}">{str(s.get('response', ''))[:80]}…</td>
        </tr>"""
    return f"""<table>
      <thead><tr><th>Sample</th><th>Score</th><th>Latency</th><th>Prompt</th><th>Response</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>"""


# ── Leaderboard JSON (Papers With Code / OpenLLM compatible) ──────────────────

def export_leaderboard_json(results: list[dict[str, Any]], suite_id: str = "") -> dict[str, Any]:
    """Emit a leaderboard-compatible JSON payload."""
    entries = []
    for run in results:
        entries.append({
            "model_name": run.get("model", ""),
            "model_provider": run.get("provider", ""),
            "dataset": run.get("dataset", ""),
            "dataset_version": run.get("dataset_version", ""),
            "split": run.get("split", ""),
            "metric": "accuracy",
            "value": run.get("accuracy", 0.0),
            "num_samples": run.get("num_samples", 0),
            "avg_latency_ms": run.get("avg_latency_ms", 0.0),
            "p95_latency_ms": run.get("p95_latency_ms", 0.0),
            "run_id": run.get("run_id", ""),
            "dataset_content_hash": run.get("dataset_hash", ""),
            "timestamp": run.get("created_at", ""),
        })

    return {
        "schema_version": "1.0",
        "suite_id": suite_id,
        "framework": "nexus-ai",
        "framework_version": _NEXUS_VERSION,
        "generated_at": _now_iso(),
        "entries": entries,
        "note": (
            "Scores produced by Nexus AI benchmark runner. "
            "Dataset content hashes are SHA-256 of the serialized sample set. "
            "Set BENCHMARK_USE_HF_DATASETS=true for live HuggingFace data."
        ),
    }


# ── Signed manifest ───────────────────────────────────────────────────────────

def generate_manifest(artifacts: dict[str, str]) -> dict[str, Any]:
    """Generate a signed manifest with SHA-256 checksums for all artifact strings.

    Args:
        artifacts: mapping of artifact_name → artifact_content (str)

    Returns:
        manifest dict with per-artifact checksums and an overall manifest hash.
    """
    checksums: dict[str, str] = {}
    for name, content in artifacts.items():
        checksums[name] = _sha256(content.encode("utf-8") if isinstance(content, str) else content)

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": _now_iso(),
        "framework": "nexus-ai",
        "framework_version": _NEXUS_VERSION,
        "artifacts": checksums,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()
    manifest["manifest_hash"] = _sha256(manifest_bytes)
    return manifest


# ── Unified export entry point ────────────────────────────────────────────────

def export_benchmark_artifacts(
    run_data: dict[str, Any] | None = None,
    suite_data: dict[str, Any] | None = None,
    full_results: list[dict[str, Any]] | None = None,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    """Export benchmark results in all requested formats.

    Args:
        run_data:     Single-dataset benchmark result (from DatasetBenchmarkResult.to_dict()).
        suite_data:   Suite-level summary (from run_dataset_suite()).
        full_results: Full per-dataset results list including sample_results.
        formats:      List of format names to include. Defaults to all.
                      Options: "jsonl", "csv", "html", "leaderboard", "manifest".

    Returns:
        Dict of format → content, plus a "manifest" entry.
    """
    requested = set(formats or ["jsonl", "csv", "html", "leaderboard", "manifest"])
    out: dict[str, Any] = {}

    if full_results is None:
        full_results = [run_data] if run_data else []
    if suite_data is None and run_data:
        suite_data = {
            "suite_id": run_data.get("run_id", ""),
            "provider": run_data.get("provider", ""),
            "model": run_data.get("model", ""),
            "overall_accuracy": run_data.get("accuracy", 0.0),
            "datasets_run": [run_data.get("dataset", "")],
        }

    if "jsonl" in requested:
        if suite_data:
            out["jsonl"] = export_suite_jsonl(suite_data, full_results)
        elif run_data:
            out["jsonl"] = export_jsonl(run_data)

    if "csv" in requested:
        if full_results:
            out["csv"] = export_suite_csv(full_results)
        elif run_data:
            out["csv"] = export_csv(run_data)

    if "html" in requested:
        out["html"] = export_html_report(
            run_data=run_data,
            suite_data=suite_data,
            full_results=full_results if suite_data else None,
        )

    if "leaderboard" in requested:
        summaries = [{k: v for k, v in r.items() if k != "sample_results"} for r in full_results]
        out["leaderboard"] = export_leaderboard_json(summaries, suite_id=suite_data.get("suite_id", "") if suite_data else "")

    if "manifest" in requested:
        artifact_strings = {k: v if isinstance(v, str) else json.dumps(v) for k, v in out.items()}
        out["manifest"] = generate_manifest(artifact_strings)

    return out
