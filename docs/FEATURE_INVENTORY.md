# Nexus AI — Complete Feature Inventory

> **Purpose:** Ground-truth map of every feature Nexus AI has, partially has, or needs.
> A feature is anything that makes the system behave differently — even a single guard clause.
> Legend: `[x]` = fully implemented and production ready | `[~]` = implemented but partial / stub / mock / non-persistent | `[ ]` = not yet started

---

## How to read this document

Each section maps to an architectural layer: from deepest backend to public-facing UI.
Sub-items are individual features, not phases or themes.
When a feature moves from `[ ]` → `[~]` → `[x]`, update the mark here.

### Taxonomy standard (L1/L2/L3)

- Level 1 (`##`): capability domains (stable backbone; keep current 19 domains unless architecture truly changes).
- Level 2 (`###`): subdomains inside each capability domain.
- Level 3 (list items): concrete features/controls with maturity status (`[ ]`, `[~]`, `[x]`) and implementation pointers.
- Minimum depth policy: each Level 1 domain should maintain at least 2-4 Level 2 subdomains.
- Inventory entries must remain factual and evidence-backed (endpoint, module, test, or runtime behavior).

### Cross-cutting subdomain checklist (apply per Level 1 domain)

- Security and compliance
- Reliability and SLOs
- Cost and performance
- Observability and auditability
- UX and accessibility

If a cross-cutting area is not applicable to a domain, add one explicit item documenting why it is intentionally out of scope.

### Feature metadata tag schema (Level 3)

Use this compact tag block for new or high-risk entries when helpful:

```markdown
- [x] Example feature name — Tags: owner=platform, priority=p1, risk=medium, stage=GA, deps=redis+postgres, validate=tests/test_v1_contracts.py::test_example|GET /example|src/example.py
```

Tag definitions:

- `owner`: accountable team/agent for lifecycle ownership.
- `priority`: execution priority (`p0`, `p1`, `p2`, `p3`).
- `risk`: delivery or operational risk (`low`, `medium`, `high`).
- `deps`: critical dependencies required for correctness.
- `validate`: validation source(s), such as tests, endpoint contract, module path.
- `stage`: release stage (`experimental`, `beta`, `GA`).

### Inventory truth vs roadmap intent

- Inventory document (`docs/FEATURE_INVENTORY.md`): factual implementation truth and current maturity only.
- Roadmap documents (`docs/ROADMAP*.md`): planned sequencing, future intent, and prioritization.
- Do not mark future intent as implemented in this file; keep planned work in roadmap artifacts until delivered.

---

harden these to full production level:

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
- [x] Deep health check endpoint (`GET /health/deep`) — verifies DB connectivity, vector store, provider reachability; used as K8s readiness probe
- [x] Liveness probe separation (`GET /health/live`) — lightweight heartbeat only, no dependency checks; used as K8s liveness probe
- [x] Graceful shutdown with in-flight request draining (SIGTERM handler waits for active requests before exit; prevents mid-stream connection drops)
- [x] Backpressure signaling (reject requests with 503 when worker queue depth exceeds configurable threshold)
- [x] Zero-downtime rolling deployment compatibility (session state moved to Redis; online_ddl.py runs idempotent ADD COLUMN IF NOT EXISTS + CREATE INDEX CONCURRENTLY at startup; no in-memory state required for cold start)

### 1.2 Database / persistence

- [x] SQLite default backend (`src/db.py`)
- [x] PostgreSQL backend via `DATABASE_URL` env switch
- [x] Chat history table (create / read / delete)
- [x] Usage records table (token counts, cost)
- [x] User accounts table (with `role` column + migration)
- [x] Alembic-compatible schema (manual migration handling) (`migrations/env.py`, `alembic.ini`)
- [x] Alembic migration files (tracked, runnable migrations) (`migrations/versions/0001_initial_schema.py`)
- [x] Native SQLite introspection helper (`tool_inspect_sqlite` / `tool_query_sqlite` are exposed through dedicated built-in `inspect_sqlite` / `sqlite_query` dispatch actions in `src/tools_builtin.py`)
- [x] Native PostgreSQL introspection helper (`tool_inspect_postgres` is exposed through the dedicated built-in `inspect_postgres` dispatch action in `src/tools_builtin.py`)
- [x] Database connection pooling configuration (asyncpg async pool + PgBouncer DSN support via `PGBOUNCER_DSN`; `PG_ASYNC_POOL_MIN`/`PG_ASYNC_POOL_SIZE` env vars; SQLite uses stdlib for single-worker dev)
- [x] Database backup / restore endpoint (`GET /api/backup`, `POST /api/restore`)
- [x] Async-safe connection pool (asyncpg AsyncPgPool in src/db.py; init_async_pool() called from app lifespan; async_pg_query/execute exposed for new high-throughput routes)
- [x] PgBouncer / connection proxy support (PGBOUNCER_DSN env overrides DATABASE_URL; DB_POOL_MODE=session/transaction/statement; statement mode disables prepared statements for pgbouncer compat)
- [x] Zero-downtime schema migrations (src/online_ddl.py: add_column_if_missing, create_index_concurrently, run_pending_migrations; called from app lifespan; all ops idempotent)
- [x] Database backup integrity verification (automated restore-test on backup completion + SHA-256 hash returned in `X-Backup-SHA256` + `X-Backup-Verified` response headers)
- [x] Offsite backup replication (HTTP PUT to `OFFSITE_BACKUP_URL` with SHA-256 header; timestamp-unique backup filenames; retention policy via `OFFSITE_BACKUP_RETENTION_DAYS`; pruning sweep after each successful upload)
- [x] GDPR cascading data deletion (full cascade: DB tables + ChromaDB memory collection + memory JSON store + RAG corpus documents + Redis session/refresh keys; `DELETE /admin/users/{username}/data` and `DELETE /orgs/{org_id}/data`) — Tags: owner=compliance, priority=p0, risk=high, stage=GA, deps=db+auth+privacy, validate=DELETE /admin/users/{username}/data|DELETE /orgs/{org_id}/data

### 1.3 Authentication and multi-user

- [x] JWT-based authentication (`src/auth.py` + routes) — PBKDF2 hashing, HS256 tokens, role-aware — Tags: owner=auth, priority=p0, risk=high, stage=GA, deps=crypto+redis, validate=src/auth.py|tests/test_auth.py
- [x] `POST /auth/register` — create account (first user → admin) — Tags: owner=auth, priority=p0, risk=high, stage=GA, deps=hash+email, validate=POST /auth/register
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
- [x] MFA / TOTP (authenticator app second factor via `pyotp`; `POST /auth/mfa/enroll`, `POST /auth/mfa/verify`, `POST /auth/mfa/disable`) — Tags: owner=auth, priority=p1, risk=high, stage=GA, deps=pyotp+redis, validate=POST /auth/mfa/enroll|POST /auth/mfa/verify
- [x] Backup recovery codes (one-time use codes generated at MFA enroll; `POST /auth/mfa/recovery-codes`)
- [x] WebAuthn / passkey support (py_webauthn; POST /auth/webauthn/register, /register/complete, /authenticate, /authenticate/complete; credentials in webauthn_credentials table; challenge lifecycle via Redis) — Tags: owner=auth, priority=p1, risk=high, stage=GA, deps=webauthn+redis, validate=POST /auth/webauthn/register
- [x] SAML 2.0 enterprise SSO (pysaml2 SP-initiated flow; GET /auth/saml/{provider}/login redirects to IdP; POST /auth/saml/{provider}/acs processes assertion, issues JWT; auto-provisions SAML users) — Tags: owner=auth, priority=p1, risk=high, stage=GA, deps=pysaml2+idp, validate=POST /auth/saml/{provider}/acs
- [x] Session concurrency limits (Redis sorted-set tracks active sessions per user; max N sessions enforced via `MAX_SESSIONS_PER_USER`; oldest sessions revoked first when limit exceeded)
- [x] Trusted device management (remember-device token bound to user agent + IP subnet; skip MFA on trusted devices)
- [x] Brute-force lockout (exponential backoff + account lock after N consecutive failed logins; admin unlock endpoint)
- [x] Suspicious login detection (Redis-backed per-user known device set + last IP; alert only on new device AND new IP subnet combination; _detect_suspicious_login() in routes.py)

### 1.4 Per-user quotas and rate limiting

- [x] Session-level rate limiting (per-minute + per-day sliding windows — Redis-backed atomic counters with in-process fallback; correct across Gunicorn multi-worker)
- [x] `GET /settings/rate-limits` — read rate-limit config
- [x] `POST /settings/rate-limits` — update rate-limit config
- [x] Per-user quota isolation (token budget per user per day via `src/profiles.py` — Redis-backed daily counters with pref-store fallback for cross-worker correctness)
- [x] Per-user spend cap with soft/hard limits (`set_quota()` / `check_quota()` — Redis-backed limits; quota enforced globally across all worker processes)
- [x] Quota overage 429 response with `X-RateLimit-*` headers (Limit, Remaining, Reset, Policy, Retry-After)
- [x] Admin dashboard for quota monitoring (`GET /admin/quota`, `POST /admin/quota/{username}`)
- [x] Quota reset scheduler (daily/weekly) (weekly cron `0 3 * * 0` + stale-key cleanup in `src/api/routes.py`)
- [x] IP-level rate limiting (pre-authentication; blocks DDoS and scraping before any user context exists; request-protection exemptions for frontend bootstrap assets/routes via `src/observability.py:_is_request_protection_exempt` covering `/`, `/static/*`, `/manifest.json`, `/sw.js`, `/favicon.ico`, `/health*`, `/metrics`)
- [x] Concurrent request limiting (max simultaneous in-flight requests per user / API key; prevents single-user queue saturation)
- [x] Redis-backed rate limit counters (atomic cross-worker sliding windows; prerequisite for correctness at scale)

### 1.5 Distributed state and caching

- [x] Redis / Valkey shared state store (single prerequisite that unblocks rate limiting, session state, quotas, pub/sub, and distributed locks across all worker processes)
- [x] Session state in Redis (cross-worker session storage; sessions survive individual worker restarts)
- [x] Distributed rate limit counters in Redis (atomic `INCR` + `EXPIRE` sliding windows for request/quota state; provider cooldowns still use `src/agent.py:_cooldowns`)
- [x] Per-user quota state in Redis (cross-worker token budget enforcement; replaces in-process profile dict)
- [x] Pub/sub channel for SSE stream cancellation (`POST /agent/stop/{stream_id}` broadcasts stop signal to all workers via Redis pub/sub)
- [x] Distributed lock (prevent duplicate task execution when multiple workers pick up the same queued job)
- [x] Response caching layer (Redis TTL cache for repeated identical prompts; configurable TTL + bypass header)
- [x] Cache invalidation API (`DELETE /admin/cache/{cache_key}`, `POST /admin/cache/flush` — admin-only)

