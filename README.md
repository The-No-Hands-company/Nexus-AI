# Claude Alt

A self-hosted code agent deployable on Railway. Pick any free LLM API — no paid plans required.

## Supported providers

Set `PROVIDER=<id>` in your Railway environment variables, then add the matching API key.

| ID | Provider | Env var | Free tier | Notable models |
|----|----------|---------|-----------|----------------|
| `groq` | Groq ⭐ | `GROQ_API_KEY` | 30 RPM, 14 400 RPD | Llama 3.3 70B, Llama 4 Scout, Kimi K2 |
| `cerebras` | Cerebras | `CEREBRAS_API_KEY` | 30 RPM, 14 400 RPD | Llama 3.3 70B, Qwen3 235B |
| `gemini` | Google Gemini | `GEMINI_API_KEY` | 15 RPM, 1 500 RPD | Gemini 2.5 Pro, Flash, Flash-Lite |
| `mistral` | Mistral AI | `MISTRAL_API_KEY` | 1 req/s, 1 B tok/mo | Mistral Large 3, Small 3.1 |
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` | 20 RPM, 50 RPD | DeepSeek R1, Llama 3.3 70B (free models) |
| `nvidia` | NVIDIA NIM | `NVIDIA_API_KEY` | 40 RPM | Llama 3.3 70B, Mistral Large, Qwen3 235B |
| `llm7` | LLM7.io | *(keyless)* | 30 RPM | DeepSeek R1, Qwen2.5 Coder |
| `cohere` | Cohere | `COHERE_API_KEY` | 20 RPM, 1 K/mo | Command A, Command R+ |
| `github_models` | GitHub Models | `GITHUB_MODELS_TOKEN` | 10–15 RPM, 50–150 RPD | GPT-4o, DeepSeek-R1, Llama 3.3 70B |
| `grok` | Grok (xAI) | `GROK_API_KEY` | paid | Grok-3 |
| `claude` | Anthropic Claude | `CLAUDE_API_KEY` | paid | claude-sonnet-4 |

> Source: [mnfst/awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis)

Override the default model with `LLM_MODEL=<model-name>`.

## Railway env vars

```
PROVIDER=groq
GROQ_API_KEY=gsk_...
GITHUB_REPO=https://github.com/your-org/your-repo
GH_TOKEN=ghp_...

# Optional overrides
LLM_MODEL=llama-3.3-70b-versatile
PORT=8000
```

## Features

- Multi-turn conversation with session history
- Agent loop: reads, writes, lists, deletes files and commits to GitHub
- `/providers` endpoint shows all configured providers and their status
- Click the active-provider pill in the header to see all providers
