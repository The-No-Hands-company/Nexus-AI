# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Sprint G: `simulate` tool — lightweight swarm prediction engine (inspired by MiroFish)
- Sprint G: Dynamic agent spawning based on task type and complexity
- Sprint G: Agent marketplace — JSON-defined agents importable/exportable via API
- Sprint G: Agent-to-agent message passing via shared workspace

---

## [0.6.0] - 2026-04-13 — Sprint F: Hierarchical Orchestration + Specialist Agents

### Added
- `src/autonomy.py`: `ReviewerAgent`, `VerifierAgent` stages in `HierarchicalOrchestrator`
- `src/autonomy.py`: Full Planner → Executor → Reviewer → Verifier pipeline
- `src/agents/`: Specialist agent registry — Architect, Security Auditor, UI/UX Designer, Data Scientist, Product Manager, Debugger, Documentation Writer, Code Reviewer
- `src/agent.py`: `OLLAMA_MODEL_REGISTRY` — 15+ models mapped to task types (coding, reasoning, creative, vision)
- `src/agent.py`: `get_best_ollama_model(task_type)` — auto-selects the best locally available Ollama model
- `src/agent.py`: Ollama `_call_single` uses auto-selected model when `_selected_model` is set
- `src/api/routes.py`: `GET /agents` — list all registered specialist agents
- `src/api/routes.py`: `POST /orchestrate/hierarchical` — run full hierarchical orchestration pipeline
- `tests/test_v1_contracts.py`: `TestSprintF` — 23 new tests (94 total)

---

## [0.5.0] - 2026-04-13 — Sprint E: Filtered Memory, Feedback, SSE Signals

### Added
- `src/memory.py`: `get_semantic_memory_filtered()` — date/tags/persona filters on Chroma + SQLite fallback; `persona` stored in Chroma metadata
- `src/db.py`: `message_feedback` table + `save_feedback`, `load_feedback_export`, `get_feedback_stats`
- `src/api/routes.py`: `GET /memory/search` — filtered semantic memory search with query params
- `src/api/routes.py`: `POST /feedback/{chat_id}/{message_idx}` — store per-message 👍👎 reaction
- `src/api/routes.py`: `GET /feedback/export` — export all feedback as training data JSON
- `src/api/routes.py`: `GET /feedback/stats` — aggregate thumbs-up/down counts
- `src/agent.py`: `_trace_steps` accumulator for reasoning steps
- `src/agent.py`: `confidence`, `trace`, `token_count` SSE events emitted before `done`
- `CHANGELOG.md`, `docs/ROADMAP.md`: Sprint A–E history and roadmap checkboxes updated
- `tests/test_v1_contracts.py`: `TestSprintE` — 18 new tests (71 total)

---

## [0.4.0] - 2026-04-13 — Sprint D: Graph-of-Thought, Consensus, Benchmark

### Added
- `src/thinking.py`: `build_got_prompt()` — Graph-of-Thought reasoning prompt; requests nodes/edges/merges/conclusion JSON
- `src/thinking.py`: `parse_got_response()` — parse GoT JSON into structured reasoning trace with graceful fallback
- `src/thinking.py`: `parse_consensus_response()` — parse cross-model consensus JSON
- `src/ensemble.py`: `call_llm_consensus()` — wraps ensemble, extracts winning text + metadata `texts` key
- `src/context_window.py`: `compress_history_with_llm()` — LLM-backed abstractive context compression, falls back to naive on error
- `src/db.py`: `benchmark_results` table + `init_benchmark_table()`, `save_benchmark_result()`, `load_benchmark_results()`
- `src/api/routes.py`: `POST /benchmark/run` — probe all available providers with 3 standardised probes
- `src/api/routes.py`: `GET /benchmark/results` — return stored benchmark history
- `src/api/routes.py`: `POST /reason/consensus` — cross-model consensus endpoint
- `src/agent.py`: Graph-of-Thought mode wired into `think_deep` tool (`"mode": "graph"`)
- `src/agent.py`: `_maybe_compress_history` upgraded to prefer LLM-backed compression for long histories
- `tests/test_v1_contracts.py`: `TestSprintD` — 13 new tests (53 total)

---

## [0.3.0] - 2026-04-13 — Sprint C: Self-Critique, MoE Routing, Memory Pruning

### Added
- `src/thinking.py`: `build_critique_prompt()`, `parse_critique_response()` — self-critique loop
- `src/ensemble.py`: Mixture-of-Experts task risk scoring, `score_task_risk()`, `is_high_risk()`, `action_risk_level()`
- `src/ensemble.py`: `pick_consensus()` — majority vote + safety tiebreak; `call_llm_ensemble()`
- `src/agent.py`: MoE boost in `_smart_order()`, CRITIQUE_THRESHOLD, self-critique path in `call_llm_smart()`
- `src/memory.py`: `prune_old_memories()` with configurable age + minimum keep
- `src/db.py`: `prune_memory_by_age()` — protected-ID-aware deletion
- `src/api/routes.py`: `POST /memory/prune`, `GET /memory/semantic`
- `tests/test_v1_contracts.py`: `TestSprintC` — 10 new tests (40 total)

---

## [0.2.0] - 2026-04-13 — Sprint B: Safety, Context Window, Ensemble

### Added
- `src/safety.py`: `GuardrailViolation`, `check_user_task()`, `block_patterns`, `sensitive_words`
- `src/context_window.py`: `ContextWindowConfig`, `ContextWindowManager`, `compress_history()`
- `src/ensemble.py`: core module scaffolding, `ENSEMBLE_SIZE`, `MIN_ENSEMBLE_SIZE`, `RISK_THRESHOLD`
- `src/api/state.py`: centralised shared state (`sessions`, `chats`, `run_results`, `execution_traces`, etc.)
- `src/api/schemas.py`: Pydantic v2 request/response models
- `src/agent.py`: `execution_traces` wiring, `_estimate_tokens()`, `_messages_token_estimate()`
- `tests/test_v1_contracts.py`: `TestSprintB` — tests for safety, context window, ensemble scaffolding

---

## [0.1.0] - 2026-04-12 — Sprint A: OpenAI-Compatible API Foundation

### Added
- `src/` package with `agent.py`, `db.py`, `memory.py`, `personas.py`, `thinking.py`, `autonomy.py`
- `src/app.py`: FastAPI application factory
- `src/api/routes.py`: `GET /v1/models`, `POST /v1/chat/completions` (streaming SSE, OpenAI-compatible)
- `src/api/schemas.py`: base request/response schema stubs
- `docs/ARCHITECTURE.md`, `docs/SECURITY.md`, `docs/ROADMAP.md`
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `LICENSE`, `SECURITY.md`
- `tests/test_v1_contracts.py`: initial test suite (Sprint A, 30 tests)