### 1.6 Secrets management

- [x] HashiCorp Vault / AWS Secrets Manager integration (provider API keys fetched from Vault at runtime; never stored in `.env` files on disk) — Tags: owner=security, priority=p0, risk=high, stage=GA, deps=vault+network, validate=src/integrations.py|tests/test_secrets.py
- [x] Automatic secret rotation (JWT signing key + provider API keys rotated on configurable schedule without restart; daemon starts at app boot via `SECRET_ROTATION_INTERVAL_SECONDS`) — Tags: owner=security, priority=p0, risk=high, stage=GA, deps=vault+scheduler, validate=src/secrets.py
- [x] Secret access audit trail (every secret fetch logged with caller identity, timestamp, and secret name — no secret values in logs)
- [x] Encrypted environment variable store (at-rest encryption for `.env` file contents when Vault is unavailable)
- [x] Per-request credential injection (decrypted credentials injected into request context only; never persisted to DB or logs)

### 1.7 Observability and structured logging

- [x] Structured JSON application log (every request + response logged as machine-parseable JSON with level, timestamp, module, and trace context)
- [x] `X-Request-ID` / `X-Correlation-ID` propagation (generated on ingress, threaded through all log lines, returned in response headers — enables request tracing across workers and external calls)
- [x] OpenTelemetry distributed tracing export (spans cover: HTTP → agent loop → tool calls → LLM provider → response; exportable to Jaeger / Zipkin / OTLP)
- [x] Prometheus metrics endpoint (`GET /metrics`) — latency histograms per endpoint, error rate counters, queue depth gauge, active SSE stream count, per-provider request counters
- [x] Log forwarding to external sink (Loki / Datadog / CloudWatch via configurable handler)
- [x] Log retention and rotation policy (configurable max log age + size; automatic purge)
- [x] Admin-accessible audit log (`GET /admin/audit-log`) — all privileged actions (role changes, quota overrides, key deletions) with actor + timestamp
- [x] Request/response body logging (AuditBodyLogMiddleware in src/app.py; gated by AUDIT_BODY_LOG=true; PII redaction via regex; sensitive fields scrubbed; response body re-streamed)

### 1.8 Multi-tenancy and org model

- [x] Organization entity (users belong to an org; billing, quotas, and data are scoped to org) — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+db, validate=src/orgs.py|tests/test_orgs.py
- [x] Org creation and management (`POST /orgs`, `GET /orgs/{org_id}`, `DELETE /orgs/{org_id}`)
- [x] Org member management (`GET/POST/DELETE /orgs/{org_id}/members`) — add/remove users, assign org roles
- [x] Org admin role (manage members, view usage, set quotas without superadmin access)
- [x] Org-scoped API keys (org_api_keys table; POST/GET/DELETE /orgs/{org_id}/api-keys; hashes never exposed; scopes array; revocation support; full audit trail)
- [x] Org-level quota and spend cap (aggregate token budget across all members; admin-configurable)
- [x] Per-org data isolation (org-scoped helpers `get_org_chats`, `get_org_usage`, `get_org_memory_entries`, `get_org_rag_documents`; routes `GET /orgs/{id}/chats`, `/orgs/{id}/memory`, `/orgs/{id}/rag/documents`, `POST /orgs/{id}/rag/ingest`; `org_id` metadata tag in vector store and RAG corpus) — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+db+vector, validate=src/orgs.py|GET /orgs/{id}/chats
- [x] Org invite / onboarding flow (`POST /orgs/{org_id}/invite` sends email; `GET /orgs/join/{token}` accepts)
- [x] Org usage dashboard (`GET /orgs/{org_id}/usage`) — member-level breakdown of tokens, cost, and quota with aggregate rollup
- [x] Org export / delete (GET /orgs/{org_id}/export returns portable JSON bundle; DELETE /orgs/{org_id}/data cascades to members/invites/chats; GDPR compliant; audit logged) — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+db+crypto, validate=DELETE /orgs/{org_id}/data

### 1.9 API versioning and lifecycle

- [x] Explicit API version in all routes (`X-API-Version` header emitted per response; entire router mounted at both bare paths (backwards-compat) and `/v1/` prefix via `app.include_router(api_router, prefix="/v1")`; all routes accessible as `/v1/<path>`)
- [x] `Sunset` and `Deprecation` response headers on deprecated endpoints (RFC 8594 compliant — configured in `_DEPRECATED_ENDPOINTS` in `src/app.py`)
- [x] Deprecation notice in `GET /v1/` root response (machine-readable list of deprecated paths + sunset dates)
- [x] API changelog endpoint (`GET /api/changelog`) — structured JSON of version changes
- [x] Version negotiation via `Accept` header (`application/vnd.nexus.v2+json` returns 406 with supported versions until v2 is available)
- [x] Breaking-change detection in CI (OpenAPI `/v1` compatibility gate via `scripts/verify_openapi_contract.py` in `.github/workflows/ci.yml` blocks removed paths/methods/required fields/status codes)

### 1.10 Operational reliability

- [x] Circuit breaker module and admin endpoints (half-open probing and reset/list support exist in `src/circuit_breaker.py` and `/admin/circuit-breakers*`, and provider fallback in `src/agent.py` now honors circuit-breaker state in routing, fallback, and health reporting)
- [x] Feature flags (per-user / per-org targeting, gradual percentage rollout; `GET /admin/flags`, `POST /admin/flags/{flag}`)
- [x] Graceful degradation mode (when all cloud providers exhausted: response cache → local Ollama → structured AllProvidersExhausted error; implemented in `_graceful_degraded_response()` in `src/agent.py`)
- [x] Automatic worker restart on OOM (scripts/oom_watchdog.py monitors /proc/{pid}/status VmRSS; sends SIGTERM to workers over OOM_THRESHOLD_MB; gunicorn master auto-replaces; configurable via OOM_THRESHOLD_MB + OOM_CHECK_INTERVAL env vars)
- [x] Startup dependency wait (container start-up script polls DB and Redis readiness before accepting traffic; prevents crash-loop on slow external service start)
- [x] Background job deduplication (identical queued tasks collapsed via distributed dedup signature + lock in `src/task_queue.py`; optional `dedupe=false` bypass on `POST /tasks/queue`)

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
- [x] Provider priority override per persona — Implementation: `src/agent.py:set_provider_persona_override()` / `get_provider_persona_override()` + `_PERSONA_PROVIDER_OVERRIDES` dict; `_smart_order()` consults override before building final provider list
- [x] Hardware-aware routing (prefer GPU-backed providers over CPU) — Implementation: `src/hardware.py:get_hardware_routing_hint()` probes system resources + GPU detection; `src/agent.py:_smart_order()` imports and calls `get_hardware_routing_hint()`, boosts GPU-favored providers when `has_gpu=True`
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
- [x] `POST /v1/images/generations` (OpenAI-compatible image-generation route backed by shared local/backend generation logic; `generate_image_local` is also registered as a built-in tool) — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); module=`src/generation.py:generate_image_local`.
- [x] `POST /v1/audio/transcriptions` (Whisper-compatible STT route delegates to shared local/provider backends including faster-whisper, Groq Whisper, and OpenAI Whisper)
- [x] `POST /v1/audio/speech` (TTS route delegates to shared local/provider backends including piper, espeak, and OpenAI TTS)
- [x] `GET/POST/DELETE /v1/files` + `GET /v1/files/{id}/content` (OpenAI Files API compatibility)
- [x] `POST/GET /v1/fine-tuning/jobs`, `GET/POST /v1/fine-tuning/jobs/{id}` (persistent OpenAI-compatible fine-tuning lifecycle with background state transitions, cancellation, and durable event history via `GET /v1/fine-tuning/jobs/{id}/events` in `src/api/routes.py` + `src/db.py`)
- [x] OpenAI Structured Outputs schema subset enforcement (`_validate_json_schema_value()` in `src/api/routes.py`)
- [x] DeepSeek `reasoning_content` field normalization (`_call_openai()` extracts and maps to `thought` field)
- [x] Gemini function-call ID mapping for parallel calls (`_call_openai()` maps `tool_calls` IDs to `_tool_calls`)
- [x] Claude `tool_use` / `tool_result` parity lifecycle normalization (`_call_claude_api()` normalizes content blocks)
- [x] Grok async deferred response lifecycle normalization (`_call_grok()` polls `/v1/deferred/` on 202)

### 2.4 Ensemble and consensus routing

- [x] `src/ensemble.py` — consensus engine — Implementation: Complete consensus engine with `score_task_risk()`, `is_high_risk()`, `pick_consensus()`, `call_llm_ensemble()`, `call_llm_consensus()`
- [x] `POST /reason/consensus` — multi-provider consensus vote — Implementation: `src/api/routes.py:@router.post("/reason/consensus")` wraps `call_llm_consensus()` with reconciliation metadata — Tags: owner=reasoning, priority=p1, risk=high, stage=GA, deps=provider_fallback+quorum, validate=POST /reason/consensus
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
- [x] Agent warm-up / pre-loading (keep agent context primed between calls) — `src/agent.py:warmup_agent()` primes LLM context with TTL cache; called at app startup via lifespan; exposed via `POST /agent/warmup`

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
- [x] Checkpointed long-run execution (`src/execution_trace.py`) (live checkpoint persistence now wired into `/autonomy/execute` and `/autonomy/execute/stream` with stepwise snapshots for replay/resume in `src/api/routes.py`) — Tags: owner=autonomy, priority=p1, risk=high, stage=GA, deps=db+state_ledger, validate=POST /autonomy/execute|GET /autonomy/trace/{trace_id}
- [x] `GET /tasks` — task list (live traces merged with DB-backed execution trace persistence in `src/api/routes.py` + `src/db.py`)
- [x] `GET /tasks/{trace_id}` — task detail (in-memory with DB fallback)
- [x] `GET /tasks/{trace_id}/replay` — deterministic trace replay (replays persisted DB traces across sessions)
- [x] `POST /tasks/{trace_id}/resume` — resume interrupted task (new resumed traces persisted to DB for cross-session continuity) — Tags: owner=autonomy, priority=p1, risk=high, stage=GA, deps=db+execution_trace, validate=POST /tasks/{trace_id}/resume
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

