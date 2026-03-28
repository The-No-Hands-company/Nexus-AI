# Claude Alt — Roadmap

Track what's been built, what's in progress, and what's coming next.

---

## ✅ Implemented

### Core agent
- Streaming SSE responses with word-by-word typewriter
- Stop button — cancel mid-stream
- Tool-call loop (up to 16 steps per request)
- `think` — internal reasoning step shown as 💭
- `plan` — announces build plan before executing, shown as 📋 card
- `clarify` — asks focused questions before complex tasks, with clickable option chips
- Multi-turn clarify — answers carry original task context so agent picks up seamlessly

### Providers & routing
- 10-provider fallback chain (LLM7 → Groq → Cerebras → Gemini → Mistral → OpenRouter → Cohere → GitHub Models → Grok → Claude)
- LLM7.io keyless fallback — always available, zero config
- Auto-fallback on 429 with configurable cooldown per provider
- Smart complexity routing — high/medium/low scoring routes tasks to appropriate model tier
- Live provider status drawer with countdown timers
- Settings panel — switch provider, model override, temperature without redeployment

### Built-in tools (no API key)
- `get_time` — any timezone with natural aliases ("Sweden" → Europe/Stockholm)
- `calculate` — safe math eval with full math module
- `weather` — wttr.in, no key
- `currency` — open.er-api.com, no key
- `convert` — 30+ unit conversions (length, weight, volume, temp, data)
- `regex` — pattern tester with match count and positions
- `base64` — encode/decode
- `json_format` — pretty-print and validate
- `generate_image` — Pollinations.ai/flux, no key, renders inline

### File & repo tools
- `write_file` — writes to session workdir; HTML/SVG auto-renders as artifact
- `read_file`, `list_files`, `delete_file`
- `clone_repo` — clones any public or private GitHub repo
- `run_command` — sandboxed shell (256MB RAM cap, 10s CPU, 60s timeout)
- `commit_push` — stage, commit, push to target repo
- `web_search` — DuckDuckGo top 5 results
- Dynamic repo targeting — agent works on any repo mentioned in chat, not hardcoded
- Token extraction + redaction — tokens stripped from messages before reaching any LLM

### Personas
- 🤖 Assistant (balanced, temp 0.2)
- 💻 Coder (expert engineer, temp 0.1, high-tier providers first)
- 🔬 Researcher (cites sources, heavy web_search, temp 0.3)
- 🎨 Creative (vivid writer, image prompt crafter, temp 0.8)
- Persona strip in header, one tap to switch
- Active persona updates --accent CSS variable live

### Chat & history
- Session history (multi-turn conversation context within a session)
- Chat history sidebar — save, reload, delete conversations
- Auto-generated title from first message
- Export chat as `.md` download
- Share chat via read-only link (`/share/{id}`)

### Memory
- Conversation summaries saved after each chat (background thread)
- Last 5 summaries injected as context at start of new sessions
- Memory count in sidebar with clear button

### Input
- File upload — drag & drop or button; text inlined, images as base64
- Voice input — Web Speech API, interim results live in textarea
- GitHub token input via 🔑 button (never sent to LLM)

### UI & rendering
- Syntax-highlighted code blocks (Highlight.js, atom-one-dark)
- Inline artifact renderer — HTML/SVG in sandboxed iframe with expand/open/copy
- Inline image bubbles with prompt caption, click to open full res
- Markdown rendering (tables, blockquotes, code, lists)
- Code viewer for file write/read operations

### Mobile & PWA
- Installable PWA (manifest.json + service worker)
- Swipe right from left edge → opens sidebar; swipe left → closes
- Haptic feedback on send, tool calls, completion
- Safe-area insets for notched phones
- 44px touch targets throughout
- -webkit-overflow-scrolling: touch for smooth scroll

---

## 🔜 In Progress / Next Up

- [x] **Persistence** — SQLite storage so chats, memory and sessions survive restarts
- [ ] **Streaming token counter** — input/output token count per response
- [ ] **Conversation search** — full-text search across saved chats
- [ ] **Pinned chats** — keep important conversations at top of sidebar

---

## 🧠 Intelligence

- [ ] **Long-context summarization** — auto-compress older turns when context window fills
- [ ] **Semantic memory** — vector search over memories instead of last-N injection
- [ ] **Agent-to-agent** — spawn a focused sub-agent for a subtask, return results to parent
- [ ] **Reasoning traces** — show full chain-of-thought for complex answers
- [ ] **Confidence scoring** — flag low-confidence responses
- [ ] **Auto-retry on bad output** — detect malformed/incomplete responses and retry with the same or next provider

---

## 🛠️ More Tools

- [ ] **YouTube transcript** — fetch and summarize YouTube videos
- [ ] **PDF reader** — extract and reason over PDF content
- [ ] **Spreadsheet tool** — read/write CSV and xlsx
- [ ] **API caller** — make arbitrary HTTP requests from within the agent loop
- [ ] **Database tool** — read-only SQL queries against a connected DB
- [ ] **Diff viewer** — before/after when the agent edits existing files
- [ ] **Screenshot tool** — capture a webpage and attach as image context

---

## 🎨 UI / UX

- [ ] **Dark/light theme toggle**
- [ ] **Font size preference**
- [ ] **Keyboard shortcuts** — Cmd+K new chat, Cmd+/ sidebar, Esc stop
- [ ] **Message reactions** — thumbs up/down for quality feedback
- [ ] **Custom persona editor** — create personas with custom system prompts and colors
- [x] **Multi-file artifact viewer** — tabbed view when agent creates multiple related files
- [x] **Resizable split view** — chat on left, artifact preview on right

---

## 🏗️ Infrastructure

- [ ] **Multi-user auth** — simple password or OAuth, separate state per user
- [ ] **Rate limiting per user** — prevent one session exhausting all provider quota
- [ ] **Usage dashboard** — provider breakdown, token counts, estimated cost
- [ ] **Webhook triggers** — run the agent from GitHub webhooks, cron jobs, etc.
- [ ] **MCP server support** — plug in external tools via Model Context Protocol
- [ ] **Provider health monitoring** — detect degraded providers before they 429
- [ ] **Cost tracking** — estimate spend across paid providers (Grok, Claude)

---

*Last updated: March 2026*
