import os, re, json, glob, time, subprocess, threading, resource
from datetime import datetime
from typing import Dict, Any, List, Iterator, Optional
from tools_builtin import dispatch_builtin
from personas import build_system_prompt, get_active_persona_name, get_persona
from db import load_custom_instructions

# ── runtime config ────────────────────────────────────────────────────────────
_config: Dict[str, Any] = {
    "provider":    os.getenv("PROVIDER", "auto").lower(),
    "model":       os.getenv("LLM_MODEL", ""),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0.2")),
    "persona":     os.getenv("PERSONA", "general"),
}
def get_config() -> Dict[str, Any]: return dict(_config)
def update_config(provider=None, model=None, temperature=None, persona=None):
    if provider    is not None: _config["provider"]    = provider.lower()
    if model       is not None: _config["model"]       = model
    if temperature is not None: _config["temperature"] = float(temperature)
    if persona     is not None: _config["persona"]     = persona
    return dict(_config)

# ── env ───────────────────────────────────────────────────────────────────────
GH_TOKEN    = os.getenv("GH_TOKEN", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
MAX_LOOP    = 16
COOLDOWN_SECONDS = int(os.getenv("RATE_LIMIT_COOLDOWN", "60"))

# ── token extraction from user messages ───────────────────────────────────────
_TOKEN_RE   = re.compile(r'gh[ps]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{80,}')
_GITHUB_URL_RE = re.compile(r'https://github\.com/[\w\-\.]+/[\w\-\.]+')
_CLONE_INTENT_RE = re.compile(
    r'\b(clone|develop|continue|work on|improve|build|update|fix|create)\b',
    re.IGNORECASE)

def extract_token(text: str) -> Optional[str]:
    m = _TOKEN_RE.search(text)
    return m.group(0) if m else None

def mask_token(text: str) -> str:
    """Replace tokens with a placeholder so they never reach the LLM."""
    return _TOKEN_RE.sub('[GITHUB_TOKEN_REDACTED]', text)

# ── session working directories ───────────────────────────────────────────────
# sid → {"dir": "/tmp/session_xxx", "token": "ghp_...", "repos": [...]}
_session_state: Dict[str, Dict] = {}

def get_session_state(sid: str) -> Dict:
    if sid not in _session_state:
        _session_state[sid] = {
            "dir":   f"/tmp/ca_session_{sid[:8]}",
            "token": GH_TOKEN,
            "repos": [],
        }
        os.makedirs(_session_state[sid]["dir"], exist_ok=True)
    return _session_state[sid]

def set_session_token(sid: str, token: str):
    s = get_session_state(sid)
    s["token"] = token

def get_session_token(sid: str) -> str:
    return get_session_state(sid).get("token", GH_TOKEN)

def get_session_dir(sid: str) -> str:
    return get_session_state(sid)["dir"]

# ── provider registry ─────────────────────────────────────────────────────────
PROVIDERS: Dict[str, Dict] = {
    "llm7":    {"label":"LLM7.io","base_url":"https://api.llm7.io/v1",
                "env_key":"LLM7_API_KEY","default_model":"deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
                "openai_compat":True,"keyless":True},
    "groq":    {"label":"Groq","base_url":"https://api.groq.com/openai/v1",
                "env_key":"GROQ_API_KEY","default_model":"llama-3.3-70b-versatile",
                "openai_compat":True},
    "cerebras":{"label":"Cerebras","base_url":"https://api.cerebras.ai/v1",
                "env_key":"CEREBRAS_API_KEY","default_model":"llama-3.3-70b",
                "openai_compat":True},
    "gemini":  {"label":"Google Gemini",
                "base_url":"https://generativelanguage.googleapis.com/v1beta/openai",
                "env_key":"GEMINI_API_KEY","default_model":"gemini-2.0-flash",
                "openai_compat":True},
    "mistral": {"label":"Mistral AI","base_url":"https://api.mistral.ai/v1",
                "env_key":"MISTRAL_API_KEY","default_model":"mistral-small-latest",
                "openai_compat":True},
    "openrouter":{"label":"OpenRouter","base_url":"https://openrouter.ai/api/v1",
                  "env_key":"OPENROUTER_API_KEY",
                  "default_model":"meta-llama/llama-3.3-70b-instruct:free",
                  "openai_compat":True},
    "nvidia":  {"label":"NVIDIA NIM","base_url":"https://integrate.api.nvidia.com/v1",
                "env_key":"NVIDIA_API_KEY","default_model":"meta/llama-3.3-70b-instruct",
                "openai_compat":True},
    "cohere":  {"label":"Cohere","base_url":"https://api.cohere.com/compatibility/v1",
                "env_key":"COHERE_API_KEY","default_model":"command-r-plus",
                "openai_compat":True},
    "github_models":{"label":"GitHub Models",
                     "base_url":"https://models.inference.ai.azure.com",
                     "env_key":"GITHUB_MODELS_TOKEN",
                     "default_model":"meta-llama/Llama-3.3-70B-Instruct",
                     "openai_compat":True},
    "grok":    {"label":"Grok (xAI)","env_key":"GROK_API_KEY",
                "default_model":"grok-3","openai_compat":False},
    "claude":  {"label":"Claude (Anthropic)","env_key":"CLAUDE_API_KEY",
                "default_model":"claude-sonnet-4-20250514","openai_compat":False},
}

# ── complexity + provider routing ─────────────────────────────────────────────
PROVIDER_TIERS = {
    "high":   ["claude","grok","gemini","openrouter","mistral"],
    "medium": ["groq","cerebras","cohere","github_models","nvidia"],
    "low":    ["llm7","groq","cerebras"],
}
_HIGH_RE = re.compile(
    r'\b(develop|implement|architect|refactor|build|create|design|'
    r'clone.*repo|continue.*development|add.*feature|fix.*bug|'
    r'write.*tests?|full.*stack|entire|complete|production|new.*project)\b',
    re.IGNORECASE)
_MED_RE = re.compile(
    r'\b(explain|summarize|compare|analyze|review|suggest|improve|'
    r'read.*file|list.*files|search|find|what does)\b', re.IGNORECASE)

def _score_complexity(task: str) -> str:
    if len(task) > 300 or _HIGH_RE.search(task): return "high"
    if _MED_RE.search(task): return "medium"
    return "low"

_cooldowns: Dict[str, float] = {}
def _is_rate_limited(pid): return time.time() < _cooldowns.get(pid, 0)
def _mark_rate_limited(pid):
    cd = 15 if PROVIDERS.get(pid,{}).get("keyless") else COOLDOWN_SECONDS
    _cooldowns[pid] = time.time() + cd
def _is_rl_error(exc):
    msg = str(exc).lower()
    if isinstance(exc, __import__('requests').HTTPError):
        if exc.response is not None and exc.response.status_code == 429: return True
    return any(p in msg for p in ["rate limit","rate_limit","too many requests","quota","throttl"])
def _has_key(cfg): return cfg.get("keyless",False) or bool(os.getenv(cfg["env_key"],"").strip())

def _smart_order(task: str) -> List[str]:
    pref = _config["provider"]
    avail = {pid for pid,cfg in PROVIDERS.items() if _has_key(cfg) and not _is_rate_limited(pid)}
    complexity = _score_complexity(task)
    tier_order = ["high","medium","low"] if complexity=="high" else \
                 ["medium","low","high"] if complexity=="medium" else ["low","medium","high"]
    ordered: List[str] = []
    for tier in tier_order:
        for pid in PROVIDER_TIERS[tier]:
            if pid in avail and pid not in ordered: ordered.append(pid)
    for pid in PROVIDERS:
        if pid in avail and pid not in ordered: ordered.append(pid)
    if pref != "auto" and pref in ordered:
        ordered.remove(pref); ordered.insert(0, pref)
    return ordered

# ── personas ──────────────────────────────────────────────────────────────────
PERSONAS: Dict[str, Dict] = {
    "general": {
        "label": "General",
        "emoji": "⚡",
        "description": "Balanced assistant for any task",
        "temperature": 0.2,
        "system_extra": "",
    },
    "coder": {
        "label": "Coder",
        "emoji": "💻",
        "description": "Focused on writing, reviewing and shipping code",
        "temperature": 0.1,
        "system_extra": (
            "You are in CODER mode. Prioritise: write_file, run_command, read_file, commit_push. "
            "Always write complete, production-quality code. Add error handling and comments. "
            "Prefer plan → write files → run tests → commit. Never leave TODOs without implementing them."
        ),
    },
    "researcher": {
        "label": "Researcher",
        "emoji": "🔬",
        "description": "Deep dives, web research and structured summaries",
        "temperature": 0.3,
        "system_extra": (
            "You are in RESEARCHER mode. Prioritise: web_search, respond with citations. "
            "Do multiple searches to cross-reference. Structure responses with headers, "
            "bullet points, and sources. Be thorough — search at least 3 angles before concluding. "
            "Always note confidence level and limitations of the information found."
        ),
    },
    "creative": {
        "label": "Creative",
        "emoji": "🎨",
        "description": "Writing, brainstorming, image prompts and ideas",
        "temperature": 0.8,
        "system_extra": (
            "You are in CREATIVE mode. Be imaginative, expressive and original. "
            "For writing tasks: vary sentence length, use vivid language, show don't tell. "
            "For image generation: craft rich detailed prompts (style, lighting, mood, composition). "
            "Use image_gen to visualise ideas. Suggest unexpected angles and perspectives."
        ),
    },
}

def get_active_persona() -> Dict:
    return PERSONAS.get(_config["persona"], PERSONAS["general"])

def get_system_prompt() -> str:
    """Build the system prompt for the current persona."""
    persona = get_active_persona()
    extra = persona["system_extra"]
    base = TOOLS_DESCRIPTION
    if extra:
        base = base.rstrip() + f"\n\nPersona instructions:\n{extra}\n"
    return base

# ── system prompt ─────────────────────────────────────────────────────────────
TOOLS_DESCRIPTION = """You are a self-hosted code agent. Smart, structured, builds things properly.

Reply ONLY with valid JSON — no markdown fences, no extra text.

Available actions:

  { "action": "clarify",    "questions": [{"id":"q1","text":"?","options":["A","B"]}] }
  { "action": "plan",       "title": "What I'm building", "steps": ["1. ...", "2. ..."] }
  { "action": "think",      "thought": "brief reasoning" }
  { "action": "respond",    "content": "<markdown>" }
  { "action": "get_time",   "timezone": "Europe/Stockholm" }
  { "action": "web_search", "query": "search terms" }
  { "action": "image_gen",  "prompt": "a cyberpunk city at night, neon lights, rain", "width": 512, "height": 512 }
  { "action": "calculate",  "expr": "2 ** 32 / 1024" }
  { "action": "weather",    "location": "Stockholm" }
  { "action": "currency",   "amount": 100, "from": "USD", "to": "SEK" }
  { "action": "convert",    "value": 5.5, "from_unit": "km", "to_unit": "miles" }
  { "action": "regex",      "pattern": "\\d+", "text": "abc 123", "flags": "i" }
  { "action": "base64",     "text": "hello", "mode": "encode" }
  { "action": "json_format","text": "{\"a\":1}" }
  { "action": "generate_image","prompt": "a glowing neon city at night","width": 1024,"height": 1024 }
  { "action": "write_file", "path": "src/app.py", "content": "..." }
  { "action": "read_file",  "path": "README.md" }
  { "action": "list_files", "pattern": "**/*.py" }
  { "action": "delete_file","path": "old.txt" }
  { "action": "run_command","cmd": "pip install flask" }
  { "action": "clone_repo", "url": "https://github.com/user/repo" }
  { "action": "commit_push","message": "feat: ...", "repo_url": "https://github.com/user/repo" }

Rules:
- clarify ONLY for new project creation where architecture choices matter. 2-4 questions max.
- plan BEFORE building 3+ files. Then execute immediately.
- clone_repo: use the exact URL from the user's message. Never use placeholder URLs.
- commit_push: always include repo_url so the right repo gets pushed.
- run_command: no rm -rf, sudo, or destructive ops.
- get_time for any time/date question — never web_search for this.
- calculate/weather/currency/convert for math, weather, money, units.
- image_gen for any request to generate, draw, create, or visualise an image.
- write_file produces artifacts if it's HTML/SVG/CSS+JS — the UI will render them.
- Never ask for info you can get with tools.
"""

# ── tool executors ────────────────────────────────────────────────────────────
import requests as _req

def _time_re() -> str:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        return ""
    except: return ""

def tool_get_time(timezone: str = "UTC") -> str:
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        ALIASES = {"sweden":"Europe/Stockholm","stockholm":"Europe/Stockholm",
            "uk":"Europe/London","london":"Europe/London",
            "new york":"America/New_York","nyc":"America/New_York",
            "los angeles":"America/Los_Angeles","la":"America/Los_Angeles",
            "tokyo":"Asia/Tokyo","japan":"Asia/Tokyo","paris":"Europe/Paris",
            "france":"Europe/Paris","berlin":"Europe/Berlin","germany":"Europe/Berlin",
            "dubai":"Asia/Dubai","uae":"Asia/Dubai","sydney":"Australia/Sydney",
            "australia":"Australia/Sydney","jakarta":"Asia/Jakarta","indonesia":"Asia/Jakarta",
            "utc":"UTC","gmt":"GMT"}
        tz_name = ALIASES.get(timezone.lower().strip(), timezone)
        try: tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError: return f"Unknown timezone: '{timezone}'"
        now = datetime.now(tz)
        return now.strftime("**%H:%M:%S** %Z — %A, %B %d %Y (UTC%z)")
    except Exception as e: return f"Time lookup failed: {e}"

def tool_web_search(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=6))
        if not results: return "No results found."
        # Return structured JSON so the agent can cite sources
        import json as _json
        sources = [{"title": r["title"], "url": r["href"],
                    "snippet": r["body"][:300], "domain": r["href"].split("/")[2] if "://" in r["href"] else ""}
                   for r in results]
        lines = [f"[{i+1}] **{s['title']}** ({s['domain']})\n{s['url']}\n{s['snippet']}"
                 for i, s in enumerate(sources)]
        structured = "\n\n".join(lines)
        structured += f"\n\n[SOURCES_JSON]{_json.dumps(sources)}[/SOURCES_JSON]"
        return structured
    except Exception as e: return f"Search failed: {e}"