- [x] `get_time` — current date/time — Pointers: tool=`get_time`; module=`src/tools_builtin.py:tool_get_time`.
- [x] `calculate` — safe math expression evaluator — Pointers: tool=`calculate`; module=`src/tools_builtin.py:dispatch_builtin` (numexpr/ast_literal_eval).
- [x] `weather` — current weather by location — Pointers: tool=`weather`; module=`src/tools_builtin.py:dispatch_builtin` (wttr.in API).
- [x] `currency` — currency conversion — Pointers: tool=`currency`; module=`src/tools_builtin.py:dispatch_builtin` (exchangerate.host API).
- [x] `convert` — unit conversion (length, weight, temp, etc.) — Pointers: tool=`convert`; module=`src/tools_builtin.py:dispatch_builtin` (pint).
- [x] `regex` — regex match / extract — Pointers: tool=`regex`; module=`src/tools_builtin.py:dispatch_builtin` (stdlib re).
- [x] `base64` — encode / decode — Pointers: tool=`base64`; module=`src/tools_builtin.py:dispatch_builtin`.
- [x] `json_format` — pretty-print and validate JSON — Pointers: tool=`json_format`; module=`src/tools_builtin.py:dispatch_builtin`.
- [x] `nexus_status` — Nexus system status — Pointers: tool=`nexus_status`; module=`src/tools_builtin.py:tool_nexus_status`.
- [x] `hash` — hash a string (SHA-256 / MD5 / bcrypt) — Pointers: tool=`hash`; module=`src/tools_builtin.py:tool_hash`.
- [x] `uuid` — generate UUIDs — Pointers: tool=`uuid`; module=`src/tools_builtin.py:tool_uuid`.
- [x] `qr_code` — generate QR code image — Pointers: tool=`qr_code`; module=`src/tools_builtin.py:tool_qr_code` (qrserver.com API).
- [x] `csv_to_json` / `json_to_csv` — format conversion — Pointers: tool=`csv_to_json`, `json_to_csv`; module=`src/tools_builtin.py:tool_csv_to_json`, `tool_json_to_csv`.
- [x] `xml_parse` — parse XML to dict — Pointers: tool=`xml_parse`; module=`src/tools_builtin.py:tool_xml_parse`.
- [x] `url_encode` / `url_decode` — Pointers: tool=`url_encode`, `url_decode`; module=`src/tools_builtin.py:tool_url_encode`.
- [x] `jwt_decode` — inspect JWT payload (no validation, read-only) — Pointers: tool=`jwt_decode`; module=`src/tools_builtin.py:tool_jwt_decode`.
- [x] `color_convert` — hex / rgb / hsl conversion — Pointers: tool=`color_convert`; module=`src/tools_builtin.py:tool_color_convert`.

### 6.2 File and repo tools

- [x] `write_file` — write file to working directory — Pointers: tool=`write_file`; module=`src/tools_builtin.py:tool_write_file`. — Tags: owner=tools, priority=p1, risk=high, stage=GA, deps=sandbox+path_restrict, validate=src/tools_builtin.py|tests/test_tools_sandbox.py
- [x] `read_file` — read file from working directory — Pointers: tool=`read_file`; module=`src/tools_builtin.py:tool_read_file`.
- [x] `list_files` — list directory contents — Pointers: tool=`list_files`; module=`src/tools_builtin.py:tool_list_files`.
- [x] `delete_file` — delete file — Pointers: tool=`delete_file`; module=`src/tools_builtin.py:tool_delete_file`. — Tags: owner=tools, priority=p1, risk=high, stage=GA, deps=sandbox+path_restrict, validate=src/tools_builtin.py|tests/test_tools_sandbox.py
- [x] `clone_repo` — git clone — Pointers: tool=`clone_repo`; module=`src/tools_builtin.py:tool_clone_repo`.
- [x] `run_command` — sandboxed shell command execution — Pointers: tool=`run_command`; module=`src/tools_builtin.py:tool_run_command` (timeout+allowlist enforcement). — Tags: owner=tools, priority=p0, risk=high, stage=GA, deps=sandbox+limits+allowlist, validate=src/tools_builtin.py|tests/test_tools_sandbox.py
- [x] `commit_push` — git commit and push — Pointers: tool=`commit_push`; module=`src/tools_builtin.py:tool_commit_push`.
- [x] `create_repo` — create GitHub repo — Pointers: tool=`create_repo`; module=`src/tools_builtin.py:tool_create_repo` (gh CLI).
- [x] Dynamic repo targeting from chat intent — Pointers: module=`src/agent.py:extract_token`, `set_session_token`.
- [x] GitHub token redaction before LLM forwarding — Pointers: module=`src/agent.py:_TOKEN_RE` (line 102).
- [x] `tool_diff` — unified diff between two strings — Pointers: tool=`diff`; module=`src/tools_builtin.py:dispatch_builtin` (difflib.unified_diff).
- [x] `move_file` / `copy_file` — file management operations — Pointers: tool=`move_file`, `copy_file`; module=`src/tools_builtin.py:tool_move_file`, `tool_copy_file`.
- [x] `search_in_files` — grep / regex search across files in workdir — Pointers: tool=`search_in_files`; module=`src/tools_builtin.py:tool_search_in_files`.
- [x] `create_directory` — mkdir — Pointers: tool=`create_directory`; module=`src/tools_builtin.py:tool_create_directory`.
- [x] `zip_files` / `unzip_files` — archive management — Pointers: tool=`zip_files`, `unzip_files`; module=`src/tools_builtin.py:tool_zip_files`, `tool_unzip_files`.
- [x] `git_status` — show uncommitted changes — Pointers: tool=`git_status`; module=`src/tools_builtin.py:dispatch_builtin` (gh/git subprocess).
- [x] `git_log` — recent commit history — Pointers: tool=`git_log`; module=`src/tools_builtin.py:dispatch_builtin`.
- [x] `git_diff` — diff against HEAD or branch — Pointers: tool=`git_diff`; module=`src/tools_builtin.py:dispatch_builtin`.
- [x] `git_checkout` — branch management — Pointers: tool=`git_checkout`; module=`src/tools_builtin.py:dispatch_builtin`.
- [x] `git_pull` — pull latest changes — Pointers: tool=`git_pull`; module=`src/tools_builtin.py:dispatch_builtin`.
- [x] `create_pull_request` — open GitHub PR — Pointers: tool=`create_pull_request`; module=`src/tools_builtin.py:dispatch_builtin` (gh CLI).
- [x] `list_issues` / `create_issue` — GitHub issue management — Pointers: tool=`list_issues`, `create_issue`; module=`src/tools_builtin.py:dispatch_builtin` (gh CLI).

### 6.3 Web and network tools

- [x] `tool_read_page` — fetch URL and extract text — Pointers: tool=`read_page`; module=`src/tools_builtin.py:tool_read_page` (httpx + html2text).
- [x] `tool_api_call` — generic authenticated HTTP request — Pointers: tool=`api_call`; module=`src/tools_builtin.py:tool_api_call`.
- [x] `tool_youtube_transcript` — get YouTube transcript — Pointers: tool=`youtube_transcript`; module=`src/tools_builtin.py:tool_youtube_transcript` (yt-dlp).
- [x] `tool_youtube` — `youtube` action now dispatches to the metadata-and-transcript helper in `src/tools_builtin.py:tool_youtube`.
- [x] `web_search` — structured web search with citations (Brave / SerpAPI / DuckDuckGo) — Pointers: tool=`web_search`; module=`src/tools_builtin.py:tool_web_search`.
- [x] `screenshot_capture` — screenshot action uses real headless-browser capture attempts from `src/vision.py:capture_screenshot` and fails explicitly when no capture backend is available.
- [x] `web_scrape_structured` — extract structured data from page (CSS selectors) — Pointers: tool=`web_scrape_structured`; module=`src/tools_builtin.py:tool_web_scrape_structured` (BeautifulSoup).
- [x] `rss_fetch` — fetch and parse RSS / Atom feed — Pointers: tool=`rss_fetch`; module=`src/tools_builtin.py:tool_rss_fetch` (feedparser).
- [x] `sitemap_crawl` — discover URLs from sitemap.xml — Pointers: tool=`sitemap_crawl`; module=`src/tools_builtin.py:tool_sitemap_crawl`.
- [x] `check_url_status` — HTTP status check (uptime monitor) — Pointers: tool=`check_url_status`; module=`src/tools_builtin.py:tool_check_url_status`.

### 6.4 Media and generation tools

