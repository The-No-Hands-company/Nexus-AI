# Nexus-AI Roadmap Features V2 (Safe Merge)

Purpose: this is a new roadmap file that preserves legacy planned features and appends audited additions.

Source safety rule:

- Existing `ROADMAP.md` is left unchanged.
- Legacy feature items are carried over here first.
- New items from external scans/audits are added in dedicated sections.

## Execution Guardrails (Must Follow)

- Build in dependency order, never feature order:
  - Foundation contracts first (schemas, capability metadata, typed errors, tool interfaces)
  - Runtime second (routing, orchestration, safety middleware, memory window management)
  - UX third (dashboards, advanced views, visual controls)
- Any roadmap item that depends on missing contracts is automatically blocked until the contract item is complete.
- Any checked item must map to concrete code paths/endpoints before it stays checked.
- New capability imports from VersaAI/Nexusclaw/DeerFlow/OSS are accepted only when they preserve Nexus AI's zero-friction default UX (`PROVIDER=auto`, no mandatory provider tuning by user).

---

## Status Legend

- `[x]` shipped
- `[ ]` not added yet
- `[-]` deferred/skip

## A. Legacy Features Carried Over

### Phase 0 - Foundation (already shipped)

#### Core agent

- [x] Streaming SSE responses with word-by-word typewriter
- [x] Stop button cancel mid-stream
- [x] Tool-call loop (up to 16 steps/request)
- [x] `think` reasoning event
- [x] `plan` event before execute
- [x] `clarify` with focused options
- [x] Multi-turn clarify carrying original task context

#### Providers and routing

- [x] 11-provider fallback chain (Ollama/glm-5.1:cloud -> LLM7.io -> Groq -> Cerebras -> Gemini -> Mistral -> OpenRouter -> Cohere -> GitHub Models -> Grok -> Claude)
- [x] Ollama local inference with OpenAI-compatible API
- [x] LLM7.io keyless fallback
- [x] Auto-fallback on 429 with cooldown
- [x] Smart complexity routing (high/medium/low)
- [x] Live provider status drawer with cooldown timers
- [x] Settings panel for provider/model/temp overrides

#### Personas

- [x] General persona
- [x] Coder persona
- [x] Researcher persona
- [x] Creative persona
- [x] Nexus Prime Cloud persona
- [x] Custom persona editor

#### Built-in tools

- [x] `get_time`
- [x] `calculate`
- [x] `weather`
- [x] `currency`
- [x] `convert`
- [x] `regex`
- [x] `base64`
- [x] `json_format`
- [x] `generate_image`
- [x] `nexus_status`
- [x] `ollama_list_models`

#### File and repo tools

- [x] `write_file`
- [x] `read_file`
- [x] `list_files`
- [x] `delete_file`
- [x] `clone_repo`
- [x] `run_command` sandboxed execution
- [x] `commit_push`
- [x] `create_repo`
- [x] Dynamic repo targeting from chat intent
- [x] Token extraction and redaction before LLM forwarding

#### Reasoning and intelligence

- [x] `think_deep` (Tree-of-Thought)
- [x] Auto-retry on malformed output
- [x] Confidence scoring
- [x] `_maybe_compress_history`
- [x] Semantic vector memory (Chroma)
- [x] Recency fallback when vector unavailable

#### Memory and history

- [x] Conversation summaries persisted
- [x] Last 5 summaries injected at new session start
- [x] Memory count and clear in sidebar
- [x] Session history
- [x] Chat save/load/delete
- [x] Auto title generation
- [x] Export chat as markdown
- [x] Share chat by read-only link
- [x] Full-text search over saved chats

#### Input

- [x] File upload (text inline, images base64)
- [x] Voice input (Web Speech)
- [x] GitHub token input not forwarded to model

#### Infrastructure and security

- [x] Multi-user auth (register/login/me)
- [x] Webhook trigger and status routes
- [x] MCP tool support via `MCP_TOOLS`
- [x] Session rate limiting via `SESSION_RATE_LIMIT`
- [x] Usage dashboard endpoint
- [x] Provider health monitoring
- [x] Cost tracking for paid providers
- [x] Sandbox protection for external task pushes
- [x] App path protection for write/delete/run_command
- [x] Sandboxed command limits (RAM/CPU/timeout)

#### UI and mobile

