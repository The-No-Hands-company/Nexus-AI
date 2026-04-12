import json
import threading
from typing import Dict

from ..db import load_chats as db_load_chats, load_projects as db_load_projects
from ..rag.rag_system import RAGSystem

run_results: Dict[str, Dict] = {}
sessions: Dict[str, list] = {}
_active_streams: Dict[str, threading.Event] = {}
chats: Dict[str, Dict] = {}
shares: Dict[str, Dict] = {}
projects: Dict[str, Dict] = {r["id"]: r for r in db_load_projects()}
_PROJECT_CONTEXT_CACHE: Dict[str, Dict] = {}
_session_requests: Dict[str, list] = {}
_reactions: Dict[str, Dict] = {}
autonomy_traces: Dict[str, Dict] = {}
execution_traces: Dict[str, list] = {}
_rag_system: RAGSystem | None = None

for _row in db_load_chats():
    _row["messages"] = json.loads(_row["messages"]) if isinstance(_row["messages"], str) else _row["messages"]
    chats[_row["id"]] = _row


def get_rag_system() -> RAGSystem:
    global _rag_system
    if _rag_system is None:
        _rag_system = RAGSystem()
    return _rag_system
