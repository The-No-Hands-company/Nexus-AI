"""Tests for chat/project workspace API routes."""

import io
import json
import zipfile
from uuid import uuid4
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from src.app import app
from src.db import init_projects_table

init_projects_table()

client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_projects_table():
    init_projects_table()


def _create_project(name: str = "Workspace Test Project") -> str:
    pid = f"proj-{uuid4().hex}"
    response = client.post("/projects", json={"id": pid, "name": name, "instructions": "test"})
    assert response.status_code == 200
    data = response.json()
    assert data.get("id") == pid
    return pid


def test_chat_import_and_auto_title():
    markdown = """# Imported

## USER
How should I structure this repository?

## ASSISTANT
Split by bounded contexts.
"""
    response = client.post("/chats/import", json={"content": markdown})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("chat_id")
    assert payload.get("title")
    assert payload.get("message_count") == 2


def test_bulk_delete_chats():
    created_ids = []
    for i in range(3):
        response = client.post("/chats", json={"title": f"bulk-{i}", "messages": []})
        assert response.status_code == 200
        created_ids.append(response.json()["chat_id"])

    response = client.post("/chats/bulk-delete", json={"ids": created_ids[:2]})
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("deleted") == 2
    assert payload.get("total_attempted") == 2


def test_project_session_creation():
    pid = _create_project("Project Session Test")
    response = client.post(f"/projects/{pid}/sessions")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("project_id") == pid
    assert payload.get("session_id")


def test_project_memory_namespace():
    pid = _create_project("Project Memory Test")

    put_response = client.post(
        f"/projects/{pid}/memory",
        json={"summary": "Repository uses modular route organization.", "tags": ["architecture"]},
    )
    assert put_response.status_code == 200

    get_response = client.get(f"/projects/{pid}/memory")
    assert get_response.status_code == 200
    payload = get_response.json()
    assert payload.get("project_id") == pid
    assert isinstance(payload.get("memory_entries"), list)


def test_project_tool_restrictions_roundtrip():
    pid = _create_project("Tool Restrictions Test")

    set_response = client.post(
        f"/projects/{pid}/tool-restrictions",
        json={"mode": "allowlist", "tools": ["read_file", "list_files"]},
    )
    assert set_response.status_code == 200

    get_response = client.get(f"/projects/{pid}/tool-restrictions")
    assert get_response.status_code == 200
    restrictions = get_response.json().get("restrictions", {})
    assert restrictions.get("mode") == "allowlist"
    assert "read_file" in restrictions.get("tools", [])


def test_project_collaborator_lifecycle():
    pid = _create_project("Collaborator Test")

    add_response = client.post(
        f"/projects/{pid}/collaborators",
        json={"username": "dev.user", "role": "editor"},
    )
    assert add_response.status_code == 200

    list_response = client.get(f"/projects/{pid}/collaborators")
    assert list_response.status_code == 200
    collaborators = list_response.json().get("collaborators", [])
    assert any(c.get("username") == "dev.user" for c in collaborators)

    remove_response = client.delete(f"/projects/{pid}/collaborators/dev.user")
    assert remove_response.status_code == 200


def test_project_export_bundle_contains_project_json():
    pid = _create_project("Export Bundle Test")
    save_chat = client.post(
        "/chats",
        json={
            "title": "Bundle Chat",
            "messages": [
                {"role": "user", "content": "Create an archive."},
                {"role": "assistant", "content": "Done."},
            ],
        },
    )
    assert save_chat.status_code == 200
    cid = save_chat.json().get("chat_id")
    assert cid

    link_response = client.post(f"/projects/{pid}/chats/{cid}")
    assert link_response.status_code == 200

    export_response = client.post(f"/projects/{pid}/export-bundle")
    assert export_response.status_code == 200

    archive = zipfile.ZipFile(io.BytesIO(export_response.content))
    names = set(archive.namelist())
    assert "project.json" in names
    project_payload = json.loads(archive.read("project.json").decode("utf-8"))
    assert project_payload.get("id") == pid


