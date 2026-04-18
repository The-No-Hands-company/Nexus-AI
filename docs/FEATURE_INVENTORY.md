# Nexus AI — Complete Feature Inventory

> **Purpose:** Ground-truth map of every feature Nexus AI has, partially has, or needs.
> A feature is anything that makes the system behave differently — even a single guard clause.
> Legend: `[x]` = fully implemented and production ready | `[~]` = implemented but partial / stub / mock / non-persistent | `[ ]` = not yet started

---

## How to read this document

Each section maps to an architectural layer: from deepest backend to public-facing UI.
Sub-items are individual features, not phases or themes.
When a feature moves from `[ ]` → `[~]` → `[x]`, update the mark here.

---

## 1. Foundational Infrastructure

### 1.1 Application bootstrap

- [x] FastAPI application factory (`src/app.py`)
- [x] `main.py` entry-point with Uvicorn configuration
- [x] CORS middleware (configurable origins)
- [x] Static file serving (`/static`)
- [x] Startup / shutdown event hooks (lifespan context manager)
- [x] Environment variable configuration (`.env` + `os.environ`)
- [x] Docker Compose single-stack deployment (`docker-compose.yml`)
- [x] Railway deploy config (`railway.toml`)
- [x] Health check endpoint (`GET /health`)
- [x] System resource endpoint (`GET /api/system/resources`)
- [x] Kubernetes / Helm chart deployment manifests (`deploy/k8s/`, `deploy/helm/nexus-ai/`)
- [x] Horizontal scaling / worker process mode (Gunicorn + Uvicorn workers) (`gunicorn.conf.py`)

### 1.2 Database / persistence

- [x] SQLite default backend (`src/db.py`)
- [x] PostgreSQL backend via `DATABASE_URL` env switch
- [x] Chat history table (create / read / delete)
- [x] Usage records table (token counts, cost)
- [x] User accounts table (with `role` column + migration)
- [x] Alembic-compatible schema (manual migration handling) (`migrations/env.py`, `alembic.ini`)
- [x] Alembic migration files (tracked, runnable migrations) (`migrations/versions/0001_initial_schema.py`)
- [x] Native SQLite introspection tool (`tool_inspect_sqlite`)
- [x] Native PostgreSQL introspection and query tool (`tool_inspect_postgres` in `src/tools_builtin.py`)
- [x] Database connection pooling configuration (PostgreSQL ThreadedConnectionPool)
- [x] Database backup / restore endpoint (`GET /api/backup`, `POST /api/restore`)

### 1.3 Authentication and multi-user

- [x] JWT-based authentication (`src/auth.py` + routes) — PBKDF2 hashing, HS256 tokens, role-aware
- [x] `POST /auth/register` — create account (first user → admin)
- [x] `POST /auth/login` — returns JWT + refresh token
- [x] `GET /auth/me` — current user info
- [x] `GET /admin/users` — admin user list
- [x] `PATCH /admin/users/{username}/role` — role management (admin/user/viewer)
- [x] `MULTI_USER=false` single-user bypass mode
- [x] `POST /auth/logout` (token revocation / blacklist)
- [x] `POST /auth/refresh` (JWT refresh token rotation)
- [x] `POST /auth/password-reset` (self-service + admin override)
- [x] Email verification on register (`POST /auth/send-verification`, `GET /auth/verify-email`)
- [x] OAuth2 / OIDC SSO provider support (Google OIDC + GitHub OAuth, `GET /auth/oauth/{provider}`)
- [x] Per-user API key management (`POST /auth/api-keys`, `GET /auth/api-keys`, `DELETE /auth/api-keys/{key_id}`)
- [x] API key scopes / permissions (`chat`, `read`, `admin`, `embeddings`, `tools`)

### 1.4 Per-user quotas and rate limiting

- [x] Session-level rate limiting (per-minute + per-day sliding windows, hard/soft mode)
- [x] `GET /settings/rate-limits` — read rate-limit config
- [x] `POST /settings/rate-limits` — update rate-limit config
- [x] Per-user quota isolation (token budget per user per day via `src/profiles.py`)
- [x] Per-user spend cap with soft/hard limits (`set_quota()` / `check_quota()`)
- [x] Quota overage 429 response with `X-RateLimit-*` headers (Limit, Remaining, Reset, Policy, Retry-After)
- [x] Admin dashboard for quota monitoring (`GET /admin/quota`, `POST /admin/quota/{username}`)
- [x] Quota reset scheduler (daily/weekly) (weekly cron `0 3 * * 0` + stale-key cleanup in `src/api/routes.py`)

---

## 2. Provider and Model Routing

### 2.1 Provider registry and fallback

- [x] 11-provider fallback chain (Ollama → LLM7 → Groq → Cerebras → Gemini → Mistral → OpenRouter → Cohere → GitHub Models → Grok → Claude) — Implementation: `src/agent.py:call_llm_with_fallback()` chains providers in order, handles 429/timeout fallback
- [x] Provider cooldown after 429 (`RATE_LIMIT_COOLDOWN=60`) — Implementation: `src/agent.py:_cooldowns` dict + `_mark_rate_limited()` / `_is_rate_limited()`
- [x] `AllProvidersExhausted` exception with structured 503 retry guidance — Implementation: `src/agent.py:AllProvidersExhausted` exception class, raised when fallback chain exhausted
- [x] `_provider_exhausted_error()` helper (scope-tagged retry payloads) (`src/agent.py:_provider_exhausted_error()`)
- [x] `GET /providers` — live provider list — Implementation: `src/api/routes.py:@router.get("/providers")` returns `get_providers_list()`
- [x] `GET /providers/health` — per-provider health + cooldown state — Implementation: `src/api/routes.py:@router.get("/providers/health")` returns `get_provider_health()` with status/capabilities/benchmarks
- [x] `GET /providers/status` (architecture doc reference, same as `/providers`) — Implementation: `src/api/routes.py:@router.get("/providers/status")` alias for health endpoint
- [x] Complexity-based model tier selection (high / medium / low) — Implementation: `src/agent.py:PROVIDER_TIERS` dict + `_score_complexity()` function
- [x] `PROVIDER=auto` zero-config default — Implementation: `src/agent.py:_config["provider"]` defaults to "auto", `_smart_order()` routes dynamically
- [x] Budget-aware routing (prefer cheapest model that meets quality bar) (`BUDGET_TIER` env + `_PROVIDER_COST_PER_1K_TOKENS` in `src/agent.py`)
- [x] Provider spend tracking per request (cost written to `usage` table) — Implementation: `src/db.py:log_usage()` writes provider/model/tokens to `usage_log` table
- [x] Provider priority override per persona — Implementation: `src/agent.py:set_provider_persona_override()` / `get_provider_persona_override()` + `_PERSONA_PROVIDER_OVERRIDES` dict
- [x] Hardware-aware routing (prefer GPU-backed providers over CPU) — Implementation: `src/hardware.py:get_hardware_routing_hint()` probes system resources, `src/agent.py:_resource_tier()` routes based on RAM/CPU availability
- [x] Provider benchmark baseline (latency / quality matrix per model) — Implementation: `src/agent.py:_PROVIDER_BENCHMARKS` dict with latency_ms, quality_score, tier, cost_tier per provider
- [x] Provider capability matrix used by router (vision / json / tools / reasoning flags) — Implementation: `src/agent.py:PROVIDER_CAPABILITIES` dict, `src/api/routes.py:@router.get("/v1/models/capabilities")` returns capability matrix

