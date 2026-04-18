"""
Built-in tools that don't need LLM calls — calculator, weather, currency,
unit converter, regex tester, base64, JSON formatter, color info.
"""
import os, re, json, math, subprocess, zipfile, base64 as b64lib
from pathlib import Path
from datetime import datetime
from .providers.model_router import ModelRouter
from .scheduler import (
    schedule_job,
    list_jobs,
    cancel_job,
    job_to_dict,
)
from .knowledge_graph import (
    kg_store as _kg_store,
    kg_query as _kg_query,
    kg_list_entities as _kg_list,
    kg_get as _kg_get,
)

# ── CALCULATOR ────────────────────────────────────────────────────────────────
_SAFE_NAMES = {k: v for k, v in math.__dict__.items() if not k.startswith('_')}
_SAFE_NAMES.update({'abs': abs, 'round': round, 'min': min, 'max': max,
                    'sum': sum, 'pow': pow, 'len': len})

def tool_calculate(expr: str) -> str:
    try:
        # Strip anything that looks like an import or dunder
        if any(kw in expr for kw in ['import','__','exec','eval','open','os','sys']):
            return "❌ Expression not allowed"
        result = eval(expr, {"__builtins__": {}}, _SAFE_NAMES)
        return f"**{expr}** = `{result}`"
    except Exception as e:
        return f"❌ Calculation error: {e}"


# ── WEATHER ───────────────────────────────────────────────────────────────────
def tool_weather(location: str) -> str:
    try:
        import requests
        loc = location.strip().replace(' ', '+')
        resp = requests.get(f"https://wttr.in/{loc}?format=j1", timeout=10)
        resp.raise_for_status()
        d = resp.json()
        cur = d['current_condition'][0]
        area = d['nearest_area'][0]
        city = area['areaName'][0]['value']
        country = area['country'][0]['value']
        desc = cur['weatherDesc'][0]['value']
        temp_c = cur['temp_C']
        temp_f = cur['temp_F']
        feels_c = cur['FeelsLikeC']
        humidity = cur['humidity']
        wind_kmph = cur['windspeedKmph']
        return (f"**{city}, {country}** — {desc}\n"
                f"🌡️ {temp_c}°C / {temp_f}°F (feels like {feels_c}°C)\n"
                f"💧 Humidity: {humidity}%  💨 Wind: {wind_kmph} km/h")
    except Exception as e:
        return f"❌ Weather lookup failed: {e}"


# ── CURRENCY ──────────────────────────────────────────────────────────────────
def tool_currency(amount: float, from_cur: str, to_cur: str) -> str:
    try:
        import requests
        # Open exchange rates free endpoint (no key needed for latest)
        resp = requests.get(
            f"https://open.er-api.com/v6/latest/{from_cur.upper()}",
            timeout=10
        )
        resp.raise_for_status()
        d = resp.json()
        if d.get('result') != 'success':
            return f"❌ Currency lookup failed: {d.get('error-type','unknown')}"
        rate = d['rates'].get(to_cur.upper())
        if not rate:
            return f"❌ Unknown currency: {to_cur}"
        converted = amount * rate
        return (f"**{amount:,.2f} {from_cur.upper()}** = "
                f"**{converted:,.2f} {to_cur.upper()}**\n"
                f"Rate: 1 {from_cur.upper()} = {rate:.4f} {to_cur.upper()}\n"
                f"*Updated: {d.get('time_last_update_utc','?')}*")
    except Exception as e:
        return f"❌ Currency error: {e}"


# ── UNIT CONVERTER ────────────────────────────────────────────────────────────
_UNITS = {
    # length (base: meter)
    'km':1000,'m':1,'cm':0.01,'mm':0.001,'mile':1609.344,'miles':1609.344,
    'yard':0.9144,'yards':0.9144,'ft':0.3048,'feet':0.3048,'inch':0.0254,'inches':0.0254,
    # weight (base: kg)
    'kg':1,'g':0.001,'mg':0.000001,'lb':0.453592,'lbs':0.453592,'oz':0.028349,
    # volume (base: liter)
    'l':1,'ml':0.001,'gallon':3.78541,'gallons':3.78541,'cup':0.236588,'cups':0.236588,
    'fl oz':0.029574,'tbsp':0.014787,'tsp':0.004929,
    # temperature handled separately
    'c':'temp','f':'temp','k':'temp',
    # data (base: byte)
    'b':1,'kb':1024,'mb':1048576,'gb':1073741824,'tb':1099511627776,
}
_UNIT_GROUPS = {
    'length':  ['km','m','cm','mm','mile','miles','yard','yards','ft','feet','inch','inches'],
    'weight':  ['kg','g','mg','lb','lbs','oz'],
    'volume':  ['l','ml','gallon','gallons','cup','cups'],
    'data':    ['b','kb','mb','gb','tb'],
}

def _temp_convert(val, from_u, to_u):
    from_u, to_u = from_u.lower(), to_u.lower()
    # to Celsius first
    if from_u == 'f':   c = (val - 32) * 5/9
    elif from_u == 'k': c = val - 273.15
    else:               c = val
    # Celsius to target
    if to_u == 'f':     return c * 9/5 + 32
    elif to_u == 'k':   return c + 273.15
    return c

def tool_convert(value: float, from_unit: str, to_unit: str) -> str:
    f, t = from_unit.lower().strip(), to_unit.lower().strip()
    # Temperature
    if f in ('c','f','k') or t in ('c','f','k'):
        result = _temp_convert(value, f, t)
        names = {'c':'°C','f':'°F','k':'K'}
        return f"**{value}{names.get(f,f)}** = **{result:.4g}{names.get(t,t)}**"
    if f not in _UNITS or t not in _UNITS:
        return f"❌ Unknown units: {from_unit} or {to_unit}"
    # Check same group
    grp_f = next((g for g,u in _UNIT_GROUPS.items() if f in u), None)
    grp_t = next((g for g,u in _UNIT_GROUPS.items() if t in u), None)
    if grp_f != grp_t:
        return f"❌ Can't convert between {grp_f or from_unit} and {grp_t or to_unit}"
    base = value * _UNITS[f]
    result = base / _UNITS[t]
    return f"**{value} {from_unit}** = **{result:.6g} {to_unit}**"


# ── REGEX TESTER ──────────────────────────────────────────────────────────────
def tool_regex(pattern: str, text: str, flags_str: str = "") -> str:
    try:
        flag_map = {'i': re.IGNORECASE, 'm': re.MULTILINE, 's': re.DOTALL}
        flags = 0
        for c in flags_str.lower():
            flags |= flag_map.get(c, 0)
        matches = list(re.finditer(pattern, text, flags))
        if not matches:
            return f"No matches for `{pattern}` in the given text."
        lines = [f"**{len(matches)} match{'es' if len(matches)>1 else ''}** for `{pattern}`:\n"]
        for i, m in enumerate(matches[:10], 1):
            lines.append(f"{i}. `{m.group()}` at position {m.start()}–{m.end()}")
            if m.groups():
                lines.append(f"   Groups: {m.groups()}")
        if len(matches) > 10:
            lines.append(f"…and {len(matches)-10} more")
        return "\n".join(lines)
    except re.error as e:
        return f"❌ Regex error: {e}"


