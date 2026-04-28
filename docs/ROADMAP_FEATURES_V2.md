# ROADMAP_FEATURES_V2

This roadmap captures the next major expansion track after the v1 contract baseline.

## Phase 1: Federated LLM

Goal: enable sovereign multi-node model collaboration while preserving privacy-first control.

- Integrate federation adapters for Petals, FATE-LLM, OpenFedLLM, Flower, and Hivemind.
- Add federated routing policy guarded by ENABLE_FEDERATED_LLM.
- Add adapter exchange workflow for LoRA sharing with provenance metadata.
- Add org-aware policy checks for cross-node model access.
- Add observability for federation latency, failover, and per-provider success rate.
- Add regression harness to validate parity with local single-node execution.

Exit Criteria:

- Federated routing can be enabled/disabled at runtime via feature flag.
- At least one end-to-end federated inference flow passes integration validation.
- Failure modes degrade gracefully to existing local provider fallback.

## Phase 2: Creative Tools (Music + 3D)

Goal: provide first-party creative generation endpoints and agent tools in a safe staged rollout.

- Add music generation tool path with future backend adapters (ACE-Step, DiffRhythm).
- Add 3D generation tool path with future backend adapters (TripoSR, Hunyuan3D).
- Gate all creative tool execution behind ENABLE_CREATIVE_TOOLS.
- Add API and tool contracts for async job creation and status polling.
- Add output safety screening and artifact metadata tracking.
- Add focused evals for prompt fidelity and artifact quality regressions.

Exit Criteria:

- Music and 3D tool stubs are available but inert unless feature flag is enabled.
- Tool responses are stable and contract-safe in both disabled and enabled modes.
- Observability exposes per-tool latency and error class distribution.
