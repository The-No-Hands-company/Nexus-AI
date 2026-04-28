"""Browser automation agent for Nexus AI.

Provides headless browser actions with human-in-the-loop takeover checkpoints.
Supports multi-step task planning, visual element detection, form filling,
navigation replay, and screenshot-based verification.

Backends (in priority order):
1. Playwright (preferred — async, reliable)
2. Selenium + WebDriver
3. Requests + BeautifulSoup (read-only fallback)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

BROWSER_BACKEND    = os.getenv("BROWSER_BACKEND", "auto")   # auto | playwright | selenium | requests
BROWSER_HEADLESS   = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"
BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "30000"))
BROWSER_STEALTH    = os.getenv("BROWSER_STEALTH", "true").lower() == "true"

_STEALTH_USER_AGENTS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


async def _new_stealth_page(browser):
    user_agent = random.choice(_STEALTH_USER_AGENTS)
    context = await browser.new_context(
        user_agent=user_agent,
        locale="en-US",
        viewport={"width": random.choice([1366, 1440, 1536]), "height": random.choice([768, 810, 864])},
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
        },
    )
    page = await context.new_page()
    if BROWSER_STEALTH:
        await page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            """
        )
    return context, page


# ── Session model ─────────────────────────────────────────────────────────────

@dataclass
class BrowserSession:
    session_id: str
    start_url:  str
    status:     str = "idle"       # idle | running | paused | completed | failed
    steps:      list[dict] = field(default_factory=list)
    current_url: str = ""
    screenshot_b64: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error:      str = ""
    hitl_checkpoints: list[str] = field(default_factory=list)  # step ids awaiting human approval
    pending_confirmation: dict | None = None
    resumable_from_step_id: str = ""
    paused_reason: str = ""
    form_plans: dict[str, dict] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id":        self.session_id,
            "start_url":         self.start_url,
            "status":            self.status,
            "steps":             self.steps,
            "current_url":       self.current_url,
            "screenshot_b64":    self.screenshot_b64[:200] + "..." if len(self.screenshot_b64) > 200 else self.screenshot_b64,
            "created_at":        self.created_at,
            "error":             self.error,
            "hitl_checkpoints":  self.hitl_checkpoints,
            "pending_confirmation": self.pending_confirmation,
            "resumable_from_step_id": self.resumable_from_step_id,
            "paused_reason": self.paused_reason,
            "form_plan_count": len(self.form_plans),
            "step_count":        len(self.steps),
        }


_sessions: dict[str, BrowserSession] = {}


# ── Backend detection ─────────────────────────────────────────────────────────

def _detect_backend() -> str:
    if BROWSER_BACKEND != "auto":
        return BROWSER_BACKEND
    try:
        import playwright  # type: ignore
        return "playwright"
    except ImportError:
        pass
    try:
        import selenium  # type: ignore
        return "selenium"
    except ImportError:
        pass
    return "requests"


# ── Playwright backend ────────────────────────────────────────────────────────