def tool_image_gen(prompt: str, width: int = 512, height: int = 512) -> str:
    """Generate image via Pollinations.ai — completely free, no API key."""
    import urllib.parse
    w = min(max(int(width), 256), 1024)
    h = min(max(int(height), 256), 1024)
    encoded = urllib.parse.quote(prompt)
    # Pollinations returns a direct image URL
    url = f"https://image.pollinations.ai/prompt/{encoded}?width={w}&height={h}&nologo=true"
    return f"![Generated image]({url})\n\n*Prompt: {prompt}*"

def tool_write_file(path: str, content: str, workdir: str) -> str:
    full = os.path.join(workdir, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f: f.write(content)
    return f"Wrote {path} ({len(content)} chars)"

def tool_read_file(path: str, workdir: str) -> str:
    full = os.path.join(workdir, path)
    if not os.path.exists(full): return f"File not found: {path}"
    with open(full, "r", encoding="utf-8", errors="replace") as f: content = f.read()
    lines = content.splitlines()
    preview = "\n".join(lines[:300])
    suffix = f"\n... ({len(lines)-300} more lines)" if len(lines)>300 else ""
    return f"```\n{preview}{suffix}\n```"

def tool_list_files(pattern: str, workdir: str) -> str:
    matches = glob.glob(os.path.join(workdir, pattern), recursive=True)
    rel = [os.path.relpath(m, workdir) for m in sorted(matches) if os.path.isfile(m)]
    return "\n".join(rel) if rel else "(no files found)"

def tool_delete_file(path: str, workdir: str) -> str:
    full = os.path.join(workdir, path)
    if not os.path.exists(full): return f"Not found: {path}"
    os.remove(full); return f"Deleted {path}"

def tool_run_command(cmd: str, workdir: str) -> str:
    BLOCKED = ["rm -rf /","sudo","ncat","mkfs","dd if=",":(){ :|:& };:"]
    for b in BLOCKED:
        if b in cmd: return f"Blocked: {cmd}"
    try:
        # Resource limits: 256MB RAM, 10s CPU
        def _preexec():
            try:
                resource.setrlimit(resource.RLIMIT_AS,  (268435456, 268435456))
                resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
            except Exception: pass

        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           cwd=workdir, timeout=60, preexec_fn=_preexec)
        out = (r.stdout + r.stderr).strip()
        return out[:4000] if out else "(no output)"
    except subprocess.TimeoutExpired: return "⏱ Command timed out after 60s"
    except Exception as e: return f"Error: {e}"