### 2.2 Ollama / local inference

- [x] Ollama OpenAI-compatible client path — Implementation: `src/agent.py:PROVIDERS["ollama"]` with `openai_compat=True`, `base_url=OLLAMA_BASE_URL`
- [x] `ollama_list_models` tool — Implementation: `src/agent.py:tool_ollama_list_models()` function, registered in `src/tools_builtin.py:dispatch_builtin()`
- [x] `tool_select_model` — task-based Ollama model selector — Implementation: `src/tools_builtin.py:tool_select_model()` uses `ModelRouter.select_model()` for code/reasoning tasks
- [x] Ollama pull-on-demand (auto-pull missing model) (`_ollama_pull()` in `src/agent.py`, `POST /ollama/pull`)
- [x] Ollama model benchmark runner endpoint (`POST /ollama/benchmark`)
- [x] GGUF model file management endpoint (`GET/DELETE /ollama/gguf`, `POST /ollama/gguf/import`)
- [x] HuggingFace model download + Ollama import pipeline (`POST /huggingface/download`)

### 2.3 OpenAI-compatible API surface

- [x] `POST /v1/chat/completions` — streaming + non-streaming — Implementation: `src/api/routes.py` endpoint with OpenAI schema normalization
- [x] `GET /v1/models` — model list — Implementation: `src/api/routes.py:@router.get("/v1/models")` returns catalog via `_v1_models_catalog()`
- [x] `GET /v1/models/capabilities` — capability matrix — Implementation: `src/api/routes.py:@router.get("/v1/models/capabilities")` returns per-provider capabilities
- [x] `GET /v1/models/{model_id}` — single model info — Implementation: `src/api/routes.py:@router.get("/v1/models/{model_id:path}")` retrieves model details including benchmarks
- [x] `GET /v1/capabilities` — system capability flags — Implementation: `src/api/routes.py:@router.get("/v1/capabilities")` returns platform-level capability aggregation
- [x] `POST /v1/embeddings` — embeddings endpoint — Implementation: `src/api/routes.py:@router.post("/v1/embeddings")` with input normalization
- [x] Strict `response_format` JSON mode enforcement (`_normalize_response_format()` + `_validate_json_output()` in `src/api/routes.py`)
- [x] Typed API error taxonomy (error type + HTTP status mapping) (`ERROR_TYPE_STATUS` dict in `src/api/schemas.py`)
- [x] OpenAI-compatible request / response schema normalization (`src/api/schemas.py`: `CompletionRequest`, `AudioSpeechRequest`, `FileObject`, `FineTuningJob`, etc.)
- [x] `POST /v1/completions` (legacy text completions endpoint)
- [x] `POST /v1/images/generations` (OpenAI-compatible image generation) — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); tool=`generate_image_local` (`src/tools_builtin.py` registry + `tool_generate_image_local`); module=`src/generation.py:generate_image_local`.
- [x] `POST /v1/audio/transcriptions` (Whisper-compatible STT, local faster-whisper + OpenAI fallback)
- [x] `POST /v1/audio/speech` (TTS endpoint, local piper/espeak + OpenAI fallback)
- [x] `GET/POST/DELETE /v1/files` + `GET /v1/files/{id}/content` (OpenAI Files API compatibility)
- [x] `POST/GET /v1/fine-tuning/jobs`, `GET/POST /v1/fine-tuning/jobs/{id}` (persistent OpenAI-compatible fine-tuning lifecycle with background state transitions, cancellation, and durable event history via `GET /v1/fine-tuning/jobs/{id}/events` in `src/api/routes.py` + `src/db.py`)
- [x] OpenAI Structured Outputs schema subset enforcement (`_validate_json_schema_value()` in `src/api/routes.py`)
- [x] DeepSeek `reasoning_content` field normalization (`_call_openai()` extracts and maps to `thought` field)
- [x] Gemini function-call ID mapping for parallel calls (`_call_openai()` maps `tool_calls` IDs to `_tool_calls`)
- [x] Claude `tool_use` / `tool_result` parity lifecycle normalization (`_call_claude_api()` normalizes content blocks)
- [x] Grok async deferred response lifecycle normalization (`_call_grok()` polls `/v1/deferred/` on 202)

### 2.4 Ensemble and consensus routing

- [x] `src/ensemble.py` — consensus engine — Implementation: Complete consensus engine with `score_task_risk()`, `is_high_risk()`, `pick_consensus()`, `call_llm_ensemble()`, `call_llm_consensus()`
- [x] `POST /reason/consensus` — multi-provider consensus vote — Implementation: `src/api/routes.py:@router.post("/reason/consensus")` wraps `call_llm_consensus()` with reconciliation metadata
- [x] High-risk task routing to consensus (risk-gated) — Implementation: `src/agent.py:call_llm_smart()` checks `score_task_risk()` vs `ensemble_threshold`, activates ensemble for high-risk tasks
- [x] `GET /settings/ensemble` — read ensemble config — Implementation: `src/api/routes.py:@router.get("/settings/ensemble")` returns ensemble mode/threshold flags
- [x] `POST /settings/ensemble` — update ensemble config — Implementation: `src/api/routes.py:@router.post("/settings/ensemble")` updates ensemble settings with validation
- [x] Configurable quorum size (2-of-3, 3-of-5) — Implementation: `src/ensemble.py:ENSEMBLE_SIZE=3`, `MIN_ENSEMBLE_SIZE=2`, configurable via API
- [x] Tie-breaking policy (confidence-weighted vs majority) — Implementation: `src/ensemble.py:pick_consensus()` uses `action_risk_level()` for tie-breaking
- [x] Ensemble result explanation in API response (`explain_consensus()` in `src/ensemble.py`, surfaced in `POST /reason/consensus`)


---

## 3. Agent Loop and Core Intelligence

### 3.1 Agent execution loop

- [x] `src/agent.py` — streaming tool-call loop
- [x] Tool-call loop (up to 16 iterations)
- [x] SSE event stream (`token`, `think`, `plan`, `tool_start`, `tool_result`, `done`)
- [x] `POST /agent` — non-streaming agent run
- [x] `POST /agent/stream` — SSE streaming agent run
- [x] `GET /agent/trace/{trace_id}` — fetch execution trace (live trace cache with DB fallback in `src/api/routes.py` + `src/db.py`)
- [x] `POST /agent/stop/{stream_id}` — cancel active stream (stop signal recorded durably for audit/state tracking in `src/api/routes.py` + `src/db.py`)
- [x] `POST /agents/{agent_id}/run` — run named specialist agent
- [x] `GET /agents/{agent_id}` — get agent spec
- [x] `GET /agents` — list all specialist agents
- [x] `POST /agents/classify` — classify task to best agent
- [x] Auto-retry on malformed LLM output
- [x] Confidence scoring on responses
- [x] `AllProvidersExhausted` → 503 retry guidance on `/agents/{agent_id}/run`
- [x] Parallel tool-call execution (fan-out multiple tools simultaneously)
- [x] Compositional (chained sequential) tool-call support
- [x] Partial tool-failure recovery (continue after one tool errors) — Pointers: route=`POST /agent`, `POST /agent/stream` (`src/api/routes.py`); tool=`dispatch_builtin` + `_tool_trace(..., status="error")` (`src/tools_builtin.py`); module=`src/agent.py:_execute_parallel_tool_call`, `src/agent.py:_run_parallel_tool_batch`.
- [x] Tool-call call ID tracking for parallel/compositional flows
- [x] Streaming token counter telemetry event
- [x] Per-request execution budget (max tokens, max tool calls, max time)
- [x] Agent warm-up / pre-loading (keep agent context primed between calls)

