"""Real-time collaboration room management.

This module provides a complete local room lifecycle (create/join/leave/close)
plus event history for replay and UI synchronization.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ── WebSocket connection manager ──────────────────────────────────────────────

class RoomConnectionManager:
    """Manages WebSocket connections per collab room."""

    def __init__(self) -> None:
        self._connections: dict[str, list["WebSocket"]] = {}

    async def connect(self, room_id: str, websocket: "WebSocket") -> None:
        await websocket.accept()
        if room_id not in self._connections:
            self._connections[room_id] = []
        self._connections[room_id].append(websocket)
        logger.info("WS connected to room %s (total %d)", room_id, len(self._connections[room_id]))

    def disconnect(self, room_id: str, websocket: "WebSocket") -> None:
        conns = self._connections.get(room_id, [])
        if websocket in conns:
            conns.remove(websocket)
        logger.info("WS disconnected from room %s (remaining %d)", room_id, len(conns))

    async def broadcast(self, room_id: str, payload: dict) -> None:
        conns = self._connections.get(room_id, [])
        message = json.dumps(payload)
        dead: list["WebSocket"] = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(room_id, ws)

    def connection_count(self, room_id: str) -> int:
        return len(self._connections.get(room_id, []))

    def all_room_counts(self) -> dict[str, int]:
        return {rid: len(conns) for rid, conns in self._connections.items() if conns}


ws_manager = RoomConnectionManager()


@dataclass
class CollabRoom:
    room_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    owner: str = ""
    members: list[str] = field(default_factory=list)
    session_id: str | None = None       # linked Nexus chat session
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_active: bool = True
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "name": self.name,
            "owner": self.owner,
            "members": list(self.members),
            "session_id": self.session_id,
            "created_at": self.created_at,
            "is_active": self.is_active,
            "updated_at": self.updated_at,
            "events": list(self.events),
        }


_rooms: dict[str, CollabRoom] = {}
_ROOM_STORE_KEY = "collab_rooms_v1"


def _serialize_room(room: CollabRoom) -> dict:
    return room.to_dict()


def _deserialize_room(payload: dict) -> CollabRoom | None:
    if not isinstance(payload, dict):
        return None
    rid = str(payload.get("room_id") or "").strip()
    if not rid:
        return None
    return CollabRoom(
        room_id=rid,
        name=str(payload.get("name") or ""),
        owner=str(payload.get("owner") or ""),
        members=[str(m) for m in (payload.get("members") or []) if str(m).strip()],
        session_id=(str(payload.get("session_id")) if payload.get("session_id") is not None else None),
        created_at=str(payload.get("created_at") or datetime.now(timezone.utc).isoformat()),
        is_active=bool(payload.get("is_active", True)),
        updated_at=str(payload.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        events=[e for e in (payload.get("events") or []) if isinstance(e, dict)][-500:],
    )


def _persist_rooms() -> None:
    try:
        from .db import save_pref
        payload = [_serialize_room(r) for r in _rooms.values()]
        save_pref(_ROOM_STORE_KEY, json.dumps(payload))
    except Exception as exc:
        logger.warning("Failed to persist collab rooms: %s", exc)


def reload_rooms_from_store() -> int:
    """Reload collab rooms from persistent pref storage.

    Returns the number of active rooms loaded into memory.
    """
    global _rooms
    try:
        from .db import load_pref
        raw = load_pref(_ROOM_STORE_KEY, "[]")
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else []
        loaded: dict[str, CollabRoom] = {}
        if isinstance(parsed, list):
            for item in parsed:
                room = _deserialize_room(item)
                if room:
                    loaded[room.room_id] = room
        _rooms = loaded
        return len(_rooms)
    except Exception as exc:
        logger.warning("Failed to reload collab rooms: %s", exc)
        return len(_rooms)


reload_rooms_from_store()

def create_room(owner: str, name: str = "", session_id: str | None = None) -> CollabRoom:
    """
    Create a new collaboration room.

    Current implementation: in-memory room storage.
    Future: DB persistence + WebSocket channel setup.

    Args:
        owner: Username of room owner
        name: Optional room name
        session_id: Optional session context ID

    Returns:
        CollabRoom object
    """
    if not owner.strip():
        raise ValueError("owner is required")

    room_id = str(uuid.uuid4())[:12]
    room = CollabRoom(
        room_id=room_id,
        owner=owner,
        name=name or f"Room-{room_id}",
        members=[owner],
        session_id=session_id,
    )
    _rooms[room_id] = room
    broadcast_to_room(room_id, {"type": "room_created", "owner": owner, "name": room.name})
    _persist_rooms()
    return room


def get_room(room_id: str) -> CollabRoom | None:
    """Return room by ID, or None."""
    return _rooms.get(room_id)


def list_rooms(username: str | None = None) -> list[CollabRoom]:
    """List all rooms, optionally filtered by member/owner."""
    rooms = list(_rooms.values())
    if username:
        rooms = [r for r in rooms if username in r.members or r.owner == username]
    return rooms


def join_room(room_id: str, username: str) -> CollabRoom:
    """
    Add *username* to a room.

    Current implementation: in-memory member list update.
    Future: DB update + presence broadcast via WebSocket.

    Args:
        room_id: ID of room to join
        username: Username joining the room

    Returns:
        Updated CollabRoom object

    Raises:
        ValueError: If room does not exist
    """
    room = _rooms.get(room_id)
    if not room:
        raise ValueError(f"Room {room_id} does not exist")

    if not username.strip():
        raise ValueError("username is required")

    if not room.is_active:
        raise ValueError(f"Room {room_id} is closed")

    if username not in room.members:
        room.members.append(username)
        room.updated_at = datetime.now(timezone.utc).isoformat()
        broadcast_to_room(room_id, {"type": "member_joined", "username": username})
        _persist_rooms()

    return room


def leave_room(room_id: str, username: str) -> bool:
    """
    Remove *username* from a room.

    Args:
        room_id: ID of room to leave
        username: Username leaving the room

    Returns:
        True if room became empty (will be archived)
    """
    room = _rooms.get(room_id)
    if not room:
        return False

    if username in room.members:
        room.members.remove(username)
        room.updated_at = datetime.now(timezone.utc).isoformat()
        broadcast_to_room(room_id, {"type": "member_left", "username": username})
        _persist_rooms()

    return len(room.members) == 0


def close_room(room_id: str) -> bool:
    """
    Close and archive a room.

    Args:
        room_id: ID of room to close

    Returns:
        True if room was found and closed
    """
    room = _rooms.get(room_id)
    if not room:
        return False

    room.is_active = False
    room.updated_at = datetime.now(timezone.utc).isoformat()
    broadcast_to_room(room_id, {"type": "room_closed"})
    _persist_rooms()
    return True


def broadcast_to_room(room_id: str, event: dict) -> None:
    """
    Broadcast an event to all members of a room via WebSocket.

    Current implementation: stores event (no actual WebSocket broadcast yet).
    Future: use FastAPI WebSocket manager to push event to all connections.

    Args:
        room_id: ID of room to broadcast to
        event: Event dictionary to broadcast
    """
    room = _rooms.get(room_id)
    if not room:
        return

    payload = dict(event or {})
    payload.setdefault("at", datetime.now(timezone.utc).isoformat())
    room.events.append(payload)
    room.events = room.events[-500:]
    _persist_rooms()

    # Async broadcast to connected WebSocket clients
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(ws_manager.broadcast(room_id, payload))
    except RuntimeError:
        pass  # No running loop in sync context


def get_room_events(room_id: str, limit: int = 100) -> list[dict]:
    """Return latest events for a room, newest last."""
    room = _rooms.get(room_id)
    if not room:
        return []
    safe_limit = max(1, min(int(limit), 500))
    return list(room.events[-safe_limit:])