- [x] `generate_image` — Pollinations image generation — Pointers: tool=`generate_image`; module=`src/tools_builtin.py:tool_generate_image` (Pollinations.ai, no API key required).
- [x] `generate_image_local` — local image generation now attempts configured backends first and falls back to real prompt-conditioned local rendering; the built-in `generate_image_local` tool is dispatched from `src/tools_builtin.py`.
- [x] `generate_video` — local video generation now emits generated frame sequences with MP4 encoding and is exposed through the built-in `generate_video` tool.
- [x] `Nexus Tunnel integration` (Nexus Systems #80) — Pointers: route=`POST /integrations/tunnel` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:connect_tunnel` (remote-first registration attempt with local fallback state).
- [x] `Nexus Guardian integration` — Pointers: route=`POST /integrations/guardian` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_with_guardian` (remote-first registration/policy fetch with local fallback queue).
- [x] `Nexus Edge integration` — Pointers: route=`POST /integrations/edge` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_edge_node` (remote-first orchestrator registration with local fallback state).
- [x] `screenshot_to_text` — OCR path exists via `src/vision.py:ocr_image_bytes` and is exposed through the built-in `ocr` dispatch branch in `src/tools_builtin.py`.
- [x] `image_describe` — vision-understand route exists via `POST /vision/understand`, and the built-in `vision_understand` dispatch branch is wired to the shared vision helpers.
- [x] `image_edit` — `edit_image()` / `image_to_image()` are exposed as the first-class `image_edit` tool action in `src/tools_builtin.py`.
- [x] `audio_transcribe` — STT route/module exist with local and provider backends, and the built-in `stt` dispatch branch is wired.
- [x] `text_to_speech` — TTS route/module exist with local and provider backends, and the built-in `tts` dispatch branch is wired.
- [x] `audio_analyse` — analysis route/module exist, the built-in `audio_analyse` dispatch branch is wired, and the shared module now includes diarization-oriented heuristics in addition to transcript-level analysis.

### 6.5 Database tools

- [x] `tool_query_db` — run SQL query on external DB — Pointers: tool=`query_db`; module=`src/tools_builtin.py:tool_query_db`.
- [x] `tool_inspect_db` — introspect external DB schema — Pointers: tool=`inspect_db`; module=`src/tools_builtin.py:tool_inspect_db`.
- [x] `tool_sqlite_query` — helper exists as `tool_query_sqlite()` in `src/tools_builtin.py` and is exposed through the built-in `sqlite_query` dispatch action.
- [x] `tool_pg_query` — PostgreSQL-specific query with type safety — Pointers: tool=`pg_query`; module=`src/tools_builtin.py:tool_pg_query`.
- [x] `tool_db_migrate` — apply migration string against a connection — Pointers: tool=`db_migrate`; module=`src/tools_builtin.py:tool_db_migrate`.

### 6.6 Scheduler tools

- [x] `tool_cron_schedule` — schedule a recurring agent task — Pointers: tool=`cron_schedule`; module=`src/tools_builtin.py:dispatch_builtin` + `src/scheduler.py:schedule_job`.
- [x] `tool_cron_list` — list scheduled jobs — Pointers: tool=`cron_list`; module=`src/tools_builtin.py:dispatch_builtin` + `src/scheduler.py:list_jobs`.
- [x] `tool_cron_cancel` — cancel a scheduled job — Pointers: tool=`cron_cancel`; module=`src/tools_builtin.py:dispatch_builtin` + `src/scheduler.py:cancel_job`.
- [x] `GET /scheduler/jobs` — list jobs via API — Pointers: route=`GET /scheduler/jobs` (`src/api/routes.py:scheduler_list_jobs`).
- [x] `POST /scheduler/jobs` — create job via API — Pointers: route=`POST /scheduler/jobs` (`src/api/routes.py:scheduler_create_job`, accepts `max_retries`, `retry_backoff_secs`).
- [x] `POST /scheduler/jobs/{job_id}/cancel` — cancel job via API — Pointers: route=`POST /scheduler/jobs/{job_id}/cancel` (`src/api/routes.py:scheduler_cancel_job`).
- [x] Cron expression validator (validate before saving) — Pointers: module=`src/scheduler.py:_parse_cron` (5-field cron validator before job creation).
- [x] Job history log (past executions + results) — Pointers: route=`GET /scheduler/jobs/{job_id}/history`; module=`src/scheduler.py:ScheduledJob.logs`.
- [x] Webhook-triggered job (trigger by external POST) — Pointers: route=`POST /scheduler/webhook/{job_id}` (`src/api/routes.py:scheduler_webhook_trigger`).
- [x] Job retry policy (max retries + backoff) — Pointers: module=`src/scheduler.py:ScheduledJob.max_retries`, `retry_count`, `retry_backoff_secs`; `_run_job` applies exponential backoff.

### 6.7 Tool safety and approval

- [x] `src/approvals.py` — HITL approval system — Pointers: module=`src/approvals.py:create_tool_approval`, `decide_tool_approval`, `consume_approved_action`. — Tags: owner=safety, priority=p1, risk=high, stage=GA, deps=auth+db, validate=src/approvals.py|GET /approvals
- [x] `GET /approvals` — list pending approvals — Pointers: route=`GET /approvals` (`src/api/routes.py`).
- [x] `POST /approvals/{approval_id}` — approve or reject — Pointers: route=`POST /approvals/{approval_id}` (`src/api/routes.py`).
- [x] `GET /settings/hitl` — HITL settings — Pointers: route=`GET /settings/hitl` (`src/api/routes.py`).
- [x] `POST /settings/hitl` — update HITL settings — Pointers: route=`POST /settings/hitl` (`src/api/routes.py`).
- [x] High-risk action approval mode (log / warn / block) — HITL approval wiring in `src/approvals.py` is integrated into the agent dispatch loop, with `warn` emitting approval metadata without blocking and `block` enforcing approval before execution.
- [x] App path protection (write / delete / run_command sandbox) — Tags: owner=platform, priority=p0, risk=high, stage=GA, validate=src/tools_builtin.py::_resolve_path,tool_write_file,tool_delete_file,tool_run_command
- [x] Sandboxed command limits (RAM / CPU / timeout) — `tool_run_command()` now enforces timeout, CPU, memory, file-size, and write-intent constraints.
- [x] Tool call audit log (persisted, queryable) — Pointers: route=`GET /admin/tool-audit`; module=`src/tools_builtin.py:get_tool_audit_log`, `_write_tool_audit`. — Tags: owner=safety, priority=p1, risk=high, stage=GA, deps=db+audit, validate=GET /admin/tool-audit
- [x] Tool call rate limiting (per tool per session) — Pointers: module=`src/tools_builtin.py:_TOOL_CALL_COUNTS`, `_check_tool_rate_limit`, `reset_tool_rate_counts`.
- [x] Tool argument schema registry (all tools have validated arg contracts) — Pointers: module=`src/tools_builtin.py:_TOOL_SCHEMAS`, `validate_tool_args`, `get_tool_schema`, `list_tool_schemas`.
- [x] Parallel tool execution risk assessment before fan-out — Pointers: route=`POST /agent`, `POST /agent/stream` (`src/api/routes.py`); tool=`n/a` (policy gating occurs before tool dispatch); module=`src/agent.py:_preflight_parallel_tool_batch`, `src/agent.py:_PARALLEL_SAFE_TOOL_ACTIONS`, `src/agent.py:_execute_parallel_tool_call` (`screen_tool_action`).

---

## 7. Safety and Guardrails

### 7.1 Safety pipeline

- [x] `src/safety_pipeline.py` — input/output safety pipeline — Tags: owner=safety, priority=p0, risk=high, stage=GA, deps=ml_model+filtering, validate=src/safety_pipeline.py
- [x] `src/safety_types.py` — typed safety verdict model
- [x] `src/safety.py` — safety rule engine
- [x] `src/safety_middleware.py` — FastAPI middleware
- [x] `POST /safety/check` — run safety check on content
- [x] `POST /safety/action-check` — check if action is safe
- [x] `POST /safety/pii-scan` — PII detection — Tags: owner=safety, priority=p1, risk=high, stage=GA, deps=regex+ml, validate=POST /safety/pii-scan
- [x] `POST /safety/prompt-injection` — prompt injection detection
- [x] `GET /safety/domain-guards` — domain guard rules
- [x] `POST /settings/domain-guards` — update domain guards
- [x] `GET /safety/profiles` — safety profile list
- [x] `GET /safety/audit` — safety decision audit log
- [x] `GET /settings/safety` — read safety config
- [x] `POST /settings/safety` — update safety config
- [x] PII redaction (actual masking in output via `scrub_pii_text()` / `screen_output()`; redacts SSN, email, phone, credit card, IP) — Tags: owner=safety, priority=p1, risk=high, stage=GA, deps=regex+privacy, validate=src/safety_pipeline.py|POST /safety/pii-scan
- [x] Toxic content classifier (supports `openai_moderation` and optional `local_transformers` backends in `src/safety/classifier.py`, with safety-pipeline integration and cached local transformer pipelines via `_LOCAL_CLF_CACHE` to avoid per-request model reload)
- [x] Output filter for unsafe completions (post-generation scan via `screen_output()`; redaction/blocking paths active)
- [x] Jailbreak / adversarial prompt pattern library (expanded `INJECTION_PATTERNS` in `src/safety_pipeline.py` covers DAN, developer-mode, persona hijack, delimiter injection, system-prompt extraction, and encoding-relay families)
- [x] Safety decision explanation in API response (`reason` and `detail` fields in safety issues)
- [x] Safety event webhook (push safety events to external SIEM) — Pointers: module=`src/agent.py:_send_safety_event_webhook` + `_push_safety_event`; env=`SAFETY_EVENT_WEBHOOK_URL`, `SAFETY_EVENT_WEBHOOK_SECRET`, `SAFETY_EVENT_WEBHOOK_TIMEOUT`. — Tags: owner=safety, priority=p1, risk=high, stage=GA, deps=webhook+auth, validate=src/agent.py|SAFETY_EVENT_WEBHOOK_URL
- [x] GDPR/CCPA data deletion request handler (`POST /privacy/data-deletion-request` validates scope and executes user/org cascade deletion using existing GDPR primitives) — Tags: owner=compliance, priority=p0, risk=high, stage=GA, deps=auth+db+privacy, validate=POST /privacy/data-deletion-request

### 7.2 Adaptive routing settings

- [x] `GET /settings/adaptive-routing`
- [x] `POST /settings/adaptive-routing`

---

## 8. Personas and Customization

### 8.1 Persona system

- [x] `src/personas.py` — persona registry
- [x] General persona
- [x] Coder persona
- [x] Researcher persona
- [x] Creative persona
- [x] Nexus Prime Cloud persona
- [x] `GET /personas` — list personas
- [x] `POST /personas/{persona_id}` — set active persona
- [x] `GET /personas/custom` — list custom personas
- [x] `POST /personas/custom` — create custom persona
- [x] `DELETE /personas/custom/{pid}` — delete custom persona
- [x] File-based persona/skill profile auto-loading (`SKILL.md` / `SOUL.md` / `AGENT.md` and related profile files, plus explicit allowlist layers like `USER.md`, `IDENTITY.md`, `TOOLS.md`, `ARCHITECT.md`, `docs/ARCHITECTURE.md`, `docs/STRATEGY_AND_GUARDRAILS.md`) — runtime discovery + schema validation + safe merge into active persona/instruction context with deterministic precedence (safety/architecture -> user preferences -> persona style), frontmatter controls (`role`, `priority`, `apply_to`, `safety_mode`), and strict size caps. Pointers: module=`src/profile_loader.py:load_profile_pack`; runtime merge=`src/agent.py:get_system_prompt`; runtime safety merge for tool gating=`src/agent.py:is_tool_allowed_for_persona`.
- [x] Persona export / import (portable JSON) — Pointers: route=`GET /personas/custom/export`, route=`POST /personas/custom/import` (`src/api/routes.py`).
- [x] Persona temperature and model tier override per persona
- [x] Persona-level CSS variable theming (visual identity per persona) — Pointers: module=`src/personas.py:PERSONAS[*].theme_vars`; route=`GET /personas` (`src/api/routes.py`).
- [x] Persona capability restrictions (limit which tools a persona can call) — Pointers: module=`src/personas.py:get_allowed_tools`; runtime gate=`src/agent.py:is_tool_allowed_for_persona` + enforcement in `src/agent.py:stream_agent_task`.
- [x] Analyst persona (data analysis + chart generation focus)
- [x] DevOps persona (infra, CI/CD, Docker focus)
- [x] Legal persona (contract review, clause extraction focus)
- [x] Medical persona (medical literature search, disclaimer-aware)
- [x] Teacher persona (Socratic, explain-to-learner style)

### 8.2 System instructions

- [x] `GET /instructions` — read system instructions
- [x] `POST /instructions` — update system instructions
- [x] Per-project instruction sets (different instructions per project context) — Pointers: route=`GET /instructions/projects/{pid}`, route=`POST /instructions/projects/{pid}` (`src/api/routes.py`), data=`projects.instructions` persisted via `db_save_project`.
- [x] Instruction versioning (history of instruction changes) — Pointers: route=`GET /instructions/versions` (`src/api/routes.py`), storage key=`instructions_history_v1` via prefs table.

### 8.3 User preferences

- [x] `GET /prefs` — read user preferences
- [x] `POST /prefs` — update user preferences
- [x] Dark / light theme toggle (full UI apply + persistence + restore + code-theme switch) — Pointers: module=`static/js/utilities/theme-prefs.js:setTheme`, `static/js/utilities/theme-prefs.js:toggleTheme`; UI=`static/index.html` (`#theme-btn`, `#theme-light`, `#theme-dark`, `#hljs-theme-link`).
- [x] Font size preference
- [x] Keyboard shortcuts
- [x] Language / locale preference
- [x] Response verbosity setting (brief / balanced / detailed)
- [x] Code block syntax theme preference
- [x] Notification preferences (browser push for long-running tasks)

---

## 9. Projects, Chats, and Session Management

### 9.1 Chat lifecycle and retrieval

- [x] `GET /chats` — list chats
- [x] `POST /chats` — create chat
- [x] `GET /chats/{cid}` — get chat
- [x] `DELETE /chats/{cid}` — delete chat
- [x] `GET /chats/search` — full-text search over chats
- [x] `POST /chats/{cid}/pin` — pin chat
- [x] `DELETE /chats/{cid}/pin` — unpin chat
- [x] `GET /chats/pinned` — list pinned chats
- [x] Auto title generation from first message — Tags: owner=platform, priority=p2, risk=low, stage=GA, validate=src/api/routes.py
- [x] Chat rename (manual title edit endpoint)
- [x] Chat archive (soft-delete / hide without permanent delete)
- [x] Bulk chat delete — Tags: owner=platform, priority=p2, risk=low, stage=GA, validate=src/api/routes.py
- [x] Chat import (restore from exported markdown) — Tags: owner=platform, priority=p2, risk=low, stage=GA, validate=src/api/routes.py

### 9.2 Sharing, export, and access controls

- [x] `GET /chats/{cid}/export` — export as markdown
- [x] `POST /chats/{cid}/share` — create share link — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+storage, validate=POST /chats/{cid}/share|src/api/routes.py
- [x] `GET /share/{share_id}` — read shared chat — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+tokenization, validate=GET /share/{share_id}|src/api/routes.py
- [x] Share link expiry / revoke — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+storage, validate=POST /chats/{cid}/share|GET /share/{share_id}|src/api/routes.py
- [x] Public share password protection — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+crypto, validate=GET /share/{share_id}|src/api/routes.py

### 9.3 Project workspace and collaboration boundaries

- [x] `GET /projects` — list projects
- [x] `POST /projects` — create project
- [x] `GET /projects/{pid}` — get project
- [x] `DELETE /projects/{pid}` — delete project
- [x] `POST /projects/{pid}/chats/{cid}` — attach chat to project
- [x] `GET /projects/{pid}/chats` — list project chats
- [x] `GET /projects/{pid}/context` — get project context
- [x] `POST /projects/{pid}/sessions` — create project session — Tags: owner=platform, priority=p2, risk=medium, stage=GA, validate=src/api/routes.py
- [x] `POST /projects/{pid}/context` — update project context
- [x] Project rename endpoint
- [x] Project-level memory namespace (all chats in project share memory) — Tags: owner=platform, priority=p2, risk=medium, stage=GA, validate=src/memory.py
- [x] Project-level tool restrictions — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+tooling, validate=POST /projects/{pid}/context|src/api/routes.py
- [x] Project collaborators (share project with other users) — Tags: owner=platform, priority=p2, risk=high, stage=GA, validate=src/api/routes.py
- [x] Project export bundle (chats + context + memory as one archive) — Tags: owner=platform, priority=p2, risk=low, stage=GA, validate=src/api/routes.py

---

## 10. Multi-Agent System

### 10.1 Specialist registry and role modeling

- [x] `src/agents/registry.py` — specialist agent definitions
- [x] Architect Agent
- [x] Security Auditor Agent
- [x] UI/UX Designer Agent
- [x] Data Scientist Agent
- [x] Legal / Compliance Agent
- [x] Product Manager Agent
- [x] Debugger Agent
- [x] Documentation Agent
- [x] DevOps / Infrastructure Agent
- [x] QA / Testing Agent
- [x] Marketing / Copy Agent
- [x] Finance / Budget Analyst Agent
- [x] Research Scientist Agent
- [x] Accessibility Auditor Agent

### 10.2 Inter-agent communication and reliability

- [x] `src/agent_bus.py` — inter-agent message bus
- [x] `GET /agents/bus/log` — message bus log (supports `?topic=` filter)
- [x] `GET /agents/bus/{agent_id}` — messages for agent (supports `?topic=` filter)
- [x] `POST /agents/bus` — publish message to bus — Tags: owner=autonomy, priority=p1, risk=high, stage=GA, deps=auth+queue, validate=POST /agents/bus|src/agent_bus.py
- [x] `GET /agents/bus/dlq` — dead-letter queue contents
- [x] `DELETE /agents/bus/dlq` — clear dead-letter queue
- [x] Bus persistence (messages survive restart via optional DB backend)
- [x] Bus topic filtering (subscribe to specific event types)
- [x] Dead-letter queue for failed agent messages

### 10.3 Agent distribution and governance

- [x] `GET /marketplace/agents` — list marketplace agents (supports `?org_id=` for private agents)
- [x] `POST /marketplace/agents` — publish agent to marketplace — Tags: owner=platform, priority=p2, risk=high, stage=GA, deps=auth+policy, validate=POST /marketplace/agents
- [x] `DELETE /marketplace/agents/{agent_id}` — remove from marketplace
- [x] `POST /marketplace/agents/import-url` — Agent import from marketplace URL (HTTPS only)
- [x] `GET /marketplace/agents/{agent_id}/versions` — Agent version history in marketplace
- [x] `GET /marketplace/agents/{agent_id}/reviews` — read agent reviews
- [x] `POST /marketplace/agents/{agent_id}/reviews` — Agent rating / review system
- [x] Private marketplace (org-scoped agent sharing via `org_id`)

### 10.4 Swarm operations and blueprint orchestration

- [x] `GET /swarm/activity` — live swarm activity feed
- [x] Swarm View UI (visual real-time agent activity graph in browser — canvas force-directed graph with idle/busy/errored node colours, drag interaction, hover tooltips, live polling via `GET /swarm/health`)
- [x] Swarm task assignment UI (Assign tab: agent picker from marketplace, task text, optional topic, dispatches to `POST /agents/bus`)
- [x] `GET /swarm/health` — Swarm health dashboard (which agents are idle / busy / errored)
- [x] `POST /swarm/pause` / `POST /swarm/resume` — Swarm pause / resume controls
- [x] `src/architecture/hierarchy.py` — agent hierarchy model
- [x] `GET /architecture/hierarchy` — hierarchy structure
- [x] `POST /architecture/blueprints` — create blueprint
- [x] `GET /architecture/blueprints` — list blueprints
- [x] `GET /architecture/blueprints/{name}` — get blueprint
- [x] `GET /architecture/registry/{name}` — agent registry entry
- [x] Blueprint validation (schema check before save)
- [x] `POST /architecture/blueprints/{name}/execute` — Blueprint execution (spawn agents from blueprint definition) — Tags: owner=autonomy, priority=p1, risk=high, stage=GA, deps=agent_bus+scheduler, validate=POST /architecture/blueprints
- [x] `GET /architecture/blueprints/{name}/export` — Blueprint export (portable JSON)
- [x] `POST /architecture/blueprints/import` — Blueprint import (portable JSON)

---

## 11. Multimodal Features

### 11.1 Vision

- [x] Vision model routing (detect image in request → route to vision-capable provider) — Pointers: module=`src/agent.py:call_llm_with_fallback` (vision detection + provider promotion); `src/agent.py:_smart_order_for_vision`; `src/vision.py:VISION_CAPABLE_PROVIDERS`.
- [x] Image input in `/v1/chat/completions` (base64 + URL formats) — Pointers: route=`POST /v1/chat/completions` (`src/api/routes.py`); vision fast-path preserves `image_url` content parts and routes to vision-capable provider.
- [x] Image input in `/agent` and `/agent/stream` — Pointers: route=`POST /agent`, `POST /agent/stream` (`src/api/routes.py`); accepts `images` list of `{url}` or `{b64, mime_type}` dicts.
- [x] Local vision model support via Ollama (LLaVA / Qwen-VL / Llama 4 Vision) — Pointers: module=`src/agent.py:OLLAMA_VISION_MODELS`, `get_best_vision_model`, `_smart_order_for_vision`; `_vision_override` consumed in `_call_openai`.
- [x] Image analysis tool (`image_describe`) — Pointers: route=`POST /vision/understand` (`src/api/routes.py`); tool=`vision_understand` (`src/tools_builtin.py`); module=`src/vision.py:describe_image` delegated from `src/tools_builtin.py:tool_vision_understand`.
- [x] Screenshot capture tool (headless browser) — Pointers: route=`n/a`; tool=`screenshot` (`src/tools_builtin.py`); module=`src/tools_builtin.py:tool_screenshot` (fully implemented via `src/vision.py:capture_screenshot`).
- [x] OCR tool (extract text from image) — Pointers: route=`n/a`; tool=`ocr` (`src/tools_builtin.py`); module=`src/vision.py:ocr_image_bytes` delegated from `src/tools_builtin.py:tool_ocr`.

### 11.2 Image generation

- [x] `generate_image` tool — Pollinations (cloud) — Pointers: tool=`generate_image`; module=`src/tools_builtin.py:tool_generate_image` (Pollinations.ai, no API key required).
- [x] Local image generation — Flux / SD3 via Ollama or ComfyUI — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); tool=`generate_image_local` (`src/tools_builtin.py`); module=`src/generation.py:generate_image_local` (configured backend attempts with local prompt-conditioned rendering fallback).
- [x] Image editing / inpainting tool
- [x] Image-to-image (style transfer) tool
- [x] Generated image persistence (save to workdir, return URL) — Pointers: module=`src/tools_builtin.py:tool_generate_image`; `save=True` param downloads and persists image via `_write_binary_tool_artifact`.