def test_no_section_labeled_route_modules_remaining():
    # Safety check: route functionality must live in domain modules, not section-number files.
    from pathlib import Path

    api_dir = Path(__file__).resolve().parents[1] / "src" / "api"
    matches = sorted(str(p.name) for p in api_dir.glob("section*.py"))
    assert matches == []


# ── Memory route tests ──────────────────────────────────────────────────────────


def test_memory_list_empty():
    response = client.get("/memory")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert "memories" in data or isinstance(data.get("memories"), list)


def test_memory_semantic():
    response = client.post("/memory/semantic", json={"key": "test-key", "value": "test-value"})
    assert response.status_code == 200

    response = client.get("/memory/semantic")
    assert response.status_code == 200


def test_memory_episodic():
    response = client.get("/memory/episodic")
    assert response.status_code == 200


def test_memory_export_roundtrip():
    client.post("/memory/semantic", json={"key": "export-key", "value": "export-value"})
    export_resp = client.get("/memory/export")
    assert export_resp.status_code == 200
    bundle = export_resp.json()
    assert isinstance(bundle, dict)

    import_resp = client.post("/memory/import", json=bundle)
    assert import_resp.status_code == 200


def test_memory_search():
    response = client.get("/memory/search?q=test")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list) or isinstance(data, dict)


# ── Session route tests ─────────────────────────────────────────────────────────


def test_session_create_and_delete():
    response = client.post("/session", json={})
    assert response.status_code == 200
    sid = response.json().get("session_id")
    assert sid

    delete_resp = client.delete(f"/session/{sid}")
    assert delete_resp.status_code == 200


def test_session_safety_profile():
    response = client.post("/session", json={})
    assert response.status_code == 200
    sid = response.json().get("session_id")

    get_resp = client.get(f"/session/{sid}/safety")
    assert get_resp.status_code == 200

    post_resp = client.post(f"/session/{sid}/safety", json={"safety_mode": "strict"})
    assert post_resp.status_code == 200


# ── Custom Instructions tests ────────────────────────────────────────────────────


def test_instructions_set_and_get():
    set_resp = client.post("/instructions", json={"text": "Test instruction text"})
    assert set_resp.status_code == 200

    get_resp = client.get("/instructions")
    assert get_resp.status_code == 200


def test_instruction_versions():
    client.post("/instructions", json={"text": "V1 instruction"})
    client.post("/instructions", json={"text": "V2 instruction"})

    versions_resp = client.get("/instructions/versions")
    assert versions_resp.status_code == 200


# ── Chat route tests ─────────────────────────────────────────────────────────────


def test_chat_save_load_delete():
    save_resp = client.post("/chats", json={"title": "Test Chat", "messages": [{"role": "user", "content": "hello"}]})
    assert save_resp.status_code == 200
    cid = save_resp.json().get("chat_id")
    assert cid

    load_resp = client.get(f"/chats/{cid}")
    assert load_resp.status_code == 200
    chat = load_resp.json()
    assert chat.get("id") == cid or chat.get("chat_id") == cid

    del_resp = client.delete(f"/chats/{cid}")
    assert del_resp.status_code == 200


def test_chat_list():
    client.post("/chats", json={"title": "List Test 1", "messages": []})
    list_resp = client.get("/chats")
    assert list_resp.status_code == 200
    chats = list_resp.json()
    assert isinstance(chats, (list, dict))


def test_chat_search():
    client.post("/chats", json={"title": "Searchable Chat", "messages": [{"role": "user", "content": "search me"}]})
    search_resp = client.get("/chats/search?q=search")
    assert search_resp.status_code == 200





# ── Prefs route tests ────────────────────────────────────────────────────────────


def test_prefs_roundtrip():
    set_resp = client.post("/prefs", json={"key": "theme", "pref_value": "dark"})
    assert set_resp.status_code == 200

    get_resp = client.get("/prefs")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert isinstance(data, dict)
