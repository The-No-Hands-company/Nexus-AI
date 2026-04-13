# Nexus-AI Roadmap Scale System

Purpose: scale roadmap planning from dozens of features to thousands without losing verification quality.

For layer-consistent counting semantics (L0 market capabilities through L3 leaf behaviors), see `docs/ROADMAP_LAYERED_FEATURE_MODEL.md`.

## 1) Scale Target

- Near-term operating target: 2,000 implemented and testable feature units.
- Mid-term target: 5,000 feature units.
- Long-term target: 12,000 to 20,000 feature units.

Machine-readable registry artifacts:

- Seed registry: `docs/registry/feature_registry_seed_v1.csv`
- Seed metadata: `docs/registry/feature_registry_seed_v1.meta.json`
- v2 registry (CSV): `docs/registry/feature_registry_v2.csv`
- v2 registry (JSONL): `docs/registry/feature_registry_v2.jsonl`
- v2 metadata: `docs/registry/feature_registry_v2.meta.json`
- v2.1 registry (CSV, preferred): `docs/registry/feature_registry_v2_1.csv`
- v2.1 registry (JSONL, preferred): `docs/registry/feature_registry_v2_1.jsonl`
- v2.1 metadata: `docs/registry/feature_registry_v2_1.meta.json`
- v2.2 registry (CSV): `docs/registry/feature_registry_v2_2.csv`
- v2.2 registry (JSONL): `docs/registry/feature_registry_v2_2.jsonl`
- v2.2 metadata: `docs/registry/feature_registry_v2_2.meta.json`
- v2.3 registry (2k): `docs/registry/feature_registry_v2_3.csv` and `.jsonl`
- v2.4 registry (5k): `docs/registry/feature_registry_v2_4.csv` and `.jsonl`
- v2.5 registry (14k budget-aligned): `docs/registry/feature_registry_v2_5.csv` and `.jsonl`
- v2.6 registry (20k frontier-scale, preferred for long-range planning): `docs/registry/feature_registry_v2_6.csv` and `.jsonl`
- v3 operational registry (20k, implementation-linked seed): `docs/registry/feature_registry_v3.csv` and `.jsonl`
- v3 operational metadata: `docs/registry/feature_registry_v3.meta.json`
- v3 state rollup: `docs/registry/feature_registry_v3_rollup.json`
- v3 domain dashboard: `docs/registry/feature_registry_v3_dashboard.md`
- v3.1 operational registry (50k expansion with ownership/evidence columns): `docs/registry/feature_registry_v3_1.csv` and `.jsonl`
- v3.1 operational metadata: `docs/registry/feature_registry_v3_1.meta.json`
- v3.1 state rollup: `docs/registry/feature_registry_v3_1_rollup.json`
- v3.1 domain dashboard: `docs/registry/feature_registry_v3_1_dashboard.md`
- generator: `scripts/build_operational_registry.py`

Feature unit definition:

- A user-visible behavior, operator capability, protocol contract, model/runtime behavior, or reliability/security guarantee that can be verified by at least one automated check.

## 2) Feature Ontology (How We Count)

To avoid vague mega-items, every roadmap item is one of these classes:

- `contract`: schema, endpoint, protocol, typed error, compatibility behavior.
- `runtime`: orchestration, routing, safety, memory, execution control, scaling behavior.
- `tooling`: agent tools, tool policies, capability permissions, connectors.
- `ux`: web/mobile/CLI interaction, discoverability, workflow speed, clarity.
- `reliability`: retries, idempotency, tracing, resilience, rollback.
- `security`: authz/authn, secrecy, policy enforcement, auditability.
- `performance`: latency, throughput, memory efficiency, startup and warm path.
- `evaluation`: benchmark, regression test, quality metric, score trend.
- `ops`: deployability, observability, diagnostics, incident response.

## 3) Feature ID System

Every feature receives a stable ID:

- Format: `NAI-<DOMAIN>-<CLASS>-<NNNNN>`
- Example: `NAI-SAFETY-RUNTIME-00427`

Domains (v1):

- `CORE` agent orchestration and reasoning
- `ROUTER` model/provider selection and failover
- `SAFETY` guardrails, policy and compliance
- `MEMORY` short/long-term context and retrieval
- `TOOLS` filesystem/shell/git/connectors
- `MULTIAGENT` planner/executor/reviewer/swarm
- `MULTIMODAL` image/audio/video/document capability
- `UX` chat, artifacts, controls, feedback loops
- `API` OpenAI-compatible and native Nexus APIs
- `AUTH` identity, sessions, access control
- `OBS` logs, traces, metrics, debugging
- `PERF` latency/cost/throughput optimization
- `DATA` storage/indexing/migrations/lifecycle
- `EVAL` benchmarks and quality scoring
- `PLATFORM` self-hosting, federation, deployment

## 4) States and Evidence

Allowed states:

- `proposed`
- `specified`
- `implemented`
- `verified`
- `released`
- `deprecated`

Each state transition requires evidence:

- `specified`: acceptance criteria + dependency list
- `implemented`: code path merged + migration notes when needed
- `verified`: test IDs and pass evidence
- `released`: exposed to users/operators and documented

Operational registry seed columns used in v3+:

- `module_path`
- `endpoint`
- `ui_surface`
- `test_id`
- `benchmark_id`
- `owner_team`
- `evidence_ref`
- `mapping_mode`
- `evidence_status`

Important: v3/v3.1 provide operational linkage seeds and dashboard coverage, not automatic proof that a row is implemented or verified. `mapping_mode=templated_operational_seed` means the row has a deterministic ownership/linkage slot that still needs domain ingestion and evidence promotion.

## 5) Dependency Graph Rules

- Contract nodes must precede runtime nodes.
- Runtime nodes must precede UX nodes.
- Security and safety checks gate release states.
- Features without verification evidence cannot be marked `verified` or `released`.

## 6) Domain Budgets (First 14,000 Features)

- `CORE`: 1,200
- `ROUTER`: 800
- `SAFETY`: 1,500
- `MEMORY`: 1,000
- `TOOLS`: 1,300
- `MULTIAGENT`: 1,200
- `MULTIMODAL`: 1,500
- `UX`: 900
- `API`: 700
- `AUTH`: 400
- `OBS`: 700
- `PERF`: 600
- `DATA`: 700
- `EVAL`: 800
- `PLATFORM`: 700

Total: 14,000

## 7) Planning Cadence

- Weekly: add/refine `proposed` and `specified` features.
- Sprint: implement and verify a bounded slice per domain.
- Monthly: reconcile roadmap claims with code reality.
- Quarterly: rebalance domain budgets based on product usage and benchmark gaps.

## 8) Definition of Genuine Missing Feature

A feature is genuinely missing when all checks are true:

- It is in `proposed` or `specified` state.
- No equivalent code path exists in current runtime or API behavior.
- Existing behavior does not satisfy its acceptance criteria.
- There is no passing test evidence for the required behavior.

## 9) Program Rules for Large-Scale Backlog

- Never create umbrella items like "be as good as frontier models" as executable tasks.
- Decompose every umbrella objective into measurable leaf features.
- Keep each feature independently testable in isolation.
- Track roadmap drift explicitly: "document says missing, code says shipped" and inverse.

## 10) Next Scale Actions

- Promote v3/v3.1 linkage seeds to code-verified rows by domain-by-domain ingestion from runtime/API/tests.
- Replace templated evidence refs with concrete test pass artifacts, benchmark result IDs, and docs references.
- Maintain a live "genuine missing" index per domain, driven from the operational rollups.
- Attach benchmark deltas and release evidence to high-impact feature clusters.