### 11.3 Audio

- [x] Voice input in UI (Web Speech API — browser-side) — Pointers: `static/index.html` `toggleVoice()` / `setListening()` (Web Speech API, Chrome/Edge; microphone button wired to task input).
- [x] STT tool (`audio_transcribe`) — Whisper local or API — Pointers: route=`POST /v1/audio/transcriptions` (`src/api/routes.py`); tool=`stt` (`src/tools_builtin.py`); module=`src/audio.py:transcribe_audio`.
- [x] TTS tool (`text_to_speech`) — Kokoro / Coqui local or API — Pointers: route=`POST /v1/audio/speech` (`src/api/routes.py`); tool=`tts` (`src/tools_builtin.py`); module=`src/audio.py:synthesize_speech`.
- [x] `POST /v1/audio/transcriptions` — OpenAI-compatible STT
- [x] `POST /v1/audio/speech` — OpenAI-compatible TTS
- [x] Audio analysis tool (sentiment / diarization / speaker ID) — Pointers: route=`POST /audio/analyse` (`src/api/routes.py`); tool=`audio_analyse` (`src/tools_builtin.py`); module=`src/audio.py:analyse_audio`.
- [x] Podcast / meeting transcript ingestion pipeline — Pointers: route=`POST /audio/ingest-transcript` (`src/api/routes.py`); module=`src/audio.py:ingest_transcript` (supports `youtube`, `audio_file`, `meeting_url` source types; ingests into RAG).

