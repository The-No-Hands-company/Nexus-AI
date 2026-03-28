"""
Built-in tools that don't need LLM calls — calculator, weather, currency,
unit converter, regex tester, base64, JSON formatter, color info.
"""
import re, json, math, base64 as b64lib
from datetime import datetime

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


# ── DISPATCH ──────────────────────────────────────────────────────────────────
def dispatch_builtin(action: dict) -> str | None:
    """Returns result string or None if not a built-in tool."""
    kind = action.get("action")
    if kind == "calculate":
        return tool_calculate(action.get("expr", ""))
    if kind == "weather":
        return tool_weather(action.get("location", ""))
    if kind == "currency":
        return tool_currency(float(action.get("amount", 1)),
                             action.get("from", "USD"), action.get("to", "EUR"))
    if kind == "convert":
        return tool_convert(float(action.get("value", 0)),
                            action.get("from_unit", ""), action.get("to_unit", ""))
    if kind == "regex":
        return tool_regex(action.get("pattern", ""), action.get("text", ""),
                          action.get("flags", ""))
    if kind == "base64":
        return tool_base64(action.get("text", ""), action.get("mode", "encode"))
    if kind == "json_format":
        return tool_json_format(action.get("text", ""))
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


# ── PDF READER ────────────────────────────────────────────────────────────────
def tool_read_pdf(path: str, workdir: str = "/tmp") -> str:
    """Extract text from a PDF file."""
    import os
    full = os.path.join(workdir, path) if not os.path.isabs(path) else path
    if not os.path.exists(full):
        return f"File not found: {path}"
    try:
        import fitz   # PyMuPDF
        doc   = fitz.open(full)
        pages = []
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                pages.append(f"--- Page {i+1} ---\n{text}")
            if sum(len(p) for p in pages) > 6000:
                pages.append("*(truncated — too long)*")
                break
        doc.close()
        return "\n\n".join(pages) if pages else "No text found in PDF."
    except ImportError:
        return "PDF reading requires PyMuPDF (pip install pymupdf)"
    except Exception as e:
        return f"PDF read failed: {e}"


# ── DIFF VIEWER ───────────────────────────────────────────────────────────────
def tool_diff(original: str, modified: str, filename: str = "file") -> str:
    """Generate a unified diff between two strings."""
    import difflib
    orig_lines = original.splitlines(keepends=True)
    mod_lines  = modified.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        orig_lines, mod_lines,
        fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm=""
    ))
    if not diff:
        return "No changes."
    return "```diff\n" + "".join(diff[:200]) + ("…" if len(diff)>200 else "") + "\n```"


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
        for i, page in enumerate(reader.pages[:20]):   # first 20 pages
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {i+1}]\n{text.strip()}")
        if not pages:
            return "❌ No extractable text found (may be a scanned PDF)"
        total = len(reader.pages)
        content = "\n\n".join(pages)
        if len(content) > 6000:
            content = content[:6000] + f"\n\n… (truncated, {total} pages total)"
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