# ── BASE64 ────────────────────────────────────────────────────────────────────
def tool_base64(text: str, mode: str = "encode") -> str:
    try:
        if mode == "encode":
            result = b64lib.b64encode(text.encode()).decode()
            return f"**Encoded:**\n```\n{result}\n```"
        else:
            result = b64lib.b64decode(text.encode()).decode()
            return f"**Decoded:**\n```\n{result}\n```"
    except Exception as e:
        return f"❌ Base64 error: {e}"


# ── JSON FORMATTER ────────────────────────────────────────────────────────────
def tool_json_format(text: str) -> str:
    try:
        parsed = json.loads(text)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        return f"```json\n{formatted}\n```"
    except json.JSONDecodeError as e:
        return f"❌ Invalid JSON: {e}"


def tool_select_model(task: str, prefer_speed: bool = False, prefer_quality: bool = False) -> str:
    try:
        router = ModelRouter()
        model_id, spec = router.select_model(task, prefer_speed=prefer_speed, prefer_quality=prefer_quality)
        languages = ", ".join(spec.languages) if spec.languages else "all"
        return (
            f"Selected model: {spec.name} ({model_id})\n"
            f"Tier: {spec.tier.value}\n"
            f"Estimated RAM: {spec.ram_required_gb}GB\n"
            f"Strengths: {', '.join(spec.strengths)}\n"
            f"Languages: {languages}"
        )
    except Exception as e:
        return f"Model selection failed: {e}"


_RAG_SYSTEM = None

def _get_rag_system():
    global _RAG_SYSTEM
    if _RAG_SYSTEM is None:
        from .rag.rag_system import RAGSystem
        _RAG_SYSTEM = RAGSystem()
    return _RAG_SYSTEM


def tool_rag_ingest(text: str = "", path: str = "", metadata: dict | None = None,
                    doc_id_prefix: str | None = None, workdir: str = "/tmp") -> str:
    if path:
        full = path if os.path.isabs(path) else os.path.join(workdir, path)
        if not os.path.exists(full):
            return f"File not found: {path}"
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception as e:
            return f"Failed to read file: {e}"

    if not text:
        return "No text or file path provided to ingest."

    try:
        count = _get_rag_system().ingest(text, metadata=metadata or {}, doc_id_prefix=doc_id_prefix)
        source = f"file {path}" if path else "text"
        return f"RAG ingested {count} chunks from {source}."
    except Exception as e:
        return f"RAG ingest failed: {e}"


def tool_rag_query(query: str, top_k: int = 5, filter_metadata: dict | None = None) -> str:
    try:
        results = _get_rag_system().query(query, top_k=top_k, filter_metadata=filter_metadata)
    except Exception as e:
        return f"RAG query failed: {e}"
    if not results:
        return "No relevant RAG results found."
    lines = []
    for i, r in enumerate(results, 1):
        doc = str(r.get("document", "")).strip().replace("\n", " ")
        score = r.get("score", "?")
        source = r.get("metadata", {}).get("source", "unknown") if isinstance(r.get("metadata"), dict) else "unknown"
        lines.append(f"{i}. score={score} source={source}\n{doc[:320]}")
    return "\n\n".join(lines)


def tool_rag_status() -> str:
    try:
        stats = _get_rag_system().stats()
        return (f"RAG status: ingested={stats.get('total_ingested', 0)}, "
                f"queries={stats.get('total_queries', 0)}, "
                f"store_count={stats.get('store_count', 0)}, "
                f"backend={stats.get('embedding_backend', 'unknown')}")
    except Exception as e:
        return f"RAG status failed: {e}"


# ── TRACE HELPER ─────────────────────────────────────────────────────────────
def _tool_trace(
    action: dict,
    result: str,
    metadata: dict | None = None,
    status: str = "done",
    error: str | None = None,
) -> dict:
    """
    Return a structured trace dict for a completed tool call.
    agent.py unpacks .result / .metadata / .status for event emission.
    Shape: { action, tool_name, status, input, result, metadata, error }
    """
    return {
        "action":    action.get("action"),
        "tool_name": action.get("action"),
        "status":    status,
        "input":     action,
        "result":    result,
        "metadata":  metadata or {},
        "error":     error,
    }


