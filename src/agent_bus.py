from __future__ import annotations

import time
import uuid
from dataclasses import dataclass


@dataclass
class AgentMessage:
    msg_id: str
    from_id: str
    to_id: str
    content: str
    ts: float
    read: bool = False
    topic: str = ""

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "from_id": self.from_id,
            "to_id": self.to_id,
            "content": self.content,
            "ts": self.ts,
            "read": self.read,
            "topic": self.topic,
        }


_MESSAGES: list[AgentMessage] = []


def post_message(from_id: str, to_id: str, content: str, topic: str | None = None) -> AgentMessage:
    msg = AgentMessage(
        msg_id=uuid.uuid4().hex,
        from_id=str(from_id),
        to_id=str(to_id),
        content=str(content),
        ts=time.time(),
        read=False,
        topic=topic or "",
    )
    _MESSAGES.append(msg)
    return msg


def read_messages(
    agent_id: str,
    mark_read: bool = False,
    limit: int = 100,
    unread_only: bool = False,
    topic: str | None = None,
) -> list[AgentMessage]:
    target = str(agent_id)
    items = [m for m in _MESSAGES if m.to_id == target]
    if unread_only:
        items = [m for m in items if not m.read]
    if topic:
        items = [m for m in items if m.topic == topic]
    items = items[-max(0, int(limit)):]
    if mark_read:

        for m in items:
            m.read = True
    return items


def unread_count(agent_id: str) -> int:
    target = str(agent_id)
    return sum(1 for m in _MESSAGES if m.to_id == target and not m.read)


def recent_log(limit: int = 50, topic: str | None = None) -> list[AgentMessage]:
    lim = max(0, int(limit))
    if lim == 0:
        return []
    msgs = _MESSAGES
    if topic:
        msgs = [m for m in msgs if m.topic == topic]
    return msgs[-lim:]


def clear_inbox(agent_id: str) -> int:
    target = str(agent_id)
    before = len(_MESSAGES)
    kept = [m for m in _MESSAGES if m.to_id != target]
    _MESSAGES.clear()
    _MESSAGES.extend(kept)
    return before - len(_MESSAGES)


def all_agents() -> list[str]:
    ids = set()
    for m in _MESSAGES:
        ids.add(m.from_id)
        ids.add(m.to_id)
    return sorted(ids)


# ── AgentBus class (OO wrapper for backward-compatible tests) ──────────


@dataclass
class DLQEntry:
    msg: AgentMessage
    reason: str
    ts: float

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg.msg_id,
            "from_id": self.msg.from_id,
            "to_id": self.msg.to_id,
            "content": self.msg.content,
            "reason": self.reason,
            "ts": self.ts,
        }


_DLQ: list[DLQEntry] = []


class AgentBus:
    """Object-oriented wrapper around module-level agent-bus functions."""

    def post(self, from_id: str, to_id: str, content: str, topic: str = "") -> AgentMessage:
        return post_message(from_id, to_id, content, topic=topic or None)

    def read(self, agent_id: str, topic: str | None = None, limit: int = 100) -> list[AgentMessage]:
        return read_messages(agent_id, topic=topic, limit=limit)

    def unread_count(self, agent_id: str) -> int:
        target = str(agent_id)
        return sum(1 for m in _MESSAGES if m.to_id == target and not m.read)

    def all_agents(self) -> list[str]:
        return all_agents()

    def send_to_dlq(self, msg: AgentMessage, reason: str = "") -> DLQEntry:
        entry = DLQEntry(msg=msg, reason=reason, ts=time.time())
        _DLQ.append(entry)
        return entry

    def get_dlq(self) -> list[DLQEntry]:
        return list(_DLQ)

    def clear_dlq(self) -> int:
        count = len(_DLQ)
        _DLQ.clear()
        return count


def send_to_dlq(msg: AgentMessage, reason: str = "") -> DLQEntry:
    return AgentBus().send_to_dlq(msg, reason=reason)


def get_dlq(limit: int = 50) -> list[DLQEntry]:
    return list(_DLQ[:limit])


def clear_dlq() -> int:
    count = len(_DLQ)
    _DLQ.clear()
    return count


_bus: AgentBus | None = None


def get_bus() -> AgentBus:
    global _bus
    if _bus is None:
        _bus = AgentBus()
    return _bus