### 3.2 Reasoning and thinking

- [x] `src/thinking.py` — Chain-of-Thought / Tree-of-Thought helpers
- [x] `think_deep` tool — Tree-of-Thought reasoning
- [x] Graph-of-Thought reasoning (`POST /reason/graph-of-thought`; prompt + parser in `src/thinking.py`, route wiring in `src/api/routes.py`)
- [x] Self-critique loop (`POST /agent/self-review`)
- [x] `GET /agent/self-review/history`
- [x] Cross-model consensus (`POST /reason/consensus`)
- [x] Generator-critic research flow (`POST /reason/generator-critic`)
- [x] Multi-agent debate (`POST /reason/debate`)
- [x] Hypothesis testing flow (`POST /reason/hypothesis`)
- [x] Reflection / retrospective loop (post-task quality review stored as learning signal and exported into fine-tuning samples via `src/api/routes.py` + `src/db.py`)
- [x] Monte Carlo Tree Search (MCTS) for planning space exploration (`POST /reason/mcts` plus automatic high-complexity pre-planning in `src/agent.py`)
- [x] Socratic reasoning mode (question-driven decomposition) (`POST /reason/socratic` in `src/api/routes.py`)
- [x] Step-by-step verification (formal proof checking for math/code) (`POST /reason/verify` in `src/api/routes.py` using `src/thinking.py` verification helpers)

### 3.3 Autonomy and orchestration

- [x] `src/autonomy.py` — multi-step orchestrator + planning system
- [x] `POST /autonomy/plan` — dry-run plan generation
- [x] `POST /autonomy/execute` — full autonomous task execution
- [x] `GET /autonomy/trace/{trace_id}` — trace retrieval (DB-backed persistence in `src/api/routes.py` + `src/db.py`)
- [x] `POST /orchestrate/hierarchical` — Planner→Executor→Reviewer→Verifier pipeline
- [x] `GET /orchestrate/hierarchical/{trace_id}` — hierarchical trace (DB-backed persistence in `src/api/routes.py` + `src/db.py`)
- [x] Structured task decomposition (PlanningSystem)
- [x] Subtask classification to tool / agent
- [x] Sequential and parallel subtask execution
- [x] SSE events: `plan`, `subtask`, `tool`, `result`, `autonomy_done`
- [x] Checkpointed long-run execution (`src/execution_trace.py`) (live checkpoint persistence now wired into `/autonomy/execute` and `/autonomy/execute/stream` with stepwise snapshots for replay/resume in `src/api/routes.py`)
- [x] `GET /tasks` — task list (live traces merged with DB-backed execution trace persistence in `src/api/routes.py` + `src/db.py`)
- [x] `GET /tasks/{trace_id}` — task detail (in-memory with DB fallback)
- [x] `GET /tasks/{trace_id}/replay` — deterministic trace replay (replays persisted DB traces across sessions)
- [x] `POST /tasks/{trace_id}/resume` — resume interrupted task (new resumed traces persisted to DB for cross-session continuity)
- [x] `DELETE /tasks/{trace_id}` — delete task trace
- [x] Task dependency graph (DAG scheduling between subtasks)
- [x] Cross-task memory sharing (results of task A injected into task B context, persisted via `task_shared_memory` in `src/db.py` and used by `src/task_queue.py`)
- [x] Task queue with priority ordering
- [x] Background task worker (run tasks without blocking HTTP response; queue state persisted and restored on worker start via `src/task_queue.py` + `src/db.py`)
- [x] Task cancellation mid-execution (not just stream stop)
- [x] Scheduled task re-run on cron triggers (re-enqueued jobs are persisted and restored through the DB-backed task queue in `src/task_queue.py` + `src/db.py`)

### 3.4 Simulation

- [x] `src/simulation.py` — simulation engine
- [x] `POST /simulate` — run agent simulation scenario
- [x] Scenario library (pre-built simulation templates)
- [x] Simulation result comparison (A/B run diffing)
- [x] Simulation → training signal pipeline (export to fine-tuning dataset)

---

## 4. Memory System

### 4.1 Short-term / session memory

- [x] Conversation history stored per session (active session history is tracked in `api/state.py:sessions` and persisted per-session in shared memory via `session_history:{sid}` keys in `src/api/routes.py`)
- [x] `_maybe_compress_history` (multi-step history compression) (wired into live agent streaming flow in `src/agent.py` and backed by `ContextWindowManager.compress_history_with_llm()`)
- [x] Last 5 summaries injected at session start (`POST /session` injects `get_memory_context()` with `MEMORY_IN_CONTEXT=5` in `src/api/routes.py` + `src/memory.py`)
- [x] `POST /session` — create session
- [x] `DELETE /session/{sid}` — delete session
- [x] `POST /session/{sid}/token` — update session token
- [x] `GET /session/{sid}/safety` — session safety state
- [x] `POST /session/{sid}/safety` — update session safety state

### 4.2 Long-term / semantic memory

- [x] `src/memory.py` — memory manager
- [x] Semantic vector store (ChromaDB) (`chromadb.PersistentClient` + collection `nexus_memory` in `src/memory.py`)
- [x] `GET /memory` — list memory entries
- [x] `DELETE /memory` — clear all memory
- [x] `POST /memory/prune` — prune low-value entries
- [x] `PATCH /memory/{entry_id}` — update entry
- [x] `DELETE /memory/{entry_id}` — delete entry
- [x] `GET /memory/semantic` — list semantic items
- [x] `POST /memory/semantic` — store semantic item
- [x] `GET /memory/search` — full-text + semantic search over memory
- [x] Memory count and clear in sidebar (`static/js/utilities/memory-projects.js:loadMemoryCount()` + `clearMemory()`)
- [x] Recency fallback when vector store unavailable (`get_semantic_memory_filtered()` SQLite fallback path in `src/memory.py`)
- [x] Episodic memory (event-based timeline storage separate from semantic) (`GET /memory/episodic` + episodic timeline persisted in `src/memory.py` metadata store)
- [x] Memory importance scoring (decay over time, boost on re-access) (`_importance_with_decay()` + `_touch_memory()` in `src/memory.py`)
- [x] Cross-session memory consolidation (merge short-term → long-term on session close) (`DELETE /session/{sid}` summarizes and stores memory in `src/api/routes.py`)
- [x] Memory provenance tracking (which session/task created each entry) (provenance fields tracked in `src/memory.py` and exposed via memory list/search outputs)
- [x] Memory export / import (portable memory bundles) (`GET /memory/export` + `POST /memory/import` in `src/api/routes.py`)

