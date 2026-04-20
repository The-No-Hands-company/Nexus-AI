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

from src.app import app


client = TestClient(app)


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