# ── DISPATCH ──────────────────────────────────────────────────────────────────
def dispatch_builtin(action: dict) -> dict | None:
    """
    Returns a structured trace dict or None if action is not a built-in tool.
    Shape: { action, tool_name, status, input, result, metadata, error }
    """
    kind = action.get("action")
    if kind == "calculate":
        r = tool_calculate(action.get("expr", ""))
        return _tool_trace(action, r, {"expr": action.get("expr", "")})
    if kind == "weather":
        r = tool_weather(action.get("location", ""))
        return _tool_trace(action, r, {"location": action.get("location", "")})
    if kind == "currency":
        r = tool_currency(float(action.get("amount", 1)),
                          action.get("from", "USD"), action.get("to", "EUR"))
        return _tool_trace(action, r, {
            "amount": action.get("amount"), "from": action.get("from"), "to": action.get("to")})
    if kind == "convert":
        r = tool_convert(float(action.get("value", 0)),
                         action.get("from_unit", ""), action.get("to_unit", ""))
        return _tool_trace(action, r, {
            "value": action.get("value"),
            "from_unit": action.get("from_unit"),
            "to_unit": action.get("to_unit"),
        })
    if kind == "regex":
        r = tool_regex(action.get("pattern", ""), action.get("text", ""),
                       action.get("flags", ""))
        return _tool_trace(action, r, {
            "pattern": action.get("pattern", ""), "flags": action.get("flags", "")})
    if kind == "base64":
        r = tool_base64(action.get("text", ""), action.get("mode", "encode"))
        return _tool_trace(action, r, {"mode": action.get("mode", "encode")})
    if kind == "json_format":
        r = tool_json_format(action.get("text", ""))
        return _tool_trace(action, r)
    if kind == "select_model":
        r = tool_select_model(action.get("task", ""),
                              bool(action.get("prefer_speed", False)),
                              bool(action.get("prefer_quality", False)))
        return _tool_trace(action, r, {
            "task": action.get("task", ""),
            "prefer_quality": action.get("prefer_quality", False),
        })
    if kind == "rag_ingest":
        r = tool_rag_ingest(action.get("text", ""), action.get("path", ""),
                            action.get("metadata", {}),
                            action.get("doc_id_prefix", None),
                            action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {
            "path": action.get("path", ""), "doc_id_prefix": action.get("doc_id_prefix")})
    if kind == "rag_query":
        r = tool_rag_query(action.get("query", ""), action.get("top_k", 5),
                           action.get("filter_metadata", None))
        return _tool_trace(action, r, {
            "query": action.get("query", ""), "top_k": action.get("top_k", 5)})
    if kind == "rag_status":
        r = tool_rag_status()
        return _tool_trace(action, r)
    if kind == "inspect_db":
        r = tool_inspect_db(action.get("connection_string", ""))
        return _tool_trace(action, r, {"connection_string": action.get("connection_string", "")})
    if kind == "query_db":
        r = tool_query_db(action.get("connection_string", ""), action.get("query", ""))
        return _tool_trace(action, r, {
            "connection_string": action.get("connection_string", ""), "query": action.get("query", "")})
    if kind == "cron_schedule":
        r = tool_cron_schedule(
            action.get("name", "background-task"),
            action.get("task", ""),
            action.get("schedule", "5m"),
        )
        return _tool_trace(action, r, {
            "name": action.get("name", "background-task"),
            "schedule": action.get("schedule", "5m"),
        })
    if kind == "cron_list":
        r = tool_cron_list()
        return _tool_trace(action, r)
    if kind == "cron_cancel":
        r = tool_cron_cancel(action.get("job_id", ""))
        return _tool_trace(action, r, {"job_id": action.get("job_id", "")})
    if kind == "kg_store":
        r = tool_kg_store(
            action.get("name", ""),
            action.get("entity_type", "concept"),
            action.get("facts", {}),
            action.get("relations", []),
        )
        return _tool_trace(action, r, {"name": action.get("name", "")})
    if kind == "kg_query":
        r = tool_kg_query(action.get("query", ""), int(action.get("limit", 10)))
        return _tool_trace(action, r, {"query": action.get("query", "")})
    if kind == "kg_list":
        r = tool_kg_list(action.get("entity_type", None))
        return _tool_trace(action, r, {"entity_type": action.get("entity_type")})
    if kind == "read_page":
        r = tool_read_page(action.get("url", ""))
        return _tool_trace(action, r, {"url": action.get("url", "")})
    if kind == "api_call":
        r = tool_api_call(action.get("method", "GET"), action.get("url", ""),
                          action.get("headers"), action.get("body"))
        return _tool_trace(action, r, {"method": action.get("method", "GET"),
                                       "url": action.get("url", "")})
    if kind == "search_in_files":
        r = tool_search_in_files(
            action.get("pattern", ""),
            action.get("include_glob", "*"),
            action.get("workdir", "/tmp"),
            int(action.get("max_results", 200)),
        )
        return _tool_trace(action, r, {"pattern": action.get("pattern", "")})
    if kind == "create_directory":
        r = tool_create_directory(action.get("path", ""), action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"path": action.get("path", "")})
    if kind == "zip_files":
        r = tool_zip_files(
            action.get("paths", []),
            action.get("output_path", "archive.zip"),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {"output_path": action.get("output_path", "archive.zip")})
    if kind == "unzip_files":
        r = tool_unzip_files(
            action.get("zip_path", ""),
            action.get("dest_path", ""),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {"zip_path": action.get("zip_path", "")})
    if kind == "git_status":
        r = tool_git_status(action.get("repo_path", "."), action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"repo_path": action.get("repo_path", ".")})
    if kind == "git_log":
        r = tool_git_log(
            action.get("repo_path", "."),
            int(action.get("max_count", 20)),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {"repo_path": action.get("repo_path", ".")})
    if kind == "git_diff":
        r = tool_git_diff(
            action.get("repo_path", "."),
            action.get("ref", "HEAD"),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {
            "repo_path": action.get("repo_path", "."),
            "ref": action.get("ref", "HEAD"),
        })
    if kind == "git_checkout":
        r = tool_git_checkout(
            action.get("repo_path", "."),
            action.get("branch", ""),
            bool(action.get("create", False)),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {
            "repo_path": action.get("repo_path", "."),
            "branch": action.get("branch", ""),
        })
    if kind == "git_pull":
        r = tool_git_pull(
            action.get("repo_path", "."),
            action.get("remote", "origin"),
            action.get("branch", ""),
            bool(action.get("ff_only", True)),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {"repo_path": action.get("repo_path", ".")})
    if kind == "create_pull_request":
        r = tool_create_pull_request(
            action.get("title", ""),
            action.get("body", ""),
            action.get("base", "main"),
            action.get("head", ""),
            action.get("repo_path", "."),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {"title": action.get("title", "")})
    if kind == "list_issues":
        r = tool_list_issues(
            action.get("repo_path", "."),
            action.get("state", "open"),
            int(action.get("limit", 20)),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {"repo_path": action.get("repo_path", ".")})
    if kind == "create_issue":
        r = tool_create_issue(
            action.get("title", ""),
            action.get("body", ""),
            action.get("labels", ""),
            action.get("repo_path", "."),
            action.get("workdir", "/tmp"),
        )
        return _tool_trace(action, r, {"title": action.get("title", "")})
    if kind in ("youtube_transcript", "youtube"):
        r = tool_youtube_transcript(action.get("url", ""))
        return _tool_trace(action, r, {"url": action.get("url", "")})
    if kind == "generate_image":
        g = tool_generate_image(action.get("prompt", ""),
                                 action.get("width", 1024), action.get("height", 1024))
        r = f"![Generated image]({g['url']})\n\n*Prompt: {g['prompt']}*"
        return _tool_trace(action, r, {"prompt": action.get("prompt", "")})
    if kind == "diff":
        r = tool_diff(action.get("original", ""), action.get("modified", ""),
                      action.get("filename", "file"))
        return _tool_trace(action, r, {"filename": action.get("filename", "file")})
    if kind == "read_csv":
        r = tool_read_csv(action.get("path", ""), action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"path": action.get("path", "")})
    if kind == "write_csv":
        r = tool_write_csv(action.get("path", ""), action.get("data", []),
                           action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"path": action.get("path", "")})
    if kind == "read_pdf":
        r = tool_read_pdf(action.get("path", ""), action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"path": action.get("path", "")})
    if kind == "read_docx":
        r = tool_read_docx(action.get("path", ""), action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"path": action.get("path", "")})
    if kind == "read_xlsx":
        r = tool_read_xlsx(action.get("path", ""), action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"path": action.get("path", "")})
    if kind == "read_pptx":
        r = tool_read_pptx(action.get("path", ""), action.get("workdir", "/tmp"))
        return _tool_trace(action, r, {"path": action.get("path", "")})
    if kind == "ollama_list_models":
        from .agent import tool_ollama_list_models
        r = tool_ollama_list_models()
        return _tool_trace(action, r)
    return None


# ── IMAGE GENERATION ──────────────────────────────────────────────────────────
def tool_generate_image(prompt: str, width: int = 1024, height: int = 1024,
                         model: str = "flux") -> dict:
    """
    Generate an image via Pollinations.ai (free, no API key).
    Returns a dict with the image URL and prompt used.
    """
    import urllib.parse
    encoded = urllib.parse.quote(prompt)
    seed    = hash(prompt) % 9999
    url     = (f"https://image.pollinations.ai/prompt/{encoded}"
               f"?width={width}&height={height}&model={model}&seed={seed}&nologo=true")
    return {"url": url, "prompt": prompt, "width": width, "height": height}