- [x] Syntax-highlighted code blocks
- [x] Inline artifact renderer for HTML/SVG
- [x] Inline image bubbles
- [x] Markdown rendering
- [x] Code viewer for file ops
- [x] Multi-file artifact tabs
- [x] Resizable split view
- [x] Dark/light theme toggle
- [x] Font size preference
- [x] Keyboard shortcuts (new chat/sidebar/stop)
- [x] Message reactions
- [x] Installable PWA
- [x] Mobile sidebar swipe gestures
- [x] Haptic feedback
- [x] Safe-area inset support
- [x] 44px touch targets

### Phase 1 - Super Intelligence Layer

- [ ] Graph-of-Thought reasoning
- [ ] Self-critique loop
- [ ] Cross-model consensus
- [ ] Mixture-of-Experts routing
- [ ] Add 20+ more Ollama/cloud models by default
- [ ] Auto-select best Ollama model by task type
- [ ] Model benchmark dashboard for new pulls
- [ ] Long-context summarization (multi-step compression)
- [ ] Persistent vector store filters (date/tags/persona)
- [ ] Memory pruning for low-value/outdated items
- [ ] Streaming token counter in UI
- [ ] Live confidence/reasoning trace badge in UI
- [ ] Per-message feedback stored as training signal

### Phase 2 - Multi-Agent Empire

- [ ] Hierarchical orchestration (Planner -> Executor -> Reviewer -> Verifier)
- [ ] Specialist agent library:
- [ ] Architect Agent
- [ ] Security Auditor Agent
- [ ] UI/UX Designer Agent
- [ ] Data Scientist Agent
- [ ] Legal/Compliance Agent
- [ ] Product Manager Agent
- [ ] Debugger Agent
- [ ] Documentation Agent
- [ ] Dynamic agent spawning
- [ ] Agent marketplace (import/share)
- [ ] Agent-to-agent communication workspace
- [ ] Swarm View UI

### Phase 3 - Multi-Modal and Sensory

- [ ] Vision understanding with local vision models
- [ ] Image generation with Pollinations + local Flux/SD3
- [ ] Video generation via local models
- [ ] PDF/Office understanding
- [ ] YouTube/video summarization
- [ ] Screenshot capture tool
- [ ] Voice I/O (STT + local TTS)
- [ ] Audio analysis (transcription/sentiment/diarization)

### Phase 4 - Sovereign AI Operating System

- [ ] Autonomous background agents (schedule/webhook)
- [ ] Long-term memory graph (vector + structured KG)
- [ ] Per-user rate limits and quotas
- [ ] Fine-tuning/LoRA adapter management
- [ ] Self-improvement loop
- [ ] Diff viewer for file edits
- [ ] Native SQLite/PostgreSQL tools with introspection

### Phase 5 - Enterprise and Ecosystem Scale

