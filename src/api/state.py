from __future__ import annotations

import threading


_state_lock = threading.Lock()

run_results: dict = {}
sessions: dict = {}
chats: dict = {}
shares: dict = {}
projects: dict = {}
_PROJECT_CONTEXT_CACHE: dict = {}
_session_requests: dict = {}
_reactions: dict = {}
_active_streams: dict = {}
autonomy_traces: dict = {}
execution_traces: dict = {}
_rag_system = None


def get_rag_system():
    global _rag_system
    if _rag_system is None:
        from ..rag.rag_system import RAGSystem

        _rag_system = RAGSystem()
    return _rag_system


def get_state_dict(name: str) -> dict:
    with _state_lock:
        state = {
            "run_results": run_results,
            "sessions": sessions,
            "chats": chats,
            "shares": shares,
            "projects": projects,
            "execution_traces": execution_traces,
        }
        return state.get(name, {})


def update_state(name: str, key: str, value) -> None:
    with _state_lock:
        state = {
            "run_results": run_results,
            "sessions": sessions,
            "chats": chats,
            "shares": shares,
            "projects": projects,
        }
        target = state.get(name)
        if target is not None:
            target[key] = value