# ── YOUTUBE TRANSCRIPT ────────────────────────────────────────────────────────
def tool_youtube_transcript(url: str) -> str:
    """Extract subtitles/transcript from a YouTube video using yt-dlp."""
    try:
        import yt_dlp, tempfile, os, json as _json
        opts = {
            "skip_download": True,
            "writeautomaticsub": True,
            "writesubtitles": True,
            "subtitleslangs": ["en", "en-US"],
            "subtitlesformat": "json3",
            "quiet": True,
            "no_warnings": True,
            "outtmpl": os.path.join(tempfile.gettempdir(), "%(id)s.%(ext)s"),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            vid_id  = info.get("id","")
            title   = info.get("title","")
            duration= info.get("duration", 0)

        # Find downloaded subtitle file
        tmp = tempfile.gettempdir()
        for ext in [f"{vid_id}.en.json3", f"{vid_id}.en-US.json3"]:
            fpath = os.path.join(tmp, ext)
            if os.path.exists(fpath):
                with open(fpath) as f:
                    data = _json.load(f)
                texts = []
                for event in data.get("events", []):
                    for seg in event.get("segs", []):
                        t = seg.get("utf8", "").strip()
                        if t and t != "\n":
                            texts.append(t)
                transcript = " ".join(texts)
                os.remove(fpath)
                mins = duration // 60
                return (f"**{title}** ({mins}m)\n\n"
                        f"{transcript[:4000]}"
                        + (" …*(truncated)*" if len(transcript) > 4000 else ""))
        return f"No English subtitles found for: {title or url}"
    except Exception as e:
        return f"YouTube transcript failed: {e}"


# ── YOUTUBE TRANSCRIPT ────────────────────────────────────────────────────────
def tool_youtube(url: str) -> str:
    """Fetch YouTube transcript via youtube-transcript-api or scrape description."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        import re as _re
        vid_match = _re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})', url)
        if not vid_match:
            return f"❌ Could not extract video ID from URL: {url}"
        vid_id = vid_match.group(1)
        transcript = YouTubeTranscriptApi.get_transcript(vid_id)
        text = " ".join(t["text"] for t in transcript)
        # Truncate to ~4000 chars
        if len(text) > 4000:
            text = text[:4000] + f"\n… (transcript truncated, {len(text)} total chars)"
        return f"**YouTube transcript** ({vid_id}):\n\n{text}"
    except ImportError:
        # Fallback: yt-dlp metadata only
        try:
            import subprocess, json as _json
            r = subprocess.run(
                ["yt-dlp", "--dump-json", "--no-download", url],
                capture_output=True, text=True, timeout=20
            )
            if r.returncode == 0:
                d = _json.loads(r.stdout)
                return (f"**{d.get('title','')}** ({d.get('uploader','')})\n"
                        f"Duration: {d.get('duration_string','?')}\n\n"
                        f"{d.get('description','No description')[:1500]}")
        except Exception:
            pass
        return "❌ youtube-transcript-api not installed. Run: pip install youtube-transcript-api"
    except Exception as e:
        return f"❌ YouTube transcript failed: {e}"


# ── PDF READER ────────────────────────────────────────────────────────────────
def tool_read_pdf(path: str, workdir: str = "/tmp") -> str:
    """Extract text from a PDF file."""
    import os as _os
    full = _os.path.join(workdir, path) if not _os.path.isabs(path) else path
    if not _os.path.exists(full):
        return f"❌ File not found: {path}"
    try:
        import pypdf
        reader = pypdf.PdfReader(full)
        pages  = []
        for i, page in enumerate(reader.pages[:50]):   # first 50 pages (production limit)
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {i+1}]\n{text.strip()}")
        if not pages:
            return "❌ No extractable text found (may be a scanned PDF)"
        total = len(reader.pages)
        content = "\n\n".join(pages)
        if len(content) > 12000:
            content = content[:12000] + f"\n\n… (truncated, {total} pages total)"
        return content
    except ImportError:
        return "❌ pypdf not installed. Run: pip install pypdf"
    except Exception as e:
        return f"❌ PDF read failed: {e}"


# ── DIFF VIEWER ───────────────────────────────────────────────────────────────
def tool_diff(original: str, modified: str, filename: str = "file") -> str:
    """Generate a unified diff between two text strings."""
    import difflib
    orig_lines = original.splitlines(keepends=True)
    mod_lines  = modified.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        orig_lines, mod_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm=""
    ))
    if not diff:
        return "No differences found."
    diff_text = "\n".join(diff)
    if len(diff_text) > 4000:
        diff_text = diff_text[:4000] + "\n… (diff truncated)"
    return f"```diff\n{diff_text}\n```"


# ── OFFICE DOCUMENT READERS ───────────────────────────────────────────────────

def tool_read_docx(path: str, workdir: str = "/tmp") -> str:
    """Extract text from a Word (.docx) file, including heading structure and tables."""
    import os as _os
    full = _os.path.join(workdir, path) if not _os.path.isabs(path) else path
    if not _os.path.exists(full):
        return f"❌ File not found: {path}"
    try:
        from docx import Document
        doc = Document(full)
        parts = []
        # Paragraphs with heading structure
        for para in doc.paragraphs:
            if not para.text.strip():
                continue
            style = para.style.name if para.style else ""
            if style.startswith("Heading "):
                try:
                    level = int(style.split()[-1])
                except (ValueError, IndexError):
                    level = 1
                marker = "#" * min(level, 4)
                parts.append(f"{marker} {para.text.strip()}")
            else:
                parts.append(para.text.strip())
        # Tables
        for tbl_idx, table in enumerate(doc.tables):
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                parts.append(f"[Table {tbl_idx + 1}]\n" + "\n".join(rows[:100]))
        content = "\n\n".join(parts)
        if len(content) > 8000:
            content = content[:8000] + f"\n\n… (truncated, {len(doc.paragraphs)} paragraphs, {len(doc.tables)} tables)"
        return content if content else "❌ No extractable text found in document."
    except ImportError:
        return "❌ python-docx not installed. Run: pip install python-docx"
    except Exception as e:
        return f"❌ DOCX read failed: {e}"


def tool_read_xlsx(path: str, workdir: str = "/tmp") -> str:
    """Extract data from an Excel (.xlsx) file."""
    import os as _os
    full = _os.path.join(workdir, path) if not _os.path.isabs(path) else path
    if not _os.path.exists(full):
        return f"❌ File not found: {path}"
    try:
        import openpyxl
        wb = openpyxl.load_workbook(full, read_only=True, data_only=True)
        lines = []
        for sheet_name in wb.sheetnames[:5]:   # first 5 sheets (production limit)
            ws = wb[sheet_name]
            lines.append(f"### Sheet: {sheet_name}")
            row_count = 0
            for row in ws.iter_rows(max_row=200, values_only=True):   # 200 rows per sheet
                cells = [str(c) if c is not None else "" for c in row]
                if any(cells):
                    lines.append(" | ".join(cells))
                    row_count += 1
            if ws.max_row and ws.max_row > 200:
                lines.append(f"… ({ws.max_row - 200} more rows in sheet)")
        wb.close()
        content = "\n".join(lines)
        return content if content.strip() else "❌ No data found in workbook."
    except ImportError:
        return "❌ openpyxl not installed. Run: pip install openpyxl"
    except Exception as e:
        return f"❌ XLSX read failed: {e}"


def tool_read_pptx(path: str, workdir: str = "/tmp") -> str:
    """Extract text from a PowerPoint (.pptx) file."""
    import os as _os
    full = _os.path.join(workdir, path) if not _os.path.isabs(path) else path
    if not _os.path.exists(full):
        return f"❌ File not found: {path}"
    try:
        from pptx import Presentation
        prs = Presentation(full)
        slides = []
        for i, slide in enumerate(prs.slides[:30]):   # first 30 slides
            texts = []
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text.strip())
            if texts:
                slides.append(f"[Slide {i+1}]\n" + "\n".join(texts))
        content = "\n\n".join(slides)
        total = len(prs.slides)
        if len(content) > 6000:
            content = content[:6000] + f"\n\n… (truncated, {total} slides total)"
        return content if content else "❌ No text found in presentation."
    except ImportError:
        return "❌ python-pptx not installed. Run: pip install python-pptx"
    except Exception as e:
        return f"❌ PPTX read failed: {e}"


# ── SPREADSHEET (CSV) ─────────────────────────────────────────────────────────
def tool_read_csv(path: str, workdir: str = "/tmp") -> str:
    import os, csv
    full = os.path.join(workdir, path) if not os.path.isabs(path) else path
    if not os.path.exists(full):
        return f"File not found: {path}"
    try:
        with open(full, newline='', encoding='utf-8', errors='replace') as f:
            reader = list(csv.reader(f))
        if not reader:
            return "Empty CSV."
        headers = reader[0]
        rows    = reader[1:51]   # first 50 data rows
        lines   = [" | ".join(headers)]
        lines  += ["-+-".join("-" * max(1,len(h)) for h in headers)]
        for row in rows:
            lines.append(" | ".join(str(v)[:30] for v in row))
        suffix = f"\n…({len(reader)-51} more rows)" if len(reader) > 51 else ""
        return f"**{path}** — {len(reader)-1} rows × {len(headers)} cols\n\n```\n" + "\n".join(lines) + f"\n```{suffix}"
    except Exception as e:
        return f"CSV read failed: {e}"


def tool_write_csv(path: str, data: list, workdir: str = "/tmp") -> str:
    """data: list of lists (first row = headers)"""
    import os, csv
    full = os.path.join(workdir, path) if not os.path.isabs(path) else path
    os.makedirs(os.path.dirname(full), exist_ok=True)
    try:
        with open(full, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(data)
        return f"Wrote {path} ({len(data)} rows)"
    except Exception as e:
        return f"CSV write failed: {e}"


# ── API CALLER ────────────────────────────────────────────────────────────────
def tool_api_call(method: str, url: str, headers: dict | None = None,
                  body: dict | str | None = None, timeout: int = 15) -> str:
    import requests as _r, json as _j
    BLOCKED_HOSTS = ["169.254.", "192.168.", "10.", "127.", "0.0.0.0", "localhost"]
    for b in BLOCKED_HOSTS:
        if b in url:
            return f"Blocked: cannot call internal/local addresses."
    try:
        method = method.upper()
        hdrs   = {"User-Agent": "ClaudeAlt/1.0", **(headers or {})}
        kwargs = {"headers": hdrs, "timeout": timeout}
        if body:
            if isinstance(body, dict):
                kwargs["json"] = body
            else:
                kwargs["data"] = body
        resp = getattr(_r, method.lower())(url, **kwargs)
        ct   = resp.headers.get("Content-Type", "")
        if "json" in ct:
            try:
                data = resp.json()
                text = _j.dumps(data, indent=2)[:3000]
            except Exception:
                text = resp.text[:3000]
        else:
            text = resp.text[:3000]
        return f"**{method} {url}**\nStatus: {resp.status_code}\n\n```\n{text}\n```"
    except Exception as e:
        return f"API call failed: {e}"


# ── PAGE READER ───────────────────────────────────────────────────────────────
def tool_read_page(url: str) -> str:
    """Fetch a webpage and return readable text (strips HTML tags)."""
    import requests as _r, re as _re, html as _html
    BLOCKED = ["localhost", "127.", "192.168.", "10.", "169.254."]
    for b in BLOCKED:
        if b in url:
            return "Blocked: internal addresses."
    try:
        resp = _r.get(url, headers={"User-Agent":"Mozilla/5.0"},
                      timeout=15, allow_redirects=True)
        resp.raise_for_status()
        text = resp.text
        # Strip scripts/styles
        text = _re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', text, flags=_re.S|_re.I)
        # Strip tags
        text = _re.sub(r'<[^>]+>', ' ', text)
        # Decode entities
        text = _html.unescape(text)
        # Collapse whitespace
        text = _re.sub(r'\s{3,}', '\n\n', text).strip()
        return text[:5000] + ("…*(truncated)*" if len(text) > 5000 else "")
    except Exception as e:
        return f"Page read failed: {e}"


# ── FILESYSTEM + GIT HELPERS ────────────────────────────────────────────────
def _resolve_path(path: str, workdir: str = "/tmp") -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(workdir) / candidate
    return candidate.resolve()


def tool_search_in_files(pattern: str, include_glob: str = "*", workdir: str = "/tmp", max_results: int = 200) -> str:
    """Search files recursively with regex and return matching lines."""
    if not pattern.strip():
        return "❌ pattern is required."
    root = _resolve_path(".", workdir)
    if not root.exists():
        return f"❌ workdir does not exist: {workdir}"

    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"❌ Invalid regex pattern: {e}"

    matches: list[str] = []
    files_scanned = 0
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        if include_glob and not file_path.match(include_glob):
            continue
        files_scanned += 1
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f, start=1):
                    if rx.search(line):
                        rel = file_path.relative_to(root)
                        matches.append(f"{rel}:{idx}: {line.rstrip()[:240]}")
                        if len(matches) >= max_results:
                            break
        except Exception:
            continue
        if len(matches) >= max_results:
            break

    if not matches:
        return f"No matches found for /{pattern}/ in {files_scanned} files."
    return (
        f"Found {len(matches)} match(es) in {files_scanned} file(s).\n\n"
        + "```\n"
        + "\n".join(matches)
        + "\n```"
    )


def tool_create_directory(path: str, workdir: str = "/tmp") -> str:
    """Create a directory recursively (mkdir -p semantics)."""
    if not path.strip():
        return "❌ path is required."
    target = _resolve_path(path, workdir)
    try:
        target.mkdir(parents=True, exist_ok=True)
        return f"✅ Directory ready: {target}"
    except Exception as e:
        return f"❌ Failed to create directory: {e}"


def tool_zip_files(paths: list[str], output_path: str, workdir: str = "/tmp") -> str:
    """Create a ZIP archive from files/directories."""
    if not paths:
        return "❌ paths is required."
    if not output_path.strip():
        return "❌ output_path is required."

    root = _resolve_path(".", workdir)
    out = _resolve_path(output_path, workdir)
    out.parent.mkdir(parents=True, exist_ok=True)

    added = 0
    try:
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for raw_path in paths:
                src = _resolve_path(raw_path, workdir)
                if not src.exists():
                    continue
                if src.is_file():
                    arcname = src.relative_to(root) if src.is_relative_to(root) else src.name
                    zf.write(src, arcname=str(arcname))
                    added += 1
                else:
                    for child in src.rglob("*"):
                        if child.is_file():
                            arcname = child.relative_to(root) if child.is_relative_to(root) else child.name
                            zf.write(child, arcname=str(arcname))
                            added += 1
        return f"✅ Created zip: {out} ({added} file(s))"
    except Exception as e:
        return f"❌ ZIP creation failed: {e}"


def tool_unzip_files(zip_path: str, dest_path: str = "", workdir: str = "/tmp") -> str:
    """Extract a ZIP archive into destination path."""
    if not zip_path.strip():
        return "❌ zip_path is required."
    src = _resolve_path(zip_path, workdir)
    if not src.exists():
        return f"❌ ZIP not found: {zip_path}"
    dest = _resolve_path(dest_path, workdir) if dest_path else _resolve_path(".", workdir)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(src, "r") as zf:
            zf.extractall(dest)
            extracted_count = len(zf.namelist())
        return f"✅ Extracted {extracted_count} entrie(s) to {dest}"
    except Exception as e:
        return f"❌ Unzip failed: {e}"


def _run_git(repo_path: str, args: list[str], workdir: str = "/tmp") -> tuple[int, str, str]:
    repo = _resolve_path(repo_path or ".", workdir)
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def tool_git_status(repo_path: str = ".", workdir: str = "/tmp") -> str:
    """Show current git working tree status."""
    code, out, err = _run_git(repo_path, ["status", "--short", "--branch"], workdir=workdir)
    if code != 0:
        return f"❌ git_status failed: {err or 'unknown error'}"
    return out or "Working tree clean."


def tool_git_log(repo_path: str = ".", max_count: int = 20, workdir: str = "/tmp") -> str:
    """Show recent git commit history."""
    if max_count <= 0:
        max_count = 20
    code, out, err = _run_git(
        repo_path,
        ["log", f"--max-count={max_count}", "--pretty=format:%h %ad %an %s", "--date=short"],
        workdir=workdir,
    )
    if code != 0:
        return f"❌ git_log failed: {err or 'unknown error'}"
    return out or "No commits found."


def tool_git_diff(repo_path: str = ".", ref: str = "HEAD", workdir: str = "/tmp") -> str:
    """Show git diff against a reference (default HEAD)."""
    code, out, err = _run_git(repo_path, ["--no-pager", "diff", ref], workdir=workdir)
    if code != 0:
        return f"❌ git_diff failed: {err or 'unknown error'}"
    if not out:
        return "No diff."
    if len(out) > 8000:
        out = out[:8000] + "\n... (diff truncated)"
    return f"```diff\n{out}\n```"


def tool_git_checkout(repo_path: str, branch: str, create: bool = False, workdir: str = "/tmp") -> str:
    """Checkout a git branch, optionally creating it."""
    if not branch.strip():
        return "❌ branch is required."
    args = ["checkout"]
    if create:
        args.append("-b")
    args.append(branch)
    code, out, err = _run_git(repo_path or ".", args, workdir=workdir)
    if code != 0:
        return f"❌ git_checkout failed: {err or 'unknown error'}"
    return out or f"✅ Checked out {branch}"


def tool_git_pull(repo_path: str = ".", remote: str = "origin", branch: str = "", ff_only: bool = True, workdir: str = "/tmp") -> str:
    """Pull latest changes from remote with optional ff-only safety."""
    args = ["pull"]
    if ff_only:
        args.append("--ff-only")
    if remote:
        args.append(remote)
    if branch:
        args.append(branch)
    code, out, err = _run_git(repo_path, args, workdir=workdir)
    if code != 0:
        return f"❌ git_pull failed: {err or 'unknown error'}"
    return out or "✅ Pull completed."


def _run_gh(args: list[str], repo_path: str = ".", workdir: str = "/tmp") -> tuple[int, str, str]:
    repo = _resolve_path(repo_path or ".", workdir)
    proc = subprocess.run(
        ["gh", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=45,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def tool_create_pull_request(title: str, body: str = "", base: str = "main", head: str = "", repo_path: str = ".", workdir: str = "/tmp") -> str:
    """Create a GitHub pull request using gh CLI."""
    if not title.strip():
        return "❌ title is required."
    args = ["pr", "create", "--title", title, "--body", body or "", "--base", base]
    if head.strip():
        args.extend(["--head", head])
    code, out, err = _run_gh(args, repo_path=repo_path, workdir=workdir)
    if code != 0:
        return f"❌ create_pull_request failed: {err or 'gh CLI error'}"
    return out or "✅ Pull request created."


def tool_list_issues(repo_path: str = ".", state: str = "open", limit: int = 20, workdir: str = "/tmp") -> str:
    """List GitHub issues using gh CLI."""
    if state not in {"open", "closed", "all"}:
        return "❌ state must be one of: open, closed, all"
    if limit <= 0:
        limit = 20
    args = ["issue", "list", "--state", state, "--limit", str(limit)]
    code, out, err = _run_gh(args, repo_path=repo_path, workdir=workdir)
    if code != 0:
        return f"❌ list_issues failed: {err or 'gh CLI error'}"
    return out or "No issues found."


def tool_create_issue(title: str, body: str = "", labels: str = "", repo_path: str = ".", workdir: str = "/tmp") -> str:
    """Create a GitHub issue using gh CLI."""
    if not title.strip():
        return "❌ title is required."
    args = ["issue", "create", "--title", title, "--body", body or ""]
    if labels.strip():
        args.extend(["--label", labels])
    code, out, err = _run_gh(args, repo_path=repo_path, workdir=workdir)
    if code != 0:
        return f"❌ create_issue failed: {err or 'gh CLI error'}"
    return out or "✅ Issue created."


# ── DATABASE QUERY TOOL ───────────────────────────────────────────────────────
def tool_query_db(connection_string: str, query: str) -> str:
    """Run a read-only SQL query. Only SELECT statements allowed."""
    import re as _re
    stripped = query.strip().upper()
    if not stripped.startswith("SELECT"):
        return "❌ Only SELECT queries are allowed."
    # Block dangerous keywords even inside SELECT
    dangerous = ["DROP ", "DELETE ", "INSERT ", "UPDATE ", "ALTER ",
                 "EXEC ", "EXECUTE ", "xp_", "--", "/*"]
    for kw in dangerous:
        if kw.upper() in query.upper():
            return f"❌ Blocked keyword in query: {kw.strip()}"
    try:
        if connection_string.startswith("sqlite:///") or connection_string.endswith(".db"):
            import sqlite3
            path = connection_string.replace("sqlite:///","")
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            rows  = conn.execute(query).fetchall()[:100]
            conn.close()
            if not rows: return "No results."
            cols = rows[0].keys()
            lines = [" | ".join(str(c) for c in cols)]
            lines += ["-+-".join("-"*max(1,len(str(c))) for c in cols)]
            for row in rows:
                lines.append(" | ".join(str(row[c])[:30] for c in cols))
            return f"```\n" + "\n".join(lines) + "\n```"
        else:
            return "❌ Only SQLite (sqlite:///path.db) supported currently."
    except Exception as e:
        return f"❌ Query failed: {e}"


def tool_inspect_db(connection_string: str) -> str:
    """Introspect a database schema — list tables, columns, types, and row counts.

    Supports:
      sqlite:///path/to/file.db  or  /path/to/file.db
      postgresql://user:pass@host/dbname  (requires psycopg2)  # pragma: allowlist secret
    """
    cs = (connection_string or "").strip()
    if not cs:
        return "❌ connection_string is required."
    try:
        if cs.startswith("sqlite:///") or cs.endswith(".db"):
            import sqlite3
            path = cs.replace("sqlite:///", "")
            conn = sqlite3.connect(path)
            c    = conn.cursor()
            tables = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()]
            if not tables:
                conn.close()
                return "No tables found."
            lines = [f"**SQLite schema** — `{path}`\n"]
            for tbl in tables:
                try:
                    cnt = c.execute(f"SELECT COUNT(*) FROM \"{tbl}\"").fetchone()[0]
                except Exception:
                    cnt = "?"
                lines.append(f"### {tbl} ({cnt} rows)")
                cols_info = c.execute(f"PRAGMA table_info(\"{tbl}\")").fetchall()
                for col in cols_info:
                    pk = " 🔑" if col[5] else ""
                    nn = " NOT NULL" if col[3] else ""
                    dv = f" DEFAULT {col[4]}" if col[4] is not None else ""
                    lines.append(f"  - **{col[1]}** `{col[2]}`{nn}{dv}{pk}")
                lines.append("")
            conn.close()
            return "\n".join(lines)

        elif cs.startswith("postgresql://") or cs.startswith("postgres://"):
            try:
                import psycopg2
                import psycopg2.extras
            except ImportError:
                return "❌ psycopg2 not installed. Run: pip install psycopg2-binary"
            conn = psycopg2.connect(cs)
            cur  = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            tables = [r["table_name"] for r in cur.fetchall()]
            if not tables:
                conn.close()
                return "No public tables found."
            lines = [f"**PostgreSQL schema** — `{cs.split('@')[-1]}`\n"]
            for tbl in tables:
                try:
                    cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
                    cnt = cur.fetchone()[0]
                except Exception:
                    cnt = "?"
                lines.append(f"### {tbl} ({cnt} rows)")
                cur.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=%s
                    ORDER BY ordinal_position
                """, (tbl,))
                for col in cur.fetchall():
                    nn = "" if col["is_nullable"] == "YES" else " NOT NULL"
                    dv = f" DEFAULT {col['column_default']}" if col["column_default"] else ""
                    lines.append(f"  - **{col['column_name']}** `{col['data_type']}`{nn}{dv}")
                lines.append("")
            conn.close()
            return "\n".join(lines)

        else:
            return "❌ Unsupported connection string. Use sqlite:///path.db or postgresql://..."
    except Exception as e:
        return f"❌ Schema inspection failed: {e}"


