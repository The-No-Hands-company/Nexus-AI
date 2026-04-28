from __future__ import annotations


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