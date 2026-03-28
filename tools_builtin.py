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