# ── BACKGROUND SCHEDULER TOOLS ───────────────────────────────────────────────
def tool_cron_schedule(name: str, task: str, schedule: str) -> str:
    """Create an autonomous background job.

    schedule supports intervals (30s/5m/2h/1d) or basic 5-field cron.
    """
    if not (task or "").strip():
        return "❌ task is required."
    try:
        job = schedule_job((name or "background-task").strip(), task.strip(), (schedule or "5m").strip())
        j = job_to_dict(job)
        return (
            f"✅ Scheduled **{j['name']}** (id `{j['id']}`)\n"
            f"- task: {j['task'][:160]}\n"
            f"- schedule: `{j['schedule']}`\n"
            f"- next_run: `{j['next_run']}`"
        )
    except Exception as e:
        return f"❌ Failed to schedule job: {e}"


def tool_cron_list() -> str:
    """List all background jobs with status and timing."""
    jobs = [job_to_dict(j) for j in list_jobs()]
    if not jobs:
        return "No scheduled jobs."
    lines = ["# Scheduled jobs"]
    for j in jobs:
        lines.append(
            f"- `{j['id']}` **{j['name']}** · {j['status']} · `{j['schedule']}` "
            f"(runs: {j['run_count']}, next: {j['next_run'] or 'n/a'})"
        )
    return "\n".join(lines)