async def _playwright_navigate(url: str) -> dict:
    try:
        from playwright.async_api import async_playwright  # type: ignore
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=BROWSER_HEADLESS)
            context, page = await _new_stealth_page(browser)
            resp    = await page.goto(url, timeout=BROWSER_TIMEOUT_MS)
            title   = await page.title()
            content = await page.content()
            screenshot = await page.screenshot(type="jpeg", quality=70)
            await context.close()
            await browser.close()
            return {
                "ok":             True,
                "url":            url,
                "title":          title,
                "content_length": len(content),
                "screenshot_b64": base64.b64encode(screenshot).decode(),
                "status_code":    resp.status if resp else None,
                "backend":        "playwright",
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backend": "playwright"}


async def _playwright_click(url: str, selector: str) -> dict:
    try:
        from playwright.async_api import async_playwright  # type: ignore
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=BROWSER_HEADLESS)
            context, page = await _new_stealth_page(browser)
            await page.goto(url, timeout=BROWSER_TIMEOUT_MS)
            await page.wait_for_timeout(random.randint(120, 360))
            await page.click(selector, timeout=BROWSER_TIMEOUT_MS)
            await page.wait_for_load_state("networkidle")
            title      = await page.title()
            new_url    = page.url
            screenshot = await page.screenshot(type="jpeg", quality=70)
            await context.close()
            await browser.close()
            return {
                "ok":             True,
                "selector":       selector,
                "new_url":        new_url,
                "title":          title,
                "screenshot_b64": base64.b64encode(screenshot).decode(),
                "backend":        "playwright",
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backend": "playwright"}


async def _playwright_fill_form(url: str, fields: dict[str, str],
                                submit_selector: str | None = None) -> dict:
    try:
        from playwright.async_api import async_playwright  # type: ignore
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=BROWSER_HEADLESS)
            context, page = await _new_stealth_page(browser)
            await page.goto(url, timeout=BROWSER_TIMEOUT_MS)
            filled = []
            for selector, value in fields.items():
                try:
                    await page.wait_for_timeout(random.randint(80, 220))
                    await page.fill(selector, value, timeout=5000)
                    filled.append(selector)
                except Exception as e:
                    logger.warning("Fill failed for %s: %s", selector, e)
            if submit_selector:
                await page.wait_for_timeout(random.randint(150, 320))
                await page.click(submit_selector, timeout=BROWSER_TIMEOUT_MS)
                await page.wait_for_load_state("networkidle")
            screenshot = await page.screenshot(type="jpeg", quality=70)
            await context.close()
            await browser.close()
            return {
                "ok":             True,
                "filled_fields":  filled,
                "new_url":        page.url,
                "screenshot_b64": base64.b64encode(screenshot).decode(),
                "backend":        "playwright",
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backend": "playwright"}


# ── Requests fallback ─────────────────────────────────────────────────────────

def _requests_navigate(url: str) -> dict:
    try:
        import requests  # type: ignore
        from bs4 import BeautifulSoup  # type: ignore
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Nexus-AI-Browser/1.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.title.string if soup.title else ""
        # Extract visible text
        for tag in soup(["script", "style", "meta", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)[:5000]
        links = [a.get("href") for a in soup.find_all("a", href=True)][:20]
        return {
            "ok":           True,
            "url":          url,
            "title":        title,
            "text_preview": text,
            "links":        links,
            "status_code":  resp.status_code,
            "backend":      "requests",
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backend": "requests"}


def _element_selector_candidates(tag: str, attrs: dict[str, str], index: int) -> list[str]:
    candidates: list[str] = []
    element_id = (attrs.get("id") or "").strip()
    if element_id:
        candidates.append(f"#{element_id}")

    name = (attrs.get("name") or "").strip()
    if name:
        candidates.append(f'{tag}[name="{name}"]')
    placeholder = (attrs.get("placeholder") or "").strip()
    if placeholder:
        candidates.append(f'{tag}[placeholder="{placeholder}"]')

    klass = (attrs.get("class") or "").strip()
    if klass:
        first_class = klass.split()[0]
        if first_class:
            candidates.append(f"{tag}.{first_class}")

    candidates.append(f"{tag}:nth-of-type({max(1, index + 1)})")

    deduped: list[str] = []
    for item in candidates:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _requests_detect_elements(url: str, max_elements: int = 40) -> dict:
    try:
        import requests  # type: ignore
        from bs4 import BeautifulSoup  # type: ignore

        resp = requests.get(url, timeout=30, headers={"User-Agent": "Nexus-AI-Browser/1.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        selectors = ["input", "textarea", "select", "button", "a", "form"]
        elements: list[dict[str, Any]] = []
        for selector in selectors:
            for idx, node in enumerate(soup.select(selector)):
                if len(elements) >= max_elements:
                    break
                attrs = {
                    "id": node.attrs.get("id", ""),
                    "name": node.attrs.get("name", ""),
                    "class": " ".join(node.attrs.get("class", [])) if isinstance(node.attrs.get("class"), list) else str(node.attrs.get("class", "") or ""),
                    "placeholder": node.attrs.get("placeholder", ""),
                    "type": node.attrs.get("type", ""),
                    "href": node.attrs.get("href", ""),
                    "action": node.attrs.get("action", ""),
                }
                text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
                elements.append(
                    {
                        "tag": selector,
                        "text": text[:200],
                        "attrs": attrs,
                        "selector_candidates": _element_selector_candidates(selector, attrs, idx),
                    }
                )
            if len(elements) >= max_elements:
                break

        forms = []
        for idx, form in enumerate(soup.select("form")[: max_elements]):
            action = str(form.attrs.get("action") or "").strip()
            method = str(form.attrs.get("method") or "get").strip().lower()
            forms.append(
                {
                    "form_selector": _element_selector_candidates("form", {
                        "id": str(form.attrs.get("id") or ""),
                        "name": str(form.attrs.get("name") or ""),
                        "class": " ".join(form.attrs.get("class", [])) if isinstance(form.attrs.get("class"), list) else str(form.attrs.get("class") or ""),
                    }, idx)[0],
                    "action": urljoin(url, action) if action else url,
                    "method": method,
                }
            )

        return {
            "ok": True,
            "url": url,
            "elements": elements,
            "forms": forms,
            "backend": "requests",
            "count": len(elements),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backend": "requests"}


async def _playwright_detect_elements(url: str, max_elements: int = 40) -> dict:
    try:
        from playwright.async_api import async_playwright  # type: ignore

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=BROWSER_HEADLESS)
            page = await browser.new_page()
            await page.goto(url, timeout=BROWSER_TIMEOUT_MS)

            script = """
() => {
  const tags = ['input','textarea','select','button','a','form'];
  const maxElements = %d;
  const out = [];
  for (const tag of tags) {
    const nodes = Array.from(document.querySelectorAll(tag));
    for (let i = 0; i < nodes.length; i++) {
      if (out.length >= maxElements) break;
      const n = nodes[i];
      const id = n.id || '';
      const name = n.getAttribute('name') || '';
      const cls = (n.className || '').toString().trim();
      const placeholder = n.getAttribute('placeholder') || '';
      const text = (n.innerText || n.textContent || '').trim().replace(/\s+/g,' ');
      const candidates = [];
      if (id) candidates.push(`#${id}`);
      if (name) candidates.push(`${tag}[name="${name}"]`);
      if (placeholder) candidates.push(`${tag}[placeholder="${placeholder}"]`);
      if (cls) candidates.push(`${tag}.${cls.split(/\s+/)[0]}`);
      candidates.push(`${tag}:nth-of-type(${i+1})`);
      out.push({
        tag,
        text: text.slice(0, 200),
        attrs: {
          id,
          name,
          class: cls,
          placeholder,
          type: n.getAttribute('type') || '',
          href: n.getAttribute('href') || '',
          action: n.getAttribute('action') || '',
        },
        selector_candidates: Array.from(new Set(candidates)),
      });
    }
    if (out.length >= maxElements) break;
  }
  return out;
}
""" % max_elements

            elements = await page.evaluate(script)
            forms = [e for e in elements if e.get("tag") == "form"]
            screenshot = await page.screenshot(type="jpeg", quality=70)
            await browser.close()
            return {
                "ok": True,
                "url": page.url,
                "elements": elements,
                "forms": forms,
                "backend": "playwright",
                "count": len(elements),
                "screenshot_b64": base64.b64encode(screenshot).decode(),
            }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "backend": "playwright"}


def _build_form_plan(fields: dict[str, Any], submit_selector: str | None = None) -> dict[str, Any]:
    plan_fields: dict[str, str] = {}
    for key, value in fields.items():
        field_name = str(key).strip()
        if not field_name:
            continue
        if field_name.startswith("#") or field_name.startswith(".") or field_name.startswith("["):
            selector = field_name
        else:
            selector = f'input[name="{field_name}"]'
        plan_fields[selector] = str(value)

    return {
        "fields": plan_fields,
        "submit_selector": submit_selector,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ── High-level session API ────────────────────────────────────────────────────

def create_session(start_url: str, hitl_checkpoints: list[str] | None = None) -> BrowserSession:
    sid = str(uuid.uuid4())[:12]
    sess = BrowserSession(
        session_id=sid,
        start_url=start_url,
        hitl_checkpoints=hitl_checkpoints or [],
    )
    _sessions[sid] = sess
    return sess


def get_session(session_id: str) -> BrowserSession | None:
    return _sessions.get(session_id)


def list_sessions() -> list[dict]:
    return [s.to_dict() for s in _sessions.values()]


async def execute_step(session_id: str, action: str, params: dict) -> dict:
    """Execute a single browser action within a session.

    Actions: navigate | click | fill_form | screenshot | extract_text | detect_elements |
    queue_form_fill | execute_form_plan
    """
    sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "error": "session not found"}

    if sess.pending_confirmation:
        return {
            "ok": False,
            "error": "pending confirmation required before next step",
            "pending_confirmation": sess.pending_confirmation,
        }

    if sess.status == "paused":
        return {"ok": False, "error": "session is paused; resume first"}

    backend = _detect_backend()
    step_id = str(uuid.uuid4())[:8]

    bypass_confirmation = bool(params.get("_confirmed_by_hitl", False))
    requires_confirmation = bool(params.get("requires_confirmation", False))
    if action in set(sess.hitl_checkpoints):
        requires_confirmation = True
    if action in {"click", "fill_form"} and bool(params.get("sensitive", False)):
        requires_confirmation = True
    if bypass_confirmation:
        requires_confirmation = False

    if requires_confirmation:
        sess.pending_confirmation = {
            "step_id": step_id,
            "action": action,
            "params": params,
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "reason": str(params.get("confirmation_reason") or "sensitive_browser_action"),
        }
        sess.status = "paused"
        sess.resumable_from_step_id = step_id
        sess.paused_reason = "awaiting_confirmation"
        return {
            "ok": True,
            "pending_confirmation": True,
            "session_id": session_id,
            "step_id": step_id,
            "action": action,
            "reason": sess.pending_confirmation.get("reason"),
        }

    step: dict[str, Any] = {
        "step_id":    step_id,
        "action":     action,
        "params":     params,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "result":     None,
        "error":      None,
    }
    sess.status = "running"

    try:
        if action == "navigate":
            url = params.get("url", sess.start_url)
            if backend == "playwright":
                result = await _playwright_navigate(url)
            else:
                result = _requests_navigate(url)
            sess.current_url    = result.get("url", url)
            sess.screenshot_b64 = result.get("screenshot_b64", "")

        elif action == "click":
            selector = params.get("selector", "")
            if backend == "playwright":
                result = await _playwright_click(sess.current_url, selector)
                sess.current_url    = result.get("new_url", sess.current_url)
                sess.screenshot_b64 = result.get("screenshot_b64", "")
            else:
                result = {"ok": False, "error": "click requires playwright backend"}

        elif action == "fill_form":
            fields = params.get("fields", {})
            submit = params.get("submit_selector")
            if backend == "playwright":
                result = await _playwright_fill_form(sess.current_url, fields, submit)
                sess.current_url    = result.get("new_url", sess.current_url)
                sess.screenshot_b64 = result.get("screenshot_b64", "")
            else:
                result = {"ok": False, "error": "fill_form requires playwright backend"}

        elif action == "screenshot":
            if sess.screenshot_b64:
                result = {"ok": True, "screenshot_b64": sess.screenshot_b64}
            else:
                result = {"ok": False, "error": "no screenshot available; navigate first"}

        elif action == "extract_text":
            r = _requests_navigate(sess.current_url or sess.start_url)
            result = {"ok": r["ok"], "text": r.get("text_preview", ""), "error": r.get("error")}

        elif action == "detect_elements":
            max_elements = int(params.get("max_elements", 40) or 40)
            target_url = str(params.get("url") or sess.current_url or sess.start_url)
            if backend == "playwright":
                result = await _playwright_detect_elements(target_url, max_elements=max(1, min(max_elements, 200)))
                if result.get("screenshot_b64"):
                    sess.screenshot_b64 = str(result.get("screenshot_b64"))
            else:
                result = _requests_detect_elements(target_url, max_elements=max(1, min(max_elements, 200)))

        elif action == "queue_form_fill":
            fields = params.get("fields") if isinstance(params.get("fields"), dict) else {}
            submit_selector = params.get("submit_selector")
            plan = _build_form_plan(fields, submit_selector=submit_selector)
            plan_id = str(uuid.uuid4())[:8]
            plan["plan_id"] = plan_id
            plan["form_selector"] = str(params.get("form_selector") or "")
            sess.form_plans[plan_id] = plan
            result = {
                "ok": True,
                "plan_id": plan_id,
                "form_selector": plan.get("form_selector"),
                "fields": plan.get("fields", {}),
                "submit_selector": plan.get("submit_selector"),
                "backend": backend,
            }

        elif action == "execute_form_plan":
            plan_id = str(params.get("plan_id") or "").strip()
            plan = sess.form_plans.get(plan_id)
            if not plan:
                result = {"ok": False, "error": "form plan not found"}
            elif backend != "playwright":
                result = {"ok": False, "error": "execute_form_plan requires playwright backend"}
            else:
                fill_result = await _playwright_fill_form(
                    sess.current_url or sess.start_url,
                    dict(plan.get("fields") or {}),
                    plan.get("submit_selector"),
                )
                if fill_result.get("ok"):
                    sess.current_url = fill_result.get("new_url", sess.current_url)
                    sess.screenshot_b64 = fill_result.get("screenshot_b64", "")
                result = {
                    **fill_result,
                    "plan_id": plan_id,
                }

        else:
            result = {"ok": False, "error": f"unknown action: {action}"}

        step["result"] = result
        step["error"]  = result.get("error") if not result.get("ok") else None

    except Exception as exc:
        step["error"]  = str(exc)
        step["result"] = {"ok": False, "error": str(exc)}
        sess.error     = str(exc)
        sess.status    = "failed"

    sess.steps.append(step)
    sess.resumable_from_step_id = step_id
    if sess.status != "failed":
        sess.status = "idle"
        sess.paused_reason = ""
    step["ok"] = step["error"] is None
    return step


async def confirm_pending_step(session_id: str, approve: bool, actor: str = "") -> dict:
    sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "error": "session not found"}
    pending = sess.pending_confirmation
    if not pending:
        return {"ok": False, "error": "no pending confirmation"}

    if not approve:
        rejection_step = {
            "step_id": pending.get("step_id") or str(uuid.uuid4())[:8],
            "action": pending.get("action"),
            "params": pending.get("params"),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "result": {"ok": False, "error": "rejected_by_user", "actor": actor},
            "error": "rejected_by_user",
        }
        sess.steps.append(rejection_step)
        sess.pending_confirmation = None
        sess.status = "idle"
        sess.paused_reason = ""
        sess.resumable_from_step_id = rejection_step["step_id"]
        return {"ok": True, "approved": False, "step": rejection_step}

    action = str(pending.get("action") or "").strip()
    params = pending.get("params") if isinstance(pending.get("params"), dict) else {}
    params = dict(params)
    params.pop("requires_confirmation", None)
    params.pop("sensitive", None)
    params["_confirmed_by_hitl"] = True
    sess.pending_confirmation = None
    sess.status = "running"
    sess.paused_reason = ""
    executed = await execute_step(session_id, action, params)
    return {"ok": True, "approved": True, "executed_step": executed, "actor": actor}


def pause_session(session_id: str, reason: str = "manual_pause") -> dict:
    sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "error": "session not found"}
    sess.status = "paused"
    sess.paused_reason = reason
    return {"ok": True, "session": sess.to_dict()}


def resume_session(session_id: str, replay_navigation: bool = False) -> dict:
    sess = _sessions.get(session_id)
    if not sess:
        return {"ok": False, "error": "session not found"}
    replayed = 0
    if replay_navigation:
        nav_steps = [s for s in sess.steps if s.get("action") == "navigate"]
        replayed = len(nav_steps)
        if nav_steps:
            last = nav_steps[-1]
            sess.current_url = (
                str((last.get("result") or {}).get("url") or "").strip()
                or str((last.get("params") or {}).get("url") or "").strip()
                or sess.current_url
            )
    if not sess.pending_confirmation and sess.status != "failed":
        sess.status = "idle"
        sess.paused_reason = ""
    return {
        "ok": True,
        "session": sess.to_dict(),
        "replayed_navigation_steps": replayed,
    }


def get_navigation_history(session_id: str) -> list[dict]:
    """Return list of URL navigation steps for a session."""
    sess = _sessions.get(session_id)
    if not sess:
        return []
    return [
        {"step_id": s["step_id"], "url": s.get("result", {}).get("url") or s.get("params", {}).get("url"),
         "ts": s["started_at"]}
        for s in sess.steps if s.get("action") == "navigate"
    ]
