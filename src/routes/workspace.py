"""Workspace routes.

Extracted from src/api/routes.py for maintainability.
Covers: sessions, chats, shares, projects, custom instructions,
memory CRUD/search, custom personas, usage, search, pins, prefs.
"""

from __future__ import annotations

import csv
import io
import json
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from ._helpers import _api_error
from ..agent import (
    _config,
    _push_safety_event,
    _session_state,
    call_llm_with_fallback,
    get_active_persona_name,
    get_session_dir,
    get_session_safety_profile,
    get_session_state,
    set_session_safety_profile,
    set_session_token,
)
from ..api.state import (
    _PROJECT_CONTEXT_CACHE,
    chats,
    projects,
    sessions,
    shares,
)
from ..db import (
    assign_chat_to_project,
    db_delete_shared_memory,
    delete_chat as db_delete_chat,
    delete_custom_persona as db_del_persona,
    delete_memory_entry as db_delete_memory,
    delete_project as db_delete_project,
    get_pinned_chats,
    get_project_chats,
    get_usage_by_user,
    get_usage_daily,
    get_usage_records,
    get_usage_stats,
    load_chat as db_load_chat,
    load_custom_instructions as db_load_ci,
    load_custom_personas as db_load_custom_personas,
    load_pref as db_load_pref,
    load_share as db_load_share,
    pin_chat as db_pin_chat,
    save_chat as db_save_chat,
    save_custom_instructions as db_save_ci,
    save_custom_persona as db_save_persona,
    save_pref as db_save_pref,
    save_project as db_save_project,
    save_share as db_save_share,
    search_chats as db_search_chats,
    update_memory_entry as db_update_memory,
)
from ..memory import (
    add_memory,
    delete_all as delete_all_memory,
    export_memory_bundle,
    get_all as get_all_memory,
    get_episodic_timeline as get_episodic_memory,
    get_memory_context,
    import_memory_bundle,
    summarize_history,
)
from ..safety_pipeline import SAFETY_POLICY_PROFILES

router = APIRouter(prefix="", tags=["workspace"])

# ── helpers ──────────────────────────────────────────────────────────────────

_TITLE_SKIP_PREFIXES = (
    "[MEMORY",
    "Tool result:",
    "Continue.",
    "Noted —",
    "You have reached",
)

def _auto_title(history: list) -> str:
    for msg in history:
        if msg.get("role") != "user":
            continue
        content = str(msg.get("content") or "").strip()
        if not content:
            continue
        if any(content.startswith(p) for p in _TITLE_SKIP_PREFIXES):
            continue
        head = content.split("\n", 1)[0].strip()
        return (head[:77] + "...") if len(head) > 80 else head
    return "New Chat"


def _extract_markdown_messages(markdown_text: str) -> list[dict]:
    messages: list[dict] = []
    lines = (markdown_text or "").splitlines()
    current_role: str | None = None
    current_content: list[str] = []

    def _flush():
        nonlocal current_role, current_content
        if current_role is None:
            return
        text = "\n".join(current_content).strip()
        if text:
            messages.append({"role": current_role, "content": text})
        current_role = None
        current_content = []

    for line in lines:
        token = line.strip().upper()
        if token in {"## USER", "**YOU:**"}:
            _flush()
            current_role = "user"
            continue
        if token in {"## ASSISTANT", "**ASSISTANT:**"}:
            _flush()
            current_role = "assistant"
            continue
        if current_role is not None:
            current_content.append(line)

    _flush()
    return messages


def _load_instruction_history() -> list[dict]:
    raw = db_load_pref("instructions_history_v1", "[]")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_instruction_history(entries: list[dict]):
    db_save_pref("instructions_history_v1", json.dumps(entries[-200:], separators=(",", ":")))


def _append_instruction_version(previous: str, current: str, project_id: str = ""):
    if previous == current:
        return
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    history = _load_instruction_history()
    history.append(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id or None,
            "previous": previous,
            "current": current,
            "changed_at": now,
        }
    )
    _save_instruction_history(history)


def _load_project_collaborators(pid: str) -> list[dict]:
    raw = db_load_pref(f"project_collaborators:{pid}", "[]")
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_project_collaborators(pid: str, collaborators: list[dict]) -> None:
    db_save_pref(f"project_collaborators:{pid}", json.dumps(collaborators))