def tool_cron_cancel(job_id: str) -> str:
    """Cancel a scheduled background job by id."""
    jid = (job_id or "").strip()
    if not jid:
        return "❌ job_id is required."
    if cancel_job(jid):
        return f"✅ Cancelled job `{jid}`."
    return f"❌ Job not found: `{jid}`"


# ── KNOWLEDGE GRAPH TOOLS ───────────────────────────────────────────────────

def tool_kg_store(name: str, entity_type: str = "concept",
                  facts: dict | None = None, relations: list | None = None) -> str:
    """Store or update an entity in the long-term knowledge graph."""
    if not name or not name.strip():
        return "❌ entity name is required."
    eid = _kg_store(name.strip(), entity_type, facts or {}, relations or [])
    rel_count = len(relations) if relations else 0
    facts_count = len(facts) if facts else 0
    return (f"✅ Stored [{entity_type}] **{name}** in knowledge graph "
            f"(id={eid[:8]}, {facts_count} facts, {rel_count} relations)")


def tool_kg_query(query: str, limit: int = 10) -> str:
    """Search the knowledge graph for entities matching a query."""
    if not query or not query.strip():
        return "❌ query is required."
    results = _kg_query(query.strip(), limit=limit)
    if not results:
        return f"No knowledge graph entries found for: {query}"
    lines = [f"**{len(results)} KG result(s) for '{query}':**\n"]
    for e in results:
        facts = e.get("facts", {})
        facts_str = ", ".join(f"{k}: {v}" for k, v in list(facts.items())[:5]) if facts else "—"
        rels = e.get("relations", [])
        rel_str = "; ".join(f"{r['relation']}→{r['entity']}" for r in rels[:3]) if rels else "—"
        lines.append(f"• **[{e['type']}] {e['name']}**")
        lines.append(f"  facts: {facts_str}")
        lines.append(f"  links: {rel_str}")
    return "\n".join(lines)


