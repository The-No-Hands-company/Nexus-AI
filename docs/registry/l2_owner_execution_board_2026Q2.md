# L2 Owner Execution Board (2026 Q2)

Purpose: immediate execution slice from the competitor-informed L1-to-L2 mapping.

- Total items: 25
- P0 items: 20
- P1 items: 5

## Owner Queues

### api-platform

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P0 | L1-12-01 | API parity for key assistant and agent features | NAI-API-CONTRACT-00003 | 93 | api parity contract tests |

### core-agent

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P0 | L1-02-01 | Repo-aware coding agent with edit-run-verify loops | NAI-CORE-RUNTIME-00002 | 93 | coding task benchmark + contract tests |
| P0 | L1-01-02 | Multi-step task planning and resumable execution | NAI-CORE-RUNTIME-00001 | 92 | trace replay tests + failure resume benchmark |

### eval-quality

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P0 | L1-11-01 | Unified benchmark runner for agentic tasks | NAI-EVAL-EVALUATION-00003 | 92 | benchmark harness CI |
| P0 | L1-02-04 | Coding benchmark harness and regression gates | NAI-EVAL-EVALUATION-00001 | 91 | benchmark result persistence + CI gate |

### identity-access

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P0 | L1-04-04 | Human confirmation before irreversible actions | NAI-AUTH-SECURITY-00001 | 95 | approval + authz integration tests |
| P0 | L1-08-01 | Team policies for tool and data access | NAI-AUTH-SECURITY-00002 | 94 | policy enforcement tests |
| P0 | L1-08-02 | Role-based access control and approvals | NAI-AUTH-SECURITY-00003 | 91 | rbac matrix tests |

### memory-systems

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P1 | L1-05-01 | User preference memory with explicit controls | NAI-MEMORY-RUNTIME-00001 | 90 | memory preference persistence tests |
| P1 | L1-05-02 | Session-to-session memory summaries | NAI-MEMORY-RUNTIME-00002 | 86 | summary recall regression tests |

### multimodal-runtime

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P1 | L1-03-01 | Image understanding with chart/table extraction | NAI-MULTIMODAL-RUNTIME-00001 | 89 | multimodal eval set |

### routing-platform

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P0 | L1-06-01 | Built-in web retrieval with grounding citations | NAI-ROUTER-RUNTIME-00002 | 93 | grounding citation checks |
| P0 | L1-10-01 | Dynamic model routing by task complexity | NAI-ROUTER-RUNTIME-00003 | 93 | routing quality benchmark |
| P1 | L1-10-02 | Latency-aware fallback and cooldown behavior | NAI-ROUTER-RUNTIME-00004 | 89 | p95/p99 fallback tests |

### safety-runtime

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P0 | L1-01-04 | Sensitive action confirmation workflow | NAI-SAFETY-SECURITY-00001 | 96 | approval-required integration tests |
| P0 | L1-09-01 | Multi-layer safety pipeline with monitor model | NAI-SAFETY-SECURITY-00005 | 96 | safety pipeline end-to-end tests |
| P0 | L1-06-03 | Hallucination guardrails for missing evidence | NAI-SAFETY-SECURITY-00004 | 95 | evidence-required response tests |
| P0 | L1-09-02 | Prompt-injection and adversarial content defenses | NAI-SAFETY-SECURITY-00006 | 95 | adversarial eval suite |
| P0 | L1-09-03 | Action policy gating for high-stakes tasks | NAI-SAFETY-SECURITY-00007 | 94 | high-stakes denylist tests |
| P0 | L1-11-04 | Safety benchmark tracking and release gating | NAI-SAFETY-SECURITY-00008 | 94 | safety gate release tests |
| P0 | L1-04-02 | Tool sandbox policy profiles by risk level | NAI-SAFETY-SECURITY-00002 | 93 | policy matrix tests |
| P0 | L1-05-04 | Memory privacy controls and retention policies | NAI-SAFETY-SECURITY-00003 | 92 | privacy config tests |

### tooling-runtime

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P0 | L1-01-01 | Browser action mode with takeover checkpoints | NAI-TOOLS-TOOLING-00001 | 95 | approval flow tests + audit trail |
| P0 | L1-04-01 | Robust tool call retries with typed error handling | NAI-TOOLS-TOOLING-00004 | 94 | retry/backoff contract tests |

### ux-product

| Priority | L1 ID | L1 Feature | L2 ID | Value | Evidence Gate |
| --- | --- | --- | --- | ---: | --- |
| P1 | L1-07-01 | Side-by-side artifact workspace for outputs | NAI-UX-UX-00001 | 89 | artifact pane UX tests |

## Execution Policy

- Start with all P0 items in each owner queue before any P1 item.
- Promote L2 state only when the listed evidence gate is satisfied.
- If a P0 item is blocked > 48h, escalate and pull the highest-value unblocked P1 for that owner.