_pins: set = set(get_pinned_chats())


# ── memory ────────────────────────────────────────────────────────────────────

@router.get("/memory")
def list_memory(): return {"memories": get_all_memory()}

@router.delete("/memory")
def clear_memory(): delete_all_memory(); return {"cleared": True}

@router.post("/memory/prune")
async def prune_memory_endpoint(request: Request):
    data = await request.json()
    max_age_days = data.get("max_age_days")
    min_keep     = data.get("min_keep")
    try:
        from ..memory import prune_old_memories
        deleted = prune_old_memories(
            max_age_days=int(max_age_days) if max_age_days is not None else None,
            min_keep=int(min_keep) if min_keep is not None else None,
        )
        return {"deleted": deleted}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@router.get("/memory/semantic")
def get_semantic_mem():
    try:
        from ..memory import get_semantic_memory
        return {"memories": get_semantic_memory("", 5)}
    except Exception as e:
        return {"memories": [], "note": str(e)}

@router.post("/memory/semantic")
async def add_semantic_mem(request: Request):
    data = await request.json()
    try:
        from ..memory import add_semantic_memory
        add_semantic_memory(data.get("summary", ""), data.get("tags", []))
        return {"added": True}
    except Exception as e:
        return {"error": str(e)}

@router.get("/memory/episodic")
def get_episodic_mem(limit: int = 100):
    return {"events": get_episodic_memory(limit=limit), "count": len(get_episodic_memory(limit=limit))}

@router.get("/memory/export")
def memory_export(limit: int = 1000):
    return export_memory_bundle(limit=limit)

@router.post("/memory/import")
async def memory_import(request: Request):
    data = await request.json()
    result = import_memory_bundle(data if isinstance(data, dict) else {}, source="api_import")
    return {"ok": True, **result}


# ── sessions ──────────────────────────────────────────────────────────────────

@router.post("/session")
async def new_session(request: Request = None):
    pid = ""
    if request:
        try:
            body = await request.json()
            pid = body.get("project_id", "")
        except Exception:
            pass
    sid = str(uuid.uuid4())
    extra_ctx = ""
    if pid and pid in projects:
        proj_ctx = project_context(pid)
        if proj_ctx.get("summary"):
            extra_ctx = f"[PROJECT: {projects[pid].get('name','project')}] {proj_ctx['summary']}"
    memory_ctx = get_memory_context()
    parts = [p for p in [extra_ctx, memory_ctx] if p]
    if parts:
        sessions[sid] = [{"role":"user","content":"\n\n".join(parts)},
                         {"role":"assistant","content":"Understood — I have context."}]
    else:
        sessions[sid] = []
    get_session_dir(sid)
    return {"session_id":sid,"has_memory":bool(memory_ctx),"has_project":bool(extra_ctx)}

@router.delete("/session/{sid}")
def clear_session(sid: str):
    history = sessions.get(sid, [])
    if history:
        try:
            summary = summarize_history(history, call_llm_with_fallback)
            if summary:
                add_memory(
                    summary,
                    tags=[sid, "session_close"],
                    persona=get_active_persona_name(),
                    session_id=sid,
                    source="session_close",
                )
        except Exception:
            pass
    sessions.pop(sid, None)
    db_delete_shared_memory(f"session_history:{sid}")
    _session_state.pop(sid, None)
    return {"cleared":sid}


@router.post("/session/{sid}/token")
async def set_token(sid: str, request: Request):
    data  = await request.json()
    token = data.get("token","").strip()
    if token: set_session_token(sid, token)
    return {"set": bool(token)}


@router.get("/session/{sid}/safety")
def get_session_safety(sid: str):
    session_profile = get_session_state(sid).get("safety_profile") if sid else None
    effective = get_session_safety_profile(sid)
    return {
        "session_id": sid,
        "session_profile": session_profile,
        "effective_profile": effective,
        "global_profile": _config.get("safety_profile", "standard"),
        "available_profiles": list(SAFETY_POLICY_PROFILES.keys()),
    }

