# Nexus AI — Roadmap

**Vision**: A sovereign, self-hosted AI platform that rivals or exceeds the intelligence, agency, and capabilities of DeepSeek, Grok, Claude, Gemini, GPT-5, and any closed-source frontier model — while remaining 100% private, unlimited, and under your control.

**Core Principle**: The user never thinks about models, limits, or routing. They choose a **mode/persona** (or create new ones) and prompt. Everything else is handled invisibly by the system.

---

## Execution Guardrails (Must Follow)

- Build in dependency order, never feature order:
  - Foundation contracts first (schemas, capability metadata, typed errors, tool interfaces)
  - Runtime second (routing, orchestration, safety middleware, memory window management)
  - UX third (dashboards, advanced views, visual controls)
- Any roadmap item that depends on missing contracts is automatically blocked until the contract item is complete.
- Any checked item must map to concrete code paths/endpoints before it stays checked.
- New capability imports from VersaAI/Nexusclaw/DeerFlow/OSS are accepted only when they preserve Nexus AI's zero-friction default UX (`PROVIDER=auto`, no mandatory provider tuning by user).

---

## ✅ Phase 0 — Foundation (Already Shipped)

### Core agent

- Streaming SSE responses with word-by-word typewriter
- Stop button — cancel mid-stream
- Tool-call loop (up to 16 steps per request)
- `think` — internal reasoning step shown as 💭
- `plan` — announces build plan before executing, shown as 📋 card
- `clarify` — asks focused questions before complex tasks, with clickable option chips
- Multi-turn clarify — answers carry original task context

### Providers & routing

