import json
import logging
import threading
from typing import Dict

from ..db import (
    init_db,
    init_projects_table,
    load_chats as db_load_chats,
    load_projects as db_load_projects,
)
from ..rag.rag_system import RAGSystem

logger = logging.getLogger(__name__)

# state.py is imported before FastAPI lifespan in some execution paths.
# Ensure required base tables exist before import-time reads.
try:
    init_db()
    init_projects_table()
except Exception:
    logger.exception("state_db_bootstrap_failed")

run_results: Dict[str, Dict] = {}
sessions: Dict[str, list] = {}
_active_streams: Dict[str, threading.Event] = {}
chats: Dict[str, Dict] = {}
shares: Dict[str, Dict] = {}
try:
    projects: Dict[str, Dict] = {r["id"]: r for r in db_load_projects()}
except Exception:
    logger.exception("state_projects_load_failed")
    projects = {}
_PROJECT_CONTEXT_CACHE: Dict[str, Dict] = {}
_session_requests: Dict[str, list] = {}
_reactions: Dict[str, Dict] = {}
autonomy_traces: Dict[str, Dict] = {}
execution_traces: Dict[str, list] = {}
_rag_system: RAGSystem | None = None

try:
    for _row in db_load_chats():
        _row["messages"] = json.loads(_row["messages"]) if isinstance(_row["messages"], str) else _row["messages"]
        chats[_row["id"]] = _row
except Exception:
    logger.exception("state_chats_load_failed")


def get_rag_system() -> RAGSystem:
    global _rag_system
    if _rag_system is None:
        _rag_system = RAGSystem()
    return _rag_system
