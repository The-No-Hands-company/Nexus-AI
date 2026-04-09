# Nexus AI — Roadmap v2 (April 2026)

**Vision**: A sovereign, self-hosted AI platform that rivals or exceeds the intelligence, agency, and capabilities of DeepSeek, Grok, Claude, Gemini, GPT-5, and any closed-source frontier model — while remaining 100% private, unlimited, and under your control.

**Core Principle**: The user never thinks about models, limits, or routing. They choose a **mode/persona** (or create new ones) and prompt. Everything else is handled invisibly by the system.

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
- [ ] **Graph-of-Thought** — graph-based reasoning beyond tree (agentic loops)
- [ ] **Self-critique loop** — agent reviews own answer before responding
- [ ] **Cross-model consensus** — run same task on 3 models, reconcile results
- [ ] **Mixture-of-Experts routing** — route subtasks to specialist model variants

### Model expansion
- [ ] Add 20+ more Ollama/cloud models by default (Qwen2.5-72B, DeepSeek-R1-70B, Llama-4 variants, Gemma-3, etc.)
- [ ] Auto-select best Ollama model based on task type (coding vs reasoning vs creative)
- [ ] Model benchmark dashboard — auto-benchmark new Ollama pulls

### Memory & context
- [ ] **Long-context summarization** — multi-step compression when window fills
- [ ] Persistent vector store with filtering by date/tags/persona
- [ ] Memory pruning — auto-delete low-value or outdated memories

### Streaming & feedback
- [ ] **Streaming token counter** — live input/output token count per response
- [ ] Live confidence + reasoning trace badge in UI
- [ ] Per-message feedback — 👍👎 stored as training signal

---

## 🤖 Phase 2 — Multi-Agent Empire (Next 4–8 weeks)

- [ ] **Hierarchical orchestration** — Planner → Executor → Reviewer → Verifier
- [ ] **Specialist agent library** (out-of-the-box):
  - Architect Agent
  - Security Auditor Agent
  - UI/UX Designer Agent
  - Data Scientist Agent
  - Legal/Compliance Agent
  - Product Manager Agent
  - Debugger Agent
  - Documentation Agent
- [ ] **Dynamic agent spawning** based on task complexity and type
- [ ] **Agent marketplace** — JSON-defined agents that users can import/share
- [ ] **Agent-to-agent communication** — shared workspace + message passing
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

## 🌌 Phase 6 — Frontier Research & Beyond (Ongoing)

- [ ] **Emotional intelligence** — consistent character memory across sessions
- [ ] **Real-time collaboration** — multiple humans + multiple agents in same session
- [ ] **Hardware-aware routing** — prefer GPU-heavy models when available, fall back to CPU models
- [ ] **Synthetic data generation** — self-play training data from agent interactions
- [ ] **Continuous benchmarking** — weekly leaderboard updates from live performance data

---

## How this keeps the user experience zero-friction

- User opens Nexus AI → picks persona/mode (or "Auto") → types prompt → done
- The massive model list, swarm of agents, multi-modal tools, and reasoning engines all run invisibly under `PROVIDER=auto`
- Advanced users can open "Agent Console" or "Swarm View" to watch the empire at work
- Sovereign, self-hosted, federated — zero lock-in, 100% private

---

*Last updated: April 2026*
