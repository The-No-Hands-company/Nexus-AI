"""Browser automation routes.

Extracted from src/api/routes.py for maintainability.
Covers: browser session lifecycle, navigation, form filling,
visual element detection, pause/resume, and confirmation.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from ._helpers import _api_error

router = APIRouter(prefix="", tags=["browser"])


@router.post("/browser/sessions")
async def api_browser_create(request: Request):
    from ..browser_agent import create_session
    body = await request.json()
    result = create_session(
        start_url=str(body.get("start_url", "https://example.com")),
        hitl_checkpoints=body.get("hitl_checkpoints", []),
    )
    return result


@router.get("/browser/sessions")
async def api_browser_list():
    from ..browser_agent import list_sessions
    return {"sessions": list_sessions()}


@router.get("/browser/sessions/{session_id}")
async def api_browser_get(session_id: str):
    from ..browser_agent import get_session
    s = get_session(session_id)
    if not s:
        return _api_error("Session not found", status_code=404)
    return s


@router.post("/browser/sessions/{session_id}/step")
async def api_browser_step(session_id: str, request: Request):
    from ..browser_agent import execute_step
    body   = await request.json()
    action = str(body.get("action", "navigate"))
    params = body.get("params", {})
    result = await execute_step(session_id, action, params)
    if not result.get("ok"):
        return _api_error(result.get("error", "Step failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/confirm")
async def api_browser_confirm(session_id: str, request: Request):
    from ..browser_agent import confirm_pending_step
    body = await request.json()
    approve = bool(body.get("approve", False))
    actor = str(body.get("actor") or body.get("username") or "")
    result = await confirm_pending_step(session_id=session_id, approve=approve, actor=actor)
    if not result.get("ok"):
        return _api_error(result.get("error", "confirmation failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/pause")
async def api_browser_pause(session_id: str, request: Request):
    from ..browser_agent import pause_session
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = str(body.get("reason") or "manual_pause")
    result = pause_session(session_id=session_id, reason=reason)
    if not result.get("ok"):
        return _api_error(result.get("error", "pause failed"), status_code=404)
    return result


@router.post("/browser/sessions/{session_id}/resume")
async def api_browser_resume(session_id: str, request: Request):
    from ..browser_agent import resume_session
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    replay_navigation = bool(body.get("replay_navigation", False))
    result = resume_session(session_id=session_id, replay_navigation=replay_navigation)
    if not result.get("ok"):
        return _api_error(result.get("error", "resume failed"), status_code=404)
    return result


@router.get("/browser/sessions/{session_id}/history")
async def api_browser_history(session_id: str):
    from ..browser_agent import get_navigation_history
    history = get_navigation_history(session_id)
    return {"history": history}


@router.post("/browser/sessions/{session_id}/visual-elements")
async def api_browser_visual_elements(session_id: str, request: Request):
    from ..browser_agent import execute_step
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    params = {
        "url": body.get("url"),
        "max_elements": body.get("max_elements", 40),
    }
    result = await execute_step(session_id=session_id, action="detect_elements", params=params)
    if not result.get("ok"):
        return _api_error(result.get("error", "visual element detection failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/form-plan")
async def api_browser_form_plan(session_id: str, request: Request):
    from ..browser_agent import execute_step
    body = await request.json()
    result = await execute_step(
        session_id=session_id,
        action="queue_form_fill",
        params={
            "fields": body.get("fields") if isinstance(body.get("fields"), dict) else {},
            "submit_selector": body.get("submit_selector"),
            "form_selector": body.get("form_selector"),
        },
    )
    if not result.get("ok"):
        return _api_error(result.get("error", "form plan creation failed"), status_code=400)
    return result


@router.post("/browser/sessions/{session_id}/form-plan/{plan_id}/execute")
async def api_browser_execute_form_plan(session_id: str, plan_id: str):
    from ..browser_agent import execute_step
    result = await execute_step(
        session_id=session_id,
        action="execute_form_plan",
        params={"plan_id": plan_id},
    )
    if not result.get("ok"):
        return _api_error(result.get("error", "form plan execution failed"), status_code=400)
    return result