- [ ] Multi-user dashboard (usage/costs/agent activity)
- [ ] Nexus Systems full-stack integration:
- [ ] Nexus Tunnel (#80)
- [ ] Nexus Guardian
- [ ] Nexus Edge
- [ ] Nexus Systems API
- [ ] Nexus AI Hub
- [ ] Persona-level CSS variables/theming
- [ ] Command palette (Cmd+K for everything)
- [ ] Nexus Blueprint export
- [ ] Open-source model leaderboard

### Phase 6 - Frontier Research and Beyond

- [ ] Emotional intelligence across sessions
- [ ] Real-time collaboration (multi-human + multi-agent)
- [ ] Hardware-aware routing (GPU preferred fallback CPU)
- [ ] Synthetic data generation from agent interactions
- [ ] Continuous benchmarking leaderboard updates

### Immediate execution sequence (legacy carried over)

#### Sprint A

- [x] Add `/v1/embeddings` OpenAI-compatible endpoint + contract tests
- [x] Add typed API error mapping
- [x] Add model capability registry endpoint
- [x] Add strict `response_format` JSON mode behavior

#### Sprint B

- [x] Add canonical safety types + centralized guardrail pipeline
- [x] Add context window manager with deterministic compression policy
- [x] Add replayable execution traces for multi-step tool runs
- [x] Add high-risk-only ensemble/consensus mode

#### Sprint C

- [ ] Add generator-critic research flow with citation confidence
- [ ] Add checkpointed long-run execution with resumability
- [x] Add optional HITL checkpoints (default off)
- [ ] Keep default UX path unchanged

## A2. External Capability Synthesis (Legacy Carried Over)

### Frontier Reference Set

We actively benchmark and borrow ideas from:

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

Execution artifact: `EXTERNAL_BORROW_MATRIX.md` (concrete borrow matrix + sprint-ready implementation tickets).

---

## B. Legacy VersaAI Porting Backlog Carried Over

### Already ported

- [x] RAG subsystem baseline
- [x] Complexity-based model routing
- [x] Core orchestrator/planning baseline
- [x] Structured tool event streaming
- [x] Autonomy routes (`/autonomy/execute`, `/autonomy/plan`, `/autonomy/trace/{trace_id}`)

### High-priority ports

- [ ] `safety/pii.py`
- [ ] `safety/prompt_injection.py`
- [ ] `safety/classifier.py`
- [ ] `safety/guardrails.py`
- [ ] `safety/input_filter.py`
- [ ] `safety/output_filter.py`
- [ ] `safety/domain_guards.py`
- [ ] `safety/audit.py`
- [ ] `safety/middleware.py`
- [ ] `memory/context_window.py`
- [ ] `memory/knowledge_graph.py`
- [ ] `agents/reasoning.py` + `reasoning_agent.py`
- [ ] `agents/research_agent.py`
- [ ] `models/model_ensemble.py`
- [ ] `multimodal.py`

### Medium-priority ports

- [ ] `agents/planning_agent.py`
- [ ] `memory/episodic.py`
- [ ] `rag/critic.py`
- [ ] `rag/query_decomposer.py`
- [ ] `generation/video_gen.py`
- [ ] `code_editor_bridge/`
- [ ] `profiles.py` (user profile layer)
- [ ] Cost tracking improvements
- [ ] Provider-aware adaptive rate-limit controls

### Additional missed modules (carried over)

- [ ] `agents/agent_base.py`
- [ ] `agents/tools/base.py`
- [ ] `agents/tools/web_search.py`
- [ ] `agents/tools/file_ops.py`
- [ ] `agents/tools/shell.py`
- [ ] `agents/tools/rag_query.py`
- [ ] `memory/conversation.py`
- [ ] `models/model_base.py`
- [ ] `models/model_registry.py`
- [ ] `models/gguf_model.py`
- [ ] `models/huggingface_model.py`
- [ ] `models/code_llm.py`
- [ ] `api/errors.py`
- [ ] `api/schemas.py`
- [ ] `safety/types.py`

### Deferred/skip ports

- [-] `versaai/` C++ performance layer (defer)
- [-] `generation/model_3d_gen.py` (skip for now)
- [-] `agents/companion_agent.py` (skip)
- [-] `plugins/blender/` (defer)

## C. New Features Added From Scans and Audits

These are additive items from external project and provider audits beyond the legacy roadmap wording.

### Compatibility and contracts

- [ ] Strict OpenAI Structured Outputs compatibility (schema subset enforcement, refusal-safe behavior)
- [ ] JSON mode safety checks and deterministic validation fallback
- [ ] Stable typed error payload contract (`error.type`, `error.code`, mapped HTTP status)
- [ ] OpenAI-compatible embeddings response shape parity with usage fields
- [ ] Capability metadata endpoint (`tools`, `vision`, `embeddings`, `json_mode`, `reasoning`)

### Tool orchestration and reliability

- [ ] Strict tool argument schema registry for all callable tools
- [ ] Parallel tool-call execution with deterministic merge and call IDs
- [ ] Compositional (sequential chained) tool-call execution support
- [ ] Partial tool-failure recovery policy with typed error continuation
- [ ] High-risk action approval mode (`log`/`warn`/`block`) in safety pipeline

### Routing and operations

- [ ] Budget-aware routing and provider spend guardrails
- [ ] Risk-gated consensus route only for high-impact tasks
- [ ] Persistent checkpoints for long-running orchestration
- [ ] Deterministic trace replay endpoint for failed runs
- [ ] Per-user quota isolation while preserving anonymous session fallback

### Research quality output

- [ ] Citation confidence metadata on research responses
- [ ] Generator-critic pass for research persona outputs
- [ ] Query decomposition path for multi-hop retrieval
- [ ] RAG answer quality critic with confidence calibration

### Provider-specific normalization

- [ ] DeepSeek reasoner normalization (`reasoning_content` handling without leaking provider-specific fields into generic contract)
- [ ] Gemini function-call ID mapping support for parallel/compositional flows
- [ ] Claude strict tool loop lifecycle alignment (`tool_use`/`tool_result` parity semantics)
- [ ] Grok-style async response lifecycle normalization for optional deferred runs

---

## A3. Sovereign Model Roadmap — Nexus Prime (Legacy Carried Over)

> **End goal:** Nexus Systems trains, owns, and serves its own frontier AI model — "Nexus Prime" — with zero dependency on any external API, provider, or corporation.

### Stage 1 — Nexus Prime Alpha: Fine-tuned (Near Term)

- [ ] Data collection pipeline — capture high-quality interaction traces (opt-in, anonymised, GDPR-compliant)
- [ ] LoRA fine-tuning harness — one-click fine-tuning on a base model; output: `.gguf` / adapter file
- [ ] Nexus Prime Alpha persona — fine-tuned Llama 4 or Qwen2.5-72B; knows Nexus ecosystem natively
- [ ] Automated eval suite — benchmark vs base model on code gen, autonomy, RAG quality, persona consistency
- [ ] Ollama integration — serve Nexus Prime Alpha via Ollama as provider chain priority #0
- [ ] LoRA adapter versioning — track adapter versions, roll back if quality regresses
- [ ] Synthetic training data generation — use agent swarm to generate instruction pairs

### Stage 2 — Nexus Prime Beta: Continual Learning (Medium Term)

- [ ] RLHF / DPO pipeline — run Direct Preference Optimisation on stored 👍👎 signals
- [ ] Continual fine-tuning scheduler — weekly re-fine-tuning; auto-promote if benchmarks improve
- [ ] Knowledge distillation — distil responses from Claude, GPT-5, Gemini into Nexus Prime
- [ ] Multi-task specialisation — separate LoRA adapters for coding/reasoning/research/creative; hot-swap
- [ ] Multimodal extension — fine-tune vision capabilities (Llama 4 Vision / Qwen2-VL base)
- [ ] Model card & transparency report — publish training methodology, data sources, evals, bias analysis

### Stage 3 — Nexus Prime 1.0: Purpose-Built Architecture (Long Term)

- [ ] Institutional dataset curation — multi-trillion token corpus from Nexus interactions, open web, code repos, scientific literature, synthetic pipelines
- [ ] Custom transformer architecture — purpose-built for agentic tool use, long context (1M+ tokens), streaming inference
- [ ] Mixture-of-Experts (MoE) design — sparse MoE with specialist expert routing; rivals dense models at fraction of inference cost
- [ ] Distributed pre-training infrastructure — multi-node training across Nexus Systems compute fleet; FSDP / DeepSpeed ZeRO-3
- [ ] Nexus Prime 1.0 release — first fully sovereign, from-scratch model; deployed at nexus-ai.app
- [ ] Open-weight release — publish Nexus Prime 1.0 weights publicly

### Stage 4 — Exascale Nexus Prime: Planetary Intelligence (Vision)

- [ ] Federated learning — devices contribute locally; gradients aggregated without raw data leaving the user's machine
- [ ] User-contributed compute network — opt-in idle GPU cycles pooled into training cluster
- [ ] Continuous pre-training at exascale — self-reinforcing loop as user base scales to billions
- [ ] Real-time knowledge integration — continuous ingestion without catastrophic forgetting (replay buffers + EWC regularisation)
- [ ] Nexus Prime Frontier — most capable AI system ever built; 100% owned and governed by the Nexus Systems community

---

## A4. Zero-Friction UX Principles (Legacy Carried Over)

- User opens Nexus AI → picks persona/mode (or "Auto") → types prompt → done
- The massive model list, swarm of agents, multi-modal tools, and reasoning engines all run invisibly under `PROVIDER=auto`
- Advanced users can open "Agent Console" or "Swarm View" to watch the empire at work
- Sovereign, self-hosted, federated — zero lock-in, 100% private

---

## D. Priority Merge Queue (No-Loss Execution)

- [ ] Typed errors
- [ ] Embeddings endpoint
- [ ] Capability registry
- [ ] Strict response format handling

1. Runtime second

- [ ] Tool schema registry
- [ ] Safety verdict pipeline
- [ ] Checkpoint + replay
- [ ] Context manager

1. Advanced features third

- [ ] Parallel/compositional tools
- [ ] Research generator-critic
- [ ] Risk-gated consensus
- [ ] Per-user quotas

## E. References

- Legacy source roadmap retained at: `ROADMAP.md`
- Audit ticket matrix: `EXTERNAL_BORROW_MATRIX.md`
- Strategy notes: `STRATEGY_AND_GUARDRAILS.md`
- Porting notes: `VERSAAI_PORTING_TRACKER.md`
- Sovereign model plan: `SOVEREIGN_MODEL_PLAN.md`
