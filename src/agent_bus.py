"""Agent-to-agent message bus — Sprint G (Phase 2: Multi-Agent Empire).

Provides an in-process publish/subscribe bus where named agents can post
messages to each other and read their inbox.

Features:
- In-memory primary store (fast path)
- Optional DB persistence via save_pref / load_pref (survives restart when enabled)
- Topic-based filtering: messages carry an optional topic tag; subscribers can
  filter reads to a specific topic or set of topics
- Dead-letter queue (DLQ): failed/undeliverable messages are moved to the DLQ
  with a reason string instead of being silently dropped
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class AgentMessage:
    msg_id:   str
    from_id:  str   # sender agent id (or "user")
    to_id:    str   # recipient agent id (or "broadcast")
    content:  str
    topic:    str   = ""   # optional topic tag for filtering
    ts:       float = field(default_factory=time.time)
    read:     bool  = False

    def to_dict(self) -> dict:
        return {
            "msg_id":  self.msg_id,
            "from_id": self.from_id,
            "to_id":   self.to_id,
            "content": self.content,
            "topic":   self.topic,
            "ts":      self.ts,
            "read":    self.read,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AgentMessage":
        return cls(
            msg_id  = d["msg_id"],
            from_id = d["from_id"],
            to_id   = d["to_id"],
            content = d["content"],
            topic   = d.get("topic", ""),
            ts      = d.get("ts", time.time()),
            read    = d.get("read", False),
        )


@dataclass
class DLQEntry:
    msg:    AgentMessage
    reason: str
    dlq_ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "msg":    self.msg.to_dict(),
            "reason": self.reason,
            "dlq_ts": self.dlq_ts,
        }


class AgentBus:
    """Thread-safe message bus for agent-to-agent communication."""

    # DB pref keys for persistence
    _PERSIST_LOG_KEY   = "agent_bus:log"
    _PERSIST_INBOX_KEY = "agent_bus:inbox"
    _PERSIST_DLQ_KEY   = "agent_bus:dlq"

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        # to_id → list of messages
        self._inbox: Dict[str, List[AgentMessage]] = {}
        # All messages (global log, capped at 2 000)
        self._log: List[AgentMessage] = []
        # Dead-letter queue
        self._dlq: List[DLQEntry] = []
        self._MAX_LOG = 2000
        self._MAX_DLQ = 500
        self._persistence_enabled: bool = False

    # ------------------------------------------------------------------
    # Persistence

    def enable_persistence(self) -> None:
        """Opt in to DB-backed persistence and restore prior state."""
        self._persistence_enabled = True
        self._restore_from_db()

    def _restore_from_db(self) -> None:
        """Load previously persisted messages from the DB."""
        try:
            from .db import load_pref
            raw_log   = load_pref(self._PERSIST_LOG_KEY,   "[]")
            raw_inbox = load_pref(self._PERSIST_INBOX_KEY, "{}")
            raw_dlq   = load_pref(self._PERSIST_DLQ_KEY,   "[]")
            log_dicts   = json.loads(raw_log)
            inbox_dicts = json.loads(raw_inbox)
            dlq_dicts   = json.loads(raw_dlq)
            with self._lock:
                self._log = [AgentMessage.from_dict(d) for d in log_dicts]
                self._inbox = {
                    aid: [AgentMessage.from_dict(m) for m in msgs]
                    for aid, msgs in inbox_dicts.items()
                }
                self._dlq = [
                    DLQEntry(
                        msg    = AgentMessage.from_dict(e["msg"]),
                        reason = e.get("reason", ""),
                        dlq_ts = e.get("dlq_ts", time.time()),
                    )
                    for e in dlq_dicts
                ]
        except Exception:
            pass  # non-fatal; start fresh if restore fails

    def _persist(self) -> None:
        """Write current in-memory state to the DB (called within lock held)."""
        if not self._persistence_enabled:
            return
        try:
            from .db import save_pref
            save_pref(self._PERSIST_LOG_KEY,   json.dumps([m.to_dict() for m in self._log]))
            save_pref(self._PERSIST_INBOX_KEY, json.dumps(
                {aid: [m.to_dict() for m in msgs] for aid, msgs in self._inbox.items()}
            ))
            save_pref(self._PERSIST_DLQ_KEY,   json.dumps([e.to_dict() for e in self._dlq]))
        except Exception:
            pass  # persistence is best-effort; never fail a write operation

    # ------------------------------------------------------------------
    # Writing

    def post(self, from_id: str, to_id: str, content: str, topic: str = "") -> AgentMessage:
        """Post a message from *from_id* to *to_id* (or "broadcast")."""
        msg = AgentMessage(
            msg_id  = uuid.uuid4().hex[:12],
            from_id = from_id,
            to_id   = to_id,
            content = content,
            topic   = topic,
        )
        with self._lock:
            self._inbox.setdefault(to_id, []).append(msg)
            if to_id == "broadcast":
                # Fan-out: copy to every known inbox except sender
                for agent_id, mailbox in self._inbox.items():
                    if agent_id not in (to_id, from_id):
                        mailbox.append(AgentMessage(
                            msg_id  = uuid.uuid4().hex[:12],
                            from_id = from_id,
                            to_id   = agent_id,
                            content = content,
                            topic   = topic,
                        ))
            self._log.append(msg)
            if len(self._log) > self._MAX_LOG:
                self._log = self._log[-self._MAX_LOG:]
            self._persist()
        return msg

    def send_to_dlq(self, msg: AgentMessage, reason: str) -> DLQEntry:
        """Move a message to the dead-letter queue."""
        entry = DLQEntry(msg=msg, reason=reason)
        with self._lock:
            self._dlq.append(entry)
            if len(self._dlq) > self._MAX_DLQ:
                self._dlq = self._dlq[-self._MAX_DLQ:]
            self._persist()
        return entry

    # ------------------------------------------------------------------
    # Reading

    def read(
        self,
        agent_id: str,
        limit: int = 20,
        unread_only: bool = False,
        mark_read: bool = True,
        topic: Optional[str] = None,
    ) -> List[AgentMessage]:
        """Return messages for *agent_id*, optionally filtered to unread / topic."""
        with self._lock:
            inbox = self._inbox.get(agent_id, [])
            msgs: List[AgentMessage] = []
            for m in inbox:
                if unread_only and m.read:
                    continue
                if topic is not None and m.topic != topic:
                    continue
                msgs.append(m)
            msgs = msgs[-limit:]
            if mark_read:
                for m in msgs:
                    m.read = True
                if self._persistence_enabled:
                    self._persist()
            return msgs

    def unread_count(self, agent_id: str) -> int:
        with self._lock:
            return sum(1 for m in self._inbox.get(agent_id, []) if not m.read)

    def clear_inbox(self, agent_id: str) -> int:
        with self._lock:
            count = len(self._inbox.get(agent_id, []))
            self._inbox.pop(agent_id, None)
            self._persist()
            return count

    # ------------------------------------------------------------------
    # Global log

    def recent_log(self, limit: int = 50, topic: Optional[str] = None) -> List[AgentMessage]:
        with self._lock:
            if topic is not None:
                msgs = [m for m in self._log if m.topic == topic]
            else:
                msgs = list(self._log)
            return msgs[-limit:]

    def all_agents(self) -> List[str]:
        with self._lock:
            return list(self._inbox.keys())

    # ------------------------------------------------------------------
    # Dead-letter queue

    def get_dlq(self, limit: int = 50) -> List[DLQEntry]:
        with self._lock:
            return list(self._dlq[-limit:])

    def clear_dlq(self) -> int:
        with self._lock:
            count = len(self._dlq)
            self._dlq.clear()
            self._persist()
            return count


# Module-level singleton used by the rest of the application
_bus = AgentBus()


def post_message(from_id: str, to_id: str, content: str, topic: str = "") -> AgentMessage:
    return _bus.post(from_id, to_id, content, topic=topic)


def read_messages(
    agent_id: str,
    limit: int = 20,
    unread_only: bool = False,
    mark_read: bool = True,
    topic: Optional[str] = None,
) -> List[AgentMessage]:
    return _bus.read(agent_id, limit=limit, unread_only=unread_only, mark_read=mark_read, topic=topic)


def unread_count(agent_id: str) -> int:
    return _bus.unread_count(agent_id)


def clear_inbox(agent_id: str) -> int:
    return _bus.clear_inbox(agent_id)


def recent_log(limit: int = 50, topic: Optional[str] = None) -> List[AgentMessage]:
    return _bus.recent_log(limit, topic=topic)


def all_agents() -> List[str]:
    return _bus.all_agents()


def send_to_dlq(msg: AgentMessage, reason: str) -> DLQEntry:
    return _bus.send_to_dlq(msg, reason)


def get_dlq(limit: int = 50) -> List[DLQEntry]:
    return _bus.get_dlq(limit)


def clear_dlq() -> int:
    return _bus.clear_dlq()


def enable_persistence() -> None:
    _bus.enable_persistence()


def get_bus() -> AgentBus:
    return _bus
