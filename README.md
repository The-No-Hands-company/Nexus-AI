# Claude Alt ⚡

A self-hosted, Claude.ai-inspired AI agent built on **free LLM APIs** — no subscriptions required. Runs on Railway (or any Docker host) and automatically falls back across 9+ providers when rate limits hit.

Live: **[claude-alt-production.up.railway.app](https://claude-alt-production.up.railway.app)**  
Org: [The-No-Hands-company](https://github.com/The-No-Hands-company)

---

## What it does

- Chat with a capable AI agent backed by Groq, Gemini, Mistral, Cerebras, OpenRouter, Cohere, GitHub Models, Grok and more
- Agent can **search the web, read/write/commit code, clone GitHub repos, run commands, generate images** and more — all via a tool-calling loop
- **Auto-fallback**: hit a rate limit on one provider → silently moves to the next
- **Smart routing**: complex coding tasks get routed to the strongest available model; simple questions go to the fastest/cheapest
- **Fully installable as a PWA** on mobile and desktop

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Agent loop | Custom streaming SSE agent with tool-call loop |
| Deployment | Docker, Railway |
| Frontend | Vanilla JS, Marked.js, Highlight.js |

---

## Quickstart (Railway)

1. Fork this repo
2. Create a new Railway project → Deploy from GitHub repo
3. Add environment variables (see below)
4. Deploy — app starts on the assigned Railway domain

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `PROVIDER` | Yes | `auto` (recommended) or a specific provider id |
| `GROQ_API_KEY` | Recommended | [console.groq.com/keys](https://console.groq.com/keys) — 14,400 req/day free |
| `GEMINI_API_KEY` | Recommended | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — 1,500 req/day free |
| `CEREBRAS_API_KEY` | Optional | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| `MISTRAL_API_KEY` | Optional | [console.mistral.ai](https://console.mistral.ai/api-keys) |
| `OPENROUTER_API_KEY` | Optional | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) |
| `COHERE_API_KEY` | Optional | [dashboard.cohere.com](https://dashboard.cohere.com/api-keys) |
| `GITHUB_MODELS_TOKEN` | Optional | github.com/settings/tokens — fine-grained, Models: read |
| `NVIDIA_API_KEY` | Optional | [build.nvidia.com](https://build.nvidia.com) |
| `GROK_API_KEY` | Optional | [console.x.ai](https://console.x.ai) (paid) |
| `CLAUDE_API_KEY` | Optional | [console.anthropic.com](https://console.anthropic.com/settings/keys) (paid) |
| `GH_TOKEN` | Optional | GitHub PAT for default repo push access |
| `GITHUB_REPO` | Optional | Default repo URL for git operations |
| `RATE_LIMIT_COOLDOWN` | Optional | Seconds to cool a rate-limited provider (default: 60) |

`LLM7.io` requires no key and is always available as a last-resort fallback.

---

## Providers & Fallback Chain

When `PROVIDER=auto`, providers are tried in this order (first available wins):

```
1. LLM7.io        — keyless, always available (DeepSeek R1 7B)
2. Groq           — llama-3.3-70b-versatile,  14,400 RPD free
3. Cerebras       — llama-3.3-70b,             30 RPM free
4. Google Gemini  — gemini-2.0-flash,          1,500 RPD free
5. Mistral AI     — mistral-small-latest,       1B tok/mo free
6. OpenRouter     — llama-3.3-70b:free,         20 RPM free
7. Cohere         — command-r-plus,             1K req/mo free
8. GitHub Models  — Llama-3.3-70B,             150 RPD free
9. Grok (xAI)     — grok-3                     (paid)
10. Claude        — claude-sonnet-4             (paid)
```

**Smart routing**: tasks scored as `high` / `medium` / `low` complexity. High-complexity tasks (new projects, architecture, full implementations) skip cheap providers and try Claude/Grok/Gemini first.

---

## Agent Tools

### Built-in (no API key, instant)
| Tool | What it does |
|---|---|
| `get_time` | Current time in any timezone, with aliases (e.g. "Sweden") |
| `calculate` | Safe math eval with full `math` module |
| `weather` | Current weather via wttr.in (no key) |
| `currency` | Live exchange rates via open.er-api.com (no key) |
| `convert` | 30+ unit conversions (length, weight, volume, temp, data) |
| `regex` | Test regex patterns with match highlighting |
| `base64` | Encode / decode |
| `json_format` | Pretty-print and validate JSON |
| `generate_image` | Image generation via Pollinations.ai/flux (no key) |

### File & repo tools
| Tool | What it does |
|---|---|
| `write_file` | Write file to session workdir; HTML/SVG renders as artifact |
| `read_file` | Read file contents (up to 300 lines preview) |
| `list_files` | Glob file listing |
| `delete_file` | Delete a file |
| `clone_repo` | Clone any GitHub repo (public or private with token) |
| `run_command` | Sandboxed shell — 256MB RAM cap, 10s CPU, 60s timeout |
| `commit_push` | Stage, commit and push to the target repo |

### Reasoning tools
| Tool | What it does |
|---|---|
| `think` | Internal reasoning step (shown as 💭 in UI) |
| `plan` | Announce a build plan before executing (shown as 📋 card) |
| `clarify` | Ask the user focused questions before a complex task |
| `web_search` | DuckDuckGo search, top 5 results |
| `respond` | Final answer (ends the loop) |

---

## Agent Personas

Switch between modes from the strip below the header:

| Persona | Best for | Temp | Provider tier |
|---|---|---|---|
| 🤖 Assistant | General questions, daily tasks | 0.2 | Medium |
| 💻 Coder | Code, architecture, debugging | 0.1 | High (best model first) |
| 🔬 Researcher | Facts, deep dives, citations | 0.3 | High |
| 🎨 Creative | Writing, storytelling, image prompts | 0.8 | Medium |

---

## Features

### Chat & UI
- ✅ Streaming responses (SSE) with word-by-word typewriter
- ✅ Stop button — cancel mid-stream
- ✅ Chat history sidebar — save, reload, delete past conversations
- ✅ Export chat as `.md` file
- ✅ Share chat via read-only link (`/share/{id}`)
- ✅ Auto-save title from first message
- ✅ Syntax-highlighted code blocks (Highlight.js, atom-one-dark)
- ✅ Inline artifact renderer — HTML/SVG files render in sandboxed iframe
- ✅ Inline image bubbles for generated images

### Input
- ✅ File upload (drag & drop or button) — text/code inlined, images as base64
- ✅ Voice input (Web Speech API, no key)
- ✅ GitHub token input without pasting in chat (🔑 button)
- ✅ Token auto-redacted before reaching any LLM

### Mobile & PWA
- ✅ Installable PWA (manifest + service worker)
- ✅ Swipe right from left edge → opens sidebar
- ✅ Swipe left → closes sidebar
- ✅ Haptic feedback on send, tool calls, and completion
- ✅ Safe-area insets (notched phones)
- ✅ Touch-friendly 44px targets throughout

### Agent memory
- ✅ Conversation summaries saved to disk after each chat
- ✅ Last 5 summaries injected as context in new sessions
- ✅ Memory count shown in sidebar with clear button

### Provider management
- ✅ Provider drawer shows fallback chain with live status
- ✅ Green/amber/grey dots — ready / cooling / no key
- ✅ Countdown timer for cooling providers (auto-refreshes)
- ✅ Settings panel — switch provider, model override, temperature
- ✅ All changes take effect immediately without redeployment

---

## Roadmap

### 🔜 Next up
- [ ] **Persistent storage** — SQLite or file-based persistence so chat history and memory survive Railway restarts (currently in-memory)
- [ ] **Streaming token counter** — show input/output token count per response
- [ ] **Multi-file artifact viewer** — tabbed view when agent creates multiple related files
- [ ] **Code execution sandbox** — Docker-in-Docker or e2b.dev for truly isolated Python/JS execution
- [ ] **Conversation search** — search across all saved chats
- [ ] **Pinned chats** — mark important conversations to keep at the top

### 🧠 Intelligence improvements
- [ ] **Long-context summarization** — auto-compress older turns when context gets long
- [ ] **Better memory** — semantic search over memories instead of just last-N
- [ ] **Agent-to-agent** — spawn a sub-agent for a subtask, return results to parent
- [ ] **Reasoning traces** — show full chain-of-thought for complex answers
- [ ] **Confidence scoring** — flag low-confidence responses for review

### 🛠️ More tools
- [ ] **YouTube transcript** — fetch and summarize YouTube videos
- [ ] **PDF reader** — extract and reason over PDF content
- [ ] **Spreadsheet tool** — read/write CSV and xlsx
- [ ] **API caller** — make HTTP requests to external APIs from within the agent loop
- [ ] **Database tool** — run read-only SQL queries against a connected DB
- [ ] **Diff tool** — show before/after when editing files
- [ ] **Screenshot tool** — capture a webpage and send as image context

### 🎨 UI / UX
- [ ] **Dark/light theme toggle**
- [ ] **Font size preference**
- [ ] **Keyboard shortcuts** (e.g. Cmd+K new chat, Cmd+/ toggle sidebar)
- [ ] **Message reactions / thumbs down for feedback**
- [ ] **Resizable input textarea**
- [ ] **Custom persona editor** — create your own persona with a custom system prompt

### 🏗️ Infrastructure
- [ ] **Multi-user auth** — simple password or OAuth login, separate session state per user
- [ ] **Rate limiting per user** — prevent one user exhausting all provider quota
- [ ] **Usage dashboard** — which providers got used, how many tokens, cost estimate
- [ ] **Webhook support** — trigger the agent from external events (GitHub webhooks, cron, etc.)
- [ ] **MCP server support** — connect external tools via Model Context Protocol

---

## Architecture

```
Browser (index.html)
    │
    │  SSE stream  /agent/stream
    ▼
FastAPI (main.py)
    │
    ├── agent.py          — tool-call loop, provider routing, streaming
    │     ├── tools_builtin.py  — calculate, weather, currency, image gen…
    │     └── personas.py       — system prompt prefixes per mode
    │
    ├── memory.py         — conversation summaries, disk persistence
    │
    └── LLM providers     — OpenAI-compat + Claude + Grok
          Groq / Gemini / Mistral / Cerebras / OpenRouter
          Cohere / GitHub Models / NVIDIA / LLM7 / Grok / Claude
```

---

## Contributing

PRs welcome. The project is intentionally kept simple — single-file modules, no build step, no heavy frameworks. If you add a new tool, add it to `tools_builtin.py` and register it in `TOOLS_DESCRIPTION` in `agent.py`.

---

*Built by [Zajfan](https://github.com/Zajfan) / [The-No-Hands-company](https://github.com/The-No-Hands-company)*
