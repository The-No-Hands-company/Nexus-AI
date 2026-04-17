"""Real-time collaboration room management.

This module provides a complete local room lifecycle (create/join/leave/close)
plus event history for replay and UI synchronization.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


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

    # TODO: async WebSocket broadcast to all connected clients in this room


def get_room_events(room_id: str, limit: int = 100) -> list[dict]:
    """Return latest events for a room, newest last."""
    room = _rooms.get(room_id)
    if not room:
        return []
    safe_limit = max(1, min(int(limit), 500))
    return list(room.events[-safe_limit:])