def tool_kg_list(entity_type: str | None = None) -> str:
    """List entities in the knowledge graph, optionally filtered by type."""
    entities = _kg_list(entity_type=entity_type, limit=50)
    if not entities:
        filter_txt = f" of type '{entity_type}'" if entity_type else ""
        return f"No knowledge graph entities{filter_txt} found."
    lines = [f"**{len(entities)} KG entit{'y' if len(entities)==1 else 'ies'}:**\n"]
    for e in entities:
        lines.append(f"• [{e['type']}] **{e['name']}** (updated: {e['updated_at'][:10]})")
    return "\n".join(lines)


# ── COST ESTIMATOR ────────────────────────────────────────────────────────────
# Approximate costs per 1M tokens (input/output) as of early 2026
PROVIDER_COSTS = {
    "groq":         (0.00,  0.00),    # free tier
    "cerebras":     (0.00,  0.00),
    "gemini":       (0.00,  0.00),    # free tier
    "mistral":      (0.00,  0.00),    # free tier
    "openrouter":   (0.00,  0.00),    # free models
    "cohere":       (0.00,  0.00),
    "github_models":(0.00,  0.00),
    "llm7":         (0.00,  0.00),
    "nvidia":       (0.00,  0.00),
    "grok":         (5.00, 15.00),    # grok-3 approx
    "claude":       (3.00, 15.00),    # claude-sonnet-4 approx
}