### 11.4 Video

- [x] YouTube summarization wired to LLM (transcript → summary) — Pointers: module=`src/tools_builtin.py:tool_youtube`; calls `call_llm_with_fallback` with summarization prompt when transcript is available.
- [x] Local video generation tool — Pointers: route=`POST /generation/video` (`src/api/routes.py`); tool=`generate_video` (`src/tools_builtin.py`); module=`src/generation.py:generate_video` (generated frame pipeline with MP4 encoding).
- [x] Video-to-text (frame sampling + vision description)
- [x] Video chapter detection

---

## 12. Fine-tuning and Sovereign Model (Nexus Prime)

### 12.1 Data collection and governance

- [x] Per-message feedback stored as training signal (`POST /feedback/{chat_id}/{message_idx}`) — Tags: owner=modeling, priority=p1, risk=high, stage=GA, deps=privacy+db, validate=POST /feedback/{chat_id}/{message_idx}|tests/test_v1_contracts.py::TestSprintE::test_feedback_endpoint_valid_thumbs_up
- [x] `GET /feedback/export` — export feedback dataset (supports `format=json|jsonl|alpaca|sharegpt`, optional trace inclusion) — Tags: owner=modeling, priority=p1, risk=high, stage=GA, deps=privacy+auth, validate=GET /feedback/export|tests/test_v1_contracts.py::TestSprintE::test_feedback_export_supports_training_formats
- [x] `GET /feedback/stats` — feedback statistics (includes `trace_total` and `trace_opt_in`)
- [x] Opt-in interaction trace collection (GDPR-compliant) (`GET/POST /feedback/consent`, `POST /feedback/trace`) — Tags: owner=modeling, priority=p1, risk=high, stage=GA, deps=privacy+consent, validate=POST /feedback/trace|GET /feedback/stats|tests/test_v1_contracts.py::TestSprintE::test_feedback_trace_opt_in_and_trace_capture
- [x] Synthetic training data generation tool (agent swarm → instruction pairs) (`POST /finetune/synthetic/generate`, `GET /finetune/synthetic/batches`)
- [x] Data curation UI (label, filter, approve training samples) (`GET /finetune/curation/ui`, `GET /finetune/curation/samples`, `POST /finetune/curation/samples/{sample_id}/review`, `POST /finetune/curation/samples/bulk-approve`)
- [x] Dataset versioning and provenance tracking (`POST /finetune/one-click` creates `dataset_version_id` + checksum + provenance; `GET /finetune/datasets/versions*` for retrieval)
- [x] Training data export in Alpaca / ShareGPT / JSONL formats

### 12.2 Fine-tuning operations and adapters

- [x] LoRA fine-tuning job endpoint (`POST /finetune/jobs`) — creates persisted job with status 'queued'
- [x] Fine-tuning job status (`GET /finetune/jobs/{job_id}`) — returns job record or 404
- [x] Fine-tuning job cancel (`DELETE /finetune/jobs/{job_id}`) — cancels queued/running job, 404 if missing
- [x] LoRA adapter versioning (store + compare adapter checkpoints) (`POST /finetune/adapters`, `GET /finetune/adapters`, `GET /finetune/adapters/{adapter_id}/compare`)
- [x] LoRA adapter hot-swap at inference (apply adapter to Ollama base) (`POST /finetune/adapters/{adapter_id}/hot-swap`, `GET /finetune/adapters/active` stores active adapter state for runtime integration)
- [x] One-click fine-tune on collected feedback data (`POST /finetune/one-click` creates dataset version/provenance and queues fine-tune job)
- [x] RLHF / DPO pipeline integration (experiment jobs create child fine-tune runs, track events, and register adapter artifacts) (`POST/GET /finetune/experiments/rlhf-dpo/jobs*`, `GET /finetune/experiments/rlhf-dpo/jobs/{job_id}/events`)
- [x] Continual fine-tuning scheduler (weekly re-tune if benchmarks improve) (policy-driven eval+delta trigger with run-now control; scheduler-integrated execution path) (`POST/GET/DELETE /finetune/continual/schedule*`, `POST /finetune/continual/schedule/{policy_id}/run-now`)

### 12.3 Model packaging and release readiness

- [x] Nexus Prime Alpha persona wired to fine-tuned Ollama model (`POST /finetune/personas/nexus-prime-alpha/wire`, `GET /finetune/personas/nexus-prime-alpha/wire`)
- [x] Automated eval suite (benchmark vs base model on code / autonomy / RAG)
- [x] Model card and transparency report endpoint (`GET /models/{model_id}/card`, `GET /models/{model_id}/transparency`, wired to eval outputs + dataset/adapter registries)
- [x] Multi-task LoRA adapters (coding / reasoning / research / creative) hot-swap (`GET/POST /finetune/adapters/multitask`, `POST /finetune/adapters/multitask/hot-swap`)
- [x] Multimodal fine-tuning extension (vision capability) (`POST /finetune/multimodal/jobs`)
- [x] Knowledge distillation pipeline (teacher: Claude/GPT → student: Nexus Prime) (`POST/GET /finetune/distill/jobs*`, child fine-tune + adapter artifact lifecycle)

---

## 13. Benchmarking

### 13.1 Benchmark execution and orchestration

- [x] `POST /benchmark/run` — run model benchmark suite
- [x] `GET /benchmark/results` — retrieve benchmark results
- [x] Automated regression benchmark on model update

### 13.2 Result history and comparative analysis

- [x] Per-model benchmark history (track quality over time) (`GET /benchmark/history`)
- [x] Benchmark leaderboard endpoint (sorted by task type) (`GET /benchmark/leaderboard`)

### 13.3 Reporting and product visibility

- [x] Public leaderboard page in UI (overflow menu panel in static UI wired to `GET /benchmark/leaderboard`)

---

## 14. Observability and Telemetry

### 14.1 Usage and cost

- [x] `GET /usage` — token / cost usage summary — Pointers: route=`GET /usage` (`src/api/routes.py`); module=`src/db.py:get_usage_stats`, `src/db.py:get_usage_daily`, `src/db.py:get_usage_records`.
- [x] Cost tracking for paid providers — Pointers: module=`src/agent.py:stream_agent_task` (per-response `cost_usd` estimate persisted); storage=`usage_log.cost_usd` (`src/db.py`).
- [x] Usage records written per request — Pointers: module=`src/agent.py:stream_agent_task` (`log_usage(...)`); storage=`usage_log` (`src/db.py`).
- [x] Per-user usage breakdown — Pointers: module=`src/db.py:get_usage_by_user`; route=`GET /usage` (`src/api/routes.py`).
- [x] Cost forecasting (project spend based on usage trend) — Pointers: route=`GET /usage` (`src/api/routes.py`, `forecast` payload).
- [x] Usage export (CSV / JSON) — Pointers: route=`GET /usage/export` (`src/api/routes.py`).
- [x] Usage webhook (push daily summary to external endpoint) — Pointers: route=`GET /usage/webhook`, `POST /usage/webhook`, `POST /usage/webhook/push` (`src/api/routes.py`).

### 14.2 Execution traces

- [x] `src/execution_trace.py` — replayable trace store — Pointers: module=`src/execution_trace.py` (`save_checkpoint`, `load_checkpoints`, `list_traces`).
- [x] `GET /tasks/{trace_id}/replay` — deterministic trace replay — Pointers: route=`GET /tasks/{trace_id}/replay` (`src/api/routes.py`).
- [x] Trace search (find traces by tool used / agent / error type) — Pointers: route=`GET /tasks/search` (`src/api/routes.py`).
- [x] Trace export (portable JSON) — Pointers: route=`GET /tasks/{trace_id}/export` (`src/api/routes.py`).
- [x] Trace diff (compare two runs of same task) — Pointers: route=`GET /tasks/{trace_id}/diff` (`src/api/routes.py`); module=`src/execution_trace.py` (file diff persistence).
- [x] Anomaly detection on traces (flag unusual execution patterns) — Pointers: route=`GET /tasks/anomalies` (`src/api/routes.py`).

### 14.3 Structured logging

- [x] Safety audit log (`GET /safety/audit`) — Pointers: route=`GET /safety/audit` (`src/api/routes.py`); storage=`src/db.py:load_safety_audit_entries`.
- [x] Agent bus log (`GET /agents/bus/log`) — Pointers: route=`GET /agents/bus/log` (`src/api/routes.py`); module=`src/agent_bus.py`.
- [x] Structured JSON application log (all requests + responses) — Pointers: module=`src/app.py:AuditBodyLogMiddleware` + structured logger wiring.
- [x] OpenTelemetry tracing export — Pointers: module=`src/observability.py` (OTLP tracer setup/export).
- [x] Prometheus metrics endpoint (`GET /metrics`) — Pointers: route=`GET /metrics` (`src/api/routes.py`); module=`src/observability.py:get_prometheus_metrics_text`.
- [x] Log forwarding to external sink (Loki / Datadog / CloudWatch) — Pointers: module=`src/observability.py` sink forwarding handlers.

---

## 15. Frontend / PWA

### 15.1 Chat UI