@router.post("/session/{sid}/safety")
async def set_session_safety(sid: str, request: Request):
    data    = await request.json()
    profile = data.get("safety_profile")
    allowed = list(SAFETY_POLICY_PROFILES.keys())
    if profile is not None:
        profile = str(profile).lower().strip()
        if profile not in allowed:
            return _api_error(f"safety_profile must be one of: {allowed}", "validation_error", 422)
    set_session_safety_profile(sid, profile)
    effective = get_session_safety_profile(sid)
    _push_safety_event("profile_change", {"scope": "session", "session_id": sid,
                                          "profile": effective, "overridden": profile is not None})
    return {
        "session_id": sid,
        "session_profile": profile,
        "effective_profile": effective,
        "global_profile": _config.get("safety_profile", "standard"),
    }


# ── chat history ──────────────────────────────────────────────────────────────

@router.get("/chats")
def list_chats():
    pinned_ids = set(get_pinned_chats())
    def _sort(ch):
        return (ch["id"] not in pinned_ids, ch["updated_at"])
    listed = sorted(chats.values(), key=_sort, reverse=True)
    return {"chats":[{"id":c["id"],"title":c["title"],"created_at":c["created_at"],
                      "updated_at":c["updated_at"],"message_count":len(c["messages"]),
                      "pinned": c["id"] in pinned_ids} for c in listed]}

@router.post("/chats")
async def save_chat(request: Request):
    data    = await request.json()
    sid     = data.get("session_id")
    history = sessions.get(sid,[]) if sid else data.get("messages",[])
    cid     = data.get("chat_id") or str(uuid.uuid4())
    title   = data.get("title") or (chats[cid]["title"] if cid in chats else None) or _auto_title(history)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    created = chats[cid]["created_at"] if cid in chats else now
    chats[cid] = {"id":cid,"title":title[:80],
                  "created_at":created,
                  "updated_at":now,"messages":history}
    db_save_chat(cid, title, created, now, history)
    def _bg():
        summary = summarize_history(history, call_llm_with_fallback)
        if summary: add_memory(summary)
    threading.Thread(target=_bg, daemon=True).start()
    return {"chat_id":cid,"title":chats[cid]["title"]}

@router.get("/chats/{cid}")
def load_chat(cid: str):
    chat = chats.get(cid) or db_load_chat(cid)
    if chat and cid not in chats:
        chats[cid] = chat
    return chat if chat else {"error":"Not found"}

@router.delete("/chats/{cid}")
def delete_chat(cid: str):
    chats.pop(cid, None)
    db_delete_chat(cid)
    return {"deleted":cid}

@router.post("/chats/bulk-delete")
async def bulk_delete_chats(request: Request):
    data = await request.json()
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return _api_error("ids must be a non-empty array", "validation_error", 422)

    deleted = 0
    failed = []
    for cid in ids[:100]:
        key = str(cid)
        try:
            chats.pop(key, None)
            db_delete_chat(key)
            deleted += 1
        except Exception as exc:
            failed.append({"id": key, "reason": str(exc)})

    return {"deleted": deleted, "failed": failed, "total_attempted": len(ids[:100])}

@router.post("/chats/import")
async def import_chat_markdown(request: Request):
    data = await request.json()
    content = str(data.get("content") or "").strip()
    if not content:
        return _api_error("content is required", "validation_error", 422)

    messages = _extract_markdown_messages(content)
    if not messages:
        return _api_error("no chat messages found in markdown", "validation_error", 422)

    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    title = str(data.get("title") or _auto_title(messages)).strip()[:80] or "Imported Chat"

    chats[cid] = {
        "id": cid,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "messages": messages,
    }
    db_save_chat(cid, title, now, now, messages)
    return {"chat_id": cid, "title": title, "message_count": len(messages)}

@router.get("/chats/{cid}/export")
def export_chat(cid: str):
    chat = chats.get(cid)
    if not chat: return {"error":"Not found"}
    lines = [f"# {chat['title']}",f"*Exported from Nexus AI — {chat['updated_at'][:10]}*",""]
    for m in chat["messages"]:
        role,content = m.get("role",""),m.get("content","")
        if not isinstance(content,str): continue
        if any(content.startswith(p) for p in ["Tool result:","Continue","[MEMORY","[GITHUB","{"]):continue
        if role=="user": lines+=[f"**You:** {content}",""]
        elif role=="assistant": lines+=[f"**Assistant:** {content}",""]
    return StreamingResponse(iter(["\n".join(lines)]),media_type="text/markdown",
        headers={"Content-Disposition":f'attachment; filename="chat-{cid[:8]}.md"'})