def estimate_cost(provider_label: str, in_tokens: int, out_tokens: int) -> float:
    key = provider_label.lower().split()[0]
    costs = PROVIDER_COSTS.get(key, (0.0, 0.0))
    return (in_tokens * costs[0] + out_tokens * costs[1]) / 1_000_000


# ── SQLITE INTROSPECTION ──────────────────────────────────────────────────────

def tool_inspect_sqlite(query: str = "", db_path: str = "") -> str:
    """Introspect a SQLite database: list tables, describe schema, or run a read-only query."""
    import sqlite3 as _sq, os as _os
    path = db_path or _os.getenv("DB_PATH", "/tmp/nexus_ai.db")
    if not _os.path.exists(path):
        return f"❌ Database not found: {path}"
    try:
        conn = _sq.connect(path)
        conn.row_factory = _sq.Row
        q = (query or "").strip()

        if not q or q.lower() in ("tables", "list tables", ".tables"):
            rows = conn.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name").fetchall()
            if not rows:
                return "No tables found."
            lines = ["**Tables:**"]
            for r in rows:
                lines.append(f"• `{r['name']}` ({r['type']})")
            conn.close()
            return "\n".join(lines)

        if q.lower().startswith("schema") or q.lower().startswith(".schema"):
            tbl = q.split(None, 1)[1].strip() if len(q.split()) > 1 else ""
            if tbl:
                row = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (tbl,)).fetchone()
                conn.close()
                return f"```sql\n{row['sql']}\n```" if row else f"Table `{tbl}` not found."
            rows = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
            conn.close()
            return "```sql\n" + "\n\n".join(r["sql"] for r in rows if r["sql"]) + "\n```"

        lower_q = q.lower().lstrip()
        if any(lower_q.startswith(kw) for kw in ("insert", "update", "delete", "drop", "alter", "create", "replace")):
            conn.close()
            return "❌ Only read-only queries are allowed (SELECT, PRAGMA, etc.)"

        rows = conn.execute(q).fetchmany(200)
        conn.close()
        if not rows:
            return "Query returned no rows."
        cols = rows[0].keys()
        header = " | ".join(cols)
        sep = " | ".join("---" for _ in cols)
        lines = [f"| {header} |", f"| {sep} |"]
        for r in rows:
            lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ SQLite error: {e}"


def tool_query_sqlite(sql: str, db_path: str = "") -> str:
    """Alias for tool_inspect_sqlite — run a read-only SQL query against the database."""
    return tool_inspect_sqlite(sql, db_path)


# ── POSTGRESQL INTROSPECTION ──────────────────────────────────────────────────

def tool_inspect_postgres(query: str = "", database_url: str = "") -> str:
    """Introspect a PostgreSQL database: list tables, describe schema, or run a read-only query."""
    import os as _os
    url = database_url or _os.getenv("DATABASE_URL", "")
    if not url:
        return "❌ DATABASE_URL not set and no database_url provided."
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    except Exception as e:
        return f"❌ Cannot connect to PostgreSQL: {e}"

    try:
        q = (query or "").strip()
        with conn.cursor() as cur:
            if not q or q.lower() in ("tables", "list tables", "\\dt"):
                cur.execute("""
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                """)
                rows = cur.fetchall()
                if not rows:
                    return "No tables found."
                lines = ["**Tables (public schema):**"]
                for r in rows:
                    lines.append(f"• `{r['table_name']}` ({r['table_type']})")
                return "\n".join(lines)

            if q.lower().startswith("schema") or q.lower().startswith("\\d "):
                tbl = q.split(None, 1)[1].strip() if len(q.split()) > 1 else ""
                if tbl:
                    cur.execute("""
                        SELECT column_name, data_type, is_nullable, column_default
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name=%s
                        ORDER BY ordinal_position
                    """, (tbl,))
                    rows = cur.fetchall()
                    if not rows:
                        return f"Table `{tbl}` not found."
                    lines = [f"**Schema for `{tbl}`:**", "| Column | Type | Nullable | Default |",
                             "| --- | --- | --- | --- |"]
                    for r in rows:
                        lines.append(f"| {r['column_name']} | {r['data_type']} | "
                                     f"{r['is_nullable']} | {r['column_default'] or ''} |")
                    return "\n".join(lines)
                return "Usage: schema <table_name>"

            if q.lower().startswith("indexes") or q.lower().startswith("indices"):
                tbl = q.split(None, 1)[1].strip() if len(q.split()) > 1 else ""
                where = "AND t.relname = %s" if tbl else ""
                params = (tbl,) if tbl else ()
                cur.execute(f"""
                    SELECT i.relname AS index_name, t.relname AS table_name,
                           ix.indisunique AS is_unique, ix.indisprimary AS is_primary,
                           array_to_string(array_agg(a.attname ORDER BY a.attnum), ', ') AS columns
                    FROM pg_index ix
                    JOIN pg_class t ON t.oid = ix.indrelid
                    JOIN pg_class i ON i.oid = ix.indexrelid
                    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
                    WHERE t.relkind = 'r' {where}
                    GROUP BY i.relname, t.relname, ix.indisunique, ix.indisprimary
                    ORDER BY t.relname, i.relname
                """, params)
                rows = cur.fetchall()
                if not rows:
                    return "No indexes found."
                lines = ["**Indexes:**", "| Index | Table | Unique | Primary | Columns |",
                         "| --- | --- | --- | --- | --- |"]
                for r in rows:
                    lines.append(f"| {r['index_name']} | {r['table_name']} | "
                                 f"{r['is_unique']} | {r['is_primary']} | {r['columns']} |")
                return "\n".join(lines)

            lower_q = q.lower().lstrip()
            if any(lower_q.startswith(kw) for kw in ("insert", "update", "delete", "drop",
                                                       "alter", "create", "replace", "truncate")):
                return "❌ Only read-only queries are allowed."

            cur.execute(q)
            rows = cur.fetchmany(200)
            if not rows:
                return "Query returned no rows."
            cols = list(rows[0].keys())
            lines = ["| " + " | ".join(cols) + " |",
                     "| " + " | ".join("---" for _ in cols) + " |"]
            for r in rows:
                lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
            return "\n".join(lines)
    except Exception as e:
        return f"❌ PostgreSQL error: {e}"
    finally:
        conn.close()
