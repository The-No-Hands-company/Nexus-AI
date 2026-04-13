# Nexus-AI Layered Feature Model

Purpose: keep feature planning honest by counting at one abstraction layer at a time while preserving traceability across layers.

## Layer Definitions

Use exactly one layer for each dashboard/report. Do not mix layers in a single count.

1. L0 Market Capabilities

- What users and announcements talk about.
- Examples: multi-agent orchestration, long-term memory, vision support, coding mode.
- Typical count size: tens to low hundreds.

1. L1 Product Capabilities

- User-visible capabilities split into concrete product surfaces.
- Examples: agent marketplace import, approval queue UI, per-provider health panel.
- Typical count size: hundreds to low thousands.

1. L2 Implementation Features

- Engineering units mapped to module/endpoint/ui/test/benchmark ownership.
- This matches the operational registry schema used in v3/v3.1.
- Typical count size: thousands to tens of thousands.

1. L3 Leaf Behaviors

- Smallest testable/observable contract behaviors and edge-case guarantees.
- Examples: retry on 429 for provider X, SSE truncation policy branch, auth scope mismatch error code.
- Typical count size: tens of thousands to 100k+ for mature platforms.

## Counting Rules

- A single report must declare its layer (`L0`, `L1`, `L2`, or `L3`) at the top.
- Never compare counts from different layers as if they are equivalent.
- Promotion rule: an item can move state only with evidence for that same layer.
- Mapping rule: each item should map up/down at least one adjacent layer when possible.

## State Model By Layer

Use the same lifecycle states, but interpret evidence at the layer boundary:

- `proposed`: item idea exists with owner.
- `specified`: acceptance criteria written for that layer.
- `implemented`: code or surface exists for the layer claim.
- `verified`: automated/manual evidence meets acceptance criteria.
- `released`: available to users/operators.
- `deprecated`: retired and migration path documented.

## What Counts As "Real Progress"

Real progress is measured at L2/L3 with evidence.

- L0/L1 progress can be announced.
- L2/L3 progress must include `test_id` and/or `benchmark_id` plus evidence links.

## Current Nexus-AI Mapping

- L2 source of truth: `docs/registry/feature_registry_v3.csv` and `docs/registry/feature_registry_v3_1.csv`
- L2 status views: `docs/registry/feature_registry_v3_rollup.json`, `docs/registry/feature_registry_v3_dashboard.md`, `docs/registry/feature_registry_v3_1_rollup.json`, `docs/registry/feature_registry_v3_1_dashboard.md`
- L2 generator: `scripts/build_operational_registry.py`

## Weekly Operating Workflow

1. Curate L0/L1 from competitor announcements and user demand.
2. Translate only selected L1 items into L2 implementation features.
3. Break high-risk L2 items into L3 leaf behaviors before coding.
4. Promote states only with evidence (tests/benchmarks/docs links).
5. Publish separate dashboards for L1 and L2/L3 so counts stay honest.

## Decision Rule For 100k Discussion

- "Do we have 100k features?" is only meaningful if explicitly asking about L3 leaf behaviors.
- It is not a valid L0/L1 marketing claim unless those layers are counted separately.
