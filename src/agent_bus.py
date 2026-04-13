"""Agent-to-agent message bus — Sprint G (Phase 2: Multi-Agent Empire).

Provides a simple in-process publish/subscribe bus where named agents can
post messages to each other and read their inbox.  All state is in-memory;
it does not survive process restarts (by design — agents are ephemeral).

For durable inter-agent communication see the DB-backed agent workspace
(Phase 4 roadmap item).
"""
from __future__ import annotations

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
    ts:       float = field(default_factory=time.time)
    read:     bool  = False

    def to_dict(self) -> dict:
        return {
            "msg_id":  self.msg_id,
            "from_id": self.from_id,
            "to_id":   self.to_id,
            "content": self.content,
            "ts":      self.ts,
            "read":    self.read,
        }


class AgentBus:
    """Thread-safe message bus for agent-to-agent communication."""

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        # to_id → list of messages
        self._inbox: Dict[str, List[AgentMessage]] = {}
        # All messages (global log, capped at 2 000)
        self._log: List[AgentMessage] = []
        self._MAX_LOG = 2000

    # ------------------------------------------------------------------
    # Writing

    def post(self, from_id: str, to_id: str, content: str) -> AgentMessage:
        """Post a message from *from_id* to *to_id* (or "broadcast")."""
        msg = AgentMessage(
            msg_id  = uuid.uuid4().hex[:12],
            from_id = from_id,
            to_id   = to_id,
            content = content,
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
                        ))
            self._log.append(msg)
            if len(self._log) > self._MAX_LOG:
                self._log = self._log[-self._MAX_LOG:]
        return msg

    # ------------------------------------------------------------------
    # Reading

    def read(
        self,
        agent_id: str,
        limit: int = 20,
        unread_only: bool = False,
        mark_read: bool = True,
    ) -> List[AgentMessage]:
        """Return messages for *agent_id*, optionally filtered to unread only."""
        with self._lock:
            inbox = self._inbox.get(agent_id, [])
            if unread_only:
                msgs = [m for m in inbox if not m.read]
            else:
                msgs = list(inbox)
            msgs = msgs[-limit:]
            if mark_read:
                for m in msgs:
                    m.read = True
            return msgs

    def unread_count(self, agent_id: str) -> int:
        with self._lock:
            return sum(1 for m in self._inbox.get(agent_id, []) if not m.read)

    def clear_inbox(self, agent_id: str) -> int:
        with self._lock:
            count = len(self._inbox.get(agent_id, []))
            self._inbox.pop(agent_id, None)
            return count

    # ------------------------------------------------------------------
    # Global log

    def recent_log(self, limit: int = 50) -> List[AgentMessage]:
        with self._lock:
            return list(self._log[-limit:])

    def all_agents(self) -> List[str]:
        with self._lock:
            return list(self._inbox.keys())


# Module-level singleton used by the rest of the application
_bus = AgentBus()


def post_message(from_id: str, to_id: str, content: str) -> AgentMessage:
    return _bus.post(from_id, to_id, content)


def read_messages(
    agent_id: str,
    limit: int = 20,
    unread_only: bool = False,
    mark_read: bool = True,
) -> List[AgentMessage]:
    return _bus.read(agent_id, limit=limit, unread_only=unread_only, mark_read=mark_read)


def unread_count(agent_id: str) -> int:
    return _bus.unread_count(agent_id)


def clear_inbox(agent_id: str) -> int:
    return _bus.clear_inbox(agent_id)


def recent_log(limit: int = 50) -> List[AgentMessage]:
    return _bus.recent_log(limit)


def all_agents() -> List[str]:
    return _bus.all_agents()


def get_bus() -> AgentBus:
    return _bus
