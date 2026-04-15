# Nexus AI — Architecture

> This document describes the system design of Nexus AI: how a user request flows from the browser through the agent loop, tool dispatch, provider fallback chain, and back as a streaming response.

---

## Table of Contents

- [Overview](#overview)
- [High-Level Component Map](#high-level-component-map)
- [Request Lifecycle](#request-lifecycle)
- [Autonomous Runtime Loop](#autonomous-runtime-loop)
- [Component Deep-Dives](#component-deep-dives)
  - [main.py — API Gateway](#mainpy--api-gateway)
  - [agent.py — Agent Loop](#agentpy--agent-loop)
  - [model_router.py — Provider Routing](#model_routerpy--provider-routing)
  - [personas.py — Persona System](#personaspy--persona-system)
  - [tools_builtin.py — Tool Registry](#tools_builtinpy--tool-registry)
  - [autonomy.py — Orchestrator](#autonomypy--orchestrator)
  - [memory.py — Memory System](#memorypy--memory-system)
  - [thinking.py — Reasoning Helpers](#thinkingpy--reasoning-helpers)
  - [rag/ — Retrieval-Augmented Generation](#rag--retrieval-augmented-generation)
  - [db.py — Persistence](#dbpy--persistence)
- [Data Flow Diagrams](#data-flow-diagrams)
- [Provider Fallback Chain](#provider-fallback-chain)
- [Streaming Architecture](#streaming-architecture)
- [Security Boundaries](#security-boundaries)
- [Configuration Reference](#configuration-reference)
- [Deployment Topology](#deployment-topology)

---

## Overview

Nexus AI is a **single-process FastAPI application** that acts as an AI agent gateway. It exposes an OpenAI-compatible HTTP API, a custom streaming agent API, and a single-file web UI served from `static/`.

The design is intentionally **flat and readable**: there is no microservices split, no message queue, and no separate worker process in the default configuration. Everything runs in one Python process (async), which makes it trivially self-hostable on any VPS or local machine.

```
Browser / API Client
        │
        ▼
  FastAPI (main.py)
        │
   ┌────┴────┐
   │  Agent  │   ◄── model_router.py (provider selection)
   │  Loop   │   ◄── personas.py    (system prompt, temp)
   │(agent.py)│  ◄── tools_builtin  (tool execution)
   └────┬────┘
        │
   Server-Sent Events (SSE)
        │
        ▼
    Browser UI (static/)
```

---

## High-Level Component Map

```
Nexus-AI/
│
├── main.py               API routes, auth middleware, SSE endpoint
├── agent.py              Streaming agent loop, tool dispatch
├── model_router.py       Provider fallback chain, complexity scorer
├── personas.py           Persona registry (system prompts + settings)
├── tools_builtin.py      All tool implementations (~20 tools)
├── autonomy.py           Multi-step orchestrator + planning system
├── memory.py             Short-term session + long-term vector memory
├── thinking.py           Chain-of-Thought / Tree-of-Thought helpers
├── db.py                 SQLite/PG models, chat history, usage records
│
├── rag/
│   ├── ingest.py         Document chunking + embedding + ChromaDB write
│   └── query.py          Semantic search, rerank, context assembly
│
└── static/
    └── index.html        Full web UI — vanilla HTML/CSS/JS, single file
```

---

## Request Lifecycle

### Standard chat request (`POST /chat`)

```
1. Browser sends POST /chat with { message, persona, session_id }

2. main.py
   └── validate session token (JWT if multi-user enabled)
   └── load session history from db.py
   └── resolve persona from personas.py
   └── call agent.run_agent() → yields SSE events

3. agent.run_agent()
   └── build system prompt (persona + memory injection)
   └── call model_router.select_provider() to pick LLM
   └── send messages to LLM with tool definitions
   └── stream response tokens → yield `token` events to client
   └── if LLM calls a tool:
       └── yield `tool_start` event
       └── dispatch to tools_builtin.dispatch_builtin()
       └── yield `tool_result` event
       └── feed tool result back into context
       └── continue loop (up to 16 iterations)
   └── when LLM calls `respond` tool → yield `done` event

4. model_router.select_provider()
   └── score task complexity (high/medium/low)
   └── try providers in priority order
   └── skip providers in cooldown (after 429)
   └── return first available provider + model

5. SSE stream closes → client renders final message
```

### Autonomy request (`POST /autonomy/execute`)

```
1. Client sends a high-level task description

2. autonomy.py Orchestrator
   └── PlanningSystem breaks task into subtasks
   └── classify_subtask() determines tool/agent per step
   └── execute subtasks sequentially or in parallel
   └── emit structured events: plan, subtask, tool, result
   └── emit autonomy_done when all subtasks complete
```

---

## Autonomous Runtime Loop

Nexus AI now models autonomous development as a closed loop with explicit handoff boundaries:

```
Supervisor -> Orchestrator -> Autonomizers -> Enforcers -> Orchestrator -> Supervisor
```

### Layer Map

| Layer | Primary Responsibility | Skill Roles |
|---|---|---|
| Supervisor | Set mission intent, policy, risk tolerance, and release priorities | Human operator (project owner) |
| Orchestrator | Plan, decompose, schedule, arbitrate conflicts, maintain world state | `nexus-ai-state-machine-governor`, `nexus-ai-task-decomposer`, `nexus-ai-conflict-resolution-lead`, `nexus-ai-resource-scheduler` |
| Autonomizers | Execute implementation loops, self-correct, monitor drift, and report telemetry | `nexus-ai-self-correcting-coder`, `nexus-ai-ci-cd-autopilot`, `nexus-ai-dependency-watcher`, `nexus-ai-synthetic-user-simulator`, `nexus-ai-telemetry-visualizer`, `nexus-ai-intent-alignment-verifier`, `nexus-ai-ask-for-help-protocol` |
| Enforcers | Validate safety, security, privacy, and compliance constraints before promotion | Existing guardrail and policy skills such as `nexus-ai-guardrails-enforcer`, `nexus-ai-red-teamer`, `nexus-ai-privacy-preserving-engineer`, `nexus-ai-compliance-officer` |

### Loop Semantics

1. Supervisor sets objective and policy constraints.
2. Orchestrator converts objective into atomic tasks, assigns model budget, and defines acceptance checks.
3. Autonomizers execute tasks in iterative build-test-fix loops and emit structured telemetry.
4. Enforcers gate progress by running safety/compliance checks and blocking unsafe transitions.
5. Orchestrator updates world state (`complete`, `buggy`, `blocked`, `next`) and either re-plans or escalates.
6. Supervisor receives summarized status, approves directional changes, or revises intent.

This design keeps planning authority centralized, execution specialized, and governance explicit.

---

## Component Deep-Dives

### main.py — API Gateway

**Responsibilities:** HTTP routing, auth, CORS, static file serving, SSE connection management.

**Key endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serve web UI |
| `POST` | `/chat` | Streaming agent chat (SSE) |
| `POST` | `/v1/chat/completions` | OpenAI-compatible completions |
| `GET` | `/v1/models` | OpenAI-compatible model list |
| `POST` | `/autonomy/execute` | Multi-step orchestrated task |
| `POST` | `/autonomy/plan` | Plan-only (dry run) |
| `GET` | `/autonomy/trace/{trace_id}` | Retrieve execution trace |
| `GET` | `/providers/status` | Provider health + cooldown state |
| `GET` | `/usage` | Token/cost usage summary |
| `POST` | `/auth/register` | Create user account |
| `POST` | `/auth/login` | Authenticate, returns JWT |
| `GET` | `/auth/me` | Current user info |
| `POST` | `/webhook/trigger` | External webhook trigger |
| `GET` | `/webhook/status/{run_id}` | Webhook run status |
| `POST` | `/rag/ingest` | Ingest document into vector store |
| `POST` | `/rag/query` | Query vector store |

**Auth model:** JWT Bearer tokens. When `MULTI_USER=false` (default), auth is skipped. When enabled, all `/chat` and sensitive endpoints require `Authorization: Bearer <token>`.

---

### agent.py — Agent Loop

**Responsibilities:** Build the context window, run the LLM tool-call loop, stream tokens and events, handle retries.

**Loop invariants:**
- Maximum 16 tool-call iterations per request (prevents runaway loops)
- Every tool call emits a structured `_tool_trace` dict: `{ tool, args, result, duration_ms }`
- `think` and `plan` are first-class tool calls — they emit visible events before the LLM continues
- The loop terminates when the LLM calls `respond` or when the iteration cap is reached

**Streaming event types (SSE `data:` payloads):**

| Event | Payload |
|---|---|
| `token` | `{ text: string }` |
| `tool_start` | `{ tool: string, args: object }` |
| `tool_result` | `{ tool: string, result: any, duration_ms: number }` |
| `plan` | `{ steps: string[] }` |
| `subtask` | `{ id, parent_id, status, metadata }` |
| `think` | `{ reasoning: string }` |
| `done` | `{ message: string, usage: object }` |
| `error` | `{ message: string, code: string }` |

---

### model_router.py — Provider Routing

**Responsibilities:** Abstract away all provider differences, manage cooldowns, score task complexity, implement the fallback chain.

**Complexity scoring:**

```python
HIGH   → new projects, architecture, full file generation, debugging unknown errors
MEDIUM → code edits, explanations, summarisation, translations
LOW    → simple Q&A, conversions, lookups
```

High-complexity tasks are routed to the strongest available model first (Ollama local, Claude, Grok, Gemini). Low-complexity tasks are routed to the fastest/cheapest (LLM7.io, Groq).

**Cooldown mechanism:** When a provider returns HTTP 429, it is placed in a cooldown map with an expiry timestamp (`RATE_LIMIT_COOLDOWN` seconds, default 60). During cooldown the provider is skipped entirely.

**Provider interface contract:** Every provider is expected to accept an OpenAI-compatible `POST /v1/chat/completions` payload. Normalisation adapters handle provider-specific deviations (DeepSeek `reasoning_content`, Gemini function-call IDs, etc.).

---

### personas.py — Persona System

**Responsibilities:** Define system prompt templates, temperature, provider preferences, and UI styling per persona.

**Built-in personas:**

| ID | Name | Temp | Provider preference |
|---|---|---|---|
| `general` | ⚡ General | 0.2 | Auto |
| `coder` | 💻 Coder | 0.1 | High-tier first |
| `researcher` | 🔬 Researcher | 0.3 | Web-search capable providers |
| `creative` | 🎨 Creative | 0.8 | Auto |
| `nexus_prime` | 🔷 Nexus Prime Cloud | 0.05 | Claude / highest-tier |

Custom personas are stored in the database and loaded at runtime. The persona system does **not** replace user profiles — personas are AI personality configs; user profiles (preferences, history) are a separate future layer (`profiles.py`).

---

### tools_builtin.py — Tool Registry

**Responsibilities:** Implement and register all built-in tools. Return structured `_tool_trace` dicts.

**Safety boundaries:**
- `run_command`: 256 MB RAM cap, 10s CPU time, 60s wall clock timeout. Cannot access `/app` (source tree) — blocked at the argument level.
- `write_file` / `delete_file`: scoped to a per-session working directory. Cannot write outside it.
- `clone_repo` / `commit_push` / `create_repo`: require `GH_TOKEN` env var; operations are logged.

Adding a new tool requires: implementation in `tools_builtin.py` + entry in the tool definitions list + entry in `CONTRIBUTING.md` docs table.

---

### autonomy.py — Orchestrator

**Responsibilities:** Break a high-level task into a DAG of subtasks, execute them in dependency order, emit structured progress events.

**Key classes:**
- `Orchestrator` — top-level task execution engine
- `PlanningSystem` — LLM-backed plan generation (produces a list of `SubTask` objects)
- `classify_subtask(task)` — heuristic + LLM classifier that assigns tools/agents per subtask

The orchestrator is the foundation for future multi-agent spawning and hierarchical Planner → Executor → Reviewer → Verifier patterns (see [docs/ROADMAP_FEATURES_V2.md](ROADMAP_FEATURES_V2.md)).

---

### memory.py — Memory System

**Responsibilities:** Manage short-term session context and long-term semantic memory.

**Two-layer model:**
1. **Session memory** — the raw conversation history for the current session, stored in SQLite and truncated when approaching the context window limit (`_maybe_compress_history`).
2. **Vector memory** — ChromaDB-backed semantic store. Past conversations are embedded and indexed. Relevant memories are injected at the top of the context window at session start.

**Memory injection:** The last 5 conversation summaries are prepended to every new session context. This gives the agent continuity across sessions without blowing the context window.

---

### thinking.py — Reasoning Helpers

**Responsibilities:** Implement Tree-of-Thought (`think_deep`) and chain-of-thought (`think`) reasoning patterns, expose them as tools the agent can call.

`think_deep` generates multiple reasoning branches, scores them by coherence and completeness, and selects the highest-scoring branch before producing the final answer. It is expensive (2–4× token cost of a standard response) and should only be used for genuinely complex multi-step problems.

---

### rag/ — Retrieval-Augmented Generation

**Responsibilities:** Ingest documents into a local vector store, answer queries by retrieving relevant chunks and synthesising a grounded answer.

```
ingest.py
  └── load document (PDF, txt, md, HTML)
  └── chunk with sliding window (512 tokens, 50 token overlap)
  └── embed with local Ollama or Groq embeddings
  └── write to ChromaDB collection

query.py
  └── embed query
  └── retrieve top-K chunks from ChromaDB
  └── rerank by relevance score
  └── assemble context string
  └── call agent with context prepended
```

When ChromaDB is unavailable, the RAG layer falls back to recency-based retrieval (most recent N document chunks loaded directly).

---

### db.py — Persistence

**Responsibilities:** Define SQLAlchemy models for chat history, usage records, user accounts, and saved sessions.

**Backends:** SQLite (default, zero-config) or PostgreSQL (set `DATABASE_URL`). The schema is identical for both; SQLite is recommended for single-user self-hosted deployments, PostgreSQL for multi-user or high-volume deployments.

**Models:**
- `ChatSession` — session metadata (id, user_id, persona, created_at)
- `ChatMessage` — individual messages (session_id, role, content, tool_traces, timestamp)
- `User` — account (id, username, hashed_password, created_at)
- `UsageRecord` — per-request token counts and estimated cost (provider, model, in_tokens, out_tokens, cost_usd)

---

## Data Flow Diagrams

### Streaming chat flow

```
Client                  main.py              agent.py          model_router.py      LLM Provider
  │                        │                     │                    │                    │
  │── POST /chat ─────────►│                     │                    │                    │
  │                        │── run_agent() ─────►│                    │                    │
  │                        │                     │── select_provider()►│                    │
  │                        │                     │                    │── try provider 1 ──►│
  │                        │                     │                    │◄─ 429 ─────────────│
  │                        │                     │                    │── cooldown p1      │
  │                        │                     │                    │── try provider 2 ──►│
  │                        │                     │◄── provider handle─│◄─ 200 stream ──────│
  │◄── SSE: token ─────────│◄── yield token ─────│                    │                    │
  │◄── SSE: tool_start ────│◄── yield tool ──────│                    │                    │
  │◄── SSE: tool_result ───│◄── yield result ────│                    │                    │
  │◄── SSE: done ──────────│◄── loop complete ───│                    │                    │
```

---

## Provider Fallback Chain

```
Priority  Provider          Model                       Free tier
────────  ────────          ─────                       ──────────
1         Ollama (local)    configured model            Unlimited (local compute)
2         LLM7.io           DeepSeek-R1-7B              Always free, no key
3         Groq              llama-3.3-70b-versatile     14,400 RPD
4         Cerebras          llama-3.3-70b               30 RPM
5         Gemini            gemini-2.0-flash            1,500 RPD
6         Mistral           mistral-small-latest        1B tok/month
7         OpenRouter        llama-3.3-70b:free          20 RPM
8         Cohere            command-r-plus              1K req/month
9         GitHub Models     Llama-3.3-70B               150 RPD
10        Grok (xAI)        grok-3                      Paid
11        Claude            claude-sonnet-4             Paid
```

Any provider returning 429 is placed in cooldown and skipped on the next attempt. The chain is re-evaluated on every request.

---

## Streaming Architecture

All responses use **Server-Sent Events (SSE)** over a persistent HTTP connection. The client does not poll; it holds one connection open per request and receives events as they are emitted.

Why SSE over WebSockets: SSE is simpler (one-directional, works through HTTP/2 multiplexing, no handshake overhead), and Nexus AI's response model is always server-push. WebSockets are reserved for future real-time collaboration features.

The `EventSourceResponse` from `sse-starlette` handles backpressure automatically. If the client disconnects mid-stream, the generator is cancelled and the LLM call is aborted.

---

## Security Boundaries

| Boundary | Protection |
|---|---|
| Shell execution (`run_command`) | 256 MB RAM, 10s CPU, 60s timeout; `/app` path blocked |
| File writes | Scoped to session working directory |
| API key handling | Keys live in env vars only; never logged, never sent to LLM in context |
| JWT tokens | HS256, configurable expiry, secret via `JWT_SECRET` env var |
| GitHub tokens | Stripped from all message context before LLM call |
| Multi-user isolation | Each user's sessions and history are query-isolated by `user_id` |
| Webhook HMAC | Optional `WEBHOOK_SECRET` for HMAC-SHA256 request validation |

See [SECURITY.md](../SECURITY.md) for the full security policy and vulnerability disclosure process.

---

## Configuration Reference

All configuration is via environment variables. A full reference lives in `.env.example`. Key variables:

| Variable | Default | Effect |
|---|---|---|
| `PROVIDER` | `auto` | Provider selection mode |
| `LLM_MODEL` | per-provider default | Override the model name |
| `DATABASE_URL` | `sqlite:///nexus.db` | SQLite or PostgreSQL URL |
| `MULTI_USER` | `false` | Enable JWT auth |
| `JWT_SECRET` | random at boot | JWT signing secret (set in prod!) |
| `SESSION_RATE_LIMIT` | `30` | Max requests/minute per session |
| `RATE_LIMIT_COOLDOWN` | `60` | Seconds to cool down a 429'd provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `NEXUS_AI_URL` | — | Self-referential URL for ecosystem integration |
| `MCP_TOOLS` | — | Comma-separated MCP server URLs |
| `WEBHOOK_SECRET` | — | HMAC secret for webhook validation |

---

## Deployment Topology

### Minimal (single-user, local)

```
localhost:8000
    └── Nexus AI (Python process)
        └── SQLite (nexus.db)
        └── ChromaDB (./chroma/)
```

### Recommended self-hosted (Docker Compose)

```
host:8000
    └── nexus-ai container
        ├── FastAPI app
        ├── SQLite or PostgreSQL
        └── ChromaDB
    └── ollama container
        └── Ollama API :11434
            └── model weights (volume)
```

### Multi-user production

```
Caddy / Nginx (TLS, reverse proxy)
    └── nexus-ai container (MULTI_USER=true, JWT_SECRET=<strong secret>)
        └── PostgreSQL (external or container)
        └── ChromaDB (container or managed)
    └── ollama container (GPU passthrough)
```

---

*For open questions and proposals, open a GitHub Discussion. For security matters, see [SECURITY.md](../SECURITY.md).*
