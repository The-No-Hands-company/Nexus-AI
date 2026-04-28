# Nexus-AI External Borrow Matrix and Implementation Tickets

## Scope and Method

This audit maps external projects and frontier APIs to concrete Nexus-AI implementation work.

- Sources reviewed: Open WebUI, LiteLLM, LangGraph, LangChain, AutoGen, CrewAI, Haystack, LlamaIndex, Open Interpreter, Ollama, DeepSeek API docs, OpenAI API docs, Anthropic Claude docs, Google Gemini docs, xAI Grok docs.
- Selection rule: borrow patterns and contracts that improve reliability, compatibility, and zero-friction UX.
- Rejection rule: do not import patterns that force users to manually manage providers, routing, or complexity.

## Concrete Borrow Matrix

| Source | Borrowable Pattern | Evidence Snapshot | Nexus-AI Target | Priority | Dependency | Risk |
|---|---|---|---|---|---|---|
| Open WebUI | OpenAI-compat request/response normalization layer | Compatibility adapters around chat and embeddings routes | `main.py` API schema boundary | P0 | Typed schemas + typed errors | Medium: schema drift if not contract-tested |
| LiteLLM | Router fallback policies with cooldowns, retries, and budgets | Multi-provider router with spend controls and fallback paths | `agent.py` provider router + new budget middleware | P0 | Capability registry + usage ledger | Medium: false budget trips |
| LangGraph | Durable checkpoint and interrupt/resume model | Thread/checkpoint persistence and resumable execution semantics | `autonomy.py` orchestration state store | P1 | Trace IDs + persisted run state | Medium: replay consistency bugs |
| LangChain | Structured output repair/retry pipeline | Output parser retry/fix patterns for schema-constrained generation | `agent.py` response post-processor | P0 | JSON schema registry | Low |
| AutoGen | Team orchestration with explicit termination and state save/load | Group chat manager, selector flow, and state persistence APIs | `autonomy.py` multi-agent runtime | P1 | Base agent interface + trace persistence | Medium |
| CrewAI | Hierarchical process contract (manager required) | Hierarchical mode constraints and planner-manager flow | `autonomy.py` planner/executor/reviewer contract | P1 | Role contracts + capability tags | Low |
| Haystack | Modular pipeline primitives for retrieval and synthesis | Composable retrieval and answer-builder components | `rag/` query pipeline | P1 | Embeddings endpoint + rerank stage | Low |
| LlamaIndex | Citation-oriented synthesis and query decomposition | Citation engines and decomposed query execution | `rag/` + response metadata schema | P1 | Structured citation schema | Low |
| Open Interpreter | Tool safety gate with approval mode and scan hooks | Safe mode and explicit execution boundaries | `agent.py` tool dispatch + policy module | P0 | Safety verdict types | Medium: overblocking if too strict |
| Ollama | Capability metadata and embeddings parity | `/api/embed` and model capability inspection | `main.py` model metadata + embeddings route | P0 | Capability registry | Low |
| DeepSeek | Reasoning-model dual channel (`reasoning_content` + final answer) handling | Reasoner docs expose separate reasoning field and restrictions | `agent.py` provider adapters + normalization | P1 | Provider-specific normalizer | Medium: leaking provider-specific fields |
| OpenAI | Structured Outputs strict schema + refusal handling | `json_schema` strict mode, refusal field, required/additionalProperties constraints | `main.py` response_format handling + tests | P0 | Schema compiler and validator | Low |
| Claude | Strict tool schema conformance and explicit tool loop states | `tool_use` -> execute -> `tool_result` lifecycle and strict tools | `agent.py` action planner and tool loop | P0 | Tool schema registry | Low |
| Gemini | Parallel/compositional tool calls and function call IDs | Function call IDs, parallel calls, compositional tool workflows | `agent.py` tool-call executor | P1 | Multi-call envelope schema | Medium: ordering/id mismatches |
| Grok/xAI | Responses API style status lifecycle and deferred retrieval | `responses` objects with status and retrieval semantics | `main.py` async run status endpoints | P2 | Run store and webhook/status model | Low |

## Borrow Decisions (Do and Do Not)

Adopt now (P0/P1):

- OpenAI-compatible strict schema handling, including refusal-safe parsing.
- Capability registry and embeddings endpoint parity.
- Typed error taxonomy and stable error payloads.
- Safety gate in tool execution path with configurable approval modes.
- Checkpointable orchestration with replay IDs for long tasks.

Defer (P2+):

- Full group-chat swarm UX and heavy multi-agent graph visualizations.
- Advanced background response lifecycle parity beyond current webhook/status needs.

Reject:

- Any UX flow that requires users to manually pick providers/models for normal use.
- Any feature that makes `PROVIDER=auto` less deterministic for baseline tasks.

## Implementation Tickets (Sprint-Ready)

### Sprint A (Contracts and Compatibility Baseline)

1. `NAI-A01` - OpenAI-compatible embeddings endpoint
- Scope: Add `POST /v1/embeddings` with OpenAI-compatible request and response schema.
- Files: `main.py`, `requirements.txt` (if tokenizer dependency needed), `README.md`.
- Acceptance:
  - Endpoint accepts batch and single inputs.
  - Returns deterministic shape (`data`, `model`, `usage`).
  - Contract tests pass against OpenAI SDK-style payloads.
- Tests:
  - Add API contract tests for success, validation error, and oversized input.

