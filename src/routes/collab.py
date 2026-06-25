from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()


def _api_error(message: str, code: str = "invalid_request", status_code: int = 400):
    return JSONResponse({"error": message, "type": code}, status_code=status_code)


# ── Collaboration HTTP Endpoints ────────────────────────────────────────

@router.post("/collab/rooms")
async def collab_create_room(request: Request):
    try:
        body = await request.json()
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    owner = str(body.get("owner") or "").strip()
    if not owner:
        return _api_error("owner is required", "validation_error", 422)

    try:
        from ..collab import create_room
        room = create_room(owner=owner, name=str(body.get("name") or ""), session_id=body.get("session_id"))
        return {"room": room.to_dict()}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/collab/rooms")
def collab_list_rooms(username: str = ""):
    from ..collab import list_rooms
    rooms = list_rooms(username=username or None)
    return {"rooms": [room.to_dict() for room in rooms], "total": len(rooms)}


@router.get("/collab/rooms/{room_id}")
def collab_get_room(room_id: str):
    from ..collab import get_room
    room = get_room(room_id)
    if not room:
        return _api_error("room not found", "not_found", 404)
    return {"room": room.to_dict()}


@router.post("/collab/rooms/{room_id}/join")
async def collab_join(room_id: str, request: Request):
    try:
        body = await request.json()
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    username = str(body.get("username") or "").strip()
    if not username:
        return _api_error("username is required", "validation_error", 422)

    try:
        from ..collab import join_room
        room = join_room(room_id=room_id, username=username)
        return {"room": room.to_dict()}
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.post("/collab/rooms/{room_id}/leave")
async def collab_leave(room_id: str, request: Request):
    try:
        body = await request.json()
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    username = str(body.get("username") or "").strip()
    if not username:
        return _api_error("username is required", "validation_error", 422)

    from ..collab import leave_room
    room_empty = leave_room(room_id=room_id, username=username)
    return {"ok": True, "room_empty": room_empty}


@router.get("/collab/rooms/{room_id}/events")
def collab_room_events(room_id: str, limit: int = 100):
    from ..collab import get_room_events
    events = get_room_events(room_id=room_id, limit=limit)
    return {"events": events, "count": len(events)}


@router.post("/collab/rooms/reload")
def collab_reload_rooms_cache():
    from ..collab import reload_rooms_from_store
    loaded = reload_rooms_from_store()
    return {"ok": True, "loaded": loaded}


@router.delete("/collab/rooms/{room_id}")
def collab_close(room_id: str):
    from ..collab import close_room
    if not close_room(room_id):
        return _api_error("room not found", "not_found", 404)
    return {"ok": True, "room_id": room_id}


# ── WebSocket Collab Room ───────────────────────────────────────────────

@router.websocket("/collab/rooms/{room_id}/ws")
async def api_collab_ws(room_id: str, websocket):
    from ..collab import ws_manager, get_room, create_room
    # Ensure room exists
    if not get_room(room_id):
        create_room(owner="ws-join", name=f"Room {room_id}")
    await ws_manager.connect(room_id, websocket)
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                # Client disconnected
                break
                
            # Broadcast to all others in room
            await ws_manager.broadcast(room_id, {
                "type":    "message",
                "room_id": room_id,
                "data":    data,
            })
    except Exception:  # Includes WebSocketDisconnect
        ws_manager.disconnect(room_id, websocket)