def tool_clone_repo(url: str, token: str, workdir: str) -> str:
    repo_name = url.rstrip('/').split('/')[-1].replace('.git','')
    dest = os.path.join(workdir, repo_name)
    if os.path.exists(os.path.join(dest, ".git")):
        return f"Already cloned at {dest}"
    auth_url = url
    if token:
        auth_url = url.replace("https://", f"https://{token}@")
    r = subprocess.run(["git","clone", auth_url, dest],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ,"GIT_TERMINAL_PROMPT":"0"})
    if r.returncode != 0:
        return f"Clone failed: {(r.stdout+r.stderr).strip()}"
    # List top-level files
    top = [f for f in os.listdir(dest) if not f.startswith('.')][:20]
    return f"Cloned to {dest}\nTop files: {', '.join(top)}"

def tool_commit_push(message: str, repo_url: str, token: str, workdir: str) -> str:
    # Find the repo dir
    repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git','') if repo_url else ""
    repo_dir = os.path.join(workdir, repo_name) if repo_name and os.path.isdir(os.path.join(workdir, repo_name)) else workdir

    def _git(args):
        return subprocess.run(["git","-C",repo_dir]+args, capture_output=True, text=True,
                              env={**os.environ,"GIT_TERMINAL_PROMPT":"0"})
    _git(["config","user.name","Claude-Alt-Agent"])
    _git(["config","user.email","agent@nohands.company"])
    _git(["add","."])
    c = _git(["commit","-m",message])
    if c.returncode != 0 and "nothing to commit" in c.stdout: return "Nothing to commit."
    push_url = repo_url.replace("https://",f"https://{token}@") if token else repo_url
    r = subprocess.run(["git","-C",repo_dir,"push",push_url],
                       capture_output=True, text=True,
                       env={**os.environ,"GIT_TERMINAL_PROMPT":"0"})
    if r.returncode != 0: raise Exception(f"Push failed: {(r.stdout+r.stderr).strip()}")
    return f"✅ Committed & pushed: {message}"

