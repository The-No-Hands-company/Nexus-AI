#!/usr/bin/env python3
"""Audit competitor-source freshness in roadmap execution artifacts.

Checks source URLs and competitor signal strings for stale model references.
Exits non-zero if stale references are found.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

BACKLOG = ROOT / "docs/registry/l1_to_l2_high_value_backlog_2026Q2.csv"
EXEC_CUT = ROOT / "docs/registry/l1_to_l2_execution_cut_2026Q2.csv"
TICKETS_DIR = ROOT / "docs/sprint-tickets/2026-Q2"
CATALOG = ROOT / "docs/COMPETITOR_L0_L1_SEED_CATALOG_2026Q2.md"

STALE_PATTERNS = [
    re.compile(r"claude-3-5-sonnet", re.IGNORECASE),
    re.compile(r"Claude\s*3\.5", re.IGNORECASE),
    re.compile(r"Sonnet\s*3\.5", re.IGNORECASE),
    re.compile(r"Opus\s*4\.5", re.IGNORECASE),
    re.compile(r"Sonnet\s*4\.5", re.IGNORECASE),
    re.compile(r"gpt-5\.2", re.IGNORECASE),
    re.compile(r"gpt-4o", re.IGNORECASE),
    re.compile(r"gpt-4\.1", re.IGNORECASE),
]


def collect_from_csv(path: Path) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    signals: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            urls.extend([u.strip() for u in row.get("source_urls", "").split("|") if u.strip()])
            s = row.get("competitor_signals", "").strip()
            if s:
                signals.append(s)
    return urls, signals


def collect_from_tickets(path: Path) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    signals: list[str] = []
    for yaml_file in sorted(path.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        for ticket in data.get("tickets", []):
            urls.extend(ticket.get("source_urls", []))
            s = str(ticket.get("competitor_signals", "")).strip()
            if s:
                signals.append(s)
    return urls, signals


def stale_hits(values: list[str]) -> list[str]:
    hits: list[str] = []
    for value in values:
        if any(p.search(value) for p in STALE_PATTERNS):
            hits.append(value)
    return hits


def main() -> int:
    urls: list[str] = []
    signals: list[str] = []

    for csv_path in [BACKLOG, EXEC_CUT]:
        c_urls, c_signals = collect_from_csv(csv_path)
        urls.extend(c_urls)
        signals.extend(c_signals)

    t_urls, t_signals = collect_from_tickets(TICKETS_DIR)
    urls.extend(t_urls)
    signals.extend(t_signals)

    catalog_text = CATALOG.read_text(encoding="utf-8")

    url_counts = Counter(urls)
    stale_url_hits = stale_hits(list(url_counts.keys()))
    stale_signal_hits = stale_hits(signals)
    stale_catalog_hits = stale_hits([catalog_text])

    print("=== Competitor Source Freshness Audit ===")
    print(f"Unique URLs: {len(url_counts)}")
    print(f"Signals checked: {len(signals)}")
    print("Top URLs:")
    for url, count in url_counts.most_common(10):
        print(f"  {count:3d}  {url}")

    total_hits = len(stale_url_hits) + len(stale_signal_hits) + len(stale_catalog_hits)
    print(f"\nStale URL hits: {len(stale_url_hits)}")
    print(f"Stale signal hits: {len(stale_signal_hits)}")
    print(f"Stale catalog hits: {len(stale_catalog_hits)}")

    if stale_url_hits:
        print("\n[URLs]")
        for hit in stale_url_hits:
            print(f"  - {hit}")

    if stale_signal_hits:
        print("\n[Signals]")
        for hit in stale_signal_hits[:20]:
            print(f"  - {hit}")
        if len(stale_signal_hits) > 20:
            print(f"  ... and {len(stale_signal_hits) - 20} more")

    if stale_catalog_hits:
        print("\n[Catalog]")
        print("  - stale token found in seed catalog")

    if total_hits:
        print("\nResult: FAIL (stale references found)")
        return 1

    print("\nResult: PASS (no stale references found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