### 4.3 Knowledge graph memory

- [x] `src/knowledge_graph.py`
- [x] `POST /kg/store` — store entity + relations
- [x] `GET /kg/query` — query by relationship
- [x] `GET /kg/entities` — list entities
- [x] `GET /kg/entities/{name}` — get entity detail
- [x] `DELETE /kg/entities/{name}` — delete entity
- [x] `tool_kg_store`, `tool_kg_query`, `tool_kg_list` tools
- [x] KG graph visualization endpoint (Cytoscape / D3 JSON format) (`GET /kg/graph` in `src/api/routes.py`, `kg_graph()` in `src/knowledge_graph.py`)
- [x] KG entity merge / deduplication (`POST /kg/merge` in `src/api/routes.py`, `kg_merge()` in `src/knowledge_graph.py`)
- [x] KG import from external ontology (OWL / RDF) (`POST /kg/import` in `src/api/routes.py`, `kg_import_ontology()` with rdflib/fallback parser)
- [x] KG-aware retrieval (KG + vector hybrid search) (`GET /kg/hybrid-search` in `src/api/routes.py`)

### 4.4 Context window management

- [x] `src/context_window.py` — context window manager
- [x] Dynamic context compression policy (`_maybe_compress_history()` + `compress_history_with_llm()` selected by conversation length in `src/agent.py`)
- [x] Deterministic compression (reproducible token budget enforcement) (`compress_to_token_budget()` in `src/context_window.py`)
- [x] Per-model context budget awareness (auto-detect model's max context) (`get_model_context_budget()` in `src/context_window.py`)
- [x] Token counting per message before send (`token_breakdown()` + `token_breakdown` SSE event in `src/agent.py`)
- [x] Context overflow early warning event in SSE stream (`context_overflow_warning` event emitted in `src/agent.py`)

---

## 5. RAG (Retrieval-Augmented Generation)

### 5.1 RAG pipeline

- [x] `src/rag/pipeline.py` — end-to-end RAG orchestration
- [x] `src/rag/chunker.py` — document chunking
- [x] `src/rag/embeddings.py` — embedding generation
- [x] `src/rag/vector_store.py` — ChromaDB vector store (with memory/FAISS fallback)
- [x] `src/rag/retriever.py` — retrieval + reranking
- [x] `src/rag/rag_system.py` — high-level RAG system class
- [x] `POST /rag/ingest` — ingest document text (incremental updates supported)
- [x] `POST /rag/query` — semantic query (citations + calibrated confidence + critic pass)
- [x] `GET /rag/status` — vector store status
- [x] `tool_rag_ingest`, `tool_rag_query`, `tool_rag_status` tools
- [x] Persistent vector store filters (date / tags / persona) (`$eq/$contains/$in/$gte/$lte` in `src/rag/vector_store.py`)

### 5.2 RAG quality and intelligence

- [x] `src/rag/critic.py` — RAG answer quality critic
- [x] `src/rag/query_decomposer.py` — multi-hop query decomposition
- [x] `src/rag/planner.py` — RAG retrieval planning
- [x] Citation confidence metadata on RAG responses (source URL + chunk ref in response)
- [x] Generator-critic pass wired into RAG query path (auto-improve answer quality)
- [x] Answer calibration (model confidence vs retrieval confidence reconciliation)
- [x] RAG result caching (identical queries skip re-embedding)
- [x] Chunk overlap deduplication on ingest
- [x] Incremental ingest (update existing doc without full re-index)
- [x] RAG corpus versioning (snapshot + rollback via `/rag/snapshots`)

### 5.3 Document understanding

- [x] `POST /documents/ingest` — upload + parse document
- [x] `POST /documents/understand` — document Q&A with LLM
- [x] `tool_read_pdf` — PDF text extraction
- [x] `tool_read_docx` — Word document extraction
- [x] `tool_read_xlsx` — Excel extraction
- [x] `tool_read_pptx` — PowerPoint extraction
- [x] `tool_read_csv` / `tool_write_csv` — CSV tools
- [x] Vision-based PDF understanding (scanned PDFs via OCR + vision model fallback path)
- [x] Table extraction from PDFs (structure-aware parsing)
- [x] Form field extraction (structured data from PDF forms)
- [x] Document comparison / diff tool (`POST /diff`, `GET /diff/history`, `GET /diff/{id}`)

---

## 6. Tools and Actions

### 6.1 Utility tools

- [ ] `get_time` — current date/time
- [ ] `calculate` — safe math expression evaluator
- [ ] `weather` — current weather by location
- [ ] `currency` — currency conversion
- [ ] `convert` — unit conversion (length, weight, temp, etc.)
- [ ] `regex` — regex match / extract
- [ ] `base64` — encode / decode
- [ ] `json_format` — pretty-print and validate JSON
- [ ] `nexus_status` — Nexus system status
- [ ] `hash` — hash a string (SHA-256 / MD5 / bcrypt)
- [ ] `uuid` — generate UUIDs
- [ ] `qr_code` — generate QR code image
- [ ] `csv_to_json` / `json_to_csv` — format conversion
- [ ] `xml_parse` — parse XML to dict
- [ ] `url_encode` / `url_decode`
- [ ] `jwt_decode` — inspect JWT payload (no validation, read-only)
- [ ] `color_convert` — hex / rgb / hsl conversion

### 6.2 File and repo tools

- [ ] `write_file` — write file to working directory
- [ ] `read_file` — read file from working directory
- [ ] `list_files` — list directory contents
- [ ] `delete_file` — delete file
- [ ] `clone_repo` — git clone
- [ ] `run_command` — sandboxed shell command execution
- [ ] `commit_push` — git commit and push
- [ ] `create_repo` — create GitHub repo
- [ ] Dynamic repo targeting from chat intent
- [ ] GitHub token redaction before LLM forwarding
- [ ] `tool_diff` — unified diff between two strings
- [ ] `move_file` / `copy_file` — file management operations
- [ ] `search_in_files` — grep / regex search across files in workdir (Audit 2026-04-17: No code backing found)
- [ ] `create_directory` — mkdir (Audit 2026-04-17: No code backing found)
- [ ] `zip_files` / `unzip_files` — archive management (Audit 2026-04-17: No code backing found)
- [ ] `git_status` — show uncommitted changes (Audit 2026-04-17: No code backing found)
- [ ] `git_log` — recent commit history (Audit 2026-04-17: No code backing found)
- [ ] `git_diff` — diff against HEAD or branch (Audit 2026-04-17: No code backing found)
- [ ] `git_checkout` — branch management (Audit 2026-04-17: No code backing found)
- [ ] `git_pull` — pull latest changes (Audit 2026-04-17: No code backing found)
- [ ] `create_pull_request` — open GitHub PR (Audit 2026-04-17: No code backing found)
- [ ] `list_issues` / `create_issue` — GitHub issue management (Audit 2026-04-17: No code backing found)

### 6.3 Web and network tools

- [ ] `tool_read_page` — fetch URL and extract text
- [ ] `tool_api_call` — generic authenticated HTTP request
- [ ] `tool_youtube_transcript` — get YouTube transcript
- [ ] `tool_youtube` — YouTube summary
- [ ] `web_search` — structured web search with citations (Brave / SerpAPI / DuckDuckGo) (Audit 2026-04-17: No code backing found)
- [~] `screenshot_capture` — headless browser screenshot — Pointers: route=`n/a`; tool=`screenshot` (`src/tools_builtin.py` registry + `tool_screenshot`); module=`src/tools_builtin.py:tool_screenshot` (stub).
- [x] `screenshot_capture` — headless browser screenshot — Pointers: route=`n/a`; tool=`screenshot` (`src/tools_builtin.py` registry + `tool_screenshot`); module=`src/vision.py:capture_screenshot`.
- [ ] `web_scrape_structured` — extract structured data from page (CSS selectors)
- [ ] `rss_fetch` — fetch and parse RSS / Atom feed
- [ ] `sitemap_crawl` — discover URLs from sitemap.xml
- [ ] `check_url_status` — HTTP status check (uptime monitor)

### 6.4 Media and generation tools

- [ ] `generate_image` — Pollinations image generation (Audit 2026-04-17: No code backing found)
- [~] `generate_image_local` — local Flux / SD3 image generation via Ollama — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); tool=`generate_image_local` (`src/tools_builtin.py`); module=`src/generation.py:generate_image_local` (stub).
- [x] `generate_image_local` — local Flux / SD3 image generation via Ollama — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); tool=`generate_image_local` (`src/tools_builtin.py`); module=`src/generation.py:generate_image_local`.
- [~] `generate_video` — local video generation — Pointers: route=`POST /generation/video` (`src/api/routes.py`); tool=`generate_video` (`src/tools_builtin.py`); module=`src/generation.py:generate_video` (stub).
- [x] `generate_video` — local video generation — Pointers: route=`POST /generation/video` (`src/api/routes.py`); tool=`generate_video` (`src/tools_builtin.py`); module=`src/generation.py:generate_video`.
- [~] `Nexus Tunnel integration` (Nexus Systems #80) — Pointers: route=`POST /integrations/tunnel` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:connect_tunnel` (mock implementation, pending WS backend).
- [~] `Nexus Tunnel integration` (Nexus Systems #80) — Pointers: route=`POST /integrations/tunnel` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:connect_tunnel` (functional, returns mocked tunnel URLs).
- [~] `Nexus Guardian integration` — Pointers: route=`POST /integrations/guardian` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_with_guardian` (mock implementation, pending API backend).
- [~] `Nexus Guardian integration` — Pointers: route=`POST /integrations/guardian` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_with_guardian` (functional, returns mocked instance IDs).
- [~] `Nexus Edge integration` — Pointers: route=`POST /integrations/edge` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_edge_node` (mock implementation, pending orchestrator backend).
- [~] `Nexus Edge integration` — Pointers: route=`POST /integrations/edge` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_edge_node` (functional, returns mocked node IDs).
- [x] `screenshot_to_text` — OCR a screenshot image — Pointers: route=`n/a`; tool=`ocr` (`src/tools_builtin.py` registry + `tool_ocr`); module=`src/vision.py:ocr_image_bytes` delegated from `src/tools_builtin.py:tool_ocr`.
- [x] `image_describe` — vision model image description — Pointers: route=`POST /vision/understand` (`src/api/routes.py`); tool=`vision_understand` (`src/tools_builtin.py` registry + `tool_vision_understand`); module=`src/vision.py:describe_image` delegated from `src/tools_builtin.py:tool_vision_understand`.
- [x] `image_edit` — inpaint / edit image with prompt
- [x] `audio_transcribe` — STT (Whisper local or API) — Pointers: route=`POST /v1/audio/transcriptions` (`src/api/routes.py`); tool=`stt` (`src/tools_builtin.py` registry + `tool_stt`); module=`src/audio.py:transcribe_audio`.
- [x] `text_to_speech` — TTS (local Kokoro / Coqui or API) — Pointers: route=`POST /v1/audio/speech` (`src/api/routes.py`); tool=`tts` (`src/tools_builtin.py` registry + `tool_tts`); module=`src/audio.py:synthesize_speech`.
- [x] `audio_analyse` — sentiment / diarization / tone on audio — Pointers: route=`POST /audio/analyse` (`src/api/routes.py`); tool=`audio_analyse` (`src/tools_builtin.py` registry + `tool_audio_analyse`); module=`src/audio.py:analyse_audio`.

### 6.5 Database tools

- [ ] `tool_query_db` — run SQL query on external DB
- [ ] `tool_inspect_db` — introspect external DB schema
- [ ] `tool_sqlite_query` — query Nexus's own SQLite database
- [ ] `tool_pg_query` — PostgreSQL-specific query with type safety
- [ ] `tool_db_migrate` — apply migration string against a connection

### 6.6 Scheduler tools

- [ ] `tool_cron_schedule` — schedule a recurring agent task
- [ ] `tool_cron_list` — list scheduled jobs
- [ ] `tool_cron_cancel` — cancel a scheduled job
- [ ] `GET /scheduler/jobs` — list jobs via API
- [ ] `POST /scheduler/jobs` — create job via API
- [ ] `POST /scheduler/jobs/{job_id}/cancel` — cancel job via API
- [ ] Cron expression validator (validate before saving)
- [ ] Job history log (past executions + results)
- [ ] Webhook-triggered job (trigger by external POST)
- [ ] Job retry policy (max retries + backoff)

### 6.7 Tool safety and approval

- [ ] `src/approvals.py` — HITL approval system
- [ ] `GET /approvals` — list pending approvals
- [ ] `POST /approvals/{approval_id}` — approve or reject
- [ ] `GET /settings/hitl` — HITL settings
- [ ] `POST /settings/hitl` — update HITL settings
- [ ] High-risk action approval mode (log / warn / block)
- [ ] App path protection (write / delete / run_command sandbox)
- [ ] Sandboxed command limits (RAM / CPU / timeout)
- [ ] Tool call audit log (persisted, queryable)
- [ ] Tool call rate limiting (per tool per session)
- [ ] Tool argument schema registry (all tools have validated arg contracts) (Audit 2026-04-17: No code backing found)
- [x] Parallel tool execution risk assessment before fan-out — Pointers: route=`POST /agent`, `POST /agent/stream` (`src/api/routes.py`); tool=`n/a` (policy gating occurs before tool dispatch); module=`src/agent.py:_preflight_parallel_tool_batch`, `src/agent.py:_PARALLEL_SAFE_TOOL_ACTIONS`, `src/agent.py:_execute_parallel_tool_call` (`screen_tool_action`).

---

## 7. Safety and Guardrails

### 7.1 Safety pipeline

- [ ] `src/safety_pipeline.py` — input/output safety pipeline
- [ ] `src/safety_types.py` — typed safety verdict model
- [ ] `src/safety.py` — safety rule engine
- [ ] `src/safety_middleware.py` — FastAPI middleware
- [ ] `POST /safety/check` — run safety check on content
- [ ] `POST /safety/action-check` — check if action is safe
- [x] `POST /safety/pii-scan` — PII detection
- [x] `POST /safety/prompt-injection` — prompt injection detection
- [ ] `GET /safety/domain-guards` — domain guard rules
- [ ] `POST /settings/domain-guards` — update domain guards
- [ ] `GET /safety/profiles` — safety profile list
- [ ] `GET /safety/audit` — safety decision audit log
- [ ] `GET /settings/safety` — read safety config
- [ ] `POST /settings/safety` — update safety config
- [ ] PII redaction (actual masking in output via `scrub_pii_text()` / `screen_output()`; redacts SSN, email, phone, credit card, IP)
- [ ] Toxic content classifier (LLM-based, not just rule-based)
- [ ] Output filter for unsafe completions (post-generation scan via `screen_output()` + `UNSAFE_OUTPUT_PATTERNS`; blocks DAN/jailbreak confirmations)
- [ ] Jailbreak / adversarial prompt pattern library (35 patterns: DAN, developer mode, persona hijack, delimiter injection, system-prompt extraction, encoding relay)
- [ ] Safety decision explanation in API response (`reason` field)
- [ ] Safety event webhook (push safety events to external SIEM)
- [ ] GDPR/CCPA data deletion request handler

### 7.2 Adaptive routing settings

- [ ] `GET /settings/adaptive-routing`
- [ ] `POST /settings/adaptive-routing`

---

## 8. Personas and Customization

### 8.1 Persona system

- [ ] `src/personas.py` — persona registry
- [ ] General persona
- [ ] Coder persona
- [ ] Researcher persona
- [ ] Creative persona
- [ ] Nexus Prime Cloud persona
- [ ] `GET /personas` — list personas
- [ ] `POST /personas/{persona_id}` — set active persona
- [ ] `GET /personas/custom` — list custom personas
- [ ] `POST /personas/custom` — create custom persona
- [ ] `DELETE /personas/custom/{pid}` — delete custom persona
- [ ] Persona export / import (portable JSON)
- [ ] Persona temperature and model tier override per persona
- [ ] Persona-level CSS variable theming (visual identity per persona)
- [ ] Persona capability restrictions (limit which tools a persona can call)
- [ ] Analyst persona (data analysis + chart generation focus)
- [ ] DevOps persona (infra, CI/CD, Docker focus)
- [ ] Legal persona (contract review, clause extraction focus)
- [ ] Medical persona (medical literature search, disclaimer-aware)
- [ ] Teacher persona (Socratic, explain-to-learner style)

### 8.2 System instructions

- [ ] `GET /instructions` — read system instructions
- [ ] `POST /instructions` — update system instructions
- [ ] Per-project instruction sets (different instructions per project context)
- [ ] Instruction versioning (history of instruction changes)

### 8.3 User preferences

- [ ] `GET /prefs` — read user preferences
- [ ] `POST /prefs` — update user preferences
- [ ] Dark / light theme toggle
- [ ] Font size preference
- [ ] Keyboard shortcuts
- [ ] Language / locale preference
- [ ] Response verbosity setting (brief / balanced / detailed)
- [ ] Code block syntax theme preference
- [ ] Notification preferences (browser push for long-running tasks)

---

## 9. Projects, Chats, and Session Management

### 9.1 Chat management

- [ ] `GET /chats` — list chats
- [ ] `POST /chats` — create chat
- [ ] `GET /chats/{cid}` — get chat
- [ ] `DELETE /chats/{cid}` — delete chat
- [ ] `GET /chats/{cid}/export` — export as markdown
- [ ] `POST /chats/{cid}/share` — create share link
- [ ] `GET /share/{share_id}` — read shared chat
- [ ] `GET /chats/search` — full-text search over chats
- [ ] `POST /chats/{cid}/pin` — pin chat
- [ ] `DELETE /chats/{cid}/pin` — unpin chat
- [ ] `GET /chats/pinned` — list pinned chats
- [ ] Auto title generation from first message
- [ ] Chat rename (manual title edit endpoint)
- [ ] Chat archive (soft-delete / hide without permanent delete)
- [ ] Bulk chat delete
- [ ] Chat import (restore from exported markdown)
- [ ] Share link expiry / revoke
- [ ] Public share password protection

### 9.2 Projects

- [ ] `GET /projects` — list projects
- [ ] `POST /projects` — create project
- [ ] `GET /projects/{pid}` — get project
- [ ] `DELETE /projects/{pid}` — delete project
- [ ] `POST /projects/{pid}/chats/{cid}` — attach chat to project
- [ ] `GET /projects/{pid}/chats` — list project chats
- [ ] `GET /projects/{pid}/context` — get project context
- [ ] `POST /projects/{pid}/sessions` — create project session
- [ ] `POST /projects/{pid}/context` — update project context
- [ ] Project rename endpoint
- [ ] Project-level memory namespace (all chats in project share memory)
- [ ] Project-level tool restrictions
- [ ] Project collaborators (share project with other users)
- [ ] Project export bundle (chats + context + memory as one archive)

---

## 10. Multi-Agent System

### 10.1 Specialist agent registry

- [ ] `src/agents/registry.py` — specialist agent definitions
- [ ] Architect Agent
- [ ] Security Auditor Agent
- [ ] UI/UX Designer Agent
- [ ] Data Scientist Agent
- [ ] Legal / Compliance Agent
- [ ] Product Manager Agent
- [ ] Debugger Agent
- [ ] Documentation Agent
- [ ] DevOps / Infrastructure Agent
- [ ] QA / Testing Agent
- [ ] Marketing / Copy Agent
- [ ] Finance / Budget Analyst Agent
- [ ] Research Scientist Agent
- [ ] Accessibility Auditor Agent

### 10.2 Agent communication bus

- [ ] `src/agent_bus.py` — inter-agent message bus
- [ ] `GET /agents/bus/log` — message bus log
- [ ] `GET /agents/bus/{agent_id}` — messages for agent
- [ ] `POST /agents/bus` — publish message to bus
- [ ] Bus persistence (messages survive restart)
- [ ] Bus topic filtering (subscribe to specific event types)
- [ ] Dead-letter queue for failed agent messages

### 10.3 Agent marketplace

- [ ] `GET /marketplace/agents` — list marketplace agents
- [ ] `POST /marketplace/agents` — publish agent to marketplace
- [ ] `DELETE /marketplace/agents/{agent_id}` — remove from marketplace
- [ ] Agent import from marketplace URL
- [ ] Agent version history in marketplace
- [ ] Agent rating / review system
- [ ] Private marketplace (org-scoped agent sharing)

### 10.4 Swarm / Swarm view

- [ ] `GET /swarm/activity` — live swarm activity feed
- [ ] Swarm View UI (visual real-time agent activity graph in browser)
- [ ] Swarm task assignment UI
- [ ] Swarm health dashboard (which agents are idle / busy / errored)
- [ ] Swarm pause / resume controls

### 10.5 Architecture blueprints

- [ ] `src/architecture/hierarchy.py` — agent hierarchy model
- [ ] `GET /architecture/hierarchy` — hierarchy structure
- [ ] `POST /architecture/blueprints` — create blueprint
- [ ] `GET /architecture/blueprints` — list blueprints
- [ ] `GET /architecture/blueprints/{name}` — get blueprint
- [ ] `GET /architecture/registry/{name}` — agent registry entry
- [ ] Blueprint validation (schema check before save)
- [ ] Blueprint execution (spawn agents from blueprint definition)
- [ ] Blueprint export / import (portable JSON)

---

## 11. Multimodal Features

### 11.1 Vision

- [ ] Vision model routing (detect image in request → route to vision-capable provider)
- [ ] Image input in `/v1/chat/completions` (base64 + URL formats)
- [ ] Image input in `/agent` and `/agent/stream`
- [ ] Local vision model support via Ollama (LLaVA / Qwen-VL / Llama 4 Vision)
- [x] Image analysis tool (`image_describe`) — Pointers: route=`POST /vision/understand` (`src/api/routes.py`); tool=`vision_understand` (`src/tools_builtin.py`); module=`src/vision.py:describe_image` delegated from `src/tools_builtin.py:tool_vision_understand`.
- [~] Screenshot capture tool (headless browser) — Pointers: route=`n/a`; tool=`screenshot` (`src/tools_builtin.py`); module=`src/tools_builtin.py:tool_screenshot` (stub).
- [x] OCR tool (extract text from image) — Pointers: route=`n/a`; tool=`ocr` (`src/tools_builtin.py`); module=`src/vision.py:ocr_image_bytes` delegated from `src/tools_builtin.py:tool_ocr`.

### 11.2 Image generation

- [ ] `generate_image` tool — Pollinations (cloud) (Audit 2026-04-17: No code backing found)
- [~] Local image generation — Flux / SD3 via Ollama or ComfyUI — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); tool=`generate_image_local` (`src/tools_builtin.py`); module=`src/generation.py:generate_image_local` (stub).
- [x] Image editing / inpainting tool
- [x] Image-to-image (style transfer) tool
- [ ] Generated image persistence (save to workdir, return URL)

### 11.3 Audio

- [ ] Voice input in UI (Web Speech API — browser-side) (Audit 2026-04-17: No code backing found)
- [x] STT tool (`audio_transcribe`) — Whisper local or API — Pointers: route=`POST /v1/audio/transcriptions` (`src/api/routes.py`); tool=`stt` (`src/tools_builtin.py`); module=`src/audio.py:transcribe_audio`.
- [x] TTS tool (`text_to_speech`) — Kokoro / Coqui local or API — Pointers: route=`POST /v1/audio/speech` (`src/api/routes.py`); tool=`tts` (`src/tools_builtin.py`); module=`src/audio.py:synthesize_speech`.
- [ ] `POST /v1/audio/transcriptions` — OpenAI-compatible STT
- [ ] `POST /v1/audio/speech` — OpenAI-compatible TTS (Audit 2026-04-17: No code backing found)
- [x] Audio analysis tool (sentiment / diarization / speaker ID) — Pointers: route=`POST /audio/analyse` (`src/api/routes.py`); tool=`audio_analyse` (`src/tools_builtin.py`); module=`src/audio.py:analyse_audio`.
- [ ] Podcast / meeting transcript ingestion pipeline

### 11.4 Video

- [ ] YouTube summarization wired to LLM (transcript → summary, currently tool returns raw transcript)
- [~] Local video generation tool — Pointers: route=`POST /generation/video` (`src/api/routes.py`); tool=`generate_video` (`src/tools_builtin.py`); module=`src/generation.py:generate_video` (stub).
- [x] Video-to-text (frame sampling + vision description)
- [x] Video chapter detection

---

## 12. Fine-tuning and Sovereign Model (Nexus Prime)

### 12.1 Training data pipeline

- [ ] Per-message feedback stored as training signal (`POST /feedback/{chat_id}/{message_idx}`)
- [ ] `GET /feedback/export` — export feedback dataset
- [ ] `GET /feedback/stats` — feedback statistics
- [ ] Opt-in interaction trace collection (GDPR-compliant)
- [ ] Synthetic training data generation tool (agent swarm → instruction pairs)
- [ ] Data curation UI (label, filter, approve training samples)
- [ ] Dataset versioning and provenance tracking
- [ ] Training data export in Alpaca / ShareGPT / JSONL formats

### 12.2 LoRA / fine-tuning harness

- [ ] LoRA fine-tuning job endpoint (`POST /finetune/jobs`) — creates persisted job with status 'queued'
- [ ] Fine-tuning job status (`GET /finetune/jobs/{job_id}`) — returns job record or 404
- [ ] Fine-tuning job cancel (`DELETE /finetune/jobs/{job_id}`) — cancels queued/running job, 404 if missing
- [ ] LoRA adapter versioning (store + compare adapter checkpoints)
- [ ] LoRA adapter hot-swap at inference (apply adapter to Ollama base)
- [ ] One-click fine-tune on collected feedback data
- [ ] RLHF / DPO pipeline integration
- [ ] Continual fine-tuning scheduler (weekly re-tune if benchmarks improve)

### 12.3 Nexus Prime model

- [ ] Nexus Prime Alpha persona wired to fine-tuned Ollama model
- [x] Automated eval suite (benchmark vs base model on code / autonomy / RAG)
- [ ] Model card and transparency report endpoint
- [ ] Multi-task LoRA adapters (coding / reasoning / research / creative) hot-swap
- [ ] Multimodal fine-tuning extension (vision capability)
- [ ] Knowledge distillation pipeline (teacher: Claude/GPT → student: Nexus Prime)

---

## 13. Benchmarking

- [ ] `POST /benchmark/run` — run model benchmark suite
- [ ] `GET /benchmark/results` — retrieve benchmark results
- [ ] Per-model benchmark history (track quality over time)
- [ ] Benchmark leaderboard endpoint (sorted by task type)
- [x] Automated regression benchmark on model update
- [ ] Public leaderboard page in UI

---

## 14. Observability and Telemetry

### 14.1 Usage and cost

- [ ] `GET /usage` — token / cost usage summary
- [ ] Cost tracking for paid providers
- [ ] Usage records written per request
- [ ] Per-user usage breakdown
- [ ] Cost forecasting (project spend based on usage trend)
- [ ] Usage export (CSV / JSON)
- [ ] Usage webhook (push daily summary to external endpoint)

### 14.2 Execution traces

- [ ] `src/execution_trace.py` — replayable trace store
- [ ] `GET /tasks/{trace_id}/replay` — deterministic trace replay
- [ ] Trace search (find traces by tool used / agent / error type)
- [ ] Trace export (portable JSON)
- [ ] Trace diff (compare two runs of same task)
- [ ] Anomaly detection on traces (flag unusual execution patterns)

### 14.3 Structured logging

- [ ] Safety audit log (`GET /safety/audit`)
- [ ] Agent bus log (`GET /agents/bus/log`)
- [ ] Structured JSON application log (all requests + responses)
- [ ] OpenTelemetry tracing export
- [ ] Prometheus metrics endpoint (`GET /metrics`)
- [ ] Log forwarding to external sink (Loki / Datadog / CloudWatch)

---

## 15. Frontend / PWA

### 15.1 Chat UI

- [ ] Streaming SSE word-by-word typewriter
- [ ] Stop button (cancel mid-stream)
- [ ] Markdown rendering
- [ ] Syntax-highlighted code blocks
- [ ] Inline artifact renderer (HTML / SVG)
- [ ] Inline image bubbles
- [ ] Multi-file artifact tabs
- [ ] Code viewer for file ops
- [ ] Resizable split view
- [ ] Message reactions
- [ ] Live confidence / reasoning trace badge
- [ ] Streaming token counter
- [ ] Code execution in UI (run Python / JS in sandboxed iframe)
- [ ] Chart / graph artifact renderer (Plotly / Chart.js output)
- [ ] Mermaid diagram renderer
- [ ] LaTeX / math equation renderer
- [ ] Message edit + re-run
- [ ] Message branch (fork conversation from earlier message)
- [ ] Message copy-as-markdown button
- [ ] Image paste input (paste clipboard image into chat)

### 15.2 Agent console and swarm view

- [ ] Swarm View UI (real-time agent graph visualization)
- [ ] Agent Console (watch tool calls and events live in a panel)
- [ ] Task progress panel (current subtask list with status)
- [ ] Agent output diff viewer (compare before/after file changes)
- [ ] Diff viewer for file edits (backend `POST /diff` exists)

### 15.3 Settings and dashboards

- [ ] Provider status drawer with cooldown timers
- [ ] Settings panel (provider / model / temp overrides)
- [ ] Multi-user admin dashboard (usage / costs / agent activity per user)
- [x] Command palette (Cmd+K for everything) — Pointers: route=`n/a`; tool=`n/a`; module=`static/js/utilities/search-command.js:openCommandPalette`, `static/js/utilities/search-command.js:_personaCommands`, `static/index.html` (Cmd+K key handlers + script include).
- [ ] Model benchmark dashboard UI
- [ ] Fine-tuning job dashboard
- [ ] RAG corpus browser (list, search, delete ingested docs)
- [ ] KG visualization panel

### 15.4 PWA and mobile

- [ ] Installable PWA (manifest + service worker)
- [ ] Mobile sidebar swipe gestures
- [ ] Haptic feedback
- [ ] Safe-area inset support
- [ ] 44px touch targets
- [ ] Dark / light theme toggle
- [ ] Font size preference
- [ ] Keyboard shortcuts (new chat / sidebar / stop)
- [ ] Offline mode (serve cached UI without backend)
- [ ] Push notifications for long-running task completion
- [ ] Desktop Electron wrapper
- [ ] Mobile native app (React Native or Capacitor)

---

## 16. Webhook and External Integrations

- [ ] `POST /webhook/trigger` — external trigger
- [ ] `GET /webhook/status/{run_id}` — run status
- [ ] Webhook payload signature verification (HMAC)
- [ ] Webhook delivery retry with exponential backoff
- [ ] Webhook event type filtering (only trigger on specific events)
- [ ] Slack integration (receive messages, send responses)
- [ ] Discord bot integration
- [ ] GitHub Actions integration (trigger on PR / push)
- [ ] Zapier / Make.com webhook connector
- [ ] MCP server mode (expose Nexus tools to external MCP clients)
- [ ] MCP tool consumption via `MCP_TOOLS` env (Nexus as MCP client)

---

## 17. Gist Backup and External Storage

- [ ] `src/gist_backup.py` — GitHub Gist backup
- [ ] S3 / R2 chat backup integration
- [ ] Export to Notion / Obsidian
- [ ] Restore from backup endpoint

---

## 18. Enterprise and Ecosystem (Phase 5 / Future)

- [~] Nexus Tunnel integration (Nexus Systems #80) — Pointers: route=`POST /integrations/tunnel` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:connect_tunnel` (stub).
- [~] Nexus Guardian integration — Pointers: route=`POST /integrations/guardian` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_with_guardian` (stub).
- [~] Nexus Edge integration — Pointers: route=`POST /integrations/edge` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_edge_node` (stub).
- [ ] Nexus Systems API passthrough
- [ ] Nexus AI Hub (multi-instance management)
- [ ] Nexus Blueprint export (portable agent workflow archive)
- [ ] Open-source model leaderboard page
- [~] Real-time collaboration (multi-human + multi-agent on same session) — Pointers: route=`POST /collab/rooms`, `GET /collab/rooms`, `GET /collab/rooms/{room_id}`, `DELETE /collab/rooms/{room_id}` (`src/api/routes.py`); tool=`n/a`; module=`src/collab.py:create_room`, `src/collab.py:join_room`, `src/collab.py:close_room` (stubs).
- [~] Real-time collaboration (multi-human + multi-agent on same session) — Pointers: route=`POST /collab/rooms`, `GET /collab/rooms`, `GET /collab/rooms/{room_id}`, `DELETE /collab/rooms/{room_id}` (`src/api/routes.py`); tool=`n/a`; module=`src/collab.py:create_room`, `src/collab.py:join_room`, `src/collab.py:close_room` (in-memory implementation, pending DB/WS).
- [x] Screenshot capture tool (headless browser) — Pointers: route=`n/a`; tool=`screenshot` (`src/tools_builtin.py`); module=`src/vision.py:capture_screenshot`.
- [x] Local image generation — Flux / SD3 via Ollama or ComfyUI — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); tool=`generate_image_local` (`src/tools_builtin.py`); module=`src/generation.py:generate_image_local`.
- [x] Audio analysis tool (sentiment / diarization / speaker ID) — Pointers: route=`POST /audio/analyse` (`src/api/routes.py`); tool=`audio_analyse` (`src/tools_builtin.py`); module=`src/audio.py:analyse_audio`.
- [x] Local video generation tool — Pointers: route=`POST /generation/video` (`src/api/routes.py`); tool=`generate_video` (`src/tools_builtin.py`); module=`src/generation.py:generate_video`.
- [ ] Federated learning module (local gradient contribution without raw data sharing)
- [x] User-contributed compute network (idle GPU opt-in)

---

## 19. Continuous Learning and Self-Improvement

- [ ] Self-improvement loop (`POST /agent/self-review`)
- [ ] Self-review history
- [ ] Per-message feedback as training signal
- [ ] Automated self-correction on low-confidence outputs
- [ ] Drift detection (flag when output quality degrades from baseline)
- [ ] Architecture drift monitoring (compare code against ARCHITECTURE.md intent)
- [ ] Weekly quality regression benchmark (auto-run on schedule)
- [ ] Self-generating test cases from production interactions

---

## Summary Counts

| Status | Count (approx)       |
|--------|----------------------|
| `[x]` Fully implemented | 189 |
| `[~]` Stub / partial    | 18  |
| `[ ]` Not yet started   | 401 |

> This document is the single source of truth for feature completeness tracking.
> Update it whenever a feature is started (`[~]`) or completed (`[x]`).
> Do **not** remove `[ ]` items — they represent deliberate scope.
