# Nexus-AI Genuine Gaps Index (April 2026)

This file tracks genuinely missing features after reconciling roadmap claims with observed code paths.

Registry linkage:

- Seed registry IDs and state baseline: `docs/registry/feature_registry_seed_v1.csv`
- Registry metadata/schema: `docs/registry/feature_registry_seed_v1.meta.json`

## Method

- Cross-check roadmap claims against current runtime/API/tool behavior.
- Mark as missing only when behavior is absent or materially incomplete.
- Keep this list focused on high-leverage gaps first.

## A) Safety and Policy

- `NAI-SAFETY-RUNTIME-00001` Policy severity profiles by tenant/environment (dev/stage/prod).
- `NAI-SAFETY-CONTRACT-00002` Structured safety audit persistence and query API.
- `NAI-SAFETY-RUNTIME-00003` Domain guards (medical/legal/finance) with selectable warn/block modes.
- `NAI-SAFETY-RUNTIME-00004` High-risk approval UX in frontend (approve/reject workflow cards).
- `NAI-SAFETY-EVAL-00005` Safety regression benchmark suite with trend scoring.

## B) Multimodal

- `NAI-MULTIMODAL-RUNTIME-00010` Native vision understanding path (image to grounded answer).
- `NAI-MULTIMODAL-TOOLS-00011` Robust PDF/Office extraction with layout-aware parsing.
- `NAI-MULTIMODAL-RUNTIME-00012` Audio transcription + diarization pipeline.
- `NAI-MULTIMODAL-RUNTIME-00013` Local TTS voice output integration.
- `NAI-MULTIMODAL-TOOLS-00014` Web screenshot capture tool integrated into agent context.

## C) Multi-Agent and Autonomy

- `NAI-MULTIAGENT-UX-00020` Full Swarm View timeline + dependency graph visualization.
- `NAI-MULTIAGENT-RUNTIME-00021` Persistent background autonomous jobs with recovery after restart.
- `NAI-MULTIAGENT-RUNTIME-00022` Human takeover controls for long-running plans.
- `NAI-MULTIAGENT-OBS-00023` Per-agent token/cost/runtime dashboard.
- `NAI-MULTIAGENT-CONTRACT-00024` Deterministic replay with reproducibility checksum.

## D) Memory and Knowledge

- `NAI-MEMORY-DATA-00030` Hybrid graph+vector memory with relation confidence tracking.
- `NAI-MEMORY-RUNTIME-00031` Memory conflict resolution policy (new vs old fact arbitration).
- `NAI-MEMORY-RUNTIME-00032` Persona-scoped and project-scoped retrieval controls in UI.
- `NAI-MEMORY-EVAL-00033` Long-horizon memory accuracy benchmark pack.

## E) Performance and Reliability

- `NAI-PERF-RUNTIME-00040` Predictive provider prewarming based on task signatures.
- `NAI-PERF-RUNTIME-00041` Streaming latency SLO enforcement and adaptive fallback.
- `NAI-PERF-OBS-00042` End-to-end waterfall traces (router -> tool -> response).
- `NAI-RELIABILITY-RUNTIME-00043` Durable job queue for background workflows.
- `NAI-RELIABILITY-RUNTIME-00044` Idempotent resume semantics for interrupted tool chains.

## F) API and Enterprise Readiness

- `NAI-API-CONTRACT-00050` Fine-grained API key scopes and per-scope quotas.
- `NAI-API-CONTRACT-00051` Per-user rate limits and quotas (current path is still session-based).
- `NAI-AUTH-RUNTIME-00052` RBAC roles for operator/admin/auditor permissions.
- `NAI-API-CONTRACT-00053` Admin policy API for safety/routing/memory controls.

## G) UX and Product Surface

- `NAI-UX-RUNTIME-00060` Operator incident console (failed runs, safety blocks, retries).
- `NAI-UX-RUNTIME-00061` Diff viewer integrated with file write and commit paths.
- `NAI-UX-RUNTIME-00062` Command palette coverage for all top-level operations.
- `NAI-UX-RUNTIME-00063` In-product explanation cards for fallback/approval/safety decisions.

## Next Prioritized Slice

1. `NAI-SAFETY-RUNTIME-00002` Safety audit persistence and query API.
2. `NAI-SAFETY-RUNTIME-00004` HITL approval frontend workflow.
3. `NAI-API-CONTRACT-00051` Per-user quota/rate-limit system.
4. `NAI-MULTIMODAL-TOOLS-00011` Production document understanding path.