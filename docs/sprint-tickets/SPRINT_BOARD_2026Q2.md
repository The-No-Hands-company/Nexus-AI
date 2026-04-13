# Sprint Board 2026 Q2

Generated: 2026-04-13 | Signals refreshed: 2026-04-13 | Source: `docs/registry/l1_to_l2_execution_cut_2026Q2.csv`

- Total tickets: 25
- P0: 20  |  P1: 5
- Owner teams: 10

## Ticket Files

| Owner Team | Tickets | File |
| --- | ---: | --- |
| api-platform | 1 | [2026-Q2/api-platform.yaml](2026-Q2/api-platform.yaml) |
| core-agent | 2 | [2026-Q2/core-agent.yaml](2026-Q2/core-agent.yaml) |
| eval-quality | 2 | [2026-Q2/eval-quality.yaml](2026-Q2/eval-quality.yaml) |
| identity-access | 3 | [2026-Q2/identity-access.yaml](2026-Q2/identity-access.yaml) |
| memory-systems | 2 | [2026-Q2/memory-systems.yaml](2026-Q2/memory-systems.yaml) |
| multimodal-runtime | 1 | [2026-Q2/multimodal-runtime.yaml](2026-Q2/multimodal-runtime.yaml) |
| routing-platform | 3 | [2026-Q2/routing-platform.yaml](2026-Q2/routing-platform.yaml) |
| safety-runtime | 8 | [2026-Q2/safety-runtime.yaml](2026-Q2/safety-runtime.yaml) |
| tooling-runtime | 2 | [2026-Q2/tooling-runtime.yaml](2026-Q2/tooling-runtime.yaml) |
| ux-product | 1 | [2026-Q2/ux-product.yaml](2026-Q2/ux-product.yaml) |

## Board Summary

| Ticket ID | Priority | Value | L1 Feature | L2 Feature ID | Owner | Evidence Gate |
| --- | --- | ---: | --- | --- | --- | --- |
| SPR-SAFETY_RUNTIME-Q2-01 | P0 | 96 | Sensitive action confirmation workflow | NAI-SAFETY-SECURITY-00001 | safety-runtime | approval-required integration tests |
| SPR-SAFETY_RUNTIME-Q2-02 | P0 | 96 | Multi-layer safety pipeline with monitor model | NAI-SAFETY-SECURITY-00005 | safety-runtime | safety pipeline end-to-end tests |
| SPR-IDENTITY_ACCESS-Q2-01 | P0 | 95 | Human confirmation before irreversible actions | NAI-AUTH-SECURITY-00001 | identity-access | approval + authz integration tests |
| SPR-SAFETY_RUNTIME-Q2-03 | P0 | 95 | Hallucination guardrails for missing evidence | NAI-SAFETY-SECURITY-00004 | safety-runtime | evidence-required response tests |
| SPR-SAFETY_RUNTIME-Q2-04 | P0 | 95 | Prompt-injection and adversarial content defenses | NAI-SAFETY-SECURITY-00006 | safety-runtime | adversarial eval suite |
| SPR-TOOLING_RUNTIME-Q2-01 | P0 | 95 | Browser action mode with takeover checkpoints | NAI-TOOLS-TOOLING-00001 | tooling-runtime | approval flow tests + audit trail |
| SPR-IDENTITY_ACCESS-Q2-02 | P0 | 94 | Team policies for tool and data access | NAI-AUTH-SECURITY-00002 | identity-access | policy enforcement tests |
| SPR-SAFETY_RUNTIME-Q2-05 | P0 | 94 | Action policy gating for high-stakes tasks | NAI-SAFETY-SECURITY-00007 | safety-runtime | high-stakes denylist tests |
| SPR-SAFETY_RUNTIME-Q2-06 | P0 | 94 | Safety benchmark tracking and release gating | NAI-SAFETY-SECURITY-00008 | safety-runtime | safety gate release tests |
| SPR-TOOLING_RUNTIME-Q2-02 | P0 | 94 | Robust tool call retries with typed error handling | NAI-TOOLS-TOOLING-00004 | tooling-runtime | retry/backoff contract tests |
| SPR-API_PLATFORM-Q2-01 | P0 | 93 | API parity for key assistant and agent features | NAI-API-CONTRACT-00003 | api-platform | api parity contract tests |
| SPR-CORE_AGENT-Q2-01 | P0 | 93 | Repo-aware coding agent with edit-run-verify loops | NAI-CORE-RUNTIME-00002 | core-agent | coding task benchmark + contract tests |
| SPR-ROUTING_PLATFORM-Q2-01 | P0 | 93 | Built-in web retrieval with grounding citations | NAI-ROUTER-RUNTIME-00002 | routing-platform | grounding citation checks |
| SPR-ROUTING_PLATFORM-Q2-02 | P0 | 93 | Dynamic model routing by task complexity | NAI-ROUTER-RUNTIME-00003 | routing-platform | routing quality benchmark |
| SPR-SAFETY_RUNTIME-Q2-07 | P0 | 93 | Tool sandbox policy profiles by risk level | NAI-SAFETY-SECURITY-00002 | safety-runtime | policy matrix tests |
| SPR-CORE_AGENT-Q2-02 | P0 | 92 | Multi-step task planning and resumable execution | NAI-CORE-RUNTIME-00001 | core-agent | trace replay tests + failure resume benchmark |
| SPR-EVAL_QUALITY-Q2-01 | P0 | 92 | Unified benchmark runner for agentic tasks | NAI-EVAL-EVALUATION-00003 | eval-quality | benchmark harness CI |
| SPR-SAFETY_RUNTIME-Q2-08 | P0 | 92 | Memory privacy controls and retention policies | NAI-SAFETY-SECURITY-00003 | safety-runtime | privacy config tests |
| SPR-EVAL_QUALITY-Q2-02 | P0 | 91 | Coding benchmark harness and regression gates | NAI-EVAL-EVALUATION-00001 | eval-quality | benchmark result persistence + CI gate |
| SPR-IDENTITY_ACCESS-Q2-03 | P0 | 91 | Role-based access control and approvals | NAI-AUTH-SECURITY-00003 | identity-access | rbac matrix tests |
| SPR-MEMORY_SYSTEMS-Q2-01 | P1 | 90 | User preference memory with explicit controls | NAI-MEMORY-RUNTIME-00001 | memory-systems | memory preference persistence tests |
| SPR-MULTIMODAL_RUNTIME-Q2-01 | P1 | 89 | Image understanding with chart/table extraction | NAI-MULTIMODAL-RUNTIME-00001 | multimodal-runtime | multimodal eval set |
| SPR-ROUTING_PLATFORM-Q2-03 | P1 | 89 | Latency-aware fallback and cooldown behavior | NAI-ROUTER-RUNTIME-00004 | routing-platform | p95/p99 fallback tests |
| SPR-UX_PRODUCT-Q2-01 | P1 | 89 | Side-by-side artifact workspace for outputs | NAI-UX-UX-00001 | ux-product | artifact pane UX tests |
| SPR-MEMORY_SYSTEMS-Q2-02 | P1 | 86 | Session-to-session memory summaries | NAI-MEMORY-RUNTIME-00002 | memory-systems | summary recall regression tests |

## Execution Policy

- P0 tickets must be completed before P1 in each owner queue.
- State promotion requires evidence_gate passing and test_id green in CI.
- Blocked P0 > 48h: escalate and advance highest-value unblocked P1 in same queue.
- `done_definition` in each YAML ticket is the merge-gate checklist.