- [x] Streaming SSE word-by-word typewriter — Pointers: backend token chunk stream in `src/agent.py` (`token_chunk` events in `stream_agent_task`); UI progressive render in `static/index.html` (`evt.type==='token_chunk'`).
- [x] Stop button (cancel mid-stream) — Pointers: UI=`static/index.html` (`#stop-btn`, `stopStream()`, `setBusy()`); route=`POST /agent/stop/{stream_id}` (`src/api/routes.py`).
- [x] Markdown rendering — Pointers: UI=`static/index.html:renderMd` (Marked.js).
- [x] Syntax-highlighted code blocks — Pointers: UI=`static/index.html` (highlight.js include + `renderMd`/`makeCodeViewer`).
- [x] Inline artifact renderer (HTML / SVG) — Pointers: module=`static/js/utilities/artifacts.js:makeArtifact`; panel wiring in `static/index.html` (`#artifact-panel`).
- [x] Inline image bubbles — Pointers: SSE handler in `static/index.html` (`evt.type==='image'`), styles `.img-bubble`.
- [x] Multi-file artifact tabs — Pointers: UI=`static/index.html` (`.artifact-tabs`, `.artifact-tab`, `openArtifactPanel`).
- [x] Code viewer for file ops — Pointers: UI=`static/index.html:makeCodeViewer` + `evt.file_content && evt.file_path` rendering.
- [x] Resizable split view — Pointers: UI=`static/index.html` (`#dragger`), module=`static/js/panels/tooling-utilities.js` drag handlers.
- [x] Message reactions — Pointers: module=`static/js/utilities/interaction-ui.js:addReactionButtons`, route=`POST /reactions`.
- [x] Live confidence / reasoning trace badge — Pointers: SSE `done` event handling in `static/index.html` (`evt.confidence` -> `.confidence-badge`).
- [x] Streaming token counter — Pointers: live SSE token telemetry handled in `static/index.html` (`evt.type==='token'`) and `static/js/utilities/ui-helpers.js:updateLiveTokenCount`.
- [x] Code execution in UI (run Python / JS in sandboxed iframe) — Pointers: panel `#code-runner-panel` in `static/index.html`; runtime in `static/js/panels/code-runner.js` (JS sandbox + Pyodide Python iframe).
- [x] Chart / graph artifact renderer (Chart.js output) — Pointers: Chart.js include in `static/index.html`; fenced ` ```chart ` block rendering in `renderMd(...)` + `enhanceRenderedContent(...)`.
- [x] Mermaid diagram renderer — Pointers: UI=`static/index.html:renderMd` (` ```mermaid ` -> `.mermaid` transform), `static/index.html:enhanceRenderedContent` (`mermaid.run(...)`).
- [x] LaTeX / math equation renderer — Pointers: UI=`static/index.html:enhanceRenderedContent` (`renderMathInElement` with `$...$` / `$$...$$` delimiters), KaTeX assets loaded in `static/index.html`.
- [x] Message edit + re-run — Pointers: module=`static/js/panels/tooling-utilities.js:addMessageActions` (`✏️ Edit`, `↺ Retry`).
- [x] Message branch (fork conversation from earlier message) — Pointers: module=`static/js/panels/tooling-utilities.js:branchFromMessage`, `_buildBranchHistory` (session fork + `__restore__` history replay).
- [x] Message copy-as-markdown button — Pointers: module=`static/js/panels/tooling-utilities.js:addMessageActions` (`⎘ MD`), `_toMarkdownForCopy`.
- [x] Image paste input (paste clipboard image into chat) — Pointers: module=`static/js/utilities/input-handling.js` (`textarea#task` paste listener -> `processFiles`).

### 15.2 Agent console and swarm view

- [x] Swarm View UI (real-time agent graph visualization) — Pointers: module=`static/js/panels/swarm.js` (canvas graph + health polling); route=`GET /swarm/health`.
- [x] Agent Console (watch tool calls and events live in a panel) — Pointers: module=`static/js/panels/swarm.js` (`/swarm/activity`, `/agents/bus/log` feed).
- [x] Task progress panel (current subtask list with status) — Pointers: UI=`static/index.html` (`#swarm-tab-progress`, `#swarm-pane-progress`); module=`static/js/panels/swarm.js:swarmRefreshProgress`, `_renderProgressTimeline`.
- [x] Agent output diff viewer (compare before/after file changes) — Pointers: UI=`static/index.html` (`#swarm-tab-diff`, `#swarm-pane-diff`); module=`static/js/panels/swarm.js:swarmRunDiffCompare`; route=`GET /tasks/{trace_id}/diff` (`src/api/routes.py`).
- [x] Diff viewer for file edits (backend `POST /diff` exists) — Pointers: module=`static/js/panels/diff-history.js:openDiffViewer`, route=`POST /diff` (`src/api/routes.py`).

### 15.3 Settings and dashboards

- [x] Provider status drawer with cooldown timers — Pointers: UI=`static/index.html` (`#drawer`, provider cards/cooldowns), route=`GET /providers/health`.
- [x] Settings panel (provider / model / temp overrides) — Pointers: UI=`static/index.html` (`#settings-modal` + `saveSettings()`), route=`GET/POST /settings`.
- [x] Multi-user admin dashboard (usage / costs / agent activity per user) — Pointers: panel `#admin-dashboard-panel` in `static/index.html`; data loader in `static/js/panels/admin-dashboard.js` (`/admin/users`, `/admin/quota`, `/usage`).
- [x] Command palette (Cmd+K for everything) — Pointers: route=`n/a`; tool=`n/a`; module=`static/js/utilities/search-command.js:openCommandPalette`, `static/js/utilities/search-command.js:_personaCommands`, `static/index.html` (Cmd+K key handlers + script include).
- [x] Model benchmark dashboard UI — Pointers: panel `#benchmark-dashboard-panel` in `static/index.html`; loader in `static/js/panels/benchmark-dashboard.js` (`/benchmark/results`, `/benchmark/history`).
- [x] Fine-tuning job dashboard — Pointers: panel `#finetune-dashboard-panel` in `static/index.html`; loader in `static/js/panels/finetune-dashboard.js`; backend list endpoint `GET /finetune/jobs` (`src/api/routes.py`).
- [x] RAG corpus browser (list, search, delete ingested docs) — Pointers: panel `#rag-corpus-panel` in `static/index.html`; loader in `static/js/panels/rag-corpus.js`; endpoints `GET/DELETE /rag/documents*` (`src/api/routes.py`).
- [x] KG visualization panel — Pointers: module=`static/js/panels/knowledge-graph.js` (`openKGPanel`, query/store wiring).

### 15.4 PWA and mobile

- [x] Installable PWA (manifest + service worker) — Pointers: `static/manifest.json`, `static/sw.js`, `static/js/utilities/device-utils.js` (`beforeinstallprompt`, SW registration).
- [x] Mobile sidebar swipe gestures — Pointers: module=`static/js/utilities/device-utils.js` (`touchstart`/`touchend` swipe open/close sidebar).
- [x] Haptic feedback — Pointers: module=`static/js/utilities/device-utils.js:haptic`.
- [x] Safe-area inset support — Pointers: CSS in `static/index.html` (`env(safe-area-inset-*)`).
- [x] 44px touch targets — Pointers: coarse-pointer media query enforcing min-height 44px in `static/index.html` CSS.
- [x] Dark / light theme toggle
- [x] Font size preference — Pointers: UI `setFontSize(...)` controls in `static/index.html` + persisted prefs.
- [x] Keyboard shortcuts (new chat / sidebar / stop) — Pointers: UI overlay + handlers in `static/index.html` / `static/js/utilities/search-command.js`.
- [x] Offline mode (serve cached UI without backend) — Pointers: upgraded service worker in `static/sw.js` (`nexus-ai-v4`) with HTML network-first + cached-shell fallback and static-asset precache; full offline chat execution not available.
- [x] Push notifications for long-running task completion — Pointers: notification permission + dispatch in `static/js/utilities/device-utils.js` (`enableTaskNotifications`, `notifyTaskComplete`) triggered from stream completion in `static/index.html`.
- [~] Browser regression spec for chat + operations panels — Pointers: `tests/playwright/tests/chat-and-operations.spec.ts` (covers chat streaming, benchmark/fine-tune dashboards, RAG/admin/code-runner panel flows).
- [~] Desktop Electron wrapper — Pointers: minimal shell scaffold in `desktop/electron/` (`main.js`, `package.json`) loading `NEXUS_AI_URL`/local server.
- [~] Mobile native app (Capacitor shell scaffold) — Pointers: `mobile/capacitor/` (`capacitor.config.ts`, `package.json`, `README.md`).

---

## 16. Webhook and External Integrations

### 16.1 Webhook runtime and delivery controls

- [x] `POST /webhook/trigger` — external trigger — Tags: owner=integrations, priority=p1, risk=high, stage=GA, deps=auth+rate_limit, validate=POST /webhook/trigger — Pointers: `src/api/routes.py:webhook_trigger`.
- [x] `GET /webhook/status/{run_id}` — run status — Pointers: `src/api/routes.py:webhook_status`.
- [x] Webhook payload signature verification (HMAC) — Tags: owner=integrations, priority=p1, risk=high, stage=GA, deps=crypto+auth, validate=POST /webhook/trigger — Pointers: `WEBHOOK_HMAC_SECRET`, `X-Webhook-Signature-256` handling in `src/api/routes.py`.
- [x] Webhook delivery retry with exponential backoff — Pointers: `max_retries` + `retry_backoff_secs` loop in `src/api/routes.py:webhook_trigger`.
- [x] Webhook event type filtering (only trigger on specific events) — Pointers: `WEBHOOK_ALLOWED_EVENTS` + `event_type` gating in `src/api/routes.py:webhook_trigger`.

### 16.2 External channel integrations

- [ ] Slack integration (receive messages, send responses)
- [ ] Discord bot integration
- [ ] GitHub Actions integration (trigger on PR / push)
- [ ] Zapier / Make.com webhook connector

### 16.3 MCP ecosystem interoperability

- [ ] MCP server mode (expose Nexus tools to external MCP clients) — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+tool_sandbox, validate=MCP server mode
- [ ] MCP tool consumption via `MCP_TOOLS` env (Nexus as MCP client) — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=network_policy+tool_sandbox, validate=MCP_TOOLS env

---

## 17. Gist Backup and External Storage

### 17.1 Gist-based backup path

- [x] `src/gist_backup.py` — GitHub Gist backup — Pointers: `src/gist_backup.py` (`restore_from_gist`, `schedule_push`, `push_now`).
- [x] Restore from backup endpoint — Pointers: route=`POST /backup/gist/restore` (`src/api/routes.py`); push helper route=`POST /backup/gist/push`.

### 17.2 Object storage replication

- [ ] S3 / R2 chat backup integration

### 17.3 Knowledge workspace export destinations

- [ ] Export to Notion / Obsidian

---

## 18. Enterprise and Ecosystem (Phase 5 / Future)

### 18.1 Nexus platform integrations