2. `NAI-A02` - Typed API error taxonomy
- Scope: Normalize API errors into stable typed categories (`validation_error`, `provider_unavailable`, `context_overflow`, `rate_limited`).
- Files: `main.py`, new `api_errors.py`.
- Acceptance:
  - All API failures map to stable `error.type` and `error.code`.
  - HTTP status mapping is deterministic.
- Tests:
  - Route-level failure tests for each error class.

3. `NAI-A03` - Strict `response_format` JSON mode behavior
- Scope: Implement strict schema path and JSON-object path behavior with explicit refusal-safe output handling.
- Files: `main.py`, `agent.py`.
- Acceptance:
  - Supports strict schema mode where provider supports it.
  - Fallbacks to validated JSON mode where strict schema is unavailable.
  - Returns typed incompatibility error if requested mode is unsupported.
- Tests:
  - Structured output schema pass/fail tests.

4. `NAI-A04` - Capability registry endpoint
- Scope: Introduce provider/model capability metadata (`tools`, `vision`, `embeddings`, `json_mode`, `reasoning`) and expose via stable endpoint.
- Files: `agent.py`, `main.py`.
- Acceptance:
  - `GET /api/capabilities` (or equivalent) returns normalized capability map.
  - Router consumes registry for model selection.
- Tests:
  - Capability schema tests and router decision tests.

### Sprint B (Safety and Reliability Runtime)

5. `NAI-B01` - Safety verdict core and guardrail pipeline
- Scope: Create canonical safety verdict types and a centralized pre/post tool guardrail pipeline.
- Files: new `safety_types.py`, new `safety_pipeline.py`, `agent.py`.
- Acceptance:
  - Every tool call receives a safety verdict.
  - Configurable modes: `log`, `warn`, `block`.
- Tests:
  - Unit tests for safe, warn, and blocked tool scenarios.

6. `NAI-B02` - Tool schema registry with strict argument validation
- Scope: Move ad-hoc tool argument handling into schema-validated registry.
- Files: `agent.py`, `tools_builtin.py`.
- Acceptance:
  - Tool args validated before execution.
  - Validation failures map to typed API errors.
- Tests:
  - Per-tool argument validation tests.

7. `NAI-B03` - Replayable trace IDs and checkpointed long-run tasks
- Scope: Persist orchestration trace and checkpoint state for resume/replay.
- Files: `autonomy.py`, `db.py`, `main.py`.
- Acceptance:
  - Long tasks can resume from latest checkpoint.
  - Trace replay endpoint returns deterministic event sequence.
- Tests:
  - Resume after simulated failure test.

8. `NAI-B04` - Context window manager
- Scope: Deterministic truncation/compression policy for long conversations.
- Files: `memory.py`, `agent.py`.
- Acceptance:
  - Policy preserves system/developer and highest-priority task turns.
  - Compression triggers are observable in logs/metadata.
- Tests:
  - Overflow regression tests with fixed token budgets.

### Sprint C (Research Quality and Advanced Orchestration)

9. `NAI-C01` - Generator-critic research flow with citation confidence
- Scope: Introduce optional two-pass generation (draft + critique) with citation confidence scoring.
- Files: `agent.py`, `rag/` modules.
- Acceptance:
  - Research persona can enable critic flow.
  - Output includes citation list + confidence metadata.
- Tests:
  - Citation-presence and confidence-shape tests.

10. `NAI-C02` - Parallel and compositional tool-call executor
- Scope: Add multi-tool execution plan handling with call IDs and deterministic merge.
- Files: `agent.py`.
- Acceptance:
  - Supports N independent tool calls and ordered reconciliation.
  - Handles partial tool failures gracefully.
- Tests:
  - Parallel call unit tests with mixed success/failure.

11. `NAI-C03` - High-risk consensus mode
- Scope: Add ensemble/consensus route for high-risk tasks only.
- Files: `model_router.py`, `agent.py`.
- Acceptance:
  - Consensus mode off by default.
  - Triggered only by configured risk predicates.
- Tests:
  - Router tests validating risk-gated activation.

12. `NAI-C04` - Per-user quotas and limits
- Scope: Upgrade current session-limited rate limiting to per-user quotas and fair-use controls.
- Files: `main.py`, `db.py`.
- Acceptance:
  - Rate limiting keyed by authenticated user when present.
  - Anonymous sessions retain fallback session limit.
- Tests:
  - Multi-user quota isolation tests.

## Dependency Graph (Execution Order)

1. `NAI-A02` -> `NAI-A01` -> `NAI-A04` -> `NAI-A03`
2. `NAI-A02` -> `NAI-B02` -> `NAI-B01`
3. `NAI-B03` + `NAI-B04` -> `NAI-C01` + `NAI-C02`
4. `NAI-A04` + `NAI-B01` -> `NAI-C03`
5. `NAI-A02` + auth layer -> `NAI-C04`

## Exit Criteria

- Sprint A complete when OpenAI-compatible embeddings/structured-output/error contracts are green in CI.
- Sprint B complete when tool safety, replayability, and context compression are active with regression tests.
- Sprint C complete when research-quality flows and advanced orchestration run without changing the default zero-friction UX.

## Notes on Current Nexus-AI Baseline

- `POST /v1/chat/completions` and `GET /v1/models` exist.
- Rate limiting is currently per-session (`SESSION_RATE_LIMIT`) rather than per-user.
- MCP call path and provider cooldown/fallback paths already exist and should be reused, not replaced.
