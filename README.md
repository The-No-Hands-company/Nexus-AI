# Nexus AI ⚡

> **Tool [#11](https://github.com/The-No-Hands-company/Nexus#tool-11) — Nexus AI Agent** within the [Nexus Systems Ecosystem](https://github.com/The-No-Hands-company).  
> Sovereign, self-hosted, zero lock-in. Powered by the full Nexus stack.

A **self-hosted AI coding agent** with full tool-use, automatic provider fallback, and smart task routing. Pick a persona, prompt, done — no model management, no rate-limit anxiety.

- 🧠 **10+ providers** — Groq, Gemini, Cerebras, Mistral, OpenRouter, Cohere, GitHub Models, Ollama (local + `glm-5.1:cloud`), Grok, Claude
- 🔄 **Auto-fallback** — silently moves to the next provider when rate-limited
- 🧭 **Smart routing** — high-complexity tasks hit the strongest models first
- 🛠️ **Tool-calling loop** — web search, code, file ops, repo ops, images, PDFs, YouTube, and more
- 📱 **PWA** — installable on mobile and desktop
- 🐳 **One-command deploy** — Docker Compose with Ollama included

---

## Quick Start — Docker Compose (Recommended)

One command, everything included:

```bash
git clone https://github.com/The-No-Hands-company/Claude-alt.git
cd Claude-alt
cp .env.example .env
# Add your API keys to .env (GROQ_API_KEY and GEMINI_API_KEY recommended)
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000)

> **Without a `.env` file**, Nexus AI still works — LLM7.io is always available keyless as a fallback.

---

## Railway (One-Click)

1. Fork this repo
2. Create a new Railway project → **Deploy from GitHub**
3. Add environment variables (see [Environment Variables](#environment-variables))
4. Deploy — done

---

## Environment Variables

Copy `.env.example` to `.env` for local Docker deploy, or set these directly in Railway:

| Variable | Required | Description |
|---|---|---|
| `PROVIDER` | Yes | `auto` (recommended) or a specific provider id |
| `LLM_MODEL` | No | Override model (default per provider) |
| `GROQ_API_KEY` | Recommended | [console.groq.com/keys](https://console.groq.com/keys) — 14,400 req/day free |
| `GEMINI_API_KEY` | Recommended | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — 1,500 req/day free |
| `CEREBRAS_API_KEY` | Optional | [cloud.cerebras.ai](https://cloud.cerebras.ai) |
| `MISTRAL_API_KEY` | Optional | [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys) |
| `OPENROUTER_API_KEY` | Optional | [openrouter.ai/settings/keys](https://openrouter.ai/settings/keys) |
| `COHERE_API_KEY` | Optional | [dashboard.cohere.com/api-keys](https://dashboard.cohere.com/api-keys) |
| `GITHUB_MODELS_TOKEN` | Optional | github.com/settings/tokens — fine-grained, Models: read |
| `NVIDIA_API_KEY` | Optional | [build.nvidia.com](https://build.nvidia.com) |
| `GROK_API_KEY` | Optional | [console.x.ai](https://console.x.ai) (paid) |
| `CLAUDE_API_KEY` | Optional | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) (paid) |
| `GH_TOKEN` | Optional | GitHub PAT for repo push/commit access |
| `GITHUB_REPO` | Optional | Default repo URL for git operations |
| `RATE_LIMIT_COOLDOWN` | Optional | Seconds before retrying a rate-limited provider (default: 60) |
| `OLLAMA_BASE_URL` | Optional | Ollama server URL (default: `http://localhost:11434/v1`) |

> **LLM7.io** and **Ollama** require no API key and are always available as fallbacks.

---

## Providers & Fallback Chain

When `PROVIDER=auto`, Nexus AI tries providers in this order (first available wins):

```
1. Ollama (Local)  — glm-5.1:cloud via local Ollama, no key, GPU-accelerated
2. LLM7.io         — keyless, always available (DeepSeek R1 7B)
3. Groq            — llama-3.3-70b-versatile,  14,400 RPD free
4. Cerebras        — llama-3.3-70b,             30 RPM free
5. Google Gemini   — gemini-2.0-flash,          1,500 RPD free
6. Mistral AI      — mistral-small-latest,       1B tok/mo free
7. OpenRouter      — llama-3.3-70b:free,         20 RPM free
8. Cohere          — command-r-plus,             1K req/mo free
9. GitHub Models   — Llama-3.3-70B,             150 RPD free
10. Grok (xAI)    — grok-3                     (paid)
11. Claude         — claude-sonnet-4             (paid)
```

### Smart Routing

Tasks are scored **high / medium / low** complexity:
- **High** — new projects, architecture, full implementations → Ollama, Claude, Grok, Gemini first
- **Medium** — code edits, debugging, explanations → Groq, Cerebras, Mistral
- **Low** — simple Q&A → LLM7.io, Groq

### Ollama + glm-5.1:cloud

Nexus AI ships with **Ollama as the #1 priority provider** when running via Docker Compose. Set your model:

```bash
# Pull the model on the Ollama host
ollama pull glm-5.1:cloud

# Or override via env
LLM_MODEL=qwen2.5:72b
```

Any Ollama model works — just `ollama pull <model-name>` and set `LLM_MODEL`.

---

## Agent Tools

### Built-in (no API key)
| Tool | What it does |
|---|---|
| `get_time` | Any timezone, natural aliases ("Sweden" → Europe/Stockholm) |
| `calculate` | Safe math with full `math` module |
| `weather` | wttr.in — no key |
| `currency` | Live exchange rates via open.er-api.com |
| `convert` | 30+ unit conversions |
| `regex` | Pattern tester with match positions |
| `base64` | Encode / decode |
| `json_format` | Pretty-print and validate JSON |
| `generate_image` | Pollinations.ai/flux — no key, renders inline |

### File & repo tools
| Tool | What it does |
|---|---|
| `write_file` | Write to session workdir; HTML/SVG auto-renders as artifact |
| `read_file` | Read file contents (up to 300 lines preview) |
| `list_files` | Glob file listing |
| `delete_file` | Delete a file |
| `clone_repo` | Clone any public or private GitHub repo |
| `run_command` | Sandboxed shell (256MB RAM, 60s timeout) |
| `commit_push` | Stage, commit and push to target repo |
| `create_repo` | Create a new GitHub repo via API then push to it |

### Reasoning & research tools
| Tool | What it does |
|---|---|
| `think` | Internal reasoning (shown as 💭) |
| `plan` | Announce build plan before executing (shown as 📋) |
| `clarify` | Ask focused questions before complex tasks |
| `web_search` | DuckDuckGo top 5 results |
| `respond` | Final answer (ends the loop) |

---

## Personas

Switch from the header strip:

| Persona | Best for | Temp | Provider tier |
|---|---|---|---|
| 🤖 Assistant | General questions, daily tasks | 0.2 | Medium |
| 💻 Coder | Code, architecture, debugging | 0.1 | High (best model first) |
| 🔬 Researcher | Facts, deep dives, citations | 0.3 | High |
| 🎨 Creative | Writing, storytelling, image prompts | 0.8 | Medium |

---

## Nexus Systems Ecosystem

Nexus AI is **Tool #11** in the [80-tool Nexus Systems Ecosystem](https://github.com/The-No-Hands-company):

- **Tool #80 — Nexus Tunnel**: pair with Nexus AI for sovereign public HTTPS URLs (no Cloudflare, no ngrok)
- **Nexus Guardian**: security + health monitoring, founder alerts
- **Nexus Systems API**: unified REST + WebSocket integration layer
- **Nexus Edge**: edge computing and IoT orchestration

> Every tool is 100% sovereign, self-hosted, federated, and zero lock-in.

---

## Features & Roadmap

See [ROADMAP.md](./ROADMAP.md) for full details.

---

*Part of the [The-No-Hands-company](https://github.com/The-No-Hands-company) · 100% sovereign, self-hosted, lock-in free.*
