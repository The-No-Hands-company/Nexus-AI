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
| `OLLAMA_BASE_URL` | Optional | Ollama server base URL (default: http://localhost:11434/v1) |

`LLM7.io` and `Ollama` require no API key and are always available as fallbacks.

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

**Ollama (Local)** — runs `glm-5.1:cloud` locally via the OpenAI-compatible API. Set `OLLAMA_BASE_URL` (default: `http://localhost:11434/v1`). No API key needed. Ollama is automatically included in the high-complexity tier for powerful local inference. To use a different model, set `PROVIDER=ollama` and `LLM_MODEL=your-model-name`.

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

## Features & Roadmap

See [ROADMAP.md](./ROADMAP.md) for a full breakdown of what's implemented, what's in progress, and what's planned.
