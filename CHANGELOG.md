# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased] — Sprint K: Web UI — Live Trace, Task History, Swarm SSE

### Added

* `static/js/panels/task-history.js`: full Task History panel — search, filter (All/Done/Running/Failed), newest/oldest sort, expandable per-trace event timeline, export (.json), delete, replay/resume shortcuts
* `static/js/panels/live-trace.js`: Live Trace panel backed by SSE — real-time event stream with colour-coded type indicators, elapsed-time stamps, timeline tick bar, inline plan step expansion, tool result previews, trace replay dropdown
* `src/api/routes.py`: `GET /swarm/live` — SSE stream that pushes `activity_log` events as they arrive (replaces 2s client polling in Swarm View)
* `src/api/routes.py`: `GET /agent/stream/live` — SSE stream of all agent events for the Live Trace panel
* `static/js/panels/swarm.js`: Activity tab now connects via SSE (`/swarm/live`) instead of polling; falls back to 3s polling on SSE failure; new-events badge on Activity tab counts unseen events while user is on another tab
* `static/index.html`: Task History (🗂) and Live Trace (📡) added to overflow menu; both panel HTML blocks added; new-events badge wired; script tags for new panel JS

---

## [Unreleased — previous]

### Added
- Sprint J (NAI-SAFETY-CONTRACT-00002): Durable SQLite-backed safety audit storage — `add_safety_audit_entry()`, `load_safety_audit_entries()`, `clear_safety_audit_entries()` in `src/db.py`
- Sprint J: `_push_safety_event()` (`src/agent.py`) now persists every audit event to the `safety_audit` table — survives process restarts
- Sprint J: `GET /safety/audit` merges DB-persisted history with fresh in-memory events for zero-loss audit trail
- Sprint J: `src/db.py` auto-creates `safety_audit` table on first access via `_ensure_safety_audit_table()`
- Sprint J: `tests/test_v1_contracts.py` — `TestSafetyAuditPersistence` (5 new tests: block event persisted, visibility after in-memory clear, session filter from DB, severity filter from DB, PII scan persisted); **281 tests total**
- Sprint J (NAI-RELIABILITY-RUNTIME-00044): Durable HITL approval storage in `hitl_approvals` table with DB-backed create/list/decide/consume helpers in `src/db.py`
- Sprint J: `src/approvals.py` migrated from in-memory-only approval state to persistent DB-backed state with cache hydration on startup
- Sprint J: `src/agent.py` now delegates approval creation/listing/decision to `src/approvals.py` to avoid runtime drift in approval semantics
- Sprint J: `tests/test_v1_contracts.py` — `TestHITLApprovalPersistence` validates listing, decision state, and consume flow after in-memory cache clears

---

## [0.9.0] - 2026-05-01 — Sprint I: Scheduler, PII Scanner, Knowledge Graph

### Added
- `src/scheduler.py`: `ScheduledJob`, `schedule_job`, `list_jobs`, `cancel_job`, `pause_job`, `resume_job`, `_cron_matches`, `_scheduler_loop` — full background cron scheduler
- `src/knowledge_graph.py`: SQLite-backed KG — `kg_store`, `kg_query`, `kg_get`, `kg_relate`, `kg_list_entities`, `kg_delete`, `kg_to_context_string`
- `src/api/routes.py`: `GET /scheduler/jobs`, `POST /scheduler/jobs`, `POST /scheduler/jobs/{job_id}/cancel`
- `src/api/routes.py`: `POST /kg/store`, `GET /kg/query`, `GET /kg/entities`, `GET /kg/entities/{name}`, `DELETE /kg/entities/{name}`
- `src/api/routes.py`: `POST /safety/pii-scan` — PII detection and redaction endpoint
- `src/api/routes.py`: `POST /safety/prompt-injection` — prompt injection scan with explain mode
- `src/api/routes.py`: Command palette support (inline Cmd+K search across all operations)
- `tests/test_v1_contracts.py`: `TestSprintI` — scheduler, PII scan, KG endpoints

---

## [0.8.0] - 2026-04-30 — Sprint H: File Diff, Swarm View, Vision Routing

### Added
- `src/execution_trace.py`: `save_file_diff`, `get_file_diffs`, `get_file_diff_detail` — per-trace diff storage
- `src/api/routes.py`: `POST /diff`, `GET /diff/history`, `GET /diff/{diff_id}` — file diff endpoints
- `src/api/routes.py`: `GET /swarm/activity` — real-time swarm activity feed (circular buffer)
- `src/agent.py`: `OLLAMA_MODEL_REGISTRY` extended with vision model (`llava`, `bakllava`) routing
- `src/tools_builtin.py`: `inspect_db` tool — schema and row introspection for SQLite targets
- `static/js/panels/swarm.js`: Swarm View panel with polling, colour-coded action feed, event count
- `tests/test_v1_contracts.py`: `TestSprintH` — diff viewer, swarm activity, `inspect_db`

---

## [0.7.0] - 2026-04-28 — Sprint G: Simulation, Dynamic Spawning, Agent Marketplace

### Added
- `src/simulation.py`: `SimulationEngine`, `PersonaAgent`, `RoundSummary`, `SimulationResult` — run parallel multi-agent debates with LLM-backed synthesis
- `src/agent_bus.py`: `AgentBus`, `AgentMessage` — agent-to-agent message passing with inbox/unread/log
- `src/api/routes.py`: `POST /simulate` — trigger simulation with configurable personas and task
- `src/api/routes.py`: `GET /marketplace/agents`, `POST /marketplace/agents`, `DELETE /marketplace/agents/{id}` — agent marketplace CRUD
- `src/api/routes.py`: `GET /agents/bus/log`, `GET /agents/bus/{agent_id}`, `POST /agents/bus` — agent bus API
- `src/autonomy.py`: dynamic agent spawning logic based on task complexity tier and required specialist type
- `tests/test_v1_contracts.py`: `TestSprintG` — simulation, marketplace, agent bus

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