- [x] Nexus Tunnel integration (Nexus Systems #80) — Pointers: route=`POST /integrations/tunnel` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:connect_tunnel` (remote-first registration attempt with local fallback state).
- [x] Nexus Guardian integration — Pointers: route=`POST /integrations/guardian` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_with_guardian` (remote-first registration/policy fetch with local fallback queue).
- [x] Nexus Edge integration — Pointers: route=`POST /integrations/edge` (`src/api/routes.py`); tool=`n/a`; module=`src/integrations.py:register_edge_node` (remote-first orchestrator registration with local fallback state).
- [ ] Nexus Systems API passthrough
- [ ] Nexus AI Hub (multi-instance management)
- [ ] Nexus Blueprint export (portable agent workflow archive)

### 18.2 Ecosystem collaboration and media primitives

- [ ] Open-source model leaderboard page
- [~] Real-time collaboration (multi-human + multi-agent on same session) — Pointers: route=`POST /collab/rooms`, `GET /collab/rooms`, `GET /collab/rooms/{room_id}`, `DELETE /collab/rooms/{room_id}` (`src/api/routes.py`); tool=`n/a`; module=`src/collab.py:create_room`, `src/collab.py:join_room`, `src/collab.py:close_room` (in-memory implementation, pending DB/WS).
- [~] Screenshot capture tool (headless browser) — Pointers: route=`n/a`; tool=`screenshot` (`src/tools_builtin.py`); module=`src/vision.py:capture_screenshot` (deterministic placeholder image, not a real browser render).
- [x] Local image generation — Flux / SD3 via Ollama or ComfyUI — Pointers: route=`POST /v1/images/generations` (`src/api/routes.py`); module=`src/generation.py:generate_image_local` (configured backend attempts with local prompt-conditioned rendering fallback).
- [~] Audio analysis tool (sentiment / diarization / speaker ID) — Pointers: route=`POST /audio/analyse` (`src/api/routes.py`); module=`src/audio.py:analyse_audio` (route exists, but no built-in dispatch action and no true diarization/speaker-ID pipeline).
- [x] Local video generation tool — Pointers: route=`POST /generation/video` (`src/api/routes.py`); module=`src/generation.py:generate_video` (generated frame pipeline with MP4 encoding).

### 18.3 Distributed intelligence and compute federation

- [ ] Federated learning module (local gradient contribution without raw data sharing) — Tags: owner=research, priority=p1, risk=high, stage=GA, deps=privacy+secure_aggregation, validate=Federated learning module
- [x] User-contributed compute network (idle GPU opt-in)

---

## 19. Continuous Learning and Self-Improvement

### 19.1 Feedback capture and learning signal quality

- [ ] Self-improvement loop (`POST /agent/self-review`)
- [ ] Self-review history
- [ ] Per-message feedback as training signal
- [ ] Self-generating test cases from production interactions

### 19.2 Automated correction and resilience loops

- [ ] Automated self-correction on low-confidence outputs — Tags: owner=autonomy, priority=p1, risk=high, stage=GA, deps=safety+evals, validate=POST /agent/self-review

### 19.3 Drift detection and governance

- [ ] Drift detection (flag when output quality degrades from baseline)
- [ ] Architecture drift monitoring (compare code against ARCHITECTURE.md intent)
- [ ] Weekly quality regression benchmark (auto-run on schedule)

---

## 20. Advanced Reasoning and Quality Operations (Phase 1 Super Intelligence)

### 20.1 Reasoning depth and model capability

- [x] Graph-of-Thought reasoning
- [x] Self-critique loop
- [x] Cross-model consensus voting
- [ ] Mixture-of-Experts routing (task-aware ensemble selection)
- [ ] Hypothesis testing flow with evidence grounding
- [ ] Socratic reasoning mode (question-driven decomposition)
- [ ] Formal proof verification (math/code step-by-step checks)

### 20.2 Quality benchmarking and regression detection

- [x] Model benchmark dashboard for Ollama pulls
- [x] Automated regression benchmark on model update
- [ ] Unified benchmark runner for agentic tasks — Tags: owner=evals, priority=p2, risk=medium, stage=GA, deps=test_harness+metrics, validate=POST /benchmark/run
- [ ] Per-model benchmark history (track quality over time)
- [ ] Continuous regression detection by capability cluster
- [ ] Human feedback integration into quality tracking
- [ ] Safety benchmark tracking and release gating

### 20.3 Learning signal and synthetic data

- [ ] Synthetic training data generation (agent swarm → instruction pairs)
- [x] Per-message feedback stored as training signal
- [ ] Self-generating test cases from production interactions
- [ ] Dataset versioning and provenance tracking
- [ ] Training data export in Alpaca / ShareGPT formats

---

## 21. Enterprise Governance and Policy Enforcement (Phase 5 / L0-08,09)

### 21.1 Team and organization controls

- [ ] Team policies for tool and data access — Tags: owner=platform, priority=p1, risk=high, stage=GA, deps=auth+policy, validate=Team policies API
- [ ] Role-based access control enhancements (beyond admin/user/viewer)
- [ ] Regional compliance and deployment controls
- [ ] Department / cost-center based quota allocation
- [ ] Audit trail export for compliance reporting

### 21.2 Policy enforcement and action approval

- [ ] Action policy gating for high-stakes tasks (approve before file delete, command run)
- [ ] Multi-tier approval workflows (manager → director → executive)
- [ ] Audit-ready safety event logging with immutable record
- [ ] Policy violation alerts with context and remediation
- [ ] Enterprise connectors and managed integrations (SSO, compliance APIs)

### 21.3 Safety and oversight

- [ ] Multi-layer safety pipeline with monitor model — Tags: owner=safety, priority=p0, risk=high, stage=GA, deps=ml_model+filtering, validate=Safety pipeline enhancements
- [ ] Prompt-injection and adversarial content defenses
- [ ] Jailbreak attempt flagging with severity scoring
- [ ] Safety decision logging to external SIEM

---

## 22. Multimodal and Media Expansion (Phase 3 / L0-03)

### 22.1 Document and media understanding

- [ ] Vision understanding with chart/table extraction — Tags: owner=vision, priority=p2, risk=medium, stage=GA, deps=vision_model+parsing, validate=Vision model routes
- [ ] PDF/Office document understanding (layout-aware)
- [ ] YouTube video summarization wired to LLM
- [ ] Screenshot capture tool (headless browser takeover)
- [ ] Document comparison and diff tool

### 22.2 Audio and voice interaction

- [ ] Audio live interaction and voice agent surface
- [ ] Voice input streaming (Web Speech + server STT)
- [ ] Audio analysis enhancements (speaker diarization, emotion detection)
- [ ] Podcast and meeting transcript ingestion pipeline
- [ ] Voice-to-text with speaker identification

### 22.3 Video generation and editing

- [ ] Video generation via local models (Flux / SD3 orchestration)
- [ ] Video-to-text (frame sampling + vision description)
- [ ] Video chapter detection and indexing
- [ ] Video editing orchestration (cuts, transitions, effects)
- [ ] Real-time video generation with streaming output

---

## 23. Advanced Task Automation and Orchestration (Phase 4 / L0-01)

### 23.1 Browser automation and computer use

- [ ] Browser action mode with takeover checkpoints — Tags: owner=autonomy, priority=p1, risk=high, stage=GA, deps=browser+sandbox+policy, validate=Browser automation mode
- [ ] Multi-step task planning and resumable execution
- [ ] Sensitive action confirmation workflow
- [ ] Visual element detection and interaction queuing
- [ ] Form filling and navigation history replay

### 23.2 Concurrent task management

- [ ] Concurrent task sessions with per-task control — Tags: owner=autonomy, priority=p1, risk=high, stage=GA, deps=state_mgmt+queuing, validate=Concurrent task management
- [ ] Task dependency graph with DAG scheduling
- [ ] Cross-task memory sharing and context injection
- [ ] Task cancellation mid-execution with state rollback
- [ ] Task priority queue and resource allocation

### 23.3 Developer tooling and debug automation

- [ ] Repo-aware coding agent with edit-run-verify loops
- [ ] Bug-fix autopilot with rollback checkpoints
- [ ] Code migration assistant for legacy stacks
- [ ] Coding benchmark harness and regression gates
- [ ] Continuous error log parsing and fix suggestion

---

## 24. Cost and Latency Intelligence (Phase 5 / L0-10)

### 24.1 Dynamic routing and cost optimization

- [ ] Dynamic model routing by task complexity — Tags: owner=platform, priority=p2, risk=low, stage=GA, deps=router+metrics, validate=Complexity scoring enhancements
- [ ] Latency-aware fallback and cooldown behavior
- [ ] Budget-aware inference and cost controls
- [ ] Cost forecasting (project spend based on usage trend)
- [ ] Per-model cost-quality tradeoff visualization

### 24.2 Performance monitoring and SLO

- [ ] SLO dashboards for p95/p99 and reliability
- [ ] Hardware-aware routing (GPU preferred, fallback CPU)
- [ ] Per-provider performance baseline and drift detection
- [ ] Latency hotspot profiling and optimization
- [ ] Resource usage tracking (memory, compute, I/O)

### 24.3 Budget and quota management

- [ ] Per-team budget allocation and tracking
- [ ] Over-budget alerts with escalation workflow
- [ ] Reserved capacity and rate guarantees
- [ ] Spot/preemptible instance support
- [ ] Cost attribution and chargeback reports

---

## 25. Platform Ecosystem and Extensibility (Phase 5 / L0-12)

### 25.1 API and SDK ecosystem

- [ ] API parity for key assistant and agent features — Tags: owner=platform, priority=p2, risk=low, stage=GA, deps=api_contracts, validate=OpenAI-compatible endpoint parity
- [ ] SDK improvements for rapid adoption (Python, TypeScript, Go)
- [ ] Deployment profiles for self-hosted and enterprise
- [ ] Nexus Blueprint export (portable agent workflow archive)
- [ ] OpenAI SDK drop-in compatibility mode

### 25.2 Marketplace and third-party integrations

- [ ] Marketplace/connectors for third-party extensions
- [ ] Custom tool registration and discovery
- [ ] Model provider plugins and custom backends
- [ ] Agent template library with one-click deploy
- [ ] Community-contributed personas and system instructions

### 25.3 Nexus Systems full-stack integration

- [x] Nexus Tunnel integration (remote registration, local fallback)
- [x] Nexus Guardian integration (policy fetch, local queue)
- [x] Nexus Edge integration (orchestrator registration, federation)
- [ ] Nexus Systems API passthrough (unified control plane)
- [ ] Nexus AI Hub (multi-instance management dashboard)
- [ ] Nexus Blueprint export and versioning

---

## Summary Counts

| Status | Count (approx)       |
|--------|----------------------|
| `[x]` Fully implemented | 172 |
| `[~]` Stub / partial    | 33  |
| `[ ]` Not yet started   | ~550+ (expanded from 467 with new Sections 20-25) |

> This document is the single source of truth for feature completeness tracking.
> Update it whenever a feature is started (`[~]`) or completed (`[x]`).
> Do **not** remove `[ ]` items — they represent deliberate scope.
> 
> **Note on Sections 20-25:** Newly added roadmap and competitor-aligned features. L1/L2 mapping from ROADMAP_FEATURES_V2.md and COMPETITOR_L0_L1_SEED_CATALOG_2026Q2.md. High-risk items tagged with metadata schema. Maturity status reflects current implementation state as of 2026-04-19.