# ── artifact detection ────────────────────────────────────────────────────────
_ARTIFACT_EXTS = {'.html','htmlv','.svg','.jsx','.tsx'}
def _is_artifact(path: str, content: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext in _ARTIFACT_EXTS: return True
    if ext in ('.js','.ts') and ('<div' in content or 'React' in content): return True
    return False

# ── direct intent handlers ────────────────────────────────────────────────────
_TIME_RE2 = re.compile(
    r'\b(what(?:\'s| is)(?: the)? (?:current )?time(?: in| at)?|'
    r'current time(?: in)?|time(?: right)? now(?: in)?|what time(?: is it)?)\b',re.IGNORECASE)
_DATE_RE2 = re.compile(
    r'\b(what(?:\'s| is)(?: the)? (?:current |today\'?s? )?date|today\'?s? date|what day is)\b',re.IGNORECASE)
_CALC_RE  = re.compile(r'^[\d\s\+\-\*\/\%\^\(\)\.e]+$')
_WEATHER_RE = re.compile(r'\bweather\b.*\bin\b|\bweather\b.*\bfor\b|\b(forecast|temperature)\b.*\bin\b',re.IGNORECASE)
_CURRENCY_RE = re.compile(r'(\d[\d,\.]*)\s*([A-Z]{3})\s+(?:to|in|→)\s*([A-Z]{3})',re.IGNORECASE)
_CONVERT_RE = re.compile(r'(\d[\d,\.]*)\s*([\w]+)\s+(?:to|in|→)\s*([\w]+)',re.IGNORECASE)

def _try_direct(task: str) -> Optional[str]:
    if _TIME_RE2.search(task):
        loc = re.search(r'\b(?:in|at|for)\s+([A-Za-z][A-Za-z\s/]{1,30})\??$',task,re.IGNORECASE)
        return tool_get_time(loc.group(1).strip() if loc else "UTC")
    if _DATE_RE2.search(task):
        return tool_get_time("UTC")
    m = _CURRENCY_RE.search(task)
    if m:
        from tools_builtin import tool_currency
        return tool_currency(float(m.group(1).replace(',','')), m.group(2), m.group(3))
    return None

# ── LLM callers ───────────────────────────────────────────────────────────────
def _parse_json(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    if not raw: raise ValueError("Empty response")
    if raw.startswith("```"):
        parts = raw.split("```"); raw = parts[1].strip()
        if raw.lower().startswith("json"): raw = raw[4:].strip()
    try: return json.loads(raw)
    except json.JSONDecodeError: return {"action":"respond","content":raw}

def _build_content(text: str, files: List[Dict]) -> Any:
    if not files: return text
    parts: List[Dict] = []
    text_files = []
    for f in files:
        if f.get("type","").startswith("image/"):
            parts.append({"type":"image_url","image_url":{"url":f"data:{f['type']};base64,{f['content']}"}})
        else:
            text_files.append(f"[File: {f['name']}]\n{f['content']}")
    full = ("\n\n".join(text_files)+"\n\n"+text).strip() if text_files else text
    parts.append({"type":"text","text":full})
    return parts

def _call_openai(cfg: Dict, messages: List[Dict]) -> Dict[str, Any]:
    import requests
    api_key = os.getenv(cfg["env_key"],"") or ("llm7" if cfg.get("keyless") else "")
    resp = requests.post(
        cfg["base_url"].rstrip("/")+"/chat/completions",
        headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"},
        json={"model":_config["model"] or cfg["default_model"],
              "messages":[{"role":"system","content":get_system_prompt()}]+messages,
              "temperature":_config["temperature"],"max_tokens":4096},
        timeout=90)
    resp.raise_for_status()
    return _parse_json(resp.json()["choices"][0]["message"]["content"])

def _call_grok(messages):
    import requests
    resp = requests.post("https://api.x.ai/v1/chat/completions",
        headers={"Authorization":f"Bearer {os.getenv('GROK_API_KEY','')}","Content-Type":"application/json"},
        json={"model":_config["model"] or "grok-3",
              "messages":[{"role":"system","content":get_system_prompt()}]+messages,
              "temperature":_config["temperature"] or get_active_persona()["temperature"],"max_tokens":4096},timeout=90)
    resp.raise_for_status()
    return _parse_json(resp.json()["choices"][0]["message"]["content"])

def _call_claude_api(messages):
    import requests
    resp = requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":os.getenv("CLAUDE_API_KEY",""),"anthropic-version":"2023-06-01","Content-Type":"application/json"},
        json={"model":_config["model"] or "claude-sonnet-4-20250514",
              "system":get_system_prompt(),"messages":messages,
              "temperature":_config["temperature"] or get_active_persona()["temperature"],"max_tokens":4096},timeout=90)
    resp.raise_for_status()
    return _parse_json(resp.json()["content"][0]["text"])

def _call_single(pid: str, messages: List[Dict]) -> Dict[str, Any]:
    cfg = PROVIDERS[pid]
    if cfg["openai_compat"]: return _call_openai(cfg, messages)
    if pid == "grok":         return _call_grok(messages)
    if pid == "claude":       return _call_claude_api(messages)
    raise ValueError(f"No caller: {pid}")

class AllProvidersExhausted(Exception): pass

def call_llm_with_fallback(messages: List[Dict], task: str = "") -> tuple[Dict, str]:
    import requests as _r
    order = _smart_order(task or (messages[-1].get("content","") if messages else ""))
    if not order: raise AllProvidersExhausted("No providers available.")
    complexity = _score_complexity(task or "")
    print(f"🧠 {complexity} → {' → '.join(order[:4])}")
    last_err = None
    for pid in order:
        if _is_rate_limited(pid): continue
        try: return _call_single(pid, messages), pid
        except Exception as e:
            last_err = e
            if _is_rl_error(e): _mark_rate_limited(pid); print(f"↩️ {pid} rate-limited")
            elif isinstance(e, (_r.ConnectionError, _r.Timeout)): print(f"⚠️ {pid} connection error")
            else: print(f"⚠️ {pid}: {e}")
    raise AllProvidersExhausted(f"All exhausted. Last: {last_err}")

def _get_custom_instructions() -> str:
    try:
        return load_custom_instructions()
    except Exception:
        return ""

# ── tool icons ────────────────────────────────────────────────────────────────
TOOL_ICONS = {
    "clarify":"❓","plan":"📋","think":"💭","get_time":"🕐",
    "web_search":"🔍","image_gen":"🎨","calculate":"🧮","weather":"🌤️","currency":"💱",
    "convert":"📐","regex":"🔎","base64":"🔡","json_format":"📄",
    "write_file":"📝","read_file":"📖","list_files":"📂","delete_file":"🗑️",
    "run_command":"⚙️","clone_repo":"📦","commit_push":"🚀","generate_image":"🎨",
}

# ── streaming agent ───────────────────────────────────────────────────────────
def stream_agent_task(task: str, history: list, files: list | None = None,
                      stop_evt=None, sid: str = "") -> Iterator[Dict[str, Any]]:
    def _stopped(): return stop_evt is not None and stop_evt.is_set()

    # Extract + store token from task; mask it before sending to LLM
    token = extract_token(task)
    if token and sid:
        set_session_token(sid, token)
        yield {"type":"system","message":"🔑 Token stored for this session (not sent to AI)"}

    workdir = get_session_dir(sid) if sid else "/tmp/ca_anon"
    os.makedirs(workdir, exist_ok=True)
    session_token = get_session_token(sid) if sid else GH_TOKEN

    # Mask tokens before LLM ever sees them
    clean_task = mask_token(task)

    # Direct answer bypass
    direct = _try_direct(clean_task)
    if direct and not files:
        msgs = list(history)
        msgs.append({"role":"user","content":clean_task})
        msgs.append({"role":"assistant","content":direct})
        yield {"type":"done","content":direct,"provider":"Built-in","model":"direct","history":msgs}
        return

    # Direct clone bypass
    urls = _GITHUB_URL_RE.findall(clean_task)
    if urls and _CLONE_INTENT_RE.search(clean_task):
        for url in urls:
            yield {"type":"tool","icon":"📦","action":"clone_repo",
                   "label":url,"result":"Cloning...","file_path":None,"file_content":None}
            result = tool_clone_repo(url, session_token, workdir)
            yield {"type":"tool","icon":"📦","action":"clone_repo",
                   "label":url,"result":result,"file_path":None,"file_content":None}
        # List files for context
        all_files = []
        for url in urls:
            rname = url.rstrip('/').split('/')[-1].replace('.git','')
            rdir  = os.path.join(workdir, rname)
            if os.path.isdir(rdir):
                all_files += [os.path.relpath(os.path.join(dp,f), workdir)
                              for dp,_,fs in os.walk(rdir) for f in fs][:50]
        file_ctx = "\n".join(all_files[:60])
        clean_task = (f"Repos cloned to {workdir}.\nFiles:\n{file_ctx}\n\n"
                      f"Task: {clean_task}\n\nNow read key files, improve, commit and push.")

    messages: List[Dict] = list(history)
    messages.append({"role":"user","content":_build_content(clean_task, files or [])})

    providers_used: List[str] = []
    complexity = _score_complexity(clean_task)
    yield {"type":"complexity","level":complexity}

    for _ in range(MAX_LOOP):
        if _stopped():
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
            yield {"type":"done","content":"*(Stopped)*","provider":cfg.get("label","—"),
                   "model":"—","history":messages}
            return

        try:
            action, pid = call_llm_with_fallback(messages, clean_task)
        except AllProvidersExhausted as e:
            time.sleep(8)
            try: action, pid = call_llm_with_fallback(messages, clean_task)
            except AllProvidersExhausted:
                yield {"type":"error","message":str(e)+"\n\nAdd more API keys to avoid rate limits."}
                return

        if pid not in providers_used:
            providers_used.append(pid)
            if len(providers_used) > 1:
                yield {"type":"fallback",
                       "chain":" → ".join(PROVIDERS[p]["label"] for p in providers_used)}

        kind = action.get("action")

        if kind == "clarify":
            yield {"type":"clarify","questions":action.get("questions",[])}
            # Preserve full message history — when user answers, the next
            # stream call receives this history and continues with full context
            messages.append({"role":"assistant","content":json.dumps(action)})
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
            yield {"type":"done","content":"","provider":cfg.get("label","?"),
                   "model":_config["model"] or cfg.get("default_model","?"),
                   "history":messages}   # full history returned and stored in session
            return

        if kind == "plan":
            yield {"type":"plan","title":action.get("title",""),"steps":action.get("steps",[])}
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":"Plan looks good. Start building."})
            continue

        if kind == "think":
            yield {"type":"think","thought":action.get("thought","")}
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":"Continue based on your reasoning."})
            continue

        if kind == "respond":
            final = action.get("content","")
            messages.append({"role":"assistant","content":final})
            cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
            yield {"type":"done","content":final,
                   "provider":cfg.get("label","?"),
                   "model":_config["model"] or cfg.get("default_model","?"),
                   "history":messages}
            return

        # Built-in tools (no LLM needed)
        builtin_result = dispatch_builtin(action)

        icon  = TOOL_ICONS.get(kind,"🔧")
        label = (action.get("query") or action.get("path") or action.get("cmd") or
                 action.get("url") or action.get("location") or action.get("expr") or
                 action.get("timezone") or kind)

        if builtin_result is not None:
            # Image generation returns a dict with url
            if isinstance(builtin_result, dict) and "url" in builtin_result:
                yield {"type":"image","url":builtin_result["url"],
                       "prompt":builtin_result.get("prompt",""),
                       "width":builtin_result.get("width",1024),
                       "height":builtin_result.get("height",1024)}
                img_result_str = f"Image generated: {builtin_result['url']}"
                messages.append({"role":"assistant","content":json.dumps(action)})
                messages.append({"role":"user","content":f"Image generated successfully. URL: {builtin_result['url']}\n\nContinue."})
                continue
            yield {"type":"tool","icon":icon,"action":kind,"label":str(label)[:120],
                   "result":str(builtin_result)[:600],"file_path":None,"file_content":None}
            messages.append({"role":"assistant","content":json.dumps(action)})
            messages.append({"role":"user","content":f"Tool result:\n{builtin_result}\n\nContinue."})
            continue

        # File-system tools (need workdir)
        file_content = None
        file_path    = None
        artifact     = False
        try:
            if kind == "write_file":
                file_path    = action.get("path","file.txt")
                fc           = action.get("content","")
                result       = tool_write_file(file_path, fc, workdir)
                file_content = fc
                artifact     = _is_artifact(file_path, fc)
            elif kind == "read_file":
                file_path = action.get("path","")
                result    = tool_read_file(file_path, workdir)
            elif kind == "list_files":
                result = tool_list_files(action.get("pattern","**/*"), workdir)
            elif kind == "delete_file":
                result = tool_delete_file(action.get("path",""), workdir)
            elif kind == "image_gen":
                result = tool_image_gen(
                    action.get("prompt",""), action.get("width",512), action.get("height",512))
            elif kind == "run_command":
                result = tool_run_command(action.get("cmd",""), workdir)
            elif kind == "clone_repo":
                url    = action.get("url","")
                result = tool_clone_repo(url, session_token, workdir)
            elif kind == "commit_push":
                repo_url = action.get("repo_url") or GITHUB_REPO
                result   = tool_commit_push(action.get("message","Update"),
                                            repo_url, session_token, workdir)
            elif kind == "get_time":
                result = tool_get_time(action.get("timezone","UTC"))
            elif kind == "web_search":
                result = tool_web_search(action.get("query",""))
            else:
                result = f"Unknown action: {kind}"
        except Exception as e:
            try:
                if kind == "write_file":   result = tool_write_file(action.get("path",""), action.get("content",""), workdir)
                elif kind == "run_command": result = tool_run_command(action.get("cmd",""), workdir)
                else: result = f"Tool failed: {e}"
            except Exception as e2: result = f"Tool failed after retry: {e2}"

        yield {"type":"tool","icon":icon,"action":kind,"label":str(label)[:120],
               "result":str(result)[:600],"file_path":file_path,
               "file_content":file_content,"artifact":artifact,
               "workdir":workdir if artifact else None}
        messages.append({"role":"assistant","content":json.dumps(action)})
        messages.append({"role":"user","content":f"Tool result:\n{result}\n\nContinue."})

    # Hit MAX_LOOP
    cfg = PROVIDERS.get(providers_used[-1] if providers_used else "",{})
    final = "Reached max steps."
    messages.append({"role":"assistant","content":final})
    yield {"type":"done","content":final,"provider":cfg.get("label","?"),
           "model":_config["model"] or cfg.get("default_model","?"),"history":messages}

# ── non-streaming wrapper ─────────────────────────────────────────────────────
def run_agent_task(task, history, files=None, sid=""):
    tool_log, fallback_notice, final = [], "", None
    for evt in stream_agent_task(task, history, files, sid=sid):
        if evt["type"]=="tool":        tool_log.append(f"{evt['icon']} **`{evt['action']}`** `{evt['label']}` → {evt['result']}")
        elif evt["type"]=="think":     tool_log.append(f"💭 *{evt['thought']}*")
        elif evt["type"]=="fallback":  fallback_notice = f"*↩️ Auto-fallback: {evt['chain']}*\n\n"
        elif evt["type"] in ("done","error"): final = evt
    if not final: return {"result":"No response.","history":history,"provider":"?","model":"?"}
    if final["type"]=="error": return {"result":f"❌ {final['message']}","history":history,"provider":"none","model":"none"}
    shown = (fallback_notice + ("\n\n".join(tool_log)+"\n\n---\n\n" if tool_log else "") + final["content"])
    return {"result":shown,"history":final.get("history",history),"provider":final["provider"],"model":final["model"]}

# ── UI helpers ────────────────────────────────────────────────────────────────
def get_providers_list():
    result = []
    for pid, cfg in PROVIDERS.items():
        has_key = _has_key(cfg)
        cooling = _is_rate_limited(pid)
        result.append({"id":pid,"label":cfg["label"],
                       "model":_config["model"] or cfg["default_model"],
                       "available":has_key and not cooling,"has_key":has_key,
                       "rate_limited":cooling,
                       "cooldown_remaining":max(0,int(_cooldowns.get(pid,0)-time.time())),
                       "keyless":cfg.get("keyless",False)})
    return result