@router.post("/chats/{cid}/share")
def share_chat(cid: str):
    chat = chats.get(cid)
    if not chat: return {"error":"Not found"}
    share_id = str(uuid.uuid4())[:8]
    share_data = {
        "title": chat["title"],
        "messages": chat["messages"],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    shares[share_id] = share_data
    db_save_share(share_id, chat["title"],
                  share_data["created_at"], chat["messages"])
    return {"share_id":share_id,"url":f"/share/{share_id}"}

@router.get("/share/{share_id}")
def view_share(share_id: str):
    chat = shares.get(share_id) or db_load_share(share_id)
    if chat and share_id not in shares:
        shares[share_id] = chat
    if not chat: return HTMLResponse("<h2>Share not found.</h2>",status_code=404)
    msgs_html=""
    for m in chat["messages"]:
        role,content=m.get("role",""),m.get("content","")
        if not isinstance(content,str):continue
        if any(content.startswith(p) for p in ["Tool result:","Continue","[MEMORY","{"]):continue
        if role=="user": msgs_html+=f'<div class="u"><strong>You</strong><p>{content}</p></div>'
        elif role=="assistant" and not content.startswith("{"): msgs_html+=f'<div class="a"><strong>Assistant</strong><p>{content}</p></div>'
    html=f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{chat['title']} — Nexus AI</title>
<style>body{{font-family:system-ui;max-width:760px;margin:40px auto;padding:0 20px;background:#09090e;color:#e2e8f0}}
h1{{font-size:1.3rem}}p.sub{{color:#64748b;font-size:.8rem;margin-bottom:30px}}
.u,.a{{padding:12px 16px;border-radius:12px;margin:10px 0}}
.u{{background:#7c6af7;color:#fff;margin-left:60px}}.a{{background:#111118;border:1px solid #1f1f2e;margin-right:60px}}
strong{{font-size:.75rem;opacity:.7;display:block;margin-bottom:4px}}p{{margin:0;line-height:1.6;white-space:pre-wrap}}
.brand{{text-align:center;margin-top:40px;font-size:.75rem;color:#64748b}}</style></head>
<body><h1>{chat['title']}</h1><p class="sub">Shared from Nexus AI · {chat['created_at'][:10]}</p>
{msgs_html}<div class="brand">Made with <a href="/" style="color:#7c6af7">Nexus AI</a></div></body></html>"""
    return HTMLResponse(html)


# ── projects ──────────────────────────────────────────────────────────────────

@router.get("/projects")
def list_projects():
    return {"projects": list(sorted(projects.values(), key=lambda p: p["updated_at"], reverse=True))}

@router.post("/projects")
async def create_project(request: Request):
    data = await request.json()
    pid  = data.get("id") or str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    proj = {
        "id":           pid,
        "name":         data.get("name","New Project")[:80],
        "instructions": data.get("instructions",""),
        "color":        data.get("color","#7c6af7"),
        "created_at":   projects[pid]["created_at"] if pid in projects else now,
        "updated_at":   now,
    }
    projects[pid] = proj
    db_save_project(pid, proj["name"], proj["instructions"],
                    proj["color"], proj["created_at"], proj["updated_at"])
    return proj

@router.get("/projects/{pid}")
def get_project(pid: str):
    return projects.get(pid) or {"error":"Not found"}

@router.delete("/projects/{pid}")
def del_project(pid: str):
    projects.pop(pid, None)
    db_delete_project(pid)
    return {"deleted": pid}

@router.post("/projects/{pid}/chats/{cid}")
def link_chat_to_project(pid: str, cid: str):
    assign_chat_to_project(pid, cid)
    return {"linked": cid}

@router.get("/projects/{pid}/chats")
def project_chat_list(pid: str):
    chat_ids = get_project_chats(pid)
    result = []
    for cid in chat_ids:
        chat = chats.get(cid) or db_load_chat(cid)
        if chat:
            result.append(chat)
    return {"chats": result}

@router.get("/projects/{pid}/context")
def project_context(pid: str):
    """Get full project context: instructions + recent chats + memory + repo info."""
    proj = projects.get(pid)
    if not proj: return {"error": "Not found"}
    ctx = _PROJECT_CONTEXT_CACHE.get(pid, {})
    if not ctx or (time.time() - ctx.get("_ts", 0)) > 300:
        chat_ids = get_project_chats(pid)
        recent_msgs = []
        for cid in chat_ids[:5]:
            if cid in chats:
                for m in chats[cid]["messages"][-8:]:
                    if m.get("role") == "user":
                        text = m.get("content","")
                        if isinstance(text, str) and len(text) > 5:
                            recent_msgs.append(text[:120])
        summary = " ".join(recent_msgs) if recent_msgs else "No prior conversations."
        ctx = {
            "summary": summary[:1000],
            "instructions": proj.get("instructions", ""),
            "name": proj.get("name", ""),
            "chat_count": len(chat_ids),
            "_ts": time.time(),
        }
        _PROJECT_CONTEXT_CACHE[pid] = ctx
    return ctx

@router.post("/projects/{pid}/sessions")
def new_project_session(pid: str):
    """Start a new session pre-loaded with project context."""
    proj = projects.get(pid)
    if not proj: return {"error": "Not found"}
    ctx = project_context(pid) if pid in projects else {}
    new_sid = str(uuid.uuid4())
    memory_ctx = get_memory_context()
    project_ctx = ctx.get("summary", "")
    session_parts = []
    if project_ctx:
        session_parts.append(f"[PROJECT CONTEXT — {proj.get('name','project')}] {project_ctx}")
    if memory_ctx:
        session_parts.append(memory_ctx)
    if session_parts:
        sessions[new_sid] = [{"role":"user","content":"\n\n".join(session_parts)},
                         {"role":"assistant","content":"Got it — I have project context."}]
    else:
        sessions[new_sid] = []
    get_session_dir(new_sid)
    return {"session_id": new_sid, "project_id": pid, "has_context": bool(session_parts)}

@router.post("/projects/{pid}/context")
async def update_project_context(pid: str, request: Request):
    """Update project context cache from agent output."""
    data = await request.json()
    proj = projects.get(pid)
    if not proj: return {"error": "Not found"}
    _PROJECT_CONTEXT_CACHE[pid] = {
        "summary": data.get("summary", ""),
        "instructions": data.get("instructions", proj.get("instructions", "")),
        "files": data.get("files", []),
        "last_session": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "_ts": time.time(),
    }
    return {"updated": pid}

@router.post("/projects/{pid}/memory")
async def set_project_memory(pid: str, request: Request):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)
    data = await request.json()
    summary = str(data.get("summary") or "").strip()
    if not summary:
        return _api_error("summary is required", "validation_error", 422)
    tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    merged_tags = ["project", pid] + [str(t) for t in tags]
    add_memory(summary, tags=merged_tags)
    return {"project_id": pid, "memory_stored": True, "tags": merged_tags}

@router.get("/projects/{pid}/memory")
def get_project_memory(pid: str):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)
    raw = get_memory_context(max_entries=100)
    entries = []
    for entry in raw if isinstance(raw, list) else []:
        tags = entry.get("tags", []) if isinstance(entry, dict) else []
        if pid in tags:
            entries.append(entry)
    return {"project_id": pid, "memory_entries": entries, "count": len(entries)}

@router.post("/projects/{pid}/tool-restrictions")
async def set_project_tool_restrictions(pid: str, request: Request):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    data = await request.json()
    mode = str(data.get("mode") or "allowlist").strip().lower()
    if mode not in {"allowlist", "denylist"}:
        return _api_error("mode must be allowlist or denylist", "validation_error", 422)
    tools = data.get("tools") if isinstance(data.get("tools"), list) else []
    payload = {"mode": mode, "tools": [str(t) for t in tools]}
    db_save_pref(f"project_tool_restrictions:{pid}", json.dumps(payload))
    return {"project_id": pid, "restrictions": payload}

@router.get("/projects/{pid}/tool-restrictions")
def get_project_tool_restrictions(pid: str):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    raw = db_load_pref(f"project_tool_restrictions:{pid}", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {"project_id": pid, "restrictions": parsed}
        except Exception:
            pass
    return {"project_id": pid, "restrictions": {"mode": "allowlist", "tools": []}}

@router.post("/projects/{pid}/collaborators")
async def add_project_collaborator(pid: str, request: Request):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    data = await request.json()
    username = str(data.get("username") or "").strip()
    role = str(data.get("role") or "viewer").strip()
    if not username:
        return _api_error("username is required", "validation_error", 422)

    collaborators = _load_project_collaborators(pid)
    if any(str(c.get("username", "")).strip().lower() == username.lower() for c in collaborators):
        return _api_error("collaborator already exists", "conflict", 409)

    collaborators.append({
        "username": username,
        "role": role,
        "added_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    _save_project_collaborators(pid, collaborators)
    return {"project_id": pid, "collaborator": username, "role": role, "status": "added"}

@router.get("/projects/{pid}/collaborators")
def list_project_collaborators(pid: str):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    collaborators = _load_project_collaborators(pid)
    return {"project_id": pid, "collaborators": collaborators, "count": len(collaborators)}

@router.delete("/projects/{pid}/collaborators/{collaborator}")
def remove_project_collaborator(pid: str, collaborator: str):
    if pid not in projects:
        return _api_error("Project not found", "not_found", 404)
    collaborators = _load_project_collaborators(pid)
    kept = [c for c in collaborators if str(c.get("username", "")).strip().lower() != collaborator.strip().lower()]
    _save_project_collaborators(pid, kept)
    return {"project_id": pid, "collaborator": collaborator, "status": "removed"}

@router.post("/projects/{pid}/export-bundle")
def export_project_bundle(pid: str):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(proj, indent=2))
        for cid in get_project_chats(pid):
            chat = chats.get(cid) or db_load_chat(cid)
            if chat:
                zf.writestr(f"chats/{cid}.json", json.dumps(chat, indent=2))
        mem_ctx = get_memory_context(max_entries=200)
        project_mem = []
        for item in mem_ctx if isinstance(mem_ctx, list) else []:
            tags = item.get("tags", []) if isinstance(item, dict) else []
            if pid in tags:
                project_mem.append(item)
        zf.writestr("memory.json", json.dumps(project_mem, indent=2))

    payload = buf.getvalue()
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="project-{pid[:8]}-bundle.zip"'},
    )


# ── custom instructions ────────────────────────────────────────────────────────

@router.get("/instructions")
def get_instructions():
    return {"instructions": db_load_ci()}

@router.get("/instructions/versions")
def get_instruction_versions(limit: int = 50, project_id: str = ""):
    entries = _load_instruction_history()
    if project_id:
        entries = [e for e in entries if str(e.get("project_id") or "") == project_id]
    safe_limit = max(1, min(int(limit), 200))
    return {"versions": list(reversed(entries))[:safe_limit]}

@router.post("/instructions")
async def set_instructions(request: Request):
    data = await request.json()
    old_value = db_load_ci()
    new_value = str(data.get("instructions", ""))
    db_save_ci(new_value)
    _append_instruction_version(old_value, new_value)
    return {"saved": True}

@router.get("/instructions/projects/{pid}")
def get_project_instructions(pid: str):
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)
    return {
        "project_id": pid,
        "instructions": proj.get("instructions", ""),
    }

@router.post("/instructions/projects/{pid}")
async def set_project_instructions(pid: str, request: Request):
    data = await request.json()
    proj = projects.get(pid)
    if not proj:
        return _api_error("Project not found", "not_found", 404)

    old_value = str(proj.get("instructions", ""))
    new_value = str(data.get("instructions", ""))
    proj["instructions"] = new_value
    proj["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db_save_project(
        pid,
        proj.get("name", "New Project"),
        new_value,
        proj.get("color", "#7c6af7"),
        proj.get("created_at", proj["updated_at"]),
        proj["updated_at"],
    )
    _append_instruction_version(old_value, new_value, project_id=pid)
    return {"saved": True, "project_id": pid}


# ── memory CRUD ────────────────────────────────────────────────────────────────

@router.patch("/memory/{entry_id}")
async def update_memory(entry_id: int, request: Request):
    data = await request.json()
    db_update_memory(entry_id, data.get("summary",""))
    return {"updated": entry_id}

@router.delete("/memory/{entry_id}")
def delete_memory_item(entry_id: int):
    db_delete_memory(entry_id)
    return {"deleted": entry_id}


# ── search ────────────────────────────────────────────────────────────────────

@router.get("/chats/search")
def search_chats_endpoint(q: str = ""):
    if not q.strip():
        return {"results": []}
    return {"results": db_search_chats(q)}


# ── pin ────────────────────────────────────────────────────────────────────────

@router.post("/chats/{cid}/pin")
async def pin_chat_endpoint(cid: str, request: Request):
    data   = await request.json()
    pinned = data.get("pinned", True)
    db_pin_chat(cid, pinned)
    if cid in chats:
        chats[cid]["pinned"] = pinned
    return {"pinned": pinned}

@router.delete("/chats/{cid}/pin")
def unpin_chat_endpoint(cid: str):
    _pins.discard(cid)
    db_pin_chat(cid, False)
    return {"unpinned": cid}

@router.get("/chats/pinned")
def get_pinned():
    result = [chats[cid] for cid in _pins if cid in chats]
    return {"chats": result}


# ── custom personas ────────────────────────────────────────────────────────────

@router.get("/personas/custom")
def list_custom_personas():
    return {"personas": db_load_custom_personas()}

@router.get("/personas/custom/export")
def export_custom_personas():
    return {
        "personas": db_load_custom_personas(),
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

@router.post("/personas/custom")
async def create_custom_persona(request: Request):
    data = await request.json()
    pid  = data.get("id") or str(uuid.uuid4())
    db_save_persona(
        pid,
        data.get("name","Custom"),
        data.get("icon","🤖"),
        data.get("description",""),
        data.get("prompt_prefix",""),
        data.get("color","#7c6af7"),
        float(data.get("temperature",0.2)),
        data.get("tier","medium"),
    )
    return {"id": pid}

@router.delete("/personas/custom/{pid}")
def delete_custom_persona_endpoint(pid: str):
    db_del_persona(pid)
    return {"deleted": pid}

@router.post("/personas/custom/import")
async def import_custom_personas(request: Request):
    data = await request.json()
    personas = data.get("personas", [])
    merge = bool(data.get("merge", True))

    if not isinstance(personas, list):
        return _api_error("personas must be a list", "validation_error", 422)

    normalized = []
    for item in personas:
        if not isinstance(item, dict):
            return _api_error("each persona must be an object", "validation_error", 422)
        pid = str(item.get("id") or uuid.uuid4())
        normalized.append(
            {
                "id": pid,
                "name": str(item.get("name") or "Custom"),
                "icon": str(item.get("icon") or "🤖"),
                "description": str(item.get("description") or ""),
                "prompt_prefix": str(item.get("prompt_prefix") or ""),
                "color": str(item.get("color") or "#7c6af7"),
                "temperature": float(item.get("temperature", 0.2)),
                "tier": str(item.get("tier") or "medium"),
            }
        )

    if not merge:
        for existing in db_load_custom_personas():
            existing_id = str(existing.get("id") or "")
            if existing_id:
                db_del_persona(existing_id)

    for persona in normalized:
        db_save_persona(
            persona["id"],
            persona["name"],
            persona["icon"],
            persona["description"],
            persona["prompt_prefix"],
            persona["color"],
            float(persona["temperature"]),
            persona["tier"],
        )

    return {
        "imported": len(normalized),
        "merge": merge,
        "total": len(db_load_custom_personas()),
    }


# ── usage dashboard ───────────────────────────────────────────────────────────

@router.get("/usage")
def usage_stats(days: int = 7, username: str = ""):
    from ..tools_builtin import estimate_cost

    safe_days = max(1, min(int(days), 365))
    usage_user = (username or "").strip()
    stats = get_usage_stats(safe_days)
    daily = get_usage_daily(safe_days)
    records = get_usage_records(days=safe_days, username=usage_user, limit=5000)
    per_user = get_usage_by_user(days=safe_days, limit=200)

    for row in stats.get("by_provider", []):
        row["est_cost_usd"] = round(
            estimate_cost(row.get("provider", ""), row.get("in_tok", 0), row.get("out_tok", 0)),
            6,
        )

    token_total = {
        "calls": 0,
        "in_tok": 0,
        "out_tok": 0,
        "cost_usd": 0.0,
    }
    for row in records:
        token_total["calls"] += 1
        token_total["in_tok"] += int(row.get("in_tokens") or 0)
        token_total["out_tok"] += int(row.get("out_tokens") or 0)
        token_total["cost_usd"] += float(row.get("cost_usd") or 0.0)
    token_total["total_tok"] = token_total["in_tok"] + token_total["out_tok"]
    token_total["cost_usd"] = round(token_total["cost_usd"], 6)

    avg_daily_tokens = 0.0
    avg_daily_calls = 0.0
    avg_daily_cost = 0.0
    if daily:
        avg_daily_tokens = sum((int(d.get("in_tok", 0)) + int(d.get("out_tok", 0))) for d in daily) / len(daily)
        avg_daily_calls = sum(int(d.get("calls", 0)) for d in daily) / len(daily)
        avg_daily_cost = token_total["cost_usd"] / len(daily)

    forecast = {
        "window_days": 7,
        "projected_calls": int(round(avg_daily_calls * 7)),
        "projected_tokens": int(round(avg_daily_tokens * 7)),
        "projected_cost_usd": round(avg_daily_cost * 7, 6),
    }

    webhook_cfg = {
        "enabled": db_load_pref("usage_webhook_enabled", "false") == "true",
        "url": db_load_pref("usage_webhook_url", ""),
    }

    return {
        "days": safe_days,
        "username": usage_user,
        "stats": stats,
        "daily": daily,
        "per_user": per_user,
        "totals": token_total,
        "forecast": forecast,
        "webhook": webhook_cfg,
    }

@router.get("/usage/export")
def usage_export(days: int = 7, format: str = "json", username: str = ""):
    safe_days = max(1, min(int(days), 365))
    fmt = (format or "json").strip().lower()
    records = get_usage_records(days=safe_days, username=(username or "").strip(), limit=50000)

    if fmt == "json":
        return {"days": safe_days, "count": len(records), "records": records}

    if fmt == "csv":
        output = io.StringIO()
        fieldnames = ["ts", "provider", "model", "task_type", "username", "in_tokens", "out_tokens", "cost_usd"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow(
                {
                    "ts": row.get("ts", ""),
                    "provider": row.get("provider", ""),
                    "model": row.get("model", ""),
                    "task_type": row.get("task_type", ""),
                    "username": row.get("username", ""),
                    "in_tokens": int(row.get("in_tokens") or 0),
                    "out_tokens": int(row.get("out_tokens") or 0),
                    "cost_usd": float(row.get("cost_usd") or 0.0),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=usage-{safe_days}d.csv"},
        )

    return _api_error("format must be json or csv", "validation_error", 422)


# ── user preferences ──────────────────────────────────────────────────────────

@router.get("/prefs")
def get_prefs():
    return {
        "theme":     db_load_pref("theme", "dark"),
        "font_size": db_load_pref("font_size", "15"),
        "keyboard_shortcuts": db_load_pref("keyboard_shortcuts", "default"),
        "language": db_load_pref("language", "en"),
        "verbosity": db_load_pref("verbosity", "balanced"),
        "code_theme": db_load_pref("code_theme", "default"),
        "notifications": db_load_pref("notifications", "enabled"),
    }

@router.post("/prefs")
async def set_prefs(request: Request):
    data = await request.json()
    for key in (
        "theme",
        "font_size",
        "keyboard_shortcuts",
        "language",
        "verbosity",
        "code_theme",
        "notifications",
    ):
        if key in data:
            db_save_pref(key, str(data[key]))
    return {"saved": True}


# ── Sprint E: filtered memory search ─────────────────────────────────────────

@router.get("/memory/search")
async def memory_search(
    request: Request,
    q: str = "",
    limit: int = 10,
    date_from: float | None = None,
    date_to: float | None = None,
    tags: str = "",
    persona: str = "",
):
    from ..memory import get_semantic_memory_filtered
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = get_semantic_memory_filtered(
        query=q,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        tags=tag_list,
        persona=persona or None,
    )
    return {"results": results, "count": len(results)}