- 11-provider fallback chain (Ollama/glm-5.1:cloud #1 → LLM7.io → Groq → Cerebras → Gemini → Mistral → OpenRouter → Cohere → GitHub Models → Grok → Claude)
- Ollama local inference with OpenAI-compatible API
- LLM7.io keyless fallback — always available, zero config
- Auto-fallback on 429 with configurable cooldown per provider
- Smart complexity routing — high/medium/low scoring routes tasks to appropriate model tier
- Live provider status drawer with countdown timers
- Settings panel — switch provider, model override, temperature without redeployment

### Personas

- ⚡ General (balanced, temp 0.2)
- 💻 Coder (expert engineer, temp 0.1, high-tier providers first)
- 🔬 Researcher (cites sources, heavy web_search, temp 0.3)
- 🎨 Creative (vivid writer, image prompt crafter, temp 0.8)
- 🔷 Nexus Prime Cloud (lead architect of the Nexus Systems Ecosystem, temp 0.05)
- Custom persona editor — create personas with custom system prompts and colors

### Built-in tools (no API key)

- `get_time` — any timezone with natural aliases
- `calculate` — safe math eval with full math module
- `weather` — wttr.in, no key
- `currency` — open.er-api.com, no key
- `convert` — 30+ unit conversions
- `regex` — pattern tester
- `base64` — encode/decode
- `json_format` — pretty-print and validate
- `generate_image` — Pollinations.ai/flux, no key, renders inline
- `nexus_status` — live Nexus Systems Ecosystem status
- `ollama_list_models` — list all locally available Ollama models

### File & repo tools

- `write_file` — writes to session workdir; HTML/SVG auto-renders as artifact
- `read_file`, `list_files`, `delete_file`
- `clone_repo` — clones any public or private GitHub repo
- `run_command` — sandboxed shell (256MB RAM cap, 10s CPU, 60s timeout)
- `commit_push` — stage, commit, push to target repo
- `create_repo` — create a new GitHub repo via API then push to it
- Dynamic repo targeting — agent works on any repo mentioned in chat
- Token extraction + redaction — tokens stripped from messages before reaching any LLM

### Reasoning & intelligence

- `think_deep` — Tree-of-Thought reasoning for complex multi-step problems
- Auto-retry on malformed/bad output (1 automatic retry)
- Confidence scoring — model reports confidence 0-1, shown as badge
- `_maybe_compress_history` — auto-compress older turns when context fills
- Semantic vector memory (Chroma) — local Ollama or Groq embeddings
- Recency fallback when vector DB unavailable

### Memory

- Conversation summaries saved after each chat (background thread)
- Last 5 summaries injected as context at start of new sessions
- Memory count in sidebar with clear button

### Chat & history

- Session history (multi-turn conversation context within a session)
- Chat history sidebar — save, reload, delete conversations
- Auto-generated title from first message
- Export chat as `.md` download
- Share chat via read-only link (`/share/{id}`)
- Full-text search across saved chats

### Input

- File upload — drag & drop or button; text inlined, images as base64
- Voice input — Web Speech API, interim results live in textarea
- GitHub token input via 🔑 button (never sent to LLM)

### Infrastructure

- Multi-user auth (JWT) — register/login/me endpoints, bcrypt passwords
- Webhook triggers — POST /webhook/trigger + status endpoint
- MCP server support — configure external tools via MCP_TOOLS env var
- Rate limiting per session (SESSION_RATE_LIMIT env var, default 30/min)
- Usage dashboard — provider breakdown, token counts, estimated cost
- Provider health monitoring — detect degraded providers before they 429
- Cost tracking — estimated spend across paid providers (Grok, Claude)

### UI & rendering

- Syntax-highlighted code blocks (Highlight.js, atom-one-dark)
- Inline artifact renderer — HTML/SVG in sandboxed iframe with expand/open/copy
- Inline image bubbles with prompt caption, click to open full res
- Markdown rendering (tables, blockquotes, code, lists)
- Code viewer for file write/read operations
- Multi-file artifact viewer — tabbed view when agent creates multiple related files
- Resizable split view — chat on left, artifact preview on right
- Dark/light theme toggle
- Font size preference
- Keyboard shortcuts — Cmd+K new chat, Cmd+/ sidebar, Esc stop
- Message reactions — 👍👎 per response, stored server-side

### Mobile & PWA

- Installable PWA (manifest.json + service worker)
- Swipe right from left edge → opens sidebar; swipe left → closes
- Haptic feedback on send, tool calls, completion
- Safe-area insets for notched phones
- 44px touch targets throughout

### Security

- Sandbox protection — agent can never push to Nexus AI repo from external tasks
- /app path protection — write/delete/run_command blocked from touching app source
- Sandbox execution (256MB RAM cap, 10s CPU, 60s timeout per command)

---

## 🧠 Phase 1 — Super Intelligence Layer (Next 2–4 weeks)

### Advanced reasoning

- [x] **Graph-of-Thought** — graph-based reasoning beyond tree (Sprint D)
- [x] **Self-critique loop** — agent reviews own answer before responding (Sprint C)
- [x] **Cross-model consensus** — run same task on 3 models, reconcile results (Sprint D)
- [x] **Mixture-of-Experts routing** — route subtasks to specialist model variants (Sprint C)

### Model expansion

- [x] Add 20+ more Ollama/cloud models by default (Qwen2.5-72B, DeepSeek-R1-70B, Llama-4 variants, Gemma-3, etc.) (Sprint F)
- [x] Auto-select best Ollama model based on task type (coding vs reasoning vs creative) (Sprint F)
- [x] Model benchmark dashboard — auto-benchmark new Ollama pulls (Sprint D)

### Memory & context

- [x] **Long-context summarization** — multi-step compression when window fills (Sprint D)
- [x] Persistent vector store with filtering by date/tags/persona (Sprint E)
- [x] Memory pruning — auto-delete low-value or outdated memories (Sprint C)

### Streaming & feedback

- [x] **Streaming token counter** — live input/output token count per response (Sprint E)
- [x] Live confidence + reasoning trace badge in UI — SSE events (Sprint E)
- [x] Per-message feedback — 👍👎 stored as training signal (Sprint E)

---

## 🤖 Phase 2 — Multi-Agent Empire (Next 4–8 weeks)

- [x] **Hierarchical orchestration** — Planner → Executor → Reviewer → Verifier (Sprint F)
- [x] **Specialist agent library** (out-of-the-box) (Sprint F):
  - Architect Agent
  - Security Auditor Agent
  - UI/UX Designer Agent
  - Data Scientist Agent
  - Product Manager Agent
  - Debugger Agent
  - Documentation Writer Agent
  - Code Reviewer Agent
- [x] **Dynamic agent spawning** based on task complexity and type (Sprint G)
- [x] **Agent marketplace** — JSON-defined agents that users can import/share (Sprint G)
- [x] **Agent-to-agent communication** — shared workspace + message passing (Sprint G)
- [ ] **Swarm View UI** — watch the agent empire work in real-time

---

## 📡 Phase 3 — Multi-Modal & Sensory Layer

- [ ] **Vision** — image understanding (via local Llava, Qwen2-VL, or Ollama vision models)
- [ ] **Image generation** — Pollinations + local Flux/SD3 + video models
- [ ] **Video generation** — local video model support via Ollama
- [ ] **PDF/Office document understanding** — extract and reason over any document
- [ ] **YouTube/video summarization** — transcript + visual analysis
- [ ] **Screenshot tool** — capture webpage and attach as image context
- [ ] **Voice I/O** — Web Speech STT + local TTS via Piper/OpenVoice
- [ ] **Audio analysis** — transcribe + sentiment + speaker diarization

---

## 🧬 Phase 4 — Sovereign AI Operating System

- [ ] **Autonomous agents** — persistent background agents, scheduled, webhook-triggered
- [ ] **Long-term memory graph** — vector + structured knowledge graph (Neo4j or SQLite)
- [ ] **Per-user rate limits + quotas** — fair access across all users
- [ ] **Fine-tuning / LoRA adapter management** — one-click training on your data
- [ ] **Self-improvement loop** — agent reviews own past performance, suggests prompt/tool improvements
- [ ] **Diff viewer** — visual before/after for every file edit
- [ ] **Native database tools** — SQLite + PostgreSQL read/write with schema introspection

---

## 🛡️ Phase 5 — Enterprise & Ecosystem Scale

- [ ] **Multi-user dashboard** — usage, costs, agent activity per user
- [ ] **Nexus Systems integration** (full stack):
  - Nexus Tunnel (#80) — automatic public URLs for all hosted tools
  - Nexus Guardian — Jarvis-style founder alerts
  - Nexus Edge — edge computing and IoT orchestration
  - Nexus Systems API — unified REST + WebSocket integration layer
  - Nexus AI Hub — central model registry and agent marketplace
- [ ] **Custom CSS variables per persona** — full UI theming
- [ ] **Command palette** — Cmd+K for everything
- [ ] **Nexus Blueprint export** — one-click deploy entire agent swarm to new server
- [ ] **Open-source model leaderboard** — auto-benchmark every Ollama model you pull

---

## External Capability Synthesis (Scanned Inputs -> Nexus AI Plan)

### Frontier Reference Set (explicit)

We actively benchmark and borrow ideas from widely used AI systems, including:

- DeepSeek (reasoning quality, cost/performance routing)
- Claude (tool-use reliability, long-context behavior)
- GPT-5 class systems (broad capability consistency, structured output quality)
- Gemini (multimodal handling and latency tradeoffs)
- Grok (real-time style interactions and provider economics)
- Open-weight ecosystem families (Llama, Qwen, Mistral, Gemma)

Rule: borrow patterns and interfaces, not lock-in. Nexus AI remains self-hosted first and provider-agnostic.

### Source A: VersaAI (deep internal scan)

- Port first (foundation contracts):
  - `api/schemas.py` style OpenAI-compatible request/response schema normalization
  - `api/errors.py` style typed error taxonomy + status mapping
  - `models/model_base.py` + `model_registry.py` interfaces for local model lifecycle
  - `agents/tools/base.py` typed tool registry and safety levels
  - `safety/types.py` canonical safety verdict model
- Port second (high-leverage runtime):
  - `memory/context_window.py` dynamic context compression
  - `models/model_ensemble.py` consensus routing for high-risk tasks
  - safety pipeline (`input_filter` -> `guardrails` -> `output_filter`)
  - structured web search tool with citations and cache

### Source B: Nexusclaw compatibility scan

- Highest-priority Nexus AI contract gaps to close:
  - `/v1/embeddings` endpoint for ecosystem compatibility
  - model capability metadata (supports vision/json/tool-use/reasoning)
  - explicit `response_format` JSON mode handling
  - stable provider health/capability endpoint for orchestrators
- Rule: prioritize compatibility endpoints before adding net-new UI features.

### Source C: DeerFlow scan

- Practical imports for next 1-2 months:
  - generator-critic research loop with citation validation
  - checkpointed long-running task orchestration
  - deterministic replay for failed multi-step runs
  - optional HITL checkpoints for risky actions (off by default)

### Source D: Broader OSS AI patterns

- Adopt:
  - strict contract tests for OpenAI-compatible endpoints
  - model/provider capability matrices feeding auto-router decisions
  - auditable safety decision logs with low overhead
- Avoid:
  - exposing provider complexity in the default UX path
  - coupling roadmap claims to unverified prototypes

### Source E: MiroFish (github.com/666ghj/MiroFish) — inspiration only, no code import

**What MiroFish is:** A swarm intelligence simulation engine that spawns hundreds of
persona-agents from seed material (news articles, policy drafts, documents), runs
configurable rounds of social evolution between them, and produces a structured
prediction report.

**License:** AGPL-3.0 — no code is imported. All implementations are original.

**Patterns we borrow:**
- `simulate` tool concept — seed a topic, generate N persona-agents with distinct
  viewpoints, run debate rounds, synthesise a prediction/consensus report
- GraphRAG seed extraction — chunk seed material into a knowledge graph before agent
  instantiation (will use our existing RAG system)
- Dual-platform parallel simulation — run persona agents across multiple providers
  simultaneously (maps to our existing ensemble infrastructure)
- ReportAgent pattern — a dedicated synthesis agent that queries the simulation state
  and produces a structured report (maps to our `HierarchicalOrchestrator` Reviewer stage)
- Dynamic temporal memory updates — each persona accumulates memory across simulation
  rounds (maps to our Chroma vector store per-agent scoped writes)

**What we do NOT adopt:**
- Zep Cloud dependency (we use our own Chroma + SQLite memory)
- Vue frontend (we keep the existing SSE-first chat UI)
- The full thousands-of-agents scale (our `simulate` tool targets 3–12 personas for
  practical latency on self-hosted hardware)

**Roadmap items derived from MiroFish:**
- `simulate` tool (Phase 2, Sprint G) — complete
- Swarm View UI (Phase 2, remaining) — shows active personas + round progress
- Long-term memory graph (Phase 4) — per-persona knowledge graph with temporal edges

Execution artifact for this section: `EXTERNAL_BORROW_MATRIX.md` (concrete borrow matrix + sprint-ready implementation tickets).

---

## 🔄 VersaAI Component Porting Tracker

> Tracks which VersaAI subsystems have been ported into Nexus AI, what's in progress, and what's queued.
> **Note on Personas vs Profiles:** Nexus-AI `personas.py` = AI personality presets (system prompts, tone, temperature). VersaAI `profiles.py` = persistent *user* profiles (preferences, behavioral history, goals, connectors). They are different — `profiles.py` should be ported as a user data layer, not a replacement for personas.

### ✅ Already Ported

| Module | What was brought over |
|---|---|
| `versaai/rag/` | Full RAG subsystem (ChromaDB, ingest, query, status) — under `Nexus-AI/rag/` |
| `versaai/models/model_router.py` | Smart complexity-based model routing — `Nexus-AI/model_router.py` |
| `versaai/agents/orchestrator.py` | Core orchestrator + planning system — `Nexus-AI/autonomy.py` (`Orchestrator`, `PlanningSystem`, `classify_subtask`) |
| `versaai/agents/` (streaming events) | Subtask event streaming — `agent.py` emits `plan`, `subtask`, `tool` structured events with `id`/`parent_id`/`status`/`metadata` |
| `versaai/tools/` (structured traces) | `dispatch_builtin` returns structured `_tool_trace` dicts instead of raw strings |
| `versaai/api/` (autonomy routes) | `/autonomy/execute`, `/autonomy/plan`, `/autonomy/trace/{trace_id}` endpoints in `main.py` |

---

### 🚨 High Priority — Port Next

| Module | What it does | Status |
|---|---|---|
| `versaai/safety/pii.py` | PII detector (email, phone, SSN, credit cards, passport, IP, DoB) using regex + Luhn algorithm | ⬜ not started |
| `versaai/safety/prompt_injection.py` | Prompt injection & jailbreak detection — structural analysis, entropy, control chars, base64/ROT13 evasion | ⬜ not started |
| `versaai/safety/classifier.py` | Content classifier: toxic, hate speech, sexual, violence, self-harm, CSAM, illegal activity — with threat level scoring | ⬜ not started |
| `versaai/safety/guardrails.py` | Central guardrail orchestrator — composes PII + injection + classifier into a single `screen_input`/`screen_output` pipeline | ⬜ not started |
| `versaai/safety/input_filter.py` | Input screening: size limits, control-char stripping, PII redaction, injection detection | ⬜ not started |
| `versaai/safety/output_filter.py` | Output screening: content classification, domain guards, PII scrubbing, action escalation | ⬜ not started |
| `versaai/safety/domain_guards.py` | Domain-specific guards: `MedicalGuard`, `FinancialGuard`, `LegalGuard` with warn/block modes | ⬜ not started |
| `versaai/safety/audit.py` | Safety audit log — ring buffer, persistence, blocked content tracking, forensic analysis | ⬜ not started |
| `versaai/safety/middleware.py` | ASGI middleware — auto-screens every request/response; SSE streaming support; 403 blocking | ⬜ not started |
| `versaai/memory/context_window.py` | Dynamic context window compression — token counting, priority-based truncation, importance scoring | ⬜ not started |
| `versaai/memory/knowledge_graph.py` | Entity-relationship graph with multi-hop BFS/DFS traversal and temporal reasoning | ⬜ not started |
| `versaai/agents/reasoning.py` + `reasoning_agent.py` | ReasoningEngine: Chain-of-Thought, ReAct, Tree-of-Thoughts, Self-Consistency with LLM step verification | ⬜ not started |
| `versaai/agents/research_agent.py` | Research agent: adaptive retrieval (search + vector DB + KG), generator-critic pattern, citations, confidence scores | ⬜ not started |
| `versaai/models/model_ensemble.py` | Model ensemble: parallel inference across models, consensus voting, fallback chains | ⬜ not started |
| `versaai/multimodal.py` | Modality detection/routing abstraction for text/image/audio/video/3D/code | ⬜ not started |

---

### 📊 Medium Priority

| Module | What it does | Status |
|---|---|---|
| `versaai/agents/planning_agent.py` | PlanningAgent wrapper with task tracking + progress reporting (complements `autonomy.py`) | ⬜ not started |
| `versaai/memory/episodic.py` | Long-term episodic memory with VectorDB + KG integration, semantic search across sessions, retention policies | ⬜ not started |
| `versaai/rag/critic.py` | RAG critic — LLM evaluation of generated answers against retrieved docs, confidence scoring | ⬜ not started |
| `versaai/rag/query_decomposer.py` | Breaks complex RAG queries into sub-queries for multi-hop retrieval | ⬜ not started |
| `versaai/generation/video_gen.py` | Video generation pipeline with temporal consistency checks | ⬜ not started |
| `versaai/code_editor_bridge/` | Chat/completion services for direct code editor integration | ⬜ not started |
| `versaai/profiles.py` | Persistent **user** profiles — preferences, behavioral history, goals, connectors. Different from Nexus-AI `personas.py` (AI personality presets) | ⬜ not started |
| Cost tracking improvements | Per-token cost estimation across all providers, budget limits, detailed cost breakdown | ⬜ not started |
| Rate limiting improvements | Provider-aware rate limiting with adaptive backoff and exhaustion detection | ⬜ not started |

---

### 💡 Deferred / Skipped

| Module | Decision | Reason |
|---|---|---|
| `versaai/` C++ performance layer | ⏳ **Defer** — port when Nexus AI is at scale | Optimisation for high-load scenarios; not needed at current scale |
| `versaai/generation/model_3d_gen.py` | ❌ **Skip** | Niche use case, high porting effort, low immediate value |
| `versaai/agents/companion_agent.py` | ❌ **Skip** | Non-differentiating; Nexus personas already cover this space |
| `versaai/plugins/blender/` | ⏳ **Defer** | VersaAI Blender add-on (REST API plugin for 3D work). Worth adapting as a "Nexus AI Integrations" ecosystem item later |

---

### 🔍 Additional Missed in First Audit

> These files were not captured in the initial audit pass. Assessed on second review.

| Module | What it does | Value | Action |
|---|---|---|---|
| `versaai/agents/agent_base.py` | Abstract `AgentBase` + `AgentMetadata` dataclass — base class all agents inherit from | Medium | **Port as dependency** when porting agents |
| `versaai/agents/tools/base.py` | Formal tool plugin framework: abstract `Tool`, `ToolResult`, `SafetyLevel` enum, `ToolRegistry` with schema generation for LLM function-calling | High | **Port** — replaces ad-hoc dispatch with a proper typed tool system |
| `versaai/agents/tools/web_search.py` | Multi-backend web search tool (SearXNG self-hosted → Brave API → DuckDuckGo scraper fallback), LRU cache, structured `ToolResult` with citations | High | **Port** — significantly better than current ad-hoc `web_search` action |
| `versaai/agents/tools/file_ops.py` | File operations tool (read/write/list/delete) conforming to `Tool` base with `SafetyLevel` tagging | Low | **Port as dependency** alongside tool framework |
| `versaai/agents/tools/shell.py` | Shell execution tool with sandbox constraints, conforming to `Tool` base | Low | **Port as dependency** alongside tool framework |
| `versaai/agents/tools/rag_query.py` | RAG query as a formal `Tool` — agents can call it via the tool framework | Low | **Port as dependency** of tool framework |
| `versaai/memory/conversation.py` | `ConversationManager` with entity extraction, topic drift detection, turn pruning, `get_context_for_generation()` — richer than current `memory.py` | High | **Port** — upgrades conversation memory with entity tracking |
| `versaai/models/model_base.py` | Abstract `ModelBase` + `ModelMetadata` dataclass — interface for all model loaders | High | **Port** — required foundation for Sovereign Model Stage 1 |
| `versaai/models/model_registry.py` | Central model registry: auto-detects format (GGUF/HF/ONNX), lifecycle management (load/unload), supports hot-swap | High | **Port** — critical for running and managing local models |
| `versaai/models/gguf_model.py` | GGUF/llama.cpp model loader with CPU/CUDA/Metal backend, quantization support, streaming | High | **Port** — load any GGUF model directly, core of Sovereign Model Stage 1 |
| `versaai/models/huggingface_model.py` | HuggingFace `transformers` model loader — load any HF Hub model for inference or fine-tuning | High | **Port** — HuggingFace pipeline needed for LoRA fine-tuning (Sovereign Model Stage 1) |
| `versaai/models/code_llm.py` | Code-specific LLM abstractions (LlamaCpp / HuggingFace / OpenAI / Anthropic backends), `GenerationConfig` | Medium | **Port** — clean interface for code generation models |
| `versaai/api/errors.py` | OpenAI-compatible structured error types (`VersaAPIError`, `ProviderUnavailableError`, `ContextOverflowError`, etc.) with HTTP status mapping | High | **Port** — makes error responses compatible with any OpenAI client library |
| `versaai/api/schemas.py` | OpenAI-compatible Pydantic schemas for chat completions (`ChatMessage`, `ChatCompletionRequest`, etc.) with input size validation | High | **Port** — makes Nexus AI work as a drop-in for LiteLLM, Open WebUI, Continue.dev, Cursor |
| `versaai/safety/types.py` | Core safety type system: `ContentCategory`, `ThreatLevel`, `SafetyAction`, `SafetyVerdict`, `PIIMatch` — required by all safety modules | High | **Port first** — prerequisite for the entire safety subsystem |

---

## 🧬 Sovereign Model Roadmap — Nexus Prime

> **End goal:** Nexus Systems trains, owns, and serves its own frontier AI model — "Nexus Prime" — with zero dependency on any external API, provider, or corporation. At planetary scale (millions → billions of users), Nexus Systems will generate enough interaction data and compute capacity to train a model that rivals or surpasses GPT-5, Gemini Ultra, and Claude — built entirely in-house.

---

### Stage 1 — Nexus Prime Alpha: Fine-tuned (Near Term)

> **Strategy:** Start with open-weight base models (Llama 4, Qwen2.5, DeepSeek-R1) and fine-tune them on Nexus-specific data using LoRA/QLoRA. Result: a model that behaves exactly the way Nexus AI needs, costs nothing to run, and is 100% owned by The No-Hands Company.

- [ ] **Data collection pipeline** — capture high-quality interaction traces from Nexus AI sessions (opt-in, anonymised, GDPR-compliant) as training signal
- [ ] **LoRA fine-tuning harness** — one-click fine-tuning on a base model using collected traces; output: a `.gguf` / adapter file
- [ ] **Nexus Prime Alpha persona** — fine-tuned Llama 4 or Qwen2.5-72B variant; knows the Nexus ecosystem, tools, codebase, and tone natively
- [ ] **Automated eval suite** — benchmark Nexus Prime Alpha vs base model on Nexus-specific tasks (code gen, autonomy, RAG quality, persona consistency)
- [ ] **Ollama integration** — serve Nexus Prime Alpha via Ollama, slot into existing provider chain as priority #0
- [ ] **LoRA adapter versioning** — track adapter versions, roll back if quality regresses
- [ ] **Synthetic training data generation** — use existing agent swarm to generate diverse, high-quality instruction pairs for continued improvement

**Target compute:** 1× NVIDIA A100 80GB (or equivalent) — fine-tuning a 70B model with QLoRA takes ~12-24h.

---

### Stage 2 — Nexus Prime Beta: Continual Learning (Medium Term)

> **Strategy:** Move from one-shot fine-tuning to a continuous feedback loop. Every interaction, correction, and human preference signal feeds back into model improvement. The model gets smarter as more users use Nexus AI.

- [ ] **RLHF / DPO pipeline** — capture 👍👎 signals already stored per message; run Direct Preference Optimisation to align model with user preferences
- [ ] **Continual fine-tuning scheduler** — weekly re-fine-tuning runs on accumulated data; automatic promotion if benchmarks improve
- [ ] **Knowledge distillation** — distil responses from the best external models (Claude, GPT-5, Gemini) into Nexus Prime to bootstrap capability without direct training cost
- [ ] **Multi-task specialisation** — separate LoRA adapters for coding, reasoning, research, creative — hot-swap based on persona/task type
- [ ] **Multimodal extension** — fine-tune vision capabilities into Nexus Prime (Llama 4 Vision / Qwen2-VL base)
- [ ] **Model card & transparency report** — publish training methodology, data sources, evals, bias analysis

---

### Stage 3 — Nexus Prime 1.0: Purpose-Built Architecture (Long Term)

> **Strategy:** At sufficient scale (100M+ users, significant GPU fleet), pre-train a model from scratch using the Nexus Systems institutional dataset. This model will be designed around Nexus's unique requirements — agentic reasoning, long-context tool use, multi-modal I/O, and sovereignty-by-design.

- [ ] **Institutional dataset curation** — curate a multi-trillion token corpus from Nexus interactions, the open web, code repositories, scientific literature, and synthetic data pipelines
- [ ] **Custom transformer architecture** — purpose-built architecture optimised for agentic tool use, long context (1M+ tokens), and streaming inference
- [ ] **Mixture-of-Experts (MoE) design** — sparse MoE with specialist expert routing for coding, reasoning, multimodal, domain knowledge; rivals dense models at fraction of inference cost
- [ ] **Distributed pre-training infrastructure** — multi-node training across Nexus Systems compute fleet (Nexus Edge + Nexus Cloud); FSDP / DeepSpeed ZeRO-3
- [ ] **Nexus Prime 1.0 release** — first fully sovereign, from-scratch model; deployed at nexus-ai.app, replacing all external providers as primary inference
- [ ] **Open-weight release** — publish Nexus Prime 1.0 weights publicly; position The No-Hands Company as a frontier AI lab

---

### Stage 4 — Exascale Nexus Prime: Planetary Intelligence (Vision)

> **Vision:** Millions to billions of Nexus Systems users generate an unprecedented stream of real-world interaction data and, collectively, enormous distributed compute. This scale enables something no single company currently achieves — a continuously learning, federated, privacy-preserving frontier model trained on the broadest possible slice of human knowledge and intent.

- [ ] **Federated learning** — devices running Nexus Systems contribute to model training locally; gradients aggregated without raw data ever leaving the user's machine
- [ ] **User-contributed compute network** — opt-in compute contribution from Nexus Systems users; idle GPU cycles pooled into a training cluster rivalling hyperscaler investments
- [ ] **Continuous pre-training at exascale** — as the user base scales toward billions, training data volume and compute capacity scale proportionally — a self-reinforcing loop
- [ ] **Real-time knowledge integration** — model continuously ingests new knowledge without catastrophic forgetting (via replay buffers + EWC regularisation)
- [ ] **Nexus Prime Frontier** — a model trained on more diverse, real-world, multi-modal data than any closed-source lab can access; the most capable AI system ever built; 100% owned and governed by the Nexus Systems community

> **Note on scale:** At 1B users each sending ~10 messages/day, Nexus Systems generates ~10 billion training examples per day — more than GPT-4 was trained on in total, every single day. This is the compounding advantage that only a truly planetary-scale open platform can achieve.

---

## 🌌 Phase 6 — Frontier Research & Beyond (Ongoing)

- [ ] **Emotional intelligence** — consistent character memory across sessions
- [ ] **Real-time collaboration** — multiple humans + multiple agents in same session
- [ ] **Hardware-aware routing** — prefer GPU-heavy models when available, fall back to CPU models
- [ ] **Synthetic data generation** — self-play training data from agent interactions
- [ ] **Continuous benchmarking** — weekly leaderboard updates from live performance data

---

## Immediate Execution Sequence (Next 3 Sprints)

### Sprint A — Contracts and compatibility baseline

- [x] Add `/v1/embeddings` with OpenAI-compatible schema and contract tests
- [x] Add typed API error mapping (provider unavailable, context overflow, validation)
- [x] Add model capability registry and expose it via health/capability endpoint
- [x] Add strict `response_format` JSON mode behavior for orchestrator clients

### Sprint B — Safety and reliability runtime

- [ ] Add canonical safety types + centralized guardrail pipeline
- [ ] Add context window manager with deterministic truncation/compression policy
- [ ] Add replayable execution traces for multi-step tool runs
- [ ] Add ensemble/consensus mode only for high-risk tasks

### Sprint C — Research-quality outputs with zero-friction UX

- [ ] Add generator-critic research flow with citation confidence scoring
- [ ] Add checkpointed long-run task execution with resumability
- [ ] Add optional HITL approval points for sensitive actions (default off)
- [ ] Keep default user path unchanged: prompt -> response, with complexity hidden

---

## How this keeps the user experience zero-friction

- [x] **Multi-user auth** — JWT Bearer tokens, PBKDF2 hashing, `/auth/register` + `/auth/login` + `/auth/me`
- [ ] **Per-user rate limits** — not fully implemented yet; current implementation is per-session via `SESSION_RATE_LIMIT` (partial)
- [x] **Usage dashboard** — `/usage` endpoint provides provider/token/cost summary
- [x] **Webhook triggers** — `/webhook/trigger` + `/webhook/status/{run_id}` with optional `WEBHOOK_SECRET` validation
- [x] **MCP server support** — `MCP_TOOLS` env var + `mcp_call` action path in agent tool loop
- [x] **Provider health monitoring** — cooldown/state exposure via provider status endpoints and in-agent cooldown tracking
- [x] **Cost tracking** — usage logging + estimated spend fields for paid providers
- User opens Nexus AI → picks persona/mode (or "Auto") → types prompt → done
- The massive model list, swarm of agents, multi-modal tools, and reasoning engines all run invisibly under `PROVIDER=auto`
- Advanced users can open "Agent Console" or "Swarm View" to watch the empire at work
- Sovereign, self-hosted, federated — zero lock-in, 100% private

---

*Last updated: April 2026 (validated against current implementation)*